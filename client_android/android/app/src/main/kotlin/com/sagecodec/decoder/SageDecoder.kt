package com.sagecodec.decoder

import android.content.res.AssetManager
import com.google.ai.edge.litert.Accelerator
import com.google.ai.edge.litert.CompiledModel
import com.google.ai.edge.litert.TensorBuffer
import com.samecodec.decoder.SameFormatException
import com.samecodec.decoder.SameMetadata
import com.samecodec.decoder.SameReader
import com.samecodec.decoder.SameSource
import org.tensorflow.lite.Interpreter
import java.io.Closeable
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.MappedByteBuffer

/** Per-window decode statistics (neural decoder only; iSTFT is outside). */
data class SageDecoderStats(
    var windowsDecoded: Long = 0,
    var totalWindowMs: Double = 0.0,
    var lastWindowMs: Double = 0.0,
    var maxWindowMs: Double = 0.0,
    var totalCoreMs: Double = 0.0,
) {
    val avgWindowMs: Double get() = if (windowsDecoded > 0) totalWindowMs / windowsDecoded else 0.0
    val rtf: Double get() = if (totalCoreMs > 0) totalWindowMs / totalCoreMs else 0.0
    fun reset() {
        windowsDecoded = 0; totalWindowMs = 0.0; lastWindowMs = 0.0
        maxWindowMs = 0.0; totalCoreMs = 0.0
    }
}

/**
 * SAGE neural audio decoder: `.sage` container -> stereo PCM.
 *
 * The LiteRT model decodes one fixed rung of 256 latent steps (11.9 s of audio)
 * to a 4x1024x1024 transformed STFT.  [SagePlanner] tiles a track into
 * grid-aligned windows with 32 steps of discarded context; [SageDsp] turns the
 * kept core into PCM.  Interior windows are bit-exact with a one-pass decode
 * (measured >100 dB spectral SNR on the 276 s test track).
 *
 * Not thread-safe: call from a single decoder thread, never from the UI thread.
 */
class SageDecoder private constructor(
    private val engine: Engine,
    val config: Config,
) : Closeable {

    enum class EngineKind { COMPILED, CLASSIC }

    data class Config(
        val threads: Int = 4,
        val rung: Int = SageConstants.DEFAULT_RUNG,
        val trim: Int = SageConstants.DEFAULT_TRIM,
        val engine: EngineKind = EngineKind.COMPILED,
        /** XNNPACK weight-cache path for the COMPILED engine (null/empty = no cache). */
        val weightCachePath: String? = null,
    )

    private interface Engine : Closeable {
        /** [latents] is (64, rung) row-major; returns (4, 1024, 4*rung). */
        fun runWindow(latents: FloatArray): FloatArray
    }

    private class CompiledEngine(model: CompiledModel, private val rung: Int) : Engine {
        private val cm = model
        private val sig = "serving_default"
        private val inputs: List<TensorBuffer> = model.createInputBuffers(sig)
        private val outputs: List<TensorBuffer> = model.createOutputBuffers(sig)

        override fun runWindow(latents: FloatArray): FloatArray {
            inputs[0].writeFloat(latents)
            cm.run(inputs, outputs, sig)
            return outputs[0].readFloat()
        }

        override fun close() {
            inputs.forEach { it.close() }
            outputs.forEach { it.close() }
            cm.close()
        }
    }

    private class ClassicEngine(model: MappedByteBuffer, config: Config) : Engine {
        private val interpreter: Interpreter
        private val inputBuffer: ByteBuffer
        private val outputBuffer: ByteBuffer
        private val outputFloats: FloatArray

        init {
            val opts = Interpreter.Options().apply {
                setNumThreads(config.threads)
                setUseXNNPACK(true)
            }
            interpreter = Interpreter(model, opts)
            val inFloats = SageConstants.LATENT_ROWS * config.rung
            val outFloats = 4 * SageConstants.BINS * 4 * config.rung
            inputBuffer = ByteBuffer.allocateDirect(inFloats * 4).order(ByteOrder.nativeOrder())
            outputBuffer = ByteBuffer.allocateDirect(outFloats * 4).order(ByteOrder.nativeOrder())
            outputFloats = FloatArray(outFloats)
        }

        override fun runWindow(latents: FloatArray): FloatArray {
            inputBuffer.rewind()
            inputBuffer.asFloatBuffer().put(latents)
            inputBuffer.rewind()
            outputBuffer.rewind()
            interpreter.run(inputBuffer, outputBuffer)
            outputBuffer.rewind()
            outputBuffer.asFloatBuffer().get(outputFloats)
            return outputFloats
        }

        override fun close() = interpreter.close()
    }

    private var reader: SameReader? = null
    private var windows: List<SagePlanner.Window> = emptyList()
    private var windowIndex = 0
    private var currentOutput: FloatArray = FloatArray(0)

    val stats = SageDecoderStats()
    val availableRungs: List<Int> get() = listOf(config.rung)
    val metadata: SameMetadata? get() = reader?.metadata
    val nextWindowIndex: Int get() = windowIndex
    val windowCount: Int get() = windows.size

    val positionSamples: Long
        get() {
            val m = metadata ?: return 0
            if (windowIndex >= windows.size) return m.origSamples
            return windows[windowIndex].coreStart.toLong() * SageConstants.SAMPLES_PER_STEP
        }

    fun open(source: SameSource) {
        closeTrack()
        val r = SameReader(source)
        val m = r.metadata
        if (m.modelId != SageConstants.MODEL_ID_SAGE) {
            r.close()
            throw SameFormatException(
                "not a SAGE file: model_id=${m.modelId} (expected ${SageConstants.MODEL_ID_SAGE})")
        }
        if (m.latentDim != SageConstants.LATENT_ROWS) {
            r.close()
            throw SameFormatException("SAGE latent rows=${m.latentDim}, expected ${SageConstants.LATENT_ROWS}")
        }
        if (m.channels != 2 || m.sampleRate != SageConstants.SAMPLE_RATE) {
            r.close()
            throw SameFormatException("SAGE requires 2ch @ 44100, got ${m.channels}ch @ ${m.sampleRate}")
        }
        reader = r
        windows = SagePlanner.plan(m.storedFrames, config.rung, config.trim)
        windowIndex = 0
        stats.reset()
    }

    /**
     * Decode the next core.  Returns planar `Array(2) { FloatArray }` or null at
     * end of track.  The final chunk is trimmed to `origSamples`.
     */
    fun decodeNextChunk(): Array<FloatArray>? {
        val r = reader ?: error("no track open")
        val m = r.metadata
        while (windowIndex < windows.size) {
            val win = windows[windowIndex]
            val t0 = System.nanoTime()
            val latents = readWindowLatents(r, win.start)
            val spec = engine.runWindow(latents)
            val dtMs = (System.nanoTime() - t0) / 1e6

            val coreStart = win.coreStart - win.start
            val coreSteps = win.coreEnd - win.coreStart
            currentOutput = SageDsp.decodeWindow(
                spec, 4 * config.rung, coreStart, coreSteps, config.rung,
            )
            val absStart = (win.start + coreStart).toLong() * SageConstants.SAMPLES_PER_STEP
            var samples = coreSteps * SageConstants.SAMPLES_PER_STEP
            if (absStart >= m.origSamples) samples = 0
            else if (absStart + samples > m.origSamples) samples = (m.origSamples - absStart).toInt()

            stats.windowsDecoded++
            stats.totalWindowMs += dtMs
            stats.lastWindowMs = dtMs
            if (dtMs > stats.maxWindowMs) stats.maxWindowMs = dtMs
            if (samples > 0) stats.totalCoreMs += samples * 1000.0 / m.sampleRate
            windowIndex++

            if (samples <= 0) continue
            val out = Array(2) { FloatArray(samples) }
            System.arraycopy(currentOutput, 0, out[0], 0, samples)
            System.arraycopy(currentOutput, coreSteps * SageConstants.SAMPLES_PER_STEP, out[1], 0, samples)
            return out
        }
        return null
    }

    private fun readWindowLatents(r: SameReader, start: Int): FloatArray {
        val m = r.metadata
        val rows = SageConstants.LATENT_ROWS
        val rung = config.rung
        val out = FloatArray(rows * rung)
        val available = minOf(rung, maxOf(0, m.storedFrames - start))
        if (available <= 0) {
            val tmp = FloatArray(rows)
            r.readLatentsInto(m.storedFrames - 1, 1, tmp)
            for (c in 0 until rows) {
                java.util.Arrays.fill(out, c * rung, c * rung + rung, tmp[c])
            }
            return out
        }
        if (available == rung) {
            r.readLatentsInto(start, rung, out)
            return out
        }
        val tmp = FloatArray(rows * available)
        r.readLatentsInto(start, available, tmp)
        for (c in 0 until rows) {
            System.arraycopy(tmp, c * available, out, c * rung, available)
            val last = tmp[c * available + available - 1]
            java.util.Arrays.fill(out, c * rung + available, c * rung + rung, last)
        }
        return out
    }

    /** Seek so the next decoded audio starts at or before [positionMs]. Returns actual start ms. */
    fun seekTo(positionMs: Long): Long {
        val m = metadata ?: error("no track open")
        val targetStep = ((positionMs * m.sampleRate / 1000) / SageConstants.SAMPLES_PER_STEP).toInt()
        var idx = windows.indexOfLast { it.coreStart <= targetStep }
        if (idx < 0) idx = 0
        windowIndex = idx
        return windows[idx].coreStart.toLong() * SageConstants.SAMPLES_PER_STEP * 1000 / m.sampleRate
    }

    fun reset() {
        windowIndex = 0
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
        fun fromAsset(
            assetManager: AssetManager,
            assetName: String = SageConstants.MODEL_ASSET,
            config: Config = Config(),
        ): SageDecoder {
            require(config.engine == EngineKind.COMPILED) { "fromAsset requires the COMPILED engine" }
            val cm = CompiledModel.create(assetManager, assetName, compiledOptions(config))
            return SageDecoder(CompiledEngine(cm, config.rung), config)
        }

        fun fromFile(path: String, config: Config = Config()): SageDecoder {
            require(config.engine == EngineKind.COMPILED) { "fromFile requires the COMPILED engine" }
            val cm = CompiledModel.create(path, compiledOptions(config))
            return SageDecoder(CompiledEngine(cm, config.rung), config)
        }

        fun fromMappedBuffer(model: MappedByteBuffer, config: Config = Config()): SageDecoder {
            return SageDecoder(ClassicEngine(model, config), config)
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
