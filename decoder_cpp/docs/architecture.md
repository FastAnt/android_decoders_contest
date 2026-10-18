# Architecture

## Pipeline

```
┌──────────────┐
│  .sst file   │
└──────┬───────┘
       │
       ▼
┌──────────────┐   CRC32 verify, 10-bit unpack
│  SstReader   │   codebook-major → frame-major transpose
└──────┬───────┘
       │ TokenStream [frames, 64]
       ▼
┌──────────────────┐   64 codebooks × 1024 entries × 256 dims
│ RvqDequantizer   │   Sum 64 embedding vectors per frame
└──────┬───────────┘
       │ embeddings [25, 256] per block
       ▼
┌──────────────┐   TFLite interpreter + XNNPACK delegate
│ LiteRtRunner │   Input: [1, 25, 256] → Output: [1, 2, 100, 481, 2]
└──────┬───────┘
       │ spectrum (real/imag)
       ▼
┌──────────────┐   PocketFFT c2r, window multiply, overlap-add
│    Istft     │   960-point IRFFT, hop=480, 100 frames → 48000 samples
└──────┬───────┘
       │ interleaved float32 PCM [48000 × 2]
       ▼
┌──────────────┐   Float→int16 with clipping
│  WavWriter   │   RIFF/WAV header, PCM16 stereo 48kHz
└──────────────┘
```

## Block Processing

The decoder processes audio in 1-second neural blocks (25 codec frames):

1. Tokens are batched into groups of 25
2. Each batch goes through RVQ → LiteRT → iSTFT
3. PCM output from all blocks is concatenated
4. Final output is trimmed to `original_samples` from SST header

The last block may have fewer than 25 frames; it is zero-padded before
inference and excess samples are trimmed by the `original_samples` limit.

## Layer Separation

```
include/spectrostream/
  decoder_c_api.h   ← Stable C ABI for FFI (Flutter/Dart, JNI)
  decoder.h         ← C++ high-level API
  sst_reader.h      ← Container parsing
  rvq_dequantizer.h ← Codebook lookup
  litert_runner.h   ← Neural inference
  istft.h           ← Signal processing
  wav_writer.h      ← File output
```

C ABI does not expose STL types. Internal C++ code uses `std::vector`,
`std::unique_ptr`, RAII. The C API allocates output via `malloc()`, caller
frees with `spectrostream_decoder_free_pcm()`.

## Thread Safety

- `Decoder` is NOT thread-safe (TFLite interpreter is single-owner)
- Each thread should create its own `Decoder` instance
- Read-only assets (codebooks, window) are shared within a `Decoder` instance

## Platform Strategy

Core code is platform-independent C++20. Platform-specific concerns:

- **Linux x86-64**: Direct build, all features
- **Android arm64-v8a**: NDK cross-compile, XNNPACK for NEON
- **Flutter**: C ABI via `dart:ffi`, `libspectrostream_decoder.so`
