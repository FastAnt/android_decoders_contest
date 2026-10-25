# Neural Codecs Client Runtime

The project is a practical Android benchmark for three edge music codecs:
SpectroStream (SST → RVQ → LiteRT/XNNPACK → iSTFT, 48 kHz),
SAGE (LiteRT, 44.1 kHz), and SAME-S (LiteRT, 44.1 kHz).
Key metrics: payload/bitrate, time-to-playback, decoder-only speed vs real time,
CPU/RAM consumption, and objective/blind-listening quality.

The benchmark framing, results, and quick start are in [README.md](README.md);
implementation patterns are in [docs/android-codec-guide.md](docs/android-codec-guide.md).

- `encoder_service/` — Python batch encoder, model export, and diagnostics.
  Source model: `ssv2_48k_stereo`, Magenta RealTime `v1_legacy`.
- `decoder_cpp/` — standalone C++20 runtime, CLI, C API, tests, and Android scripts.
- `client_android/` — Flutter client with MP3/SpectroStream/SAGE/SAME-S modes,
  Kotlin/LiteRT bridges, network profiles, and HISTORY.
- `docs/` — setup, Android guide, benchmark reports, blind6 quality analysis,
  charts, and validation.
- `decoder_cpp/docs/` — architecture and SST container specification.
- `media/` — local source media, tokens, and reference WAVs.
  Encoder input: `media/data/input/`, output: `media/data/encoded/`,
  Python reference WAVs: `media/data/reconstructed/`.
- `models/`, `decoder_cpp/models/` — source model cache and exported weights.
- `third_party/`, `decoder_cpp/third_party/` — downloaded external dependencies.

SpectroStream source weights and prebuilt core models are not included in Git; links
to sources and export are in `models/README.md`, setup, and model-export.
Media, external dependencies, environments, and builds are excluded. The
SAGE and SAME-S decoder weights are intentionally included under their respective
licenses; SpectroStream binary models remain local and are not stored in Git.
Android icons are application resources and remain in `res/`. Empty stub
directories have been removed; create new directories together with their contents.

Python script paths are computed relative to `__file__`; do not add
absolute paths to the working copy. Reports from past experiments are kept
next to the code of the corresponding component.

## Working with a track

Preparation order: [docs/setup.md](docs/setup.md), then
[docs/roundtrip.md](docs/roundtrip.md); for C++ without prebuilt assets —
[docs/model-export.md](docs/model-export.md). Actually verified commands
and limitations are recorded in [docs/validation.md](docs/validation.md).

For CPU, set `CUDA_VISIBLE_DEVICES=-1` after `source encoder_service/env.sh`.
Do not treat the batch encoder exit code as sufficient verification: track errors
are written to `error.json`, and the process may return 0. Check metadata,
counters, and files; use a new output directory inside `media/`.
Python verification decodes the tokens of the current run; independent reading of SST
is verified via the C++ CLI. q16/q32 in metadata are estimates; SST is stored as q64.

Do not rewrite the reference track for a smoke test. Do not upgrade dependencies
to the latest versions to work around an installation error without separate
verification. Reports from past experiments may describe outdated limitations.
