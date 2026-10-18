# Neural Codecs Client Runtime

The project investigates client-side CPU decoding of Google SpectroStream from Magenta
RealTime: 48 kHz stereo audio → SST tokens → RVQ → LiteRT/XNNPACK → iSTFT → PCM.
Key metrics: data size, bitrate, startup speed, real-time factor,
CPU/RAM consumption, and streaming playback.

Current structure and launch commands are described in [README.md](README.md).

- `encoder_service/` — Python batch encoder, model export, and diagnostics.
  Source model: `ssv2_48k_stereo`, Magenta RealTime `v1_legacy`.
- `decoder_cpp/` — standalone C++20 runtime, CLI, C API, tests, and Android scripts.
- `client_android/` — Flutter client with MP3/neural demo and network profiles.
- `decoder_cpp/docs/` — architecture and SST container specification.
- `media/` — local source media, tokens, and reference WAVs.
  Encoder input: `media/data/input/`, output: `media/data/encoded/`,
  Python reference WAVs: `media/data/reconstructed/`.
- `models/`, `decoder_cpp/models/` — source model cache and exported weights.
- `third_party/`, `decoder_cpp/third_party/` — downloaded external dependencies.

SpectroStream source weights and prebuilt core models are not included in Git; links
to sources and export are in `models/README.md`, setup, and model-export.
Media, external dependencies, environments, and builds are excluded. Flutter demo files
in `client_android/assets/` are a small generated track included in the repository;
binary models are not stored alongside them. Android icons are application resources
and remain in `res/`. Empty stub directories have been removed; create new directories
together with their contents.

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
