# What Has Been Verified

Date: 2026-10-18. Updated 2026-10-25 with the SAME-S integration and the
on-device Samsung SM-S931B run. The earlier validation was performed in an
existing prepared working copy, after reorganizing media and updating
documentation.

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

## SAME-S Integration (2026-10-25)

- Generated `client_android/assets/same/demo.same` from the checked-in
  `demo.mp3` with the SAME-S encoder (`int8-pc`, zlib, tflite-w8a8 backend):
  343,565 bytes, 20.57 kbit/s, 1,440 stored / 1,439 valid latent frames,
  12 chunks, 5,892,096 original samples (133.607619 s).
- The decoded length matches `client_android/assets/sage/demo.sage`
  (5,892,096 samples), so MP3/SAGE/SAME-S use the same source duration.
- Python reference decoder restored 5,892,096 samples, peak 0.977, no errors.
- Sliced model `dec_w8a8_s128.tflite` (81,517,872 bytes) was compared with the
  full `dec_w8a8.tflite` export on the same `(1,256,128)` window; the `s128`
  outputs are bit-identical (maxdiff 0.0).
- `flutter analyze --no-pub` and `flutter test --no-pub` pass with the new
  SAME-S mode and Dart service.
- A debug APK was built successfully with the SAME-S model and demo container
  bundled (`assets/flutter_assets/assets/same/`); the debug APK is about 886 MB.

On-device (Samsung SM-S931B, Android 15, 2026-10-25):

- Installed the debug APK; Settings exposes `NEURAL SAME-S`; applying it loads
  `same_xnnwc_81517872.bin`, initializes LiteRT with `rungs=[128]`, and applies
  CPU affinity (`affinity(8) -> 0`).
- Playback reaches `STREAM DONE (SAME-S, 12 CHUNKS)`; all 13 decoder windows
  are emitted, with exact total length 5,892,096 frames.
- Time to playback after the measurement fix: 1.055 s (first run), 0.907 s,
  0.902 s, 1.246 s (later mode-switch run), and 0.977 s (final run); median
  0.977 s. The same corrected metric gives SAGE 0.984 s, SpectroStream f25
  0.971 s, and MP3 7.422 s (the 5.35 MB asset is downloaded in full under the
  Typical 6 Mbit/s simulation).
- PSS: 608 MB with SAME-S loaded, 640–656 MB after later runs, and 429 MB after
  switching from SpectroStream back to SAME-S (the previous decoder was
  released). SAGE was 1,119.6 MB and SpectroStream 1,069.8 MB in the same
  process.
- `AudioTrack` was initialized and the player reached the playing state; no
  crash or OOM occurred while switching SAME-S → SAGE → SpectroStream → SAME-S.
- A separate 3-codec × {T1/C1, T2/C2} matrix (3 repeats each, Typical network)
  was recorded in HISTORY: SpectroStream 2.137/1.747 s, SAGE 1.360/0.954 s,
  SAME-S 1.576/1.091 s (avg, T1/C1 then T2/C2); see
  [codec-speed-1c2t.md](codec-speed-1c2t.md).
- Decoder-only 4 s PCM at T2/C1 (2 threads on 1 core): SAME-S 0.611 s
  (6.5× realtime), SAGE 1.329 s (3.0×), SpectroStream 6.043 s (0.66×, slower
  than realtime); see [decode-4s-2t1c.md](decode-4s-2t1c.md).

Measurement fix (applies to all modes):

- `AudioPlayerService` previously awaited `just_audio`'s `play()` future, which
  completes when playback finishes/pauses; the timer therefore included the
  first chunk. It now calls `play()` without awaiting it and waits for
  `playing + ready/completed`. The old Tensor G2 app-level startup values are
  historical and not directly comparable.
- The MP3 branch did not update its status label, so it stayed at `PREPARING`
  even after the timer stopped; the label is now `STREAMING (MP3)`.

Not confirmed by this run:

- Android-vs-Python PCM comparison for this integration and subjective audio
  quality; acoustic output was not captured with a microphone.
- Battery/energy, thermal soak, release builds, low-end SoCs, and a clean-clone
  Android build.
- MP3 PSS and a separate MP3 quality check.

## What This Validation Does Not Confirm

A fresh installation of the Python environment and a download of weights/sources
from the network from a clean clone were not repeated. Revisions and commands for this are recorded
in [setup.md](setup.md); checksums of the local source weights and
the main runtime set were verified.

GPU encoding, a new Android APK, actual playback on a device,
long-running load tests, and audio quality metrics were not part of the
2026-10-18 run. The 2026-10-25 SAME-S on-device run is described above.
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
