// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 FastAnt
package com.samecodec.decoder

import java.io.File
import java.io.RandomAccessFile
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.zip.CRC32
import java.util.zip.Inflater

/** Thrown for malformed or unsupported .same files. */
class SameFormatException(message: String) : Exception(message)

/** Random-access byte source for a .same file (file, memory, or HTTP range). */
interface SameSource {
    val size: Long
    fun readAt(offset: Long, length: Int): ByteArray
    fun close() {}
}

class FileSameSource(file: File) : SameSource {
    private val raf = RandomAccessFile(file, "r")
    override val size: Long = raf.length()
    @Synchronized
    override fun readAt(offset: Long, length: Int): ByteArray {
        val buf = ByteArray(length)
        raf.seek(offset)
        raf.readFully(buf)
        return buf
    }
    override fun close() = raf.close()
}

class ByteArraySameSource(private val data: ByteArray) : SameSource {
    override val size: Long = data.size.toLong()
    override fun readAt(offset: Long, length: Int): ByteArray =
        data.copyOfRange(offset.toInt(), offset.toInt() + length)
}

data class SameMetadata(
    val quantMode: Int,
    val entropy: Int,
    val channels: Int,
    val sampleRate: Int,
    val origSamples: Long,
    val latentDim: Int,
    val storedFrames: Int,
    val validFrames: Int,
    val chunkFrames: Int,
    val numChunks: Int,
    val modelId: Int,
    val flags: Int,
    val fileSize: Long,
) {
    val durationSec: Double get() = origSamples.toDouble() / sampleRate
    val bitrateKbps: Double get() = fileSize * 8.0 / durationSec / 1000.0
    val quantName: String get() = QUANT_NAMES.getOrElse(quantMode) { "?$quantMode" }

    companion object {
        val QUANT_NAMES = mapOf(
            0 to "fp32", 1 to "fp16", 2 to "bf16",
            3 to "int8-pc", 4 to "int8-pchunk", 5 to "int8-pt",
        )
    }
}

/**
 * Reader for the `.same` v1 container (see samec/format.py for the spec).
 * Dequantizes storage chunks to float latents on demand, with CRC32 checks.
 */
class SameReader(private val source: SameSource) {
    val metadata: SameMetadata
    private val globalParams: FloatArray? // (rows*2) [scale, min] pairs for int8-pc / int8-pt
    private val tocOffset: LongArray
    private val tocLength: IntArray
    private val tocFrames: IntArray
    private val tocCrc: LongArray

    init {
        val header = source.readAt(0, HEADER_LEN)
        val buf = ByteBuffer.wrap(header).order(ByteOrder.LITTLE_ENDIAN)
        val magic = ByteArray(4).also { buf.get(it) }
        if (!magic.contentEquals(MAGIC) && !magic.contentEquals(MAGIC_SAGE))
            throw SameFormatException("bad magic, not a .same/.sage file")
        val version = buf.short.toInt()
        if (version != VERSION) throw SameFormatException("unsupported .same version $version")
        val headerLen = buf.short.toInt()
        if (headerLen != HEADER_LEN) throw SameFormatException("unsupported header length $headerLen")
        val quantMode = buf.get().toInt()
        val entropy = buf.get().toInt()
        val channels = buf.get().toInt()
        buf.get() // reserved
        val sampleRate = buf.int
        val origSamples = buf.long
        val latentDim = buf.int
        val storedFrames = buf.int
        val validFrames = buf.int
        val chunkFrames = buf.int
        val numChunks = buf.int
        val tocOffsetPos = buf.long
        val modelId = buf.int
        val flags = buf.int
        val storedCrc = buf.int.toLong() and 0xFFFFFFFFL
        val crc = CRC32()
        crc.update(header, 0, HEADER_LEN - 4)
        if (crc.value != storedCrc) throw SameFormatException("header CRC32 mismatch")
        if (quantMode !in 0..5) throw SameFormatException("unknown quant mode $quantMode")
        if (entropy !in 0..1) throw SameFormatException("unknown entropy mode $entropy")

        globalParams = when (quantMode) {
            Q_INT8_PC -> readFloats(HEADER_LEN.toLong(), latentDim * 2)
            Q_INT8_PT -> readFloats(HEADER_LEN.toLong(), 2)
            else -> null
        }

        val tocBytes = source.readAt(tocOffsetPos, numChunks * TOC_ENTRY_SIZE)
        val tb = ByteBuffer.wrap(tocBytes).order(ByteOrder.LITTLE_ENDIAN)
        tocOffset = LongArray(numChunks)
        tocLength = IntArray(numChunks)
        tocFrames = IntArray(numChunks)
        tocCrc = LongArray(numChunks)
        for (i in 0 until numChunks) {
            tocOffset[i] = tb.long
            tocLength[i] = tb.int
            tocFrames[i] = tb.int
            tocCrc[i] = tb.int.toLong() and 0xFFFFFFFFL
        }
        metadata = SameMetadata(
            quantMode, entropy, channels, sampleRate, origSamples, latentDim,
            storedFrames, validFrames, chunkFrames, numChunks, modelId, flags, source.size,
        )
    }

    private fun readFloats(offset: Long, count: Int): FloatArray {
        val bytes = source.readAt(offset, count * 4)
        val out = FloatArray(count)
        ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer().get(out)
        return out
    }

    /** Read and dequantize storage chunk [index] into [out] (latentDim x frames, row-major). Returns frames. */
    fun readChunkInto(index: Int, out: FloatArray): Int {
        val m = metadata
        if (index !in 0 until m.numChunks) throw SameFormatException("chunk index $index out of range")
        val frames = tocFrames[index]
        var blob = source.readAt(tocOffset[index], tocLength[index])
        val crc = CRC32()
        crc.update(blob)
        if (crc.value != tocCrc[index]) throw SameFormatException("chunk $index CRC32 mismatch (corrupt file)")

        var params: FloatArray? = globalParams
        var payloadOff = 0
        if (m.quantMode == Q_INT8_PCHUNK) {
            val n = m.latentDim * 2
            params = FloatArray(n)
            ByteBuffer.wrap(blob, 0, n * 4).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer().get(params)
            payloadOff = n * 4
        }
        if (m.entropy == ENTROPY_ZLIB) {
            val expected = m.latentDim * frames * BYTES_PER_ELEM[m.quantMode]
            val raw = ByteArray(expected)
            val inf = Inflater()
            inf.setInput(blob, payloadOff, blob.size - payloadOff)
            val n = inf.inflate(raw)
            inf.end()
            if (n != expected) throw SameFormatException("chunk $index: zlib size $n != expected $expected")
            blob = raw
            payloadOff = 0
        }
        dequantize(blob, payloadOff, m.quantMode, m.latentDim, frames, params, out)
        return frames
    }

    /** Read latents [start, start+frames) into [out], spanning storage chunks as needed. */
    fun readLatentsInto(start: Int, frames: Int, out: FloatArray) {
        val m = metadata
        val dim = m.latentDim
        require(out.size >= dim * frames) { "output buffer too small" }
        var pos = start
        val end = start + frames
        val tmp = FloatArray(dim * m.chunkFrames)
        while (pos < end) {
            val ci = pos / m.chunkFrames
            val within = pos - ci * m.chunkFrames
            val cf = readChunkInto(ci, tmp)
            val take = minOf(cf - within, end - pos)
            // copy rows: tensor layout is (dim, frames) row-major
            for (c in 0 until dim) {
                System.arraycopy(tmp, c * cf + within, out, c * frames + (pos - start), take)
            }
            pos += take
        }
    }

    fun close() = source.close()

    companion object {
        const val HEADER_LEN = 64
        const val VERSION = 1
        const val TOC_ENTRY_SIZE = 20
        const val SAMPLES_PER_LATENT = 4096
        val MAGIC = byteArrayOf(0x53, 0x41, 0x4D, 0x45) // "SAME"
        /** SAGE shares the container layout; magic "SAGE", modelId 2, latentDim 64. */
        val MAGIC_SAGE = byteArrayOf(0x53, 0x41, 0x47, 0x45) // "SAGE"
        const val MODEL_SAME_S = 1
        const val MODEL_SAGE = 2

        const val Q_FP32 = 0
        const val Q_FP16 = 1
        const val Q_BF16 = 2
        const val Q_INT8_PC = 3
        const val Q_INT8_PCHUNK = 4
        const val Q_INT8_PT = 5
        const val ENTROPY_ZLIB = 1
        private val BYTES_PER_ELEM = intArrayOf(4, 2, 2, 1, 1, 1)

        internal fun dequantize(
            raw: ByteArray, off: Int, mode: Int, dim: Int, frames: Int,
            params: FloatArray?, out: FloatArray,
        ) {
            val n = dim * frames
            when (mode) {
                Q_FP32 -> ByteBuffer.wrap(raw, off, n * 4).order(ByteOrder.LITTLE_ENDIAN)
                    .asFloatBuffer().get(out, 0, n)
                Q_FP16 -> {
                    val sb = ByteBuffer.wrap(raw, off, n * 2).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
                    for (i in 0 until n) out[i] = halfToFloat(sb.get(i).toInt())
                }
                Q_BF16 -> {
                    var p = off
                    for (i in 0 until n) {
                        val bits = ((raw[p].toInt() and 0xFF) or ((raw[p + 1].toInt() and 0xFF) shl 8)) shl 16
                        out[i] = Float.fromBits(bits)
                        p += 2
                    }
                }
                Q_INT8_PT -> {
                    val scale = params!![0]
                    val min = params[1]
                    for (i in 0 until n) out[i] = (raw[off + i].toInt() and 0xFF) * scale + min
                }
                Q_INT8_PC, Q_INT8_PCHUNK -> {
                    val prm = params!!
                    var p = off
                    for (c in 0 until dim) {
                        val scale = prm[c * 2]
                        val min = prm[c * 2 + 1]
                        val base = c * frames
                        for (f in 0 until frames) {
                            out[base + f] = (raw[p++].toInt() and 0xFF) * scale + min
                        }
                    }
                }
                else -> throw SameFormatException("unknown quant mode $mode")
            }
        }

        internal fun halfToFloat(h: Int): Float {
            val sign = (h shr 15) and 1
            val exp = (h shr 10) and 0x1F
            val frac = h and 0x3FF
            return when {
                exp == 0 -> {
                    if (frac == 0) {
                        if (sign == 1) -0.0f else 0.0f
                    } else {
                        var e = -14
                        var f = frac
                        while (f and 0x400 == 0) {
                            f = f shl 1
                            e--
                        }
                        val bits = (sign shl 31) or ((e + 127) shl 23) or ((f and 0x3FF) shl 13)
                        Float.fromBits(bits)
                    }
                }
                exp == 0x1F -> Float.fromBits((sign shl 31) or (0xFF shl 23) or (frac shl 13))
                else -> Float.fromBits((sign shl 31) or ((exp - 15 + 127) shl 23) or (frac shl 13))
            }
        }
    }
}
