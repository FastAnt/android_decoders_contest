# Client Android Report

## Context Snapshot
- Date: 2026-07-12
- Scope: Flutter demo app for startup comparison MP3 vs Neural Codec
- Root: &lt;repository&gt;/client_android

## What Exists In Current App

### 0) Startup optimization status (latest)
- Decoder model is no longer recreated twice per Neural run.
- App now uses a persistent decoder worker isolate with cached native decoder handle.
- If model/threads are unchanged, next Neural Play reuses already loaded model state.
- Warmup is triggered after assets are ready and on model/threads changes.

### 1) Flutter app baseline
- App scaffold exists and runs from lib/main.dart.
- Single screen demo is implemented in lib/screens/demo_screen.dart.
- Dependencies configured in pubspec.yaml:
  - ffi
  - path_provider
  - just_audio
- Android config in android/app/build.gradle.kts:
  - minSdk = 26
  - abiFilters = arm64-v8a

### 2) UI and controls
- Screen title: MP3 vs Neural Codec Startup Time.
- Controls implemented:
  - Network: 3G / 4G / 5G
  - Mode: MP3 / Neural Codec
  - Model: f25 FP32 / f25 FP16 / f75 FP32
  - Threads: 1 / 2 / 4 / 6 / 8
  - Play / Stop
- Defaults implemented:
  - Network: 4G
  - Mode: Neural Codec
  - Model: f25 FP32
  - Threads: 6

### 3) Startup timing and simulated download
- Timer starts on Play.
- Simulated network uses profile throughput + ping.
- Downloaded bytes are updated in UI during prepare phase.
- Timer stops at actual playback start event (not at decode finish).

### 4) MP3 mode behavior
- Uses bundled asset assets/audio/demo.mp3.
- Simulates full file download before playback start.
- Starts playback with just_audio and captures startup time.

### 5) Neural mode behavior
- Uses bundled .sst and selected model.
- Simulates startup threshold equal to one second of SST transfer.
- After threshold is reached:
  - runs native first-block decode in isolate through FFI stream API,
  - converts first decoded PCM block to temp WAV,
  - starts playback,
  - stops startup timer.
- Background decode continues from the same native stream session (no duplicate first-block decode).
- Decoder reuse status is surfaced in UI text (loaded vs reused).

### 6) Asset installation strategy
- On first launch, neural assets are copied from Flutter assets to app support directory:
  - <app_support>/spectrostream/
- Copy is one-time, validated by file size state (install_state.json).
- Re-copy occurs only if size check fails.

### 7) Daily traffic section
- Implemented for 100 tracks/day.
- Uses real bundled file sizes (not hardcoded constants in UI rendering logic).
- Shows:
  - MP3 MB/day
  - Neural MB/day
  - Saving ratio x

## Bundled Artifacts (Current Sizes)
- assets/audio/demo.mp3: 6,485,854 bytes
- assets/spectrostream/demo.sst: 326,832 bytes
- assets/spectrostream/spectrostream_decoder_core_fp32_f25.tflite: 142,784,864 bytes
- assets/spectrostream/spectrostream_decoder_core_fp16_f25.tflite: 71,426,396 bytes
- assets/spectrostream/spectrostream_decoder_core_fp32_f75.tflite: 142,778,576 bytes
- assets/spectrostream/rvq_codebooks.f32: 67,108,864 bytes
- assets/spectrostream/istft_window_f960.f32: 3,840 bytes
- android/app/src/main/jniLibs/arm64-v8a/libspectrostream_decoder.so: 72,805,280 bytes
- android/app/src/main/jniLibs/arm64-v8a/libc++_shared.so: 9,236,352 bytes

## Current App Limitations

1. Neural playback is startup-focused, not full continuous track playback.
- App starts sound from first decoded block.
- Remaining decoded audio is not appended into a continuous audio stream player pipeline.

2. Background decode currently does compute work but is not connected to live playback queue.
- It is useful for timing/throughput experiments, not full listener experience.

2.1 First-ever warmup can still be slow on device.
- FP16 first run can still include heavy one-time model load/interpreter init cost.
- Optimization mainly improves subsequent runs and avoids duplicate per-play model loads.

3. Startup signal uses player state/position heuristics.
- Works for demo, but precise audio output timestamp is not guaranteed frame-accurate across devices.

4. Asset footprint is very large for APK-bundled delivery.
- Current requirement says bundled-in-APK and no cloud, but this is heavy for production.

5. Only arm64-v8a path is configured/tested in app integration.

6. No advanced runtime telemetry yet.
- No persistent logging for startup breakdown (ping phase, transfer phase, decode phase, player start).

## decoder_cpp: Changes Already Done

### A) C++ API additions
- In include/spectrostream/decoder.h:
  - Added StreamDecodeResult struct.
  - Added opaque StreamSession concept.
  - Added methods:
    - create_stream_session
    - create_stream_session_raw
    - decode_next_block
    - destroy_stream_session

### B) Decoder implementation refactor
- In src/decoder.cpp:
  - Extracted reusable core block synthesis logic.
  - Added stream session state (tokens, block index, model layout, emitted frame count).
  - Added block-by-block decode path for session mode.
  - Kept existing full decode_file path backward-compatible.

### C) C ABI extension
- In include/spectrostream/decoder_c_api.h:
  - Added stream handle type.
  - Added exported functions:
    - spectrostream_decoder_stream_create
    - spectrostream_decoder_stream_decode_next
    - spectrostream_decoder_stream_destroy

- In src/decoder_c_api.cpp:
  - Implemented stream handle lifecycle.
  - Added argument validation and error propagation.
  - Preserved existing old API behavior.

### D) Test updates
- In tests/test_c_api.c:
  - Added stream decode smoke test path.

### E) Verified exported symbols in Android .so
- Existing:
  - spectrostream_decoder_create
  - spectrostream_decoder_decode_file
  - spectrostream_decoder_free_pcm
  - spectrostream_decoder_destroy
  - spectrostream_decoder_last_error
- New:
  - spectrostream_decoder_stream_create
  - spectrostream_decoder_stream_decode_next
  - spectrostream_decoder_stream_destroy

## What Still Needs To Be Added In decoder_cpp

Priority 1 (required for robust continuous neural playback):
1. Stream metadata function(s)
- Add API to query stream parameters without consuming blocks:
  - sample_rate, channels, total_blocks, total_pcm_frames, block_pcm_frames.
- Suggested C ABI:
  - spectrostream_decoder_stream_get_info(...)

2. Better stream progress API
- Return current_block_index and total_blocks in decode_next response.
- This simplifies UI progress and diagnostics.

3. Explicit stream error accessor
- Add per-stream error getter:
  - spectrostream_decoder_stream_last_error(...)
- Current implementation writes errors primarily to parent decoder handle.

4. Stream cancel API
- Add cancellation to stop long background decode quickly and safely.
- Suggested C ABI:
  - spectrostream_decoder_stream_cancel(...)

Priority 2 (performance and integration quality):
5. Optional decode output format selection
- Add PCM16 output mode to reduce conversion overhead in Dart when needed.

6. Reuse-friendly stream lifecycle guarantees
- Clarify and test behavior for:
  - decode_next after done,
  - double destroy,
  - invalid handle transitions.

7. Lightweight warmup entrypoint
- Optional model warmup call to reduce first inference latency in UX-critical startup tests.

Priority 3 (future extensibility):
8. Seek/range decode support
- Support starting stream from a block offset for scrubbing or resume scenarios.

9. Streaming from memory buffer (not only file path)
- Useful for future encrypted/containerized delivery.

## Files Most Relevant For Next Agent
- Flutter app:
  - lib/main.dart
  - lib/screens/demo_screen.dart
  - lib/models/demo_config.dart
  - lib/services/network_simulator.dart
  - lib/services/asset_installer.dart
  - lib/services/spectrostream_ffi.dart
  - lib/services/audio_player_service.dart
  - pubspec.yaml
  - android/app/build.gradle.kts

- Native decoder:
  - decoder_cpp/include/spectrostream/decoder.h
  - decoder_cpp/src/decoder.cpp
  - decoder_cpp/include/spectrostream/decoder_c_api.h
  - decoder_cpp/src/decoder_c_api.cpp
  - decoder_cpp/tests/test_c_api.c

## Validation Status (Current)
- Flutter analyze: clean
- Flutter tests: passing
- Android decoder .so exports stream ABI symbols

## Practical Next Step Recommendation
- Keep current startup demo behavior as milestone baseline.
- Next implementation cycle should focus on true continuous neural playback pipeline that consumes stream blocks and feeds player without dropping to first-block-only experience.
