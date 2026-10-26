# Documentation index

This repository is a practical benchmark and reference implementation for
running neural music codecs on Android edge devices.

## Start here

- [Project README](../README.md) — benchmark overview, results, quick start.
- [Android codec guide](android-codec-guide.md) — implementation patterns,
  asset packaging, threading, audio, measurement, and a codec-addition checklist.
- [Model downloads](model-download.md) — SAGE and SAME-S runtime decoders,
  checksums, and release links.
- [Setup](setup.md) — Python environment, source weights, C++ dependencies.
- [Round-trip](roundtrip.md) — audio → SST → WAV.
- [Model export](model-export.md) — source weights → Android runtime assets.

## Codec implementations

- [SpectroStream / SST format](../decoder_cpp/docs/sst_format.md)
- [Decoder architecture](../decoder_cpp/docs/architecture.md)
- [SAME-S device report](same-s-device-report.md)

## Benchmarks and measurements

- [Android performance study](performance.md) — SpectroStream and SAGE on
  Tensor G2, with the old app-metric caveat.
- [Codec speed matrix](codec-speed-1c2t.md) — 3 codecs × {T1/C1, T2/C2} startup.
- [Decode 4 s on 1 core / 2 threads](decode-4s-2t1c.md) — decoder-only comparison.
- [Decode 4 s at default settings](decode-4s.md) — 6 threads, all cores.
- [Blind6 listening result + objective quality](blind6-analysis.md) — one
  listener: SpectroStream 80, SAGE 77, SAME-S 37; waveform vs spectral trade-off.
- [Validation](validation.md) — what was verified, what was not.
- [Benchmark data](benchmarks/README.md) — raw JSON and plotting scripts.

## App and codec build

- [Flutter/Android client](../client_android/README.md)
- [C++ decoder](../decoder_cpp/README.md)
- [Python encoder](../encoder_service/README.md)

## Contributing

- [Contribution guide](../CONTRIBUTING.md)

## Licensing

- [Weights and licenses](../WEIGHTS.md)
- [Third-party notices](../THIRD_PARTY_NOTICES.md)
- [License files](../LICENSES/README.md)

All documentation is in English.
