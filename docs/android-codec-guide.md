# Android neural audio codec guide

A practical guide to integrating a neural music decoder into an Android app and
benchmarking it on edge hardware. The repository implements three backends side
by side; this document explains the reusable parts, not just one codec.

## 1. What you need

- An Android app (this project uses Flutter, but the native patterns are the
  same for a native Android app).
- A decoder that can run on the CPU: LiteRT/TFLite with XNNPACK, or a C++
  runtime with a stable C ABI.
- Encoded assets and decoder weights. Keep them out of the APK when they are
  large; copy them to app storage on first launch.
- A PCM output path: `AudioTrack`, `just_audio`/ExoPlayer, or another player.
- A benchmark protocol: network profile, decoder warm-up, thread/core limits,
  repeats, and a way to inspect history.

## 2. Architecture used here

```text
Flutter UI (Dart)
  ├─ mode / model / thread / core settings
  ├─ simulated network + asset installer
  ├─ startup timer and HISTORY
  └─ audio player (just_audio, PCM16 WAV chunks)
        │
        ├─ SpectroStream: dart:ffi isolate → C++ decoder → TFLite/XNNPACK → iSTFT
        ├─ SAGE:          MethodChannel → Kotlin bridge → LiteRT → SageDsp
        └─ SAME-S:        MethodChannel → Kotlin bridge → LiteRT → PCM
```

Two integration styles are deliberately included:

| Style | Codec | When to use |
|---|---|---|
| C ABI + `dart:ffi` | SpectroStream | Existing C++ decoder, DSP stages, strict control over native memory |
| Kotlin + MethodChannel | SAGE, SAME-S | LiteRT/Java API, simpler Android library, no custom JNI |

The app keeps **one large decoder alive at a time**. Switching modes stops the
session, releases the inactive decoder, and warms the selected one.

## 3. Package the assets

Models are large. The app uses this sequence:

1. Put model/container files under `client_android/assets/<codec>/`.
2. On first launch, copy them to the application support directory with an
   install-state file (`revision` + file sizes).
3. Load the decoder from the copied file path, not from the APK.
4. Use a weight-cache path in `cacheDir` for LiteRT/XNNPACK.
5. Bump the asset revision whenever a model or demo track changes.

Example (SAME-S):

```dart
await file.writeAsBytes(bytes, flush: true);
final config = SameDecoder.Config(
  threads: threads,
  rung: 128,
  trim: 8,
  engine: SameDecoder.EngineKind.COMPILED,
  weightCachePath: cachePath,
);
final decoder = SameDecoder.fromFile(modelPath, config);
```

The model file is 81.5 MB; keeping it out of the APK is often preferable for
real distribution, but this benchmark includes it for reproducibility.

## 4. Keep decoding off the UI thread

A LiteRT interpreter or C++ decoder is not thread-safe.

- Kotlin bridge: one `Executors.newSingleThreadExecutor()` per codec; all
  commands (`preload`, `start`, `next`, `stop`, `release`) are serialized.
- C++/FFI: one Dart isolate per decoder; never call the native handle from the
  UI isolate.
- Send PCM back in chunks; a 10 s stereo float chunk is ~3.9 MB, so avoid
  copying it more than necessary.

Useful log line from the bridge:

```kotlin
Log.i("SameBridge", "decoder init ${modelBytes}B threads=$threads cores=$cores")
```

## 5. CPU affinity and threads

`THREADS` is the LiteRT/XNNPACK worker count. `CORES` pins the decoder thread
and the workers it creates (the app selects the highest-numbered CPUs).

- Call `sched_setaffinity` **on the decoder thread before creating the model**
  so XNNPACK workers inherit the mask.
- `CORES=1, THREADS=2` is legal but means two workers share one CPU; it can be
  slower than one thread and can make a codec miss real time.
- The JNI affinity symbol in this repository belongs to `SageBridge`
  (`Java_com_neuralcodecs_client_1android_SageBridge_nativeSetAffinity`).
  `SameBridge` reuses it through a Kotlin lambda; copying the `external fun`
  declaration into another class would look for a different symbol.
- `CORES` is an affinity restriction, not a reservation. Other app/system
  threads can still use those CPUs.

## 6. Audio output and the startup metric

A simple pipeline is:

1. Decode the first block/window.
2. Write it as a temporary WAV (PCM16 stereo).
3. `just_audio.setAudioSources([...])` and start playback.
4. Decode later blocks on the decoder thread and enqueue more WAV sources.

### Pitfall: do not await `play()`

`just_audio`'s `play()` future completes when playback **finishes or pauses**,
not when audio starts. Awaiting it makes "time to playback" equal to the first
chunk duration (for SAME-S, an 11.15 s window looked like 12 s). Use:

```dart
unawaited(_player.play());
await waitForPlaybackStart(); // playing && (ready || completed)
```

`waitForPlaybackStart` should use `PlayerState.playing` plus
`ProcessingState.ready`, not `position > 0` alone.

### Window granularity matters

| Codec | Unit for 4 s | What you actually pay |
|---|---|---|
| SpectroStream | 1 s block | 4 blocks |
| SAGE | 2.97 s core window | 2 windows (~5.94 s of compute) |
| SAME-S | 11.15 s window | 1 window |

So "4 s decode" is **not** `RTF × 4` for SAGE/SAME-S. This is why the
[4 s benchmark](decode-4s-2t1c.md) reports window-level sums.

## 7. Add a new codec: checklist

1. **Container/encoder**: define the file format and metadata (sample rate,
   channels, original sample count, model id, checksums).
2. **Android decoder**: provide a pure decoder class with `open`, `decodeNext`,
   `reset`, `close`, and statistics (window time, windows decoded).
3. **Bridge**: a MethodChannel handler with `preload/start/next/stop/release`,
   one executor, and errors as `PlatformException`.
4. **Dart service**: mirror the bridge and convert `Uint8List` PCM to
   `Float32List`.
5. **Assets/installer**: add files, sizes, revision, and model path.
6. **Mode plumbing**: extend the mode enum and every switch (warm-up, network
   size, play, stop, pump, labels, target counter).
7. **UI**: add the mode chip; for a fixed model, show a read-only row; keep the
   existing visual style.
8. **Memory lifecycle**: release inactive decoders; stop the session before
   changing mode.
9. **Tests**: Python round-trip, a model/decoder parity check, `flutter analyze`,
   `flutter test`, and an on-device smoke run.
10. **Docs/licensing**: model provenance, checksum, license, attribution, and
    benchmark results.

The SAME-S integration is a complete worked example:

- [SAME-S device report](same-s-device-report.md)
- [SAME-S integration plan (Russian, historical)](same-s-integration-plan.ru.md)
- [SameBridge](../client_android/android/app/src/main/kotlin/com/neuralcodecs/client_android/SameBridge.kt)
- [SameDecoder](../client_android/android/app/src/main/kotlin/com/samecodec/decoder/SameDecoder.kt)

## 8. Benchmark protocol

A reproducible run needs more than one timing:

- **Startup:** from Play to the player's `ready`/playing state.
- **Decode-only:** sum the decoder windows needed for the target duration;
  exclude network and player.
- **Memory:** process PSS with the decoder loaded, and after mode switches.
- **Quality:** objective metrics on aligned segments, plus a blind listening
  test if possible.
- **Configuration:** device, Android version, build type, network profile,
  `THREADS`, `CORES`, warm/cold model, repeats.

Do not compare a network-inclusive startup with a pure decode number. State
which one is on the slide.

### Results in this repository

| Report | What it covers |
|---|---|
| [performance.md](performance.md) | SpectroStream/SAGE Tensor G2 study, old app metric caveat |
| [codec-speed-1c2t.md](codec-speed-1c2t.md) | 3 codecs × {T1/C1, T2/C2} startup, Samsung S25 |
| [decode-4s-2t1c.md](decode-4s-2t1c.md) | 4 s PCM at 2 threads / 1 core |
| [same-s-device-report.md](same-s-device-report.md) | SAME-S integration, PSS, window logs |
| [blind6-analysis.md](blind6-analysis.md) | objective quality trade-off from blind6 |
| [validation.md](validation.md) | what was and was not verified |

## 9. Quality: no free winner

The blind6 objective data shows a split:

- **SAME-S** wins SI-SDR and waveform SNR in all 30 trials.
- **SpectroStream** wins MR-STFT, log-mel, and ICC in all 30 trials.
- **SAGE** is generally between or below them on these metrics.

The codecs optimize different things. A product decision needs a listening test
on the target content; the `blind6` artifact has the fixtures but no exported
human votes. See [blind6-analysis.md](blind6-analysis.md) for the charts and the
missing-data caveat.

## 10. Licensing

- Original code/docs: Apache-2.0.
- SAGE weights: CC BY-NC-SA 4.0.
- SAME-S weights: Stability AI Community License (non-commercial/research;
  commercial registration required; full text in `LICENSES/`).
- SpectroStream weights: not in this repository; see setup/model-export.

Keep model files and licenses separate from the Apache-2.0 code. See
[WEIGHTS.md](../WEIGHTS.md) and [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).
