# Android Build Report — SpectroStream C++ Decoder

> Historical report. Measurements reflect the environment, model versions and code at the time of the experiment.

Report for integration into a Flutter application.

---

## Build artifacts

### Main library

```
build-android-arm64/libspectrostream_decoder.so
```

- ABI: `arm64-v8a`
- minSdk: 26
- STL: `c++_shared` (requires `libc++_shared.so` alongside)
- Stripped size: **5.2 MiB**
- Dependencies: no external `.so` files except `libc++_shared.so`

### Runtime dependency

```
$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so
```

This library must be placed alongside `libspectrostream_decoder.so` in `jniLibs/arm64-v8a/`.

### Test CLI (not needed by Flutter, debugging only)

```
build-android-arm64/spectrostream_decode     — 3.8 MiB stripped
build-android-arm64/test_c_api               — 3.8 MiB stripped
```

---

## C ABI for Flutter FFI

### Header

```
include/spectrostream/decoder_c_api.h
```

### Functions

```c
// Create a decoder. Returns an opaque handle.
// On error, returns a handle with decoder=NULL; the error is in last_error.
SpectroStreamDecoderHandle spectrostream_decoder_create(
    const char* model_path,        // path to .tflite
    const char* codebooks_path,    // path to rvq_codebooks.f32
    const char* window_path,       // path to istft_window_f960.f32
    int num_threads                // recommendation: 4 for arm64
);

// Decode a .sst file into PCM float32 interleaved stereo.
// pcm_out is allocated by the library; free it via free_pcm.
// Returns 0 on success, -1 on error.
int spectrostream_decoder_decode_file(
    SpectroStreamDecoderHandle handle,
    const char* sst_path,
    float** pcm_out,               // [out] interleaved float32
    int64_t* frame_count_out,      // [out] PCM frames (samples per channel)
    int* sample_rate_out,          // [out] always 48000
    int* channels_out              // [out] always 2
);

// Free the PCM buffer.
void spectrostream_decoder_free_pcm(float* pcm);

// Destroy the decoder.
void spectrostream_decoder_destroy(SpectroStreamDecoderHandle handle);

// Get the last error text (does not need to be freed).
const char* spectrostream_decoder_last_error(SpectroStreamDecoderHandle handle);
```

### ABI guarantees

- No C++ exceptions across the boundary (everything is caught internally)
- No STL types in the public API (only `const char*`, `float*`, `int`, `int64_t`)
- `SpectroStreamDecoderHandle` is `void*`
- Thread safety: one handle = one thread. Different handles can be used from different threads.
- Repeated decode with one handle works (verified by test)
- `spectrostream_decoder_destroy(NULL)` is safe

### Error codes

- `spectrostream_decoder_create` returns a non-null handle even on error
- Check: `spectrostream_decoder_last_error(handle)` — if the string is non-empty, the decoder is not initialized
- `spectrostream_decoder_decode_file` returns `-1` on error, `0` on success

---

## Dart FFI Binding (example)

```dart
import 'dart:ffi';
import 'dart:io';
import 'package:ffi/ffi.dart';

typedef SpectroStreamHandle = Pointer<Void>;

// Native function signatures
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
    int threads = 4,
  }) {
    _lib = DynamicLibrary.open('libspectrostream_decoder.so');

    final create = _lib.lookupFunction<NativeCreate,
        Pointer<Void> Function(Pointer<Utf8>, Pointer<Utf8>, Pointer<Utf8>, int)>(
        'spectrostream_decoder_create');

    final m = modelPath.toNativeUtf8();
    final c = codebooksPath.toNativeUtf8();
    final w = windowPath.toNativeUtf8();
    _handle = create(m, c, w, threads);
    malloc.free(m);
    malloc.free(c);
    malloc.free(w);

    final err = lastError();
    if (err.isNotEmpty) {
      throw Exception('SpectroStream init failed: $err');
    }
  }

  String lastError() {
    final fn = _lib.lookupFunction<NativeLastError,
        Pointer<Utf8> Function(Pointer<Void>)>(
        'spectrostream_decoder_last_error');
    return fn(_handle).toDartString();
  }

  void dispose() {
    final destroy = _lib.lookupFunction<NativeDestroy,
        void Function(Pointer<Void>)>('spectrostream_decoder_destroy');
    destroy(_handle);
  }
}
```

---

## Models and assets for Flutter

### Files needed on the device

| File | Size | Description |
|------|--------|----------|
| `spectrostream_decoder_core_fp32_f75.tflite` | 136 MiB | Main model (context-aware, high quality) |
| `spectrostream_decoder_core_fp32_f25.tflite` | 136 MiB | Fast model (no context, boundary artifacts present) |
| `spectrostream_decoder_core_fp16_f25.tflite` | 68 MiB | Fast FP16 model (2x smaller) |
| `rvq_codebooks.f32` | 64 MiB | Codebooks for RVQ dequantization |
| `istft_window_f960.f32` | 3.8 KiB | iSTFT window function |

### Placement strategy in Flutter

**Do NOT put them in APK assets** — 200+ MiB of raw data in total.

Recommended approach:

1. Keep the models on external storage or app-specific storage
2. Download them on first launch (or bundle them in an expansion file)
3. Pass the paths to `spectrostream_decoder_create` as absolute strings

Example location on the device:

```
/data/data/com.example.app/files/spectrostream/
├── spectrostream_decoder_core_fp32_f75.tflite
├── rvq_codebooks.f32
└── istft_window_f960.f32
```

---

## Building the .so for a Flutter project

### Option 1: Pre-built .so (recommended to start with)

```
android/app/src/main/jniLibs/arm64-v8a/
├── libspectrostream_decoder.so
└── libc++_shared.so
```

Flutter automatically packs the contents of `jniLibs/` into the APK.

### Option 2: CMake integration via Gradle

In `android/app/build.gradle`:

```groovy
android {
    defaultConfig {
        ndk {
            abiFilters 'arm64-v8a'
        }
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

**Note**: the first build through Gradle takes 5+ minutes (TFLite compilation).

### Option 3: Pre-build with a script

```bash
cd /path/to/decoder_cpp
./android/build.sh
cp build-android-arm64/libspectrostream_decoder.so \
   /path/to/flutter_app/android/app/src/main/jniLibs/arm64-v8a/
```

---

## Commands for a reproducible build

```bash
cd decoder_cpp

# 1. Make sure the Linux build exists (host flatc is required)
test -f build/flatbuffers-flatc/bin/flatc || {
    mkdir -p build && cd build
    cmake .. -DCMAKE_BUILD_TYPE=Release
    cmake --build . -j$(nproc)
    cd ..
}

# 2. Build Android arm64
./android/build.sh

# 3. Result
ls -lh build-android-arm64/libspectrostream_decoder.so
```

The NDK is auto-detected from `$HOME/Android/Sdk/ndk/` (the latest version is used).

Explicitly:

```bash
export ANDROID_NDK_HOME=$HOME/Android/Sdk/ndk/28.2.13676358
./android/build.sh
```

---

## Performance (Linux baseline, for reference)

| Configuration | RTF | Decode time for 162 s of audio |
|--------------|-----|------------------------|
| FP32 f75, 8 threads, x86-64 | 2.46 | 399 s |
| FP32 f25, 8 threads, x86-64 | 0.88 | 143 s |

On Android ARM64 with XNNPACK + NEON, the expected values are:
- f25 FP32: RTF ~0.5–1.5 (depends on the SoC)
- f75 FP32: RTF ~1.5–4.0
- f25 FP16: RTF ~0.3–0.8

**Actual numbers will follow after running `./android/benchmark.sh` on the device.**

---

## Decode output

- Sample rate: 48000 Hz
- Channels: 2 (stereo)
- Format: float32 interleaved (L R L R ...)
- Length: exactly `original_samples` from the SST header
- For playback: convert to PCM16 or pass to AudioTrack as float

---

## Model selection for Flutter

| Model | Quality | Speed | RAM | Recommendation |
|--------|----------|----------|-----|--------------|
| f75 FP32 | Best (56 dB SNR, no artifacts) | Slow | ~400 MiB | Offline high-quality |
| f25 FP32 | Good (boundary clicks present) | Fast | ~250 MiB | Fast preview |
| f25 FP16 | Good | Fastest | ~180 MiB | Real-time on a mid-range SoC |
| f75 FP16 | Best | Medium | ~300 MiB | **Not exported yet** |

For the first Flutter prototype: start with **f25 FP32**, then switch to f75 FP16 once the model is ready.

---

## What is NOT included in the library

- Network download of SST files (streaming)
- AudioTrack/Oboe playback
- UI
- Model download management
- Background service

The library is pure decode: `.sst` path in → PCM float32 out.

---

## File structure for the Flutter agent

```
decoder_cpp/
├── android/
│   ├── build.sh              ← build the .so
│   ├── deploy.sh             ← push to the device for testing
│   ├── benchmark.sh          ← measurements
│   └── ...
├── build-android-arm64/
│   ├── libspectrostream_decoder.so   ← THIS goes into jniLibs
│   └── spectrostream_decode          ← CLI for debugging on the device
├── include/
│   └── spectrostream/
│       └── decoder_c_api.h           ← contract for the FFI binding
├── models/                           ← NOT in the APK, download separately
│   ├── spectrostream_decoder_core_fp32_f75.tflite
│   ├── rvq_codebooks.f32
│   └── istft_window_f960.f32
└── CMakeLists.txt
```

---

## Known limitations

1. **The FP16 f75 model is not exported** — requires the Python script from `encoder_service/`
2. **GPU delegate** — builds with `--gpu`, but has not been tested on a real device
3. **Streaming decode** — the current API processes the whole file. Streaming playback needs a new block-based API.
4. **arm64-v8a only** — armeabi-v7a has not been tested and is not needed (minSdk 26 = almost all devices are arm64)
