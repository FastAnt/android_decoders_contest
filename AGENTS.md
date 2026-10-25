# Working with Neural Codecs

Start with [README.md](README.md) and the [documentation index](docs/README.md).
For Android integration patterns, read [docs/android-codec-guide.md](docs/android-codec-guide.md).
Practical order:

1. [docs/setup.md](docs/setup.md) — Python, source weights, and C++ dependencies.
2. [docs/roundtrip.md](docs/roundtrip.md) — your track → SST → WAV.
3. [docs/model-export.md](docs/model-export.md) — producing C++ assets from source weights.
4. [docs/validation.md](docs/validation.md) — completed validations and their limitations.

Run guide commands from the repository root unless explicitly stated otherwise.
SpectroStream source weights and prebuilt core models are not included in Git; links
and download/export order are in `models/README.md`, setup, and model-export.
A clean clone has no user media, external checkouts, environments, or builds.
Their preparation is described in setup; weight checksums are in `docs/`.

For CPU, set `CUDA_VISIBLE_DEVICES=-1` after sourcing
`encoder_service/env.sh`, because that file resets the variable.
Changing `--verify-first` alone does not cancel skipping an existing track.

The batch encoder can return 0 after an individual track fails: check
counters, metadata, error.json, and the actual files. Use a new experiment
directory inside `media/` so a previous result is not mistaken for a new one.
Do not overwrite the local reference track for a smoke test.

Python verification decodes the tokens of the current process. For independent
verification of a saved SST, use the C++ CLI, as in roundtrip.
q16/q32 in metadata are transmission estimates; the recorded SST contains q64.

SST/RVQ tests depend on a specific local fixture. For your own short
SST, use the CLI and C API with explicit paths. Old experiment reports
do not replace current instructions; they may describe outdated limitations.
