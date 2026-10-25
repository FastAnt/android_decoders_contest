// Vendored from the same_codec Android decoder
// (android_decoder/src/main/java/com/samecodec/decoder/SameDecoder.kt; upstream
// SHA-256 036762de91478dd244974fc737cdd54a02071589164c71374bc79b68dba5c5ae).
// Local change: validate .same model_id and 44.1 kHz before decoding.
package com.samecodec.decoder

import android.content.res.AssetManager
import com.google.ai.edge.litert.Accelerator
import com.google.ai.edge.litert.CompiledModel
import com.google.ai.edge.litert.TensorBuffer
import org.tensorflow.lite.Interpreter
import java.io.Closeable
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.MappedByteBuffer

/**
 * Window plan shared with the Python implementation (samec/rung.plan_windows):
 * fixed-size decoder windows of [rung] latent frames, [trim] frames of overlap
 * discarded on each inner side. All starts are even (SAME-S 2-latent block phase).
 * Measured SAME-S decoder receptive field is [-2,+3] latent frames, so the
 * default trim of 8 makes tiling bit-exact vs a single whole-track decode.
 */
object RungPlanner {
    data class Window(val start: Int, val keepLo: Int, val keepHi: Int) {
        val coreStart: Int get() = start + keepLo
        val coreFrames: Int get() = keepHi - keepLo
    }

    fun plan(total: Int, rung: Int, trim: Int): List<Window> {
        if (total <= rung) return listOf(Window(0, 0, total))
        val step = rung - 2 * trim
        require(step > 0) { "rung $rung cannot tile with trim $trim" }
        val starts = mutableListOf<Int>()
        var s = 0
        while (s < total - rung) {
            starts += s
            s += step
        }
        if (starts.isEmpty() || starts.last() != total - rung) starts += total - rung
        return starts.mapIndexed { k, st ->
            Window(
                start = st,
                keepLo = if (k == 0) 0 else trim,
                keepHi = if (st + rung >= total) rung else rung - trim,
            )
        }
    }
}

/** Per-window decode statistics. */
data class DecoderStats(
    var windowsDecoded: Long = 0,
    var totalWindowMs: Double = 0.0,
    var lastWindowMs: Double = 0.0,
    var maxWindowMs: Double = 0.0,
    var totalCoreMs: Double = 0.0,
) {
    val avgWindowMs: Double get() = if (windowsDecoded > 0) totalWindowMs / windowsDecoded else 0.0
    val rtf: Double get() = if (totalCoreMs > 0) totalWindowMs / totalCoreMs else 0.0
    fun reset() {
        windowsDecoded = 0; totalWindowMs = 0.0; lastWindowMs = 0.0; maxWindowMs = 0.0; totalCoreMs = 0.0
    }
}

/**
 * SAME-S neural audio decoder: .same container -> stereo PCM via the official
 * LiteRT rung decoder model (multi-signature dec_w8a8.tflite).
 *
 * Two inference engines:
 *  - COMPILED: LiteRT CompiledModel API with explicit CpuOptions (thread count and
 *    XNNPACK weight cache actually reach XNNPACK). Preferred.
 *  - CLASSIC: org.tensorflow.lite.Interpreter (runSignature or run()). Note:
 *    Interpreter.Options.setNumThreads does NOT propagate to the implicitly
 *    created XNNPACK delegate, which then runs single-threaded (measured).
 *
 * Not thread-safe: call from a single decoder thread. Never call from the UI thread.
 */
class SameDecoder private constructor(
    private val engine: Engine,
    val config: Config,
) : Closeable {

    enum class EngineKind { COMPILED, CLASSIC }

    data class Config(
        val threads: Int = 4,
        val useXnnpack: Boolean = true,
        val rung: Int = 128,
        val trim: Int = 8,
        val engine: EngineKind = EngineKind.COMPILED,
        /** XNNPACK weight-cache path for the COMPILED engine (null = no cache file). */
        val weightCachePath: String? = null,
        /** CLASSIC engine only: classic run() instead of runSignature(). */
        val useClassicRun: Boolean = false,
    )

    private interface Engine : Closeable {
        /** Run one window; [latents] holds (256, rung) row-major; returns planar (2*rung*4096). */
        fun runWindow(latents: FloatArray): FloatArray
        fun availableRungs(): List<Int>
    }

    // ---------------- LiteRT CompiledModel engine ----------------

    private class CompiledEngine(
        model: CompiledModel,
        private val rung: Int,
    ) : Engine {
        private val sigName = "s$rung"
        private val inputBuffers: List<TensorBuffer> = model.createInputBuffers(sigName)
        private val outputBuffers: List<TensorBuffer> = model.createOutputBuffers(sigName)
        private val cm: CompiledModel = model

        override fun runWindow(latents: FloatArray): FloatArray {
            inputBuffers[0].writeFloat(latents)
            cm.run(inputBuffers, outputBuffers, sigName)
            return outputBuffers[0].readFloat()
        }

        override fun availableRungs(): List<Int> = listOf(rung)
        override fun close() {
            inputBuffers.forEach { it.close() }
            outputBuffers.forEach { it.close() }
            cm.close()
        }
    }

    // ---------------- Classic Interpreter engine ----------------

    private class ClassicEngine(
        model: MappedByteBuffer,
        private val config: Config,
    ) : Engine {
        private val interpreter: Interpreter
        private val signatureByRung: Map<Int, String>
        private val inputName: String
        private val outputName: String
        private val inputBuffer: ByteBuffer =
            ByteBuffer.allocateDirect(LATENT_DIM * config.rung * 4).order(ByteOrder.nativeOrder())
        private val outputBuffer: ByteBuffer =
            ByteBuffer.allocateDirect(2 * config.rung * SAMPLES_PER_LATENT * 4).order(ByteOrder.nativeOrder())
        private val inputFloats = inputBuffer.asFloatBuffer()
        private val outputFloats = outputBuffer.asFloatBuffer()
        private val outArray = FloatArray(2 * config.rung * SAMPLES_PER_LATENT)

        init {
            val opts = Interpreter.Options().apply {
                setNumThreads(config.threads)
                setUseXNNPACK(config.useXnnpack)
            }
            interpreter = Interpreter(model, opts)
            signatureByRung = interpreter.signatureKeys
                .filter { it.startsWith("s") && it.drop(1).all(Char::isDigit) }
                .associateBy({ it.drop(1).toInt() }, { it })
            if (config.useClassicRun) {
                inputName = ""
                outputName = ""
            } else {
                require(signatureByRung.containsKey(config.rung)) {
                    "model has no rung ${config.rung}; available: ${signatureByRung.keys.sorted()}"
                }
                val sig = signatureByRung.getValue(config.rung)
                inputName = interpreter.getSignatureInputs(sig).first()
                outputName = interpreter.getSignatureOutputs(sig).first()
            }
        }

        override fun runWindow(latents: FloatArray): FloatArray {
            inputBuffer.rewind()
            inputFloats.position(0)
            inputFloats.put(latents, 0, LATENT_DIM * config.rung)
            inputBuffer.rewind()
            outputBuffer.rewind()
            outputFloats.position(0)
            if (config.useClassicRun) {
                interpreter.run(inputBuffer, outputBuffer)
            } else {
                interpreter.runSignature(
                    mapOf<String, Any>(inputName to inputBuffer),
                    mapOf<String, Any>(outputName to outputBuffer),
                    signatureByRung.getValue(config.rung),
                )
            }
            outputFloats.position(0)
            outputFloats.get(outArray, 0, outArray.size)
            return outArray
        }

        override fun availableRungs(): List<Int> = signatureByRung.keys.sorted()
        override fun close() = interpreter.close()
    }

    // ---------------- Decoder ----------------

    private var windowLatents = FloatArray(LATENT_DIM * config.rung)
    private var reader: SameReader? = null
    private var windows: List<RungPlanner.Window> = emptyList()
    private var windowIndex = 0
    // Latent frames emitted so far. The anchored last window may overlap the
    // previous core; streaming emission must form a partition (no duplicates).
    private var emittedLatents = 0

    val stats = DecoderStats()
    val availableRungs: List<Int> get() = engine.availableRungs()

    fun open(source: SameSource) {
        closeTrack()
        reader = SameReader(source)
        val m = metadata!!
        require(m.modelId == SameReader.MODEL_SAME_S) {
            "not a SAME-S file: model_id=${m.modelId} (expected ${SameReader.MODEL_SAME_S})"
        }
        require(m.sampleRate == 44100) {
            "SAME-S requires 44100 Hz, got ${m.sampleRate}"
        }
        require(m.latentDim == LATENT_DIM) { "unsupported latent dim ${m.latentDim}" }
        require(m.channels == 2) { "unsupported channel count ${m.channels}" }
        windows = RungPlanner.plan(m.storedFrames, config.rung, config.trim)
        windowIndex = 0
        emittedLatents = 0
        stats.reset()
    }

    val metadata: SameMetadata? get() = reader?.metadata
    val nextWindowIndex: Int get() = windowIndex
    val windowCount: Int get() = windows.size

    val positionSamples: Long
        get() {
            if (windows.isEmpty()) return 0
            if (windowIndex >= windows.size) return metadata!!.origSamples
            return emittedLatents.toLong() * SAMPLES_PER_LATENT
        }

    /**
     * Decode the next window's core segment.
     * @return planar PCM Array(2) { FloatArray(coreFrames * 4096) }, or null at end of track.
     * The final chunk is trimmed so the total emitted samples never exceed origSamples.
     */
    fun decodeNextChunk(): Array<FloatArray>? {
        val r = reader ?: error("no track open")
        if (windowIndex >= windows.size) return null
        val win = windows[windowIndex]
        val m = r.metadata

        val t0 = System.nanoTime()
        val framesAvail = minOf(config.rung, m.storedFrames - win.start)
        r.readLatentsInto(win.start, framesAvail, windowLatents)
        if (framesAvail < config.rung) {
            // Short track (< one rung): repeat last latent frame (Python reference policy).
            for (c in 0 until LATENT_DIM) {
                val last = windowLatents[c * config.rung + framesAvail - 1]
                for (f in framesAvail until config.rung) windowLatents[c * config.rung + f] = last
            }
        }
        val planar = engine.runWindow(windowLatents)
        val dtMs = (System.nanoTime() - t0) / 1e6

        val effLo = maxOf(win.keepLo, emittedLatents - win.start)
        val effCoreFrames = win.keepHi - effLo
        var coreSamples = effCoreFrames * SAMPLES_PER_LATENT
        val absStart = (win.start + effLo).toLong() * SAMPLES_PER_LATENT
        if (absStart + coreSamples > m.origSamples) {
            coreSamples = maxOf(0, (m.origSamples - absStart).toInt())
        }
        emittedLatents = win.start + effLo + effCoreFrames
        val perChannel = config.rung * SAMPLES_PER_LATENT
        val off = effLo * SAMPLES_PER_LATENT
        val out = Array(2) { ch ->
            FloatArray(coreSamples).also {
                System.arraycopy(planar, ch * perChannel + off, it, 0, coreSamples)
            }
        }

        stats.windowsDecoded++
        stats.totalWindowMs += dtMs
        stats.lastWindowMs = dtMs
        if (dtMs > stats.maxWindowMs) stats.maxWindowMs = dtMs
        stats.totalCoreMs += coreSamples * 1000.0 / m.sampleRate
        windowIndex++
        return out
    }

    /** Seek so the next decoded audio starts at or before [positionMs]; returns actual start ms. */
    fun seekTo(positionMs: Long): Long {
        val m = metadata ?: error("no track open")
        val targetLatent = ((positionMs * m.sampleRate / 1000) / SAMPLES_PER_LATENT).toInt()
        var idx = windows.indexOfLast { it.coreStart <= targetLatent }
        if (idx < 0) idx = 0
        windowIndex = idx
        emittedLatents = windows[idx].coreStart
        return windows[idx].coreStart.toLong() * SAMPLES_PER_LATENT * 1000 / m.sampleRate
    }

    fun reset() {
        windowIndex = 0
        emittedLatents = 0
    }

    private fun closeTrack() {
        reader?.close()
        reader = null
        windows = emptyList()
        windowIndex = 0
    }

    override fun close() {
        closeTrack()
        engine.close()
    }

    companion object {
        const val LATENT_DIM = 256
        const val SAMPLES_PER_LATENT = 4096

        /** Preferred: LiteRT CompiledModel from an APK asset. */
        fun fromAsset(assetManager: AssetManager, assetName: String, config: Config = Config()): SameDecoder {
            require(config.engine == EngineKind.COMPILED) { "fromAsset requires COMPILED engine" }
            val cm = CompiledModel.create(assetManager, assetName, compiledOptions(config))
            return SameDecoder(CompiledEngine(cm, config.rung), config)
        }

        /** LiteRT CompiledModel from a filesystem path. */
        fun fromFile(path: String, config: Config = Config()): SameDecoder {
            require(config.engine == EngineKind.COMPILED) { "fromFile requires COMPILED engine" }
            val cm = CompiledModel.create(path, compiledOptions(config))
            return SameDecoder(CompiledEngine(cm, config.rung), config)
        }

        /** Classic Interpreter over a memory-mapped model buffer. */
        fun fromMappedBuffer(model: MappedByteBuffer, config: Config = Config()): SameDecoder {
            return SameDecoder(ClassicEngine(model, config), config)
        }

        private fun compiledOptions(config: Config): CompiledModel.Options {
            val opts = CompiledModel.Options(setOf(Accelerator.CPU))
            opts.cpuOptions = CompiledModel.CpuOptions(
                numThreads = config.threads,
                xnnPackWeightCachePath = config.weightCachePath ?: "",
            )
            return opts
        }
    }
}
