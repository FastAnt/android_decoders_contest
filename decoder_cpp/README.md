# SpectroStream C++ Decoder

Fast, portable SpectroStream neural codec decoder for Linux and Android.

## Prerequisites

- CMake 3.22+
- C++20 compiler (GCC 12+ or Clang 15+)
- Local TensorFlow Lite sources in `third_party/tensorflow/` (tested: TensorFlow v2.18.0)
- Internet connection for additional dependencies on first configure
- Exported model/codebooks/window for decoding; the standard core assets are included in Git

## Build (Linux x86-64)

```bash
cd decoder_cpp
mkdir -p build && cd build
cmake .. -DCMAKE_BUILD_TYPE=Release
cmake --build . -j$(nproc)
```

TensorFlow Lite must already exist at `third_party/tensorflow/`; CMake fetches
additional dependencies such as PocketFFT. See [setup](../docs/setup.md) for
recorded revisions and [model export](../docs/model-export.md) for runtime assets.

## Usage

The examples below run from `decoder_cpp/build/` after the build above.
For an arbitrary input track, follow the complete [SST/WAV walkthrough](../docs/roundtrip.md)
from the repository root. The example SST below is a local fixture excluded from Git.

### Full decode

```bash
mkdir -p ../../media/reconstructed/cpp
./spectrostream_decode \
  --model ../models/spectrostream_decoder_core_fp32_f25.tflite \
  --codebooks ../models/rvq_codebooks.f32 \
  --window ../models/istft_window_f960.f32 \
  --input ../../media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f/069569e7525fdd1e462b9f5b1a394a9f.sst \
  --output ../../media/reconstructed/cpp/reconstructed_cpp.wav
```

### Inspect SST container

```bash
./spectrostream_decode --inspect \
  --input ../../media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f/069569e7525fdd1e462b9f5b1a394a9f.sst
```

## Output

The CLI produces a 48 kHz stereo PCM16 WAV file and prints timing:

```
SST parse:         X.X ms
RVQ dequant:       X.X ms
LiteRT infer:      X.X ms
iSTFT:             X.X ms
Total decode:      X.X ms

Audio duration:  XXX.X s
RTF:             X.XXXX
```

## Architecture

```
.sst file
  → SstReader (10-bit unpack, CRC32 verify)
  → RvqDequantizer (64 codebooks × 1024 × 256)
  → LiteRtRunner (TFLite/XNNPACK inference)
  → Istft (PocketFFT c2r + overlap-add)
  → WavWriter (PCM16 RIFF)
```

## Library

The project also builds `libspectrostream_decoder.so` with a stable C ABI
suitable for Flutter/Dart FFI integration.

## Android NDK Build (arm64-v8a)

### Prerequisites

- Android NDK r28+ (tested with r28c)
- Linux host build already done (provides host `flatc`)
- Internet connection (for KleidiAI download on first build)

### Quick build

Android commands below run from `decoder_cpp/`, not from `decoder_cpp/build/`.

```bash
./android/build.sh
```

This auto-detects NDK, builds host tools if needed, downloads KleidiAI, and
produces stripped arm64-v8a binaries.

### Manual build

```bash
export ANDROID_NDK_HOME=$HOME/Android/Sdk/ndk/28.2.13676358

cmake -S . -B build-android-arm64 \
  -G Ninja \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE="$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake" \
  -DANDROID_ABI=arm64-v8a \
  -DANDROID_PLATFORM=android-26 \
  -DANDROID_STL=c++_shared \
  -DBUILD_SHARED_LIB=ON \
  -DBUILD_CLI=ON \
  -DBUILD_TESTS=ON \
  -DENABLE_SANITIZERS=OFF \
  -DENABLE_GPU_DELEGATE=OFF \
  -DTFLITE_HOST_TOOLS_DIR="$(pwd)/build" \
  -DKLEIDIAI_SOURCE_DIR="$(pwd)/third_party/kleidiai"

cmake --build build-android-arm64 -j$(nproc)
```

### Deploy to device

```bash
./android/deploy.sh
```

Pushes executable, shared library, libc++_shared.so, models, and test SST
to `/data/local/tmp/spectrostream/` on the connected device.

### Run on device

```bash
adb shell "cd /data/local/tmp/spectrostream && LD_LIBRARY_PATH=. ./spectrostream_decode \
  --model models/spectrostream_decoder_core_fp32_f75.tflite \
  --codebooks models/rvq_codebooks.f32 \
  --window models/istft_window_f960.f32 \
  --input test.sst \
  --output output.wav \
  --threads 4"
```

### Benchmark

```bash
./android/benchmark.sh              # CPU thread scaling for all available models
./android/thermal_test.sh           # Sustained 5-minute decode, watch for throttling
./android/memory_profile.sh         # Peak RSS over time
./android/gpu_probe.sh              # GPU delegate test (requires --gpu build)
```

### GPU delegate build

```bash
./android/build.sh --gpu
```

Then use `--gpu` flag when running:

```bash
adb shell "cd /data/local/tmp/spectrostream && LD_LIBRARY_PATH=. ./spectrostream_decode \
  --model models/spectrostream_decoder_core_fp32_f75.tflite \
  --codebooks models/rvq_codebooks.f32 \
  --window models/istft_window_f960.f32 \
  --input test.sst --output output.wav --gpu --threads 4"
```

### Verify output

```bash
./android/verify.sh    # Pulls Android WAV, compares against Linux reference
```

### Android binary sizes (stripped)

| Artifact | Size |
|----------|------|
| spectrostream_decode | ~3.8 MiB |
| libspectrostream_decoder.so | ~5.2 MiB |

### CLI options

```
--model <path>       TFLite model file
--codebooks <path>   RVQ codebooks .f32 file
--window <path>      iSTFT window .f32 file
--input <path>       Input .sst file
--output <path>      Output .wav file (default: reconstructed_cpp.wav)
--threads <N>        CPU threads (default: 4)
--gpu                Use GPU delegate (requires ENABLE_GPU_DELEGATE build)
--benchmark <N>      Run decode N times, report avg/min/max RTF
--inspect            Only inspect .sst container, no decode
```

## Tests

From the repository root:

```bash
ctest --test-dir decoder_cpp/build --output-on-failure
```

SST reader and RVQ tests require the original local fixture under
`media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f/`; they check fixed properties
of that track. C API tests also require exported f25 assets and run multiple
decodes, so the full-track test can take time. A new track is not a drop-in
replacement for the fixed reader test. For a short C API check:

```bash
decoder_cpp/build/test_c_api \
  decoder_cpp/models/spectrostream_decoder_core_fp32_f25.tflite \
  decoder_cpp/models/rvq_codebooks.f32 \
  decoder_cpp/models/istft_window_f960.f32 \
  /path/to/short-track.sst
```

`--inspect` requires only an SST file, without model weights. Output directories
for `--output` must already exist. See [validation](../docs/validation.md) for
the checks actually performed; historical reports are not installation guides.
