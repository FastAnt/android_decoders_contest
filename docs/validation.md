# What Has Been Verified

Date: 2026-10-18. The validation was performed in an existing prepared working
copy, after reorganizing media and updating documentation.

## Environment and Model Provenance

- Ubuntu 24.04.4 LTS x86-64, Python 3.12.3.
- TensorFlow Python 2.20.0, NumPy 2.4.6, protobuf 7.35.1;
  `pip check` — `No broken requirements found`.
- Magenta RealTime `04ebaa7da13701734281c630ffd13f7ee9893e45`.
- Source weights from Hugging Face `google/magenta-realtime`, revision
  `c05f8d6d608afd588469b7a8ef0929d5a1f8f6bb`, reconstructed from the metadata of
  15 files in the local cache; their SHA256 are recorded in `source-model.sha256`.
- TensorFlow Lite source v2.18.0,
  `6550e4bd80223cdb8be6c3afd1f81e86a4d433c3`.
- PocketFFT `c90e55b3d529f8efa40ed01a20de22405f45fc65`.
- GCC 13.3, CMake 3.28.3, FFmpeg 6.1.1.

## Compression and Decoding

On the first three seconds of the local `client_android/assets/audio/demo.mp3`:

- Python batch encoder on CPU: one successful track, zero errors,
  `container_validated: true`.
- SST: 6112 bytes, 75 codec frames, 3 chunks, CRC status OK.
- Python reference WAV: PCM16, 48000 Hz, stereo, 144000 PCM frames,
  576044 bytes.
- The independent C++ CLI read the written SST and created a WAV with the same
  format, length, and size. This validates structure and length, not audio
  quality and not bit-for-bit equality between the implementations' WAVs.

All six Bash blocks from [roundtrip.md](roundtrip.md) were extracted from Markdown
and successfully executed as a single scenario with the local demo file
and `--max-seconds 3`. Reading the catalog, the WAV checks, and ffprobe were also verified.
Experiment logs and files are in the Git-excluded
`media/docs-smoke/`; these paths are local evidence,
not required documentation inputs.

## Model Export

The recipe from [model-export.md](model-export.md) was executed in a new directory:
codebooks → dynamic SavedModel → fixed f25 SavedModel →
FP32/FP16 builtin-only core and iSTFT window.

The exporter exited with code 0 and `FP32 validation PASSED`.
For this run, FP32 audio RMSE relative to the full TensorFlow decoder:
`8.040e-07`, SNR `103.32 dB`; FP16 audio RMSE `1.073e-04`, SNR `60.81 dB`.
This is a numerical validation of the exporter on its test embeddings, not
an assessment of music encoding quality. A re-export is not required to have
the same TFLite bytes as the distributed original set.

The new FP32 model, new codebooks, and window were also verified via
`test_c_api` on a short SST. All its checks passed: create/destroy,
normal and repeated decoding, stream info, cancellation, and API errors.
Large intermediate SavedModels and re-exported weights are deleted after
verification; the log and JSON report are kept in `media/docs-smoke/`.

## Build and Tests

- Rebuilt the C++ CLI and test targets with the existing local dependencies.
- `sst_reader`, `rvq_dequantizer`, and `istft` pass via CTest.
  For iSTFT, the CTest working directory was fixed: the test reads the window from `models/`
  relative to `decoder_cpp/`, like the other asset tests.
- The full CTest with repeated decoding of the original 162-second fixture
  in `c_api` was not repeated; instead, the C API was verified on a 3-second SST.
- `flutter analyze --no-pub` passed without warnings.
- The widget test passed after `flutter pub get --offline` on Flutter 3.44.8 /
  Dart 3.12.2. Before the generated package config was updated, paths from the
  previous Flutter SDK were used, causing a compilation error inside Flutter.
  The new SDK temporarily updated five SDK dependencies; the original `pubspec.lock`
  was restored, and the dependency update was not included in the documentation change.

## What This Validation Does Not Confirm

A fresh installation of the Python environment and a download of weights/sources
from the network from a clean clone were not repeated. Revisions and commands for this are recorded
in [setup.md](setup.md); checksums of the local source weights and
the main runtime set were verified.

GPU encoding, a new Android APK, actual playback on a device,
long-running load tests, and audio quality metrics were not part of this run.
The widget test does not confirm FFI or audio output. The completeness of the
Gradle Wrapper distribution for a clean clone is noted in the
[client README](../client_android/README.md).

Timing measurements for the short run were performed concurrently with the build;
they cannot be considered a reliable comparative benchmark.

## Weights and Git

The source SpectroStream SavedModels (encoder, decoder, quantizer), the prebuilt
core models f25/f75/f100 in FP32/FP16, and the codebooks/window are **not stored
in Git**: they are downloaded from Hugging Face or exported as described in the
setup and model-export guides. Prepared Flutter assets are copies of the
canonical decoder files. The full 32-file set is listed in
`packaged-weights.sha256` for verification after preparation. The Hugging Face
loader cache, intermediate exported SavedModels, ONNX/Flex experiments, media,
dependencies, and builds remain excluded.
