# decoder_cpp — Implementation Report

> Historical report. Measurements reflect the environment, model versions and code at the time of the experiment.

## Status: context-aware decode implemented and verified

Pipeline: `.sst` → 10-bit unpack → RVQ dequant → LiteRT inference → C++ iSTFT → PCM16 WAV.

Boundary artifacts eliminated. Sample-exact output. Formal verification against the Python q64 reference passed.

---

## Launch commands

```bash
cd decoder_cpp

# Context-aware decode (high quality, no boundary artifacts):
./build/spectrostream_decode \
  --model models/spectrostream_decoder_core_fp32_f75.tflite \
  --codebooks models/rvq_codebooks.f32 \
  --window models/istft_window_f960.f32 \
  --input ../media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f/069569e7525fdd1e462b9f5b1a394a9f.sst \
  --output ../media/reconstructed/cpp/reconstructed_cpp_ctx.wav \
  --threads 8

# Fast mode (RTF < 1, boundary artifacts present):
./build/spectrostream_decode \
  --model models/spectrostream_decoder_core_fp32_f25.tflite \
  --codebooks models/rvq_codebooks.f32 \
  --window models/istft_window_f960.f32 \
  --input ../media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f/069569e7525fdd1e462b9f5b1a394a9f.sst \
  --output ../media/reconstructed/cpp/reconstructed_cpp.wav \
  --threads 8

# Container inspection only:
./build/spectrostream_decode --inspect \
  --input ../media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f/069569e7525fdd1e462b9f5b1a394a9f.sst
```

---

## Run result (f75, context-aware)

```
INFO: Created TensorFlow Lite XNNPACK delegate for CPU.
SpectroStream C++ Decoder
========================
Model + assets loaded in 168.9 ms

=== Decode Timing ===
SST parse:           5.4 ms
RVQ dequant:       140.1 ms
LiteRT infer:   398671.1 ms
iSTFT:             565.0 ms
Total decode:   399437.8 ms

Audio duration: 162.075 s
RTF:            2.4645
Sample rate:    48000 Hz
Channels:       2
PCM frames:     7779614

Written: reconstructed_cpp_ctx.wav (PCM16 stereo 48kHz)
```

---

## Verification against the Python q64 reference

Reference: `media/data/reconstructed/069569e7525fdd1e462b9f5b1a394a9f/069569e7525fdd1e462b9f5b1a394a9f.q64.wav`

Python reference decoded with: inference_chunk=8s, context=1s, full TensorFlow decoder.

### Before and after context-aware

| Metric | f25 (no context) | f75 (context=25) |
|---------|-----------------|------------------|
| **Global SNR** | 15.26 dB | **56.04 dB** |
| Max abs error | 1.46 | 0.19 |
| RMSE | 0.043 | 0.00039 |
| Mid-block SNR median | 35.98 dB | 60.79 dB |
| **Boundary SNR median** | 4.91 dB | **61.14 dB** |
| Mid/Boundary gap | 31.1 dB | **-0.4 dB** |
| Clicks | Yes | **No** |
| Sample count exact | Yes | Yes |

### Conclusion

- **Boundary artifacts are fully eliminated.** The gap between the middle of a block and its boundary is < 1 dB.
- **56 dB SNR** is the residual difference between C++ (3-second chunks) and Python (8-second chunks). Both are free of artifacts.
- **No clicks.** The maximum sample jump at a boundary (0.164) ≤ the average jump in the middle of a block.
- **Sample-exact output.** 7,779,614 PCM frames = `original_samples` from the SST header.

---

## Performance

| Configuration | RTF | Inference/block |
|--------------|-----|-----------------|
| f25 (no ctx), 8 threads | **0.88** | 0.88 s |
| f25 (no ctx), 4 threads | 1.26 | 1.26 s |
| f75 (ctx=25), 8 threads | 2.46 | 2.46 s |

Bottleneck: LiteRT inference (99.8% of the time). SST parse + RVQ + iSTFT = < 1 second per 162 seconds of audio.

### Paths to real time with context-aware decoding on Android

| Optimization | Expected RTF |
|-------------|---------------|
| FP16 model + ARM NEON | 1.2–1.5 |
| GPU delegate (Adreno/Mali) | 0.3–0.8 |
| f100 model (core=50, ctx=25) → 2x fewer inferences | ~1.2 |
| INT8 + NNAPI/NPU | 0.2–0.5 |

---

## Context-aware decode architecture

```
Codec frames:  [0..24] [25..49] [50..74] [75..99] ...

Block 0:  pad(25) + frames[0..24]  + frames[25..49]   → iSTFT → take center 48000
Block 1:  frames[0..24]  + frames[25..49] + frames[50..74]  → iSTFT → take center 48000
Block 2:  frames[25..49] + frames[50..74] + frames[75..99]  → iSTFT → take center 48000
...
```

For each 1-second output block:
1. Assemble the window: 25 frames left context + 25 frames core + 25 frames right context
2. RVQ dequantize → 75×256 embeddings
3. LiteRT inference [1,75,256] → spectrum [1,2,300,481,2]
4. iSTFT (300 STFT frames) → 144000 PCM samples (3 seconds)
5. Extract the central second: samples[48000:96000] (per channel)
6. Append to the output

At the edges (start/end of file): zero-padding instead of the missing context.

---

## Implemented components

| Component | File | Description |
|-----------|------|----------|
| SstReader | sst_reader.cpp | SST1 parse, 10-bit unpack, CRC32, codebook-major transpose |
| RvqDequantizer | rvq_dequantizer.cpp | 64 codebooks × 1024 entries × 256 dims, sum embeddings |
| LiteRtRunner | litert_runner.cpp | TFLite + XNNPACK, auto-detect model shape (f25/f75/any) |
| Istft | istft.cpp | PocketFFT c2r, variable STFT frames, window OLA |
| Decoder | decoder.cpp | Context-aware sliding window orchestration |
| WavWriter | wav_writer.cpp | PCM16 RIFF/WAV |
| C ABI | decoder_c_api.cpp | Stable C interface for Flutter FFI |
| CLI | cli/main.cpp | Argument parsing, timing, inspect mode |

### Build artifacts

```
build/spectrostream_decode              — Linux CLI (7.8 MB)
build/libspectrostream_decoder.so.1.0.0 — Shared library (8.5 MB)
build/test_sst_reader                   — Unit test ✓
build/test_rvq_dequantizer              — Unit test ✓
build/test_istft                        — Unit test ✓
```

### Models

```
models/spectrostream_decoder_core_fp32_f25.tflite  — 136 MiB, input [1,25,256]
models/spectrostream_decoder_core_fp32_f75.tflite  — 136 MiB, input [1,75,256]
models/spectrostream_decoder_core_fp16_f25.tflite  — 68 MiB, input [1,25,256]
models/rvq_codebooks.f32                           — 64 MiB, [64,1024,256]
models/istft_window_f960.f32                       — 3.8 KiB, 960 float32
```

---

## Technologies

- C++20, CMake 3.22+
- TensorFlow Lite 2.18.0 (built from source, XNNPACK delegate, builtin ops only)
- PocketFFT (header-only C++ FFT, portable)
- No dependency on Python, the TensorFlow runtime, ONNX, or the Flex delegate

---

## Documentation

```
docs/sst_format.md    — Complete binary specification of the SST1 container
docs/architecture.md  — Pipeline architecture and threading model
README.md             — Build and run instructions
```

---

## Next steps

1. **Android NDK arm64-v8a build** — CMakeLists is ready; cross-compilation has not been verified on a real device
2. **FP16 inference** — the f16 model is already exported for f25, needed for f75
3. **GPU delegate probe** — benchmark on Adreno/Mali
4. **RAM/temperature profiling** on the phone
5. **f100 model (core=50, ctx=25)** — half as many inferences at the same quality

---

## Build

```bash
cd decoder_cpp
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)
```

The first build takes ~5 minutes (TFLite compilation). Subsequent builds take seconds.
