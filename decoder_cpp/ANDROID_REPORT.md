# SpectroStream Android Decoder — Full Report

> Historical report. Measurements reflect the environment, model versions and code at the time of the experiment.

Date: 2026-07-12
Device: Samsung Galaxy S24 (SM-S931B), Exynos 2400, Android 15, 12 GB RAM

---

## Status: READY FOR FLUTTER INTEGRATION

f25 FP32 decodes a 162-second track faster than real time (RTF 0.79, 6 threads).
f75 FP32 context-aware decode — sample-exact, 99.8 dB SNR vs Linux, no boundary artifacts.
C ABI — all tests passed. The library is ready to be integrated via Flutter FFI.

---

## 1. Build artifacts

### Library for Flutter

```
decoder_cpp/build-android-arm64/libspectrostream_decoder.so   — 5.2 MiB (stripped)
```

The STL runtime is required alongside it:

```
libc++_shared.so   — 8.9 MiB
```

Source: `$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so`

### Build parameters

| Parameter | Value |
|----------|----------|
| ABI | arm64-v8a |
| minSdk | 26 |
| STL | c++_shared |
| NDK | r28c (28.2.13676358) |
| TFLite | 2.18.0 (builtin ops only) |
| Delegate | XNNPACK CPU |
| Build type | Release |
| Page alignment | 16 KiB (Android 15 compatible) |

### Dynamic dependencies (system libs only)

```
libm.so
libdl.so
liblog.so
libc++_shared.so
libc.so
```

No dependency on Python, full TensorFlow, ONNX, or the Flex delegate.

### Debug executables (not needed by Flutter, for adb shell)

```
decoder_cpp/build-android-arm64/spectrostream_decode   — 3.8 MiB
decoder_cpp/build-android-arm64/test_c_api             — 3.8 MiB
```

---

## 2. C ABI

### Header

```
decoder_cpp/include/spectrostream/decoder_c_api.h
```

### Exported symbols (confirmed with llvm-nm)

```
T spectrostream_decoder_create
T spectrostream_decoder_decode_file
T spectrostream_decoder_free_pcm
T spectrostream_decoder_destroy
T spectrostream_decoder_last_error
```

### Signatures

```c
// Create a decoder. On error, handle != NULL but the internal decoder = NULL.
SpectroStreamDecoderHandle spectrostream_decoder_create(
    const char* model_path,        // absolute path to .tflite
    const char* codebooks_path,    // absolute path to rvq_codebooks.f32
    const char* window_path,       // absolute path to istft_window_f960.f32
    int num_threads                // recommendation: 4–6
);

// Decode .sst → PCM float32 interleaved stereo.
// Returns 0 = ok, -1 = error.
int spectrostream_decoder_decode_file(
    SpectroStreamDecoderHandle handle,
    const char* sst_path,
    float** pcm_out,               // [out] malloc'd buffer, free via free_pcm
    int64_t* frame_count_out,      // [out] PCM frames (samples per channel)
    int* sample_rate_out,          // [out] always 48000
    int* channels_out              // [out] always 2
);

void spectrostream_decoder_free_pcm(float* pcm);
void spectrostream_decoder_destroy(SpectroStreamDecoderHandle handle);
const char* spectrostream_decoder_last_error(SpectroStreamDecoderHandle handle);
```

### Guarantees

- `SpectroStreamDecoderHandle` = `void*`
- No C++ exceptions across the boundary
- No STL types in the public API
- Thread safety: one handle — one thread; different handles are safe to use in parallel
- Repeated decode with one handle works (confirmed by test)
- `spectrostream_decoder_destroy(NULL)` is safe
- Creation error check: `spectrostream_decoder_last_error(h)` — empty string = ok

### Device test result

```
TEST: null handle safety... OK
TEST: error handling... OK
TEST: create/destroy... OK
TEST: decode file... OK (frames=7779614, sr=48000, ch=2)
TEST: double decode (reuse handle)... OK (both decodes: 7779614 frames)

ALL TESTS PASSED
```

---

## 3. Models and assets

### Files for the device

| File | Size | Purpose |
|------|--------|------------|
| `spectrostream_decoder_core_fp32_f75.tflite` | 136 MiB | Context-aware, best quality |
| `spectrostream_decoder_core_fp32_f25.tflite` | 136 MiB | Fast, RTF < 1 with 6 threads |
| `spectrostream_decoder_core_fp16_f25.tflite` | 68 MiB | FP16 fast (even faster) |
| `rvq_codebooks.f32` | 64 MiB | RVQ codebooks (64×1024×256 float32) |
| `istft_window_f960.f32` | 3.8 KiB | iSTFT window (960 float32) |

### Placement

**Do NOT put them in APK assets** — 200+ MiB in total.

Recommendation: download on first launch into app-specific storage.

```
/data/data/com.example.app/files/spectrostream/
├── spectrostream_decoder_core_fp32_f25.tflite
├── rvq_codebooks.f32
└── istft_window_f960.f32
```

Paths are passed as absolute strings to `spectrostream_decoder_create()`.

---

## 4. Decode results on the device

### Correctness — f75 FP32 context-aware

```
Sample rate:    48000 Hz
Channels:       2 (stereo)
PCM frames:     7,779,614   ← EXACT MATCH vs Linux
Audio duration: 162.075 s
```

### Android ARM64 vs Linux x86-64 comparison

| Metric | Value |
|---------|----------|
| Sample count | **EXACT MATCH** (15,559,228 interleaved samples) |
| SNR | **99.8 dB** |
| Max abs error | 0.000031 |
| RMSE | 0.0000026 |
| NaN/Inf | 0 |
| Boundary clicks | **None** |

Cause of the residual difference: XNNPACK ARM NEON vs x86 SSE float rounding. Inaudible.

### Output WAV (available for listening)

```
media/reconstructed/android/reconstructed_android_f75.wav
```

PCM16 stereo 48 kHz, 30 MiB, 162 seconds. No artifacts.

---

## 5. Performance

### Thread scaling — Samsung Galaxy S24

| Model | Threads | Inference | Total | RTF | Realtime? |
|-------|--------:|----------:|------:|----:|-----------|
| f25 FP32 | 2 | 319,114 ms | 319,635 ms | 1.97 | No |
| f25 FP32 | 4 | 192,260 ms | 192,826 ms | 1.19 | No |
| **f25 FP32** | **6** | **127,041 ms** | **127,511 ms** | **0.79** | **Yes** |
| f75 FP32 | 4 | 680,778 ms | 682,196 ms | 4.21 | No |
| f75 FP32 | 6 | 418,584 ms | 419,873 ms | 2.59 | No |

### Conclusions

- **f25 FP32 with 6 threads: RTF 0.79** — decodes faster than real time
- f75 FP32: 2.6–4.2x slower than real time (depends on the thread count)
- Model load: 143–390 ms
- Bottleneck: LiteRT inference (>99.8% of total time)
- SST parse + RVQ + iSTFT = less than 1.5 seconds per 162 seconds of audio

### Thread scaling efficiency

```
2 → 4 threads: ×1.66 speedup
4 → 6 threads: ×1.51 speedup
```

Diminishing returns after 4 threads (the small Exynos cores are less efficient).

---

## 6. Flutter integration

### Option 1: Pre-built .so (recommended)

```
flutter_app/android/app/src/main/jniLibs/arm64-v8a/
├── libspectrostream_decoder.so    ← from build-android-arm64/
└── libc++_shared.so               ← from the NDK sysroot
```

Flutter automatically packs jniLibs into the APK.

### Option 2: CMake via Gradle

```groovy
android {
    defaultConfig {
        ndk { abiFilters 'arm64-v8a' }
        externalNativeBuild {
            cmake {
                arguments '-DBUILD_SHARED_LIB=ON',
                          '-DBUILD_CLI=OFF',
                          '-DBUILD_TESTS=OFF',
                          '-DENABLE_SANITIZERS=OFF',
                          '-DTFLITE_HOST_TOOLS_DIR=/path/to/decoder_cpp/build',
                          '-DKLEIDIAI_SOURCE_DIR=/path/to/decoder_cpp/third_party/kleidiai'
            }
        }
    }
    externalNativeBuild {
        cmake {
            path '/path/to/decoder_cpp/CMakeLists.txt'
            version '3.22.0+'
        }
    }
}
```

### Dart FFI binding (example)

```dart
import 'dart:ffi';
import 'package:ffi/ffi.dart';

typedef NativeCreate = Pointer<Void> Function(
    Pointer<Utf8>, Pointer<Utf8>, Pointer<Utf8>, Int32);
typedef NativeDecodeFile = Int32 Function(
    Pointer<Void>, Pointer<Utf8>, Pointer<Pointer<Float>>,
    Pointer<Int64>, Pointer<Int32>, Pointer<Int32>);
typedef NativeFreePcm = Void Function(Pointer<Float>);
typedef NativeDestroy = Void Function(Pointer<Void>);
typedef NativeLastError = Pointer<Utf8> Function(Pointer<Void>);

class SpectroStreamDecoder {
  late final DynamicLibrary _lib;
  late final Pointer<Void> _handle;

  SpectroStreamDecoder({
    required String modelPath,
    required String codebooksPath,
    required String windowPath,
    int threads = 6,
  }) {
    _lib = DynamicLibrary.open('libspectrostream_decoder.so');
    final create = _lib.lookupFunction<NativeCreate,
        Pointer<Void> Function(Pointer<Utf8>, Pointer<Utf8>, Pointer<Utf8>, int)>(
        'spectrostream_decoder_create');

    final m = modelPath.toNativeUtf8();
    final c = codebooksPath.toNativeUtf8();
    final w = windowPath.toNativeUtf8();
    _handle = create(m, c, w, threads);
    malloc.free(m); malloc.free(c); malloc.free(w);

    final err = lastError;
    if (err.isNotEmpty) throw Exception('SpectroStream init: $err');
  }

  String get lastError {
    final fn = _lib.lookupFunction<NativeLastError,
        Pointer<Utf8> Function(Pointer<Void>)>(
        'spectrostream_decoder_last_error');
    return fn(_handle).toDartString();
  }

  void dispose() {
    final fn = _lib.lookupFunction<NativeDestroy,
        void Function(Pointer<Void>)>('spectrostream_decoder_destroy');
    fn(_handle);
  }
}
```

### Critical rules for the Flutter agent

1. `decode_file` is **blocking**; it decodes the entire track. Do not call it on the UI isolate.
2. `free_pcm` is **mandatory** after every decode, otherwise memory leaks.
3. One handle — one thread. For parallel decode, create separate handles.
4. Output format: float32 interleaved (L R L R ...); conversion to PCM16 is required for AudioTrack.
5. Model load takes ~150–400 ms — do it at initialization, not on every decode.

---

## 7. Model selection

| Scenario | Model | Threads | RTF (S24) | Quality |
|----------|--------|--------:|----------:|----------|
| Offline decode | f25 FP32 | 6 | 0.79 | Good (clicks at boundaries) |
| High-quality offline | f75 FP32 | 6 | 2.59 | Excellent (no artifacts) |
| Realtime preview | f25 FP16 | 6 | ~0.4* | Good |
| Best quality + speed | f75 FP16 | 6 | ~1.3* | Excellent |

\* FP16 estimate; actual measurements after model export.

**Recommendation for the first Flutter prototype:** f25 FP32, 6 threads. Already faster than real time.

---

## 8. Known limitations

1. **f75 FP32 is not realtime** — RTF 2.59 on S24. Suitable for background decode, not for playback.
2. **FP16 f75 is not exported** — requires Python from `encoder_service/`.
3. **GPU delegate not tested** — builds with `--gpu`, may yield RTF < 1.0 for f75.
4. **No streaming decode** — the current API processes the whole file.
5. **~200 MiB RAM baseline** — 136 MiB model + 64 MiB codebooks + activations.
6. **arm64-v8a only** — armeabi-v7a is not needed (minSdk 26).

---

## 9. Project structure

```
decoder_cpp/
├── CMakeLists.txt                        ← supports Android cross-compile
├── android/
│   ├── build.sh                          ← full automated build
│   ├── deploy.sh                         ← push to the device
│   ├── benchmark.sh                      ← thread scaling benchmark
│   ├── thermal_test.sh                   ← sustained load test
│   ├── memory_profile.sh                 ← RSS tracking
│   ├── gpu_probe.sh                      ← GPU delegate test
│   ├── verify.sh                         ← comparison with the Linux reference
│   ├── run_all.sh                        ← full pipeline
│   └── results/
│       └── ANDROID_DEVICE_REPORT.md      ← device report
├── build-android-arm64/
│   ├── libspectrostream_decoder.so       ← THIS goes into jniLibs
│   ├── spectrostream_decode              ← CLI for debugging
│   └── test_c_api                        ← smoke test
├── include/spectrostream/
│   └── decoder_c_api.h                   ← FFI contract
├── models/                               ← download separately, not in the APK
├── third_party/
│   ├── tensorflow/                       ← TFLite source
│   └── kleidiai/                         ← XNNPACK ARM dep
└── src/                                  ← portable core (do not touch)
```

---

## 10. Reproduction commands

```bash
cd decoder_cpp

# Build (if not built yet)
./android/build.sh

# Deploy to a connected device
./android/deploy.sh

# Decode on the device
adb shell "cd /data/local/tmp/spectrostream && \
  LD_LIBRARY_PATH=. ./spectrostream_decode \
  --model models/spectrostream_decoder_core_fp32_f25.tflite \
  --codebooks models/rvq_codebooks.f32 \
  --window models/istft_window_f960.f32 \
  --input data/069569e7525fdd1e462b9f5b1a394a9f.sst \
  --output output/decoded.wav --threads 6"

# Pull the result
adb pull /data/local/tmp/spectrostream/output/decoded.wav .
```
