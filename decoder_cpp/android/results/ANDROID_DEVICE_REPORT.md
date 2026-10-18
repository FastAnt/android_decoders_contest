# Android Device Report — SpectroStream Decoder

> Historical report. Measurements reflect the environment, model versions and code at the time of the experiment.

## Device

| Parameter | Value |
|----------|----------|
| Manufacturer | Samsung |
| Model | SM-S931B (Galaxy S24) |
| SoC | Exynos 2400 |
| Android | 15 |
| API level | 35 |
| ABI | arm64-v8a |
| RAM | 12 GB |
| CPU cores | 8 (1×3.2 GHz + 3×2.9 GHz + 4×1.95 GHz) |

---

## Artifact verification

### Architecture

```
libspectrostream_decoder.so: ELF 64-bit LSB shared object, ARM aarch64
spectrostream_decode:        ELF 64-bit LSB pie executable, ARM aarch64
test_c_api:                  ELF 64-bit LSB pie executable, ARM aarch64
```

### Dynamic dependencies

```
libm.so
libdl.so
liblog.so
libc++_shared.so
libc.so
```

No dependencies on Python, full TensorFlow, ONNX, or Flex.

### Exported C ABI symbols

```
T spectrostream_decoder_create
T spectrostream_decoder_decode_file
T spectrostream_decoder_free_pcm
T spectrostream_decoder_destroy
T spectrostream_decoder_last_error
```

All 5 required symbols are exported.

### 16 KiB page alignment (Android 15)

```
LOAD segments align = 0x4000 (16384 bytes)
```

Compatible with Android 15 16 KiB pages.

### Sizes (stripped)

| File | Size |
|------|--------|
| libspectrostream_decoder.so | 5.2 MiB |
| spectrostream_decode | 3.8 MiB |
| test_c_api | 3.8 MiB |
| libc++_shared.so | 8.9 MiB |

### Checksums — Host vs Device

All SHA-256 checksums matched. Data integrity on the device is confirmed.

---

## C ABI Smoke Test

**Result: ALL TESTS PASSED**

```
TEST: null handle safety... OK
TEST: error handling... OK (got error: Cannot open codebook file: /nonexistent/codebooks.f32...)
TEST: create/destroy... OK
TEST: decode file... OK (frames=7779614, sr=48000, ch=2)
TEST: double decode (reuse handle)... OK (both decodes: 7779614 frames)
```

Confirmed:
- the handle is created
- decode returns 7,779,614 PCM frames
- sample rate = 48000, channels = 2
- repeated decode with the same handle works
- error handling without a crash
- NULL handle is safe

---

## Full decode — f75 FP32 context-aware

```
Model + assets loaded in 143.3 ms
Backend: XNNPACK CPU

=== Decode Timing ===
SST parse:           3.5 ms
RVQ dequant:       256.8 ms
LiteRT infer:   680778.2 ms
iSTFT:            1072.6 ms
Total decode:   682195.5 ms

Audio duration: 162.075 s
RTF:            4.2091
Sample rate:    48000 Hz
Channels:       2
PCM frames:     7779614
```

**RTF 4.21** (4 threads) — 4.2x slower than real time.

---

## Android output vs Linux reference

```
Android: 15,559,228 samples, 48000 Hz, 2 ch, 7,779,614 frames
Linux:   15,559,228 samples, 48000 Hz, 2 ch, 7,779,614 frames

Sample count: EXACT MATCH
Max abs error:  0.000031
RMSE:           0.00000255
SNR:            99.8 dB

No NaN/Inf: OK
Ch0 boundary check: OK
Ch1 boundary check: OK

VERDICT: EXCELLENT - Android output matches Linux (SNR > 80 dB)
```

**99.8 dB SNR** — practically bit-exact. The difference is caused only by XNNPACK ARM vs x86 float rounding.

No boundary clicks. No NaN/Inf. Sample count exact.

---

## CPU Benchmark — Thread Scaling

| Model | Threads | LiteRT Infer | Total Decode | RTF |
|-------|--------:|-------------:|-------------:|----:|
| f25 FP32 | 2 | 319,114 ms | 319,635 ms | **1.97** |
| f25 FP32 | 4 | 192,260 ms | 192,826 ms | **1.19** |
| f25 FP32 | 6 | 127,041 ms | 127,511 ms | **0.79** |
| f75 FP32 | 4 | 680,778 ms | 682,196 ms | **4.21** |
| f75 FP32 | 6 | 418,584 ms | 419,873 ms | **2.59** |

### Key findings

1. **f25 FP32 with 6 threads: RTF 0.79 — faster than real time** on the Galaxy S24
2. f75 FP32 with 6 threads: RTF 2.59 — 2.5x slower than real time
3. Thread scaling is effective: 2→4 = ~1.65x, 4→6 = ~1.5x
4. Bottleneck: 99.8% of the time is LiteRT inference

### Model load time

~143–390 ms (depends on whether the file cache is warm).

---

## Decoded WAV

```
android/results/reconstructed_android_f75.wav
```

- PCM16 stereo 48 kHz
- 30 MiB
- 162.075 seconds
- 7,779,614 PCM frames
- No boundary artifacts
- Ready for listening

---

## Final status

### What works

| Criterion | Status |
|----------|--------|
| arm64-v8a build | ✅ |
| Binary runs on the device | ✅ |
| C ABI symbols exported | ✅ |
| 16 KiB alignment | ✅ |
| f75 context-aware decode | ✅ |
| Sample count exact | ✅ |
| SNR > 80 dB vs Linux | ✅ (99.8 dB) |
| No boundary clicks | ✅ |
| No NaN/Inf | ✅ |
| C ABI smoke test | ✅ |
| f25 realtime with 6 threads | ✅ (RTF 0.79) |

### What was not tested in this run

- f25 with 1 thread (expected RTF ~3.8)
- f75 with 1/2 threads
- FP16 model
- GPU delegate
- Peak RSS
- Thermal stability (5 min)
- NNAPI

---

## Recommendations for the next step

### For Flutter (offline decode)

Use **f25 FP32 with 6 threads** — already faster than real time.

### For real-time playback

1. Export **FP16 f25** → expected RTF ~0.4–0.5
2. Or export **f75 FP16** → RTF ~1.3–1.7 with 6 threads (but without clicks)

### For minimal memory

f25 FP32 (no context) — 136 MiB model + 64 MiB codebooks ≈ 200 MiB baseline.

### GPU delegate

Potentially could yield RTF < 1.0 for f75, but requires a separate test (`./android/build.sh --gpu`).

---

## Reproducing the result

```bash
cd decoder_cpp

# Build (if not built)
./android/build.sh

# Deploy
./android/deploy.sh

# Decode
adb shell "cd /data/local/tmp/spectrostream && \
  LD_LIBRARY_PATH=. ./spectrostream_decode \
  --model models/spectrostream_decoder_core_fp32_f75.tflite \
  --codebooks models/rvq_codebooks.f32 \
  --window models/istft_window_f960.f32 \
  --input data/069569e7525fdd1e462b9f5b1a394a9f.sst \
  --output output/decoded.wav \
  --threads 6"

# Pull result
adb pull /data/local/tmp/spectrostream/output/decoded.wav .
```
