package com.neuralcodecs.client_android

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.sagecodec.decoder.SageDecoder
import com.samecodec.decoder.FileSameSource
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.Executors

/**
 * Serializes SAGE decoding on a dedicated thread and exposes it to Flutter.
 *
 * The decoder owns LiteRT TensorBuffers and an XNNPACK arena; it must never be
 * called from the UI thread or concurrently.  Every MethodChannel command is
 * queued on [executor], and the result is delivered back on the main thread.
 */
class SageBridge(context: Context, messenger: BinaryMessenger) :
    MethodChannel.MethodCallHandler {

    companion object {
        const val CHANNEL = "neuralcodecs/sage"

        init {
            // The CPU-affinity helper is exported by the SpectroStream C++
            // runtime.  Loading the same library here lets the SAGE executor
            // pin its LiteRT worker threads as well.
            runCatching { System.loadLibrary("spectrostream_decoder") }
                .onFailure { Log.e("SageBridge", "loadLibrary failed", it) }
        }
    }

    private external fun nativeSetAffinity(numCores: Int): Int

    private val appContext = context.applicationContext
    private val channel = MethodChannel(messenger, CHANNEL)
    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "sage-decoder")
    }
    private val mainHandler = Handler(Looper.getMainLooper())

    private var decoder: SageDecoder? = null
    private var decoderKey: String? = null

    init {
        channel.setMethodCallHandler(this)
    }

    override fun onMethodCall(call: MethodCall, result: MethodChannel.Result) {
        executor.execute {
            try {
                val payload = when (call.method) {
                    "preload" -> preload(call)
                    "start" -> start(call)
                    "next" -> next()
                    "stop" -> {
                        stop()
                        emptyMap<String, Any?>()
                    }
                    "release" -> {
                        release()
                        emptyMap<String, Any?>()
                    }
                    else -> throw IllegalArgumentException(
                        "Unknown SAGE command: ${call.method}",
                    )
                }
                mainHandler.post { result.success(payload) }
            } catch (error: Throwable) {
                mainHandler.post {
                    result.error(
                        "SAGE_ERROR",
                        error.message ?: error.toString(),
                        null,
                    )
                }
            }
        }
    }

    fun dispose() {
        channel.setMethodCallHandler(null)
        executor.execute { release() }
        executor.shutdown()
    }

    private fun preload(call: MethodCall): Map<String, Any?> {
        val modelPath = call.argument<String>("modelPath")
            ?: throw IllegalArgumentException("modelPath is required")
        val threads = (call.argument<Int>("threads") ?: 4).coerceIn(1, 8)
        val cores = (call.argument<Int>("cores") ?: 0).coerceIn(0, 8)
        val reused = ensureDecoder(modelPath, threads, cores)
        return mapOf("reused" to reused)
    }

    private fun start(call: MethodCall): Map<String, Any?> {
        val modelPath = call.argument<String>("modelPath")
            ?: throw IllegalArgumentException("modelPath is required")
        val sagePath = call.argument<String>("sagePath")
            ?: throw IllegalArgumentException("sagePath is required")
        val threads = (call.argument<Int>("threads") ?: 4).coerceIn(1, 8)
        val cores = (call.argument<Int>("cores") ?: 0).coerceIn(0, 8)

        val reused = ensureDecoder(modelPath, threads, cores)
        val active = decoder ?: throw IllegalStateException("SAGE decoder is not initialized")
        active.open(FileSameSource(File(sagePath)))
        val chunk = active.decodeNextChunk()
            ?: throw IllegalStateException("SAGE track produced no audio")
        return chunkPayload(active, chunk, reused)
    }

    private fun next(): Map<String, Any?> {
        val active = decoder ?: throw IllegalStateException("SAGE decoder is not initialized")
        val meta = active.metadata ?: throw IllegalStateException("SAGE metadata unavailable")
        val chunk = active.decodeNextChunk()
        if (chunk == null) {
            return mapOf(
                "pcm" to ByteArray(0),
                "frameCount" to 0,
                "sampleRate" to meta.sampleRate,
                "channels" to meta.channels,
                "totalSamples" to meta.origSamples,
                "durationSeconds" to meta.durationSec,
                "windowsDecoded" to active.stats.windowsDecoded.toInt(),
                "windowCount" to active.windowCount,
                "done" to true,
                "decoderReused" to false,
            )
        }
        return chunkPayload(active, chunk, false)
    }

    private fun chunkPayload(
        active: SageDecoder,
        chunk: Array<FloatArray>,
        reused: Boolean,
    ): Map<String, Any?> {
        val meta = active.metadata ?: throw IllegalStateException("SAGE metadata unavailable")
        if (meta.channels != 2) {
            throw IllegalStateException("SAGE expected stereo, got ${meta.channels} channels")
        }
        val frames = chunk[0].size
        val interleaved = ByteBuffer
            .allocate(frames * 2 * Float.SIZE_BYTES)
            .order(ByteOrder.LITTLE_ENDIAN)
        for (index in 0 until frames) {
            interleaved.putFloat(chunk[0][index])
            interleaved.putFloat(chunk[1][index])
        }
        val done = active.nextWindowIndex >= active.windowCount
        return mapOf(
            "pcm" to interleaved.array(),
            "frameCount" to frames,
            "sampleRate" to meta.sampleRate,
            "channels" to meta.channels,
            "totalSamples" to meta.origSamples,
            "durationSeconds" to meta.durationSec,
            "windowsDecoded" to active.stats.windowsDecoded.toInt(),
            "windowCount" to active.windowCount,
            "done" to done,
            "decoderReused" to reused,
        )
    }

    private fun ensureDecoder(
        modelPath: String,
        threads: Int,
        cores: Int,
    ): Boolean {
        val key = "$modelPath|$threads|$cores"
        if (decoder != null && decoderKey == key) {
            return true
        }

        val affinity = runCatching { nativeSetAffinity(cores) }
        affinity.onFailure {
            Log.e("SageBridge", "nativeSetAffinity($cores) failed", it)
        }
        affinity.onSuccess {
            Log.i("SageBridge", "nativeSetAffinity($cores) -> $it")
        }

        decoder?.close()
        decoder = null
        decoderKey = null

        val modelBytes = File(modelPath).length()
        val cachePath = File(
            appContext.cacheDir,
            "sage_xnnwc_${modelBytes}.bin",
        ).absolutePath
        val config = SageDecoder.Config(
            threads = threads,
            rung = 128,
            trim = 32,
            engine = SageDecoder.EngineKind.COMPILED,
            weightCachePath = cachePath,
        )
        decoder = SageDecoder.fromFile(modelPath, config)
        decoderKey = key
        return false
    }

    private fun stop() {
        decoder?.reset()
    }

    private fun release() {
        decoder?.close()
        decoder = null
        decoderKey = null
    }
}
