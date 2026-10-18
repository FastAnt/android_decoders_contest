package com.sagecodec.decoder

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.pow
import kotlin.math.sin
import kotlin.math.sqrt

/**
 * Spectrogram-to-PCM stage of the SAGE decoder.
 *
 * The LiteRT graph stops at the transformed stereo STFT in grouped layout
 * `[Re_L, Re_R, Im_L, Im_R]`, 1024 bins (Nyquist cropped).  This object applies
 * the inverse power-law pre-transform (alpha 0.65, beta 0.35) and a centered
 * Hann iSTFT (n_fft 2048, hop 512), matching `torch.istft` to ~1e-7.
 *
 * Decoding is block-local: each fixed-rung window carries at least 32 steps of
 * context, so a core block can be synthesized with 3 frames of context on each
 * side and then emitted.  This avoids keeping a whole-track spectrogram or PCM
 * buffer in memory.
 */
object SageDsp {
    private const val N = SageConstants.N_FFT
    private const val BINS = SageConstants.BINS
    private const val HOP = SageConstants.STFT_HOP
    private const val SAMPLES_PER_STEP = SageConstants.SAMPLES_PER_STEP
    private const val ALPHA = 0.65
    private const val BETA = 0.35
    private const val EPS = 1e-8
    private const val EPS_POW = 1e-8
    private const val INV_ALPHA = 1.0 / 0.65
    private const val CONTEXT_FRAMES = 3

    private val window = FloatArray(N) { n ->
        (0.5 - 0.5 * cos(2.0 * PI * n / N)).toFloat()
    }
    private val windowSq = FloatArray(N) { window[it] * window[it] }

    private val cosTable = FloatArray(N / 2) { k -> cos(2.0 * PI * k / N).toFloat() }
    private val sinTable = FloatArray(N / 2) { k -> sin(2.0 * PI * k / N).toFloat() }
    private val bitReverse = IntArray(N) { Integer.reverse(it) ushr (32 - 11) }

    /**
     * Decode the core of one rung window.
     *
     * @param spec TFLite output, `(4, 1024, 4*rung)` row-major.
     * @param windowFrames number of STFT frames in [spec] (`4*rung`).
     * @param coreStartStep core start, in latent steps relative to the window.
     * @param coreSteps core length, in latent steps.
     * @param rung window length, in latent steps.
     * @return planar PCM, `[L..., R...]`, of `coreSteps * 2048` samples.
     */
    fun decodeWindow(
        spec: FloatArray,
        windowFrames: Int,
        coreStartStep: Int,
        coreSteps: Int,
        rung: Int,
    ): FloatArray {
        require(spec.size >= 4 * BINS * windowFrames) {
            "spec has ${spec.size}, expected ${4 * BINS * windowFrames}"
        }
        val f0Step = maxOf(0, coreStartStep - CONTEXT_FRAMES)
        val f1Step = minOf(rung, coreStartStep + coreSteps + CONTEXT_FRAMES)
        val frameCount = (f1Step - f0Step) * 4
        val outLen = maxOf(0, (frameCount - 1) * HOP)
        val length = coreSteps * SAMPLES_PER_STEP
        val out = FloatArray(2 * length)
        if (frameCount <= 1 || outLen <= 0) return out

        val accL = FloatArray(outLen + N)
        val accR = FloatArray(outLen + N)
        val norm = FloatArray(outLen + N)
        val re = FloatArray(N)
        val im = FloatArray(N)
        val fftRe = FloatArray(N)
        val fftIm = FloatArray(N)

        for (t in 0 until frameCount) {
            val frame = f0Step * 4 + t
            for (c in 0..1) {
                val baseRe = (c * BINS) * windowFrames + frame
                val baseIm = ((2 + c) * BINS) * windowFrames + frame
                for (k in 0 until BINS) {
                    val r = spec[baseRe + k * windowFrames]
                    val i = spec[baseIm + k * windowFrames]
                    val mag = sqrt(r * r + i * i)
                    var ur = 0f
                    var ui = 0f
                    if (mag > EPS) {
                        ur = r / mag
                        ui = i / mag
                    }
                    val scaled = maxOf(mag / BETA, EPS_POW)
                    val restored = scaled.toDouble().pow(INV_ALPHA).toFloat()
                    val or = ur * restored
                    val oi = ui * restored
                    fftRe[k] = if (or.isFinite()) or else 0f
                    fftIm[k] = if (oi.isFinite()) oi else 0f
                }
                fftRe[BINS] = 0f
                fftIm[BINS] = 0f
                for (k in 1 until BINS) {
                    fftRe[N - k] = fftRe[k]
                    fftIm[N - k] = -fftIm[k]
                }
                inverseFft(fftRe, fftIm)

                val acc = if (c == 0) accL else accR
                val p = t * HOP - N / 2
                var n = 0
                while (n < N) {
                    val idx = p + n
                    if (idx in 0 until outLen) {
                        val w = window[n]
                        acc[idx] += fftRe[n] * w
                        if (c == 0) norm[idx] += windowSq[n]
                    }
                    n++
                }
            }
        }

        for (i in 0 until outLen) {
            val nv = norm[i]
            if (nv > 1e-11f) {
                accL[i] /= nv
                accR[i] /= nv
            }
        }

        val localStart = (coreStartStep - f0Step) * SAMPLES_PER_STEP
        val take = minOf(length, maxOf(0, outLen - localStart))
        if (take > 0) {
            System.arraycopy(accL, localStart, out, 0, take)
            System.arraycopy(accR, localStart, out, length, take)
        }
        return out
    }

    /** In-place inverse FFT (sign +, 1/N scaling), radix-2 DIT. */
    private fun inverseFft(re: FloatArray, im: FloatArray) {
        var i = 0
        while (i < N) {
            val j = bitReverse[i]
            if (j > i) {
                val tr = re[i]; re[i] = re[j]; re[j] = tr
                val ti = im[i]; im[i] = im[j]; im[j] = ti
            }
            i++
        }
        var len = 2
        while (len <= N) {
            val half = len / 2
            val step = N / len
            var start = 0
            while (start < N) {
                var j = 0
                var k = 0
                while (j < half) {
                    val wr = cosTable[k]
                    val wi = sinTable[k]
                    val a = start + j
                    val b = a + half
                    val vr = re[b] * wr - im[b] * wi
                    val vi = re[b] * wi + im[b] * wr
                    re[b] = re[a] - vr
                    im[b] = im[a] - vi
                    re[a] += vr
                    im[a] += vi
                    j++
                    k += step
                }
                start += len
            }
            len = len shl 1
        }
        val scale = 1.0f / N
        for (idx in 0 until N) {
            re[idx] *= scale
            im[idx] *= scale
        }
    }
}
