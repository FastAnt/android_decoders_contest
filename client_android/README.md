# Neural Codecs Android Client

A Flutter application for comparing the startup time of MP3, SpectroStream, and
SAGE. SpectroStream is decoded through `dart:ffi` and the C++ runtime; SAGE goes
through a Kotlin bridge to LiteRT. The app exposes network profiles, a
SpectroStream model selector, and CPU thread counts.

## Prerequisites

You need Flutter with a Dart SDK compatible with `pubspec.yaml` (`^3.10.7`), the
Android SDK, the NDK, and an `arm64-v8a` device or emulator running Android
API 26+. The widget test was verified on Flutter 3.44.8 / Dart 3.12.2; the
original lockfile was created by a different SDK. Running `flutter pub get` on a
new SDK may update dependencies pinned by Flutter itself; review such changes
and commit them separately from documentation changes.

Flutter/Android sources and the Gradle Wrapper are stored in Git. Models and
native `.so` files must be prepared before building:

- `assets/audio/demo.mp3`, `assets/spectrostream/demo.sst`, and
  `assets/sage/demo.sage` — a small generated demo track already included in
  the repository. All three modes use the same track.
- `assets/spectrostream/` — `spectrostream_decoder_core_fp32_f25.tflite`,
  `spectrostream_decoder_core_fp32_f75.tflite`,
  `spectrostream_decoder_core_fp16_f25.tflite`,
  `spectrostream_decoder_core_fp16_f75.tflite`,
  `spectrostream_decoder_core_fp16_f100.tflite`, `rvq_codebooks.f32`, and
  `istft_window_f960.f32`. These files are **not tracked in Git**: export them
  as described in [../docs/model-export.md](../docs/model-export.md) and copy
  them here.
- `assets/sage/` — `dec_w8a8.tflite` (SAGE rung 128, int8). This model is also
  **not tracked in Git**; the link to the upstream SAGE project and the
  preparation steps are in [assets/sage/README.md](assets/sage/README.md).
  `demo.sage` is already included. SAGE uses
  `com.google.ai.edge.litert:litert:2.3.0` and Kotlin 2.4.
- `android/app/src/main/jniLibs/arm64-v8a/` — `libspectrostream_decoder.so`
  from the Android build of the decoder and `libc++_shared.so` from the
  matching NDK.

Building the native runtime is described in
[../decoder_cpp/README.md](../decoder_cpp/README.md). Android icons live in
`android/app/src/main/res/`.

## THREADS and CORES

`THREADS` is the number of TFLite/XNNPACK/LiteRT worker threads. It is not a
core count: the OS schedules the threads on any available CPU.

`CORES` is an affinity restriction for the decoder thread and the worker threads
it creates. The highest-numbered CPUs are selected (typically the performance
cores); `8` means "all available CPUs". This is not exclusive core reservation:
Android and other app threads can still use those CPUs. Usually `THREADS <=
CORES` makes sense; with more threads, they share the same cores.

## Using a Different Track

The app demonstrates a pre-prepared track rather than acting as an arbitrary
file player. The demo track is already at `assets/audio/demo.mp3`,
`assets/spectrostream/demo.sst`, and `assets/sage/demo.sage`. For your own track,
prepare an MP3, a SpectroStream SST, and a SAGE container and place them under
these names; all three modes must use the same source.

In `lib/services/asset_installer.dart`, the SST duration is hardcoded as
`_sstDurationSeconds = 133.607625`; for your own demo track it must be
reconciled with `metadata.json`. When replacing the demo set, increase
`_assetRevision`, otherwise the device may keep the old assets. Also clear the
app data or reinstall the app.

## Running

Commands from `client_android/`:

```bash
flutter pub get
flutter analyze
flutter test
flutter run
```

Models for the build must be prepared in advance; see "Prerequisites".
The overall project structure and data locations are described in
[../README.md](../README.md). Implementation details and experiment results are
in [client_report.md](client_report.md).

When switching Flutter SDK, run `flutter pub get` first: the saved
`.dart_tool/package_config.json` may reference the previous SDK and cause
compilation errors inside Flutter even though `flutter analyze` passes. Do not
move `.dart_tool/` and `build/` between machines.

The widget test checks that the screen exists; it does not confirm actual
playback, FFI operation, or Android APK correctness. The current
[validation results](../docs/validation.md) describe this boundary.

The Gradle Wrapper (`android/gradlew`, `android/gradlew.bat`,
`android/gradle/wrapper/gradle-wrapper.jar`, and the wrapper settings) is
included in Git. `local.properties`, Gradle caches, and build outputs remain
local. A full Android build from a clean clone has not yet been confirmed.
