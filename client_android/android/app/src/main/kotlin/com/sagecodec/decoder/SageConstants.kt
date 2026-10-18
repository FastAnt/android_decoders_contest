package com.sagecodec.decoder

/**
 * Fixed geometry of the SAGE_FTe992 decoder and the `.sage` container.
 *
 * SAGE latents are (16 channels, 4 frequency bands, T time steps).  One time
 * step covers four STFT frames (hop 512) = 2048 PCM samples at 44.1 kHz.
 */
object SageConstants {
    const val SAMPLE_RATE = 44100
    const val LATENT_CHANNELS = 16
    const val BANDS = 4
    const val LATENT_ROWS = LATENT_CHANNELS * BANDS // 64 container rows
    const val STFT_HOP = 512
    const val SAMPLES_PER_STEP = 4 * STFT_HOP // 2048
    const val N_FFT = 2048
    const val BINS = 1024 // Nyquist bin is cropped by SAGE

    /** SAGE's time grid: the collapsed Swin stage's window (32 latent steps). */
    const val TIME_GRID = 32

    /** Decoder rung exported into the LiteRT model. */
    const val DEFAULT_RUNG = 128

    /** Context discarded on the inner side of every window (32 steps = 1.49 s). */
    const val DEFAULT_TRIM = 32

    const val MODEL_ID_SAGE = 2

    const val MODEL_ASSET = "dec_w8a8.tflite"
    const val MODEL_ASSET_FP32 = "dec_fp32.tflite"
}
