# Contributing

This repository is a benchmark and reference implementation for neural audio
codecs on Android. Contributions are welcome if they keep measurements
reproducible and licenses clear.

## Good contributions

- bug fixes in the Flutter app, Kotlin/LiteRT bridges, or C++ decoder;
- a new codec mode with a documented container, decoder, and license;
- a benchmark run with device, build, network profile, `THREADS`/`CORES`, and
  raw data;
- documentation fixes, especially setup/export steps that fail on a clean
  checkout;
- a multi-listener export for the blind6 protocol.

## Before opening a pull request

```bash
# Flutter/Dart
cd client_android
flutter analyze
flutter test

# Python data/chart scripts (from the repository root)
cd ..
python -m json.tool docs/benchmarks/blind6_mapping.json >/dev/null
uv run --with matplotlib python docs/benchmarks/plot_blind6.py

# C++ decoder (if touched)
cd decoder_cpp/build
cmake --build . -j"$(nproc)"
ctest --output-on-failure
```

Also check that no generated build directories, local SDK paths, model caches,
`local.properties`, `.env` files, or personal data are staged.

## Benchmark pull requests

A performance number is only useful with its context. Include:

- device model, Android version, build type (debug/release), ABI;
- codec/model file and checksum;
- `THREADS` and `CORES`;
- network profile and whether network/player startup is included;
- number of runs and the raw values;
- whether the number is time-to-playback, decoder-only, PSS, or quality.

Do not mix a network-inclusive startup with a decoder-only number. Update the
JSON under `docs/benchmarks/` and the corresponding report, not just a chart.

## New codecs and model weights

- Document the container format and sample rate.
- Add a license and attribution for the weights; do not commit a model whose
  redistribution terms are unclear.
- Keep model files out of Git unless the license explicitly allows
  redistribution and the file is intentionally part of the benchmark.
- Update `WEIGHTS.md`, `THIRD_PARTY_NOTICES.md`, and `LICENSES/` when needed.
- Add the mode to `DemoMode`, the settings screen, the asset installer, the
  decoder service, warm-up/play/stop paths, and tests.

See the [Android codec guide](docs/android-codec-guide.md) for the integration
checklist.

## Data and privacy

- Do not commit absolute paths, usernames, browser/session metadata, API keys,
  or private listening data.
- Blind-test exports should contain only trial ranks, scores, and the minimum
  protocol metadata. Remove page URLs, user agents, timezone, viewport, and
  listener identifiers.
- Generated demo media must be content you have the right to publish.

## License of contributions

By contributing code or documentation, you agree that your contribution is
licensed under the repository's Apache-2.0 license, unless it is a model weight
or other third-party material with a separate license stated in the pull
request.
