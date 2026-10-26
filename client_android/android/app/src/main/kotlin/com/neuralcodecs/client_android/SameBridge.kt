// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 FastAnt
package com.neuralcodecs.client_android

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.samecodec.decoder.FileSameSource
import com.samecodec.decoder.SameDecoder
import com.samecodec.decoder.SameReader
import io.flutter.plugin.common.BinaryMessenger
import io.flutter.plugin.common.MethodCall
import io.flutter.plugin.common.MethodChannel
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.Executors

/**
 * Serializes SAME-S decoding on a dedicated thread and exposes it to Flutter.
 *
 * [SameDecoder] owns LiteRT TensorBuffers and an XNNPACK arena; it must never
 * be called from the UI thread or concurrently. Every MethodChannel command is
 * queued on [executor], and the result is delivered back on the main thread.
 *
 * CPU affinity is applied through [applyAffinity]. The JNI symbol for
 * setAffinity lives on SageBridge, so MainActivity passes a lambda bound to the
 * existing SageBridge instance instead of duplicating the external declaration
 * here (that would look for a different JNI symbol and fail to link).
 */
class SameBridge(
    context: Context,
    messenger: BinaryMessenger,
    private val applyAffinity: ((Int) -> Int)? = null,
) : MethodChannel.MethodCallHandler {

    companion object {
        const val CHANNEL = "neuralcodecs/same"
    }

    private val appContext = context.applicationContext
    private val channel = MethodChannel(messenger, CHANNEL)
    private val executor = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "same-decoder")
    }
    private val mainHandler = Handler(Looper.getMainLooper())

    private var decoder: SameDecoder? = null
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
                        "Unknown SAME-S command: ${call.method}",
                    )
                }
                mainHandler.post { result.success(payload) }
            } catch (error: Throwable) {
                mainHandler.post {
                    result.error(
                        "SAME_ERROR",
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
        val samePath = call.argument<String>("samePath")
            ?: throw IllegalArgumentException("samePath is required")
        val threads = (call.argument<Int>("threads") ?: 4).coerceIn(1, 8)
        val cores = (call.argument<Int>("cores") ?: 0).coerceIn(0, 8)

        val reused = ensureDecoder(modelPath, threads, cores)
        val active = decoder ?: throw IllegalStateException("SAME-S decoder is not initialized")
        active.open(FileSameSource(File(samePath)))
        val meta = active.metadata
            ?: throw IllegalStateException("SAME-S metadata unavailable")
        if (meta.modelId != SameReader.MODEL_SAME_S) {
            throw IllegalStateException(
                "not a SAME-S file: model_id=${meta.modelId} " +
                    "(expected ${SameReader.MODEL_SAME_S})",
            )
        }
        if (meta.sampleRate != 44100 || meta.channels != 2) {
            throw IllegalStateException(
                "SAME-S requires 2ch @ 44100, got ${meta.channels}ch @ ${meta.sampleRate}",
            )
        }
        val chunk = active.decodeNextChunk()
            ?: throw IllegalStateException("SAME-S track produced no audio")
        return chunkPayload(active, chunk, reused)
    }

    private fun next(): Map<String, Any?> {
        val active = decoder ?: throw IllegalStateException("SAME-S decoder is not initialized")
        val meta = active.metadata ?: throw IllegalStateException("SAME-S metadata unavailable")
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
        active: SameDecoder,
        chunk: Array<FloatArray>,
        reused: Boolean,
    ): Map<String, Any?> {
        val meta = active.metadata ?: throw IllegalStateException("SAME-S metadata unavailable")
        if (meta.channels != 2) {
            throw IllegalStateException("SAME-S expected stereo, got ${meta.channels} channels")
        }
        if (chunk.size < 2) {
            throw IllegalStateException("SAME-S expected planar stereo, got ${chunk.size} planes")
        }
        val frames = chunk[0].size
        if (chunk[1].size != frames) {
            throw IllegalStateException(
                "SAME-S channel lengths differ: ${chunk[0].size} vs ${chunk[1].size}",
            )
        }
        val interleaved = ByteBuffer
            .allocate(frames * 2 * Float.SIZE_BYTES)
            .order(ByteOrder.LITTLE_ENDIAN)
        for (index in 0 until frames) {
            interleaved.putFloat(chunk[0][index])
            interleaved.putFloat(chunk[1][index])
        }
        val done = active.nextWindowIndex >= active.windowCount
        Log.i(
            "SameBridge",
            "chunk frames=$frames windows=${active.stats.windowsDecoded}/" +
                "${active.windowCount} last=${active.stats.lastWindowMs}ms done=$done",
        )
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

        val affinity = runCatching { applyAffinity?.invoke(cores) }
        affinity.onFailure {
            Log.e("SameBridge", "affinity($cores) failed", it)
        }
        affinity.onSuccess {
            Log.i("SameBridge", "affinity($cores) -> $it")
        }

        decoder?.close()
        decoder = null
        decoderKey = null

        val modelBytes = File(modelPath).length()
        val cachePath = File(
            appContext.cacheDir,
            "same_xnnwc_${modelBytes}.bin",
        ).absolutePath
        val config = SameDecoder.Config(
            threads = threads,
            rung = 128,
            trim = 8,
            engine = SameDecoder.EngineKind.COMPILED,
            weightCachePath = cachePath,
        )
        decoder = SameDecoder.fromFile(modelPath, config)
        decoderKey = key
        Log.i(
            "SameBridge",
            "decoder init ${modelBytes}B threads=$threads cores=$cores " +
                "rungs=${decoder?.availableRungs}",
        )
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
