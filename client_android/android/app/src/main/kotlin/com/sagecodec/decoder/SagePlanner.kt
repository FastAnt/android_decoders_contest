package com.sagecodec.decoder

/**
 * Window plan for fixed-rung SAGE decoding.
 *
 * Two constraints come from the model, not from taste:
 *  - every window start must be a multiple of [grid] (32 latent steps), or the
 *    Swin window/shift phase differs from a one-pass decode;
 *  - the temporal receptive field is ~16 steps, so [trim] steps of context are
 *    discarded on the inner side of each window.
 *
 * The timeline is padded up to a multiple of the grid with edge-replicated
 * latents.  Cores partition the padded timeline exactly; the decoder trims the
 * emitted PCM to `origSamples`.
 */
object SagePlanner {
    data class Window(val start: Int, val coreStart: Int, val coreEnd: Int) {
        val inputFrames: Int get() = coreEnd - coreStart
    }

    fun paddedTotal(total: Int, rung: Int, grid: Int = SageConstants.TIME_GRID): Int {
        if (total <= 0) return rung
        val rounded = ((total + grid - 1) / grid) * grid
        return maxOf(rung, rounded)
    }

    fun plan(total: Int, rung: Int = SageConstants.DEFAULT_RUNG,
             trim: Int = SageConstants.DEFAULT_TRIM,
             grid: Int = SageConstants.TIME_GRID): List<Window> {
        require(total > 0) { "total must be > 0" }
        require(rung > 0 && rung % grid == 0) { "rung $rung must be a positive multiple of $grid" }
        require(trim % grid == 0) { "trim $trim must be a multiple of $grid" }
        val step = rung - 2 * trim
        require(step > 0 && step % grid == 0) { "rung $rung cannot tile with trim $trim" }

        val padded = paddedTotal(total, rung, grid)
        if (padded <= rung) {
            return listOf(Window(0, 0, minOf(total, rung)))
        }
        val n = (padded + step - 1) / step
        val out = ArrayList<Window>(n)
        for (k in 0 until n) {
            val a = k * step
            val b = minOf(a + step, padded)
            val s = if (k == 0) 0 else minOf(a - trim, padded - rung)
            require(s >= 0 && s % grid == 0) { "unaligned start $s for core [$a,$b)" }
            out.add(Window(s, a, b))
        }
        return out
    }
}
