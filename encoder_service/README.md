# Python Encoder and SpectroStream Export

[Environment and weight setup](../docs/setup.md) ·
[Full cycle on your own track](../docs/roundtrip.md) ·
[Exporting C++ assets](../docs/model-export.md)

All examples are run from the repository root. Scripts compute default
directories relative to `__file__`; CLI path arguments are relative to the current
working directory. Do not run re-encoding in the reference fixture directory
unless you intend to replace it.

## batch_encode.py

Input is a file or a recursively scanned directory with the extensions
`.wav`, `.wave`, `.mp3`, `.flac`, `.ogg`, `.opus`, `.m4a`, and `.aac`.
FFmpeg converts audio to float32 PCM 48000 Hz stereo.
Encoding uses RVQ depth 64 and writes SST1 with 10-bit tokens.

Main options:

- `--input PATH` — file/directory; default `media/data/input/`.
- `--output DIR` — SST and metadata; default `media/data/encoded/`.
- `--reconstructed DIR` — reference WAVs; default `media/data/reconstructed/`.
- `--device cpu|gpu|auto` — default `gpu`; for CPU on a GPU machine, also
  set `CUDA_VISIBLE_DEVICES=-1` after `source encoder_service/env.sh`.
- `--max-seconds N` — limit each track to the first N seconds.
- `--limit N` — process the first N files found.
- `--verify-first N` — reconstruct the first N new tracks; default 0.
- `--verify-depths 16,32,64` — reference decoding depths;
  only 16, 32, and 64 are allowed, default all three.
- `--force` — re-process previously encoded files.
- `--inference-chunk-seconds N` — central inference fragment, default 8 s.
- `--context-seconds N` — context on each side, default 1 s.

The container is split into chunks of 25 codec frames (1 s) with separate CRCs.
This is a separate concept from the 8-second inference fragments.

```bash
source encoder_service/.venv/bin/activate
source encoder_service/env.sh
export CUDA_VISIBLE_DEVICES=-1
python encoder_service/batch_encode.py --help
```

For batch processing, pass your own directory to `--input`.
The same 32-character ID in MP3 and WAV filenames produces the same output ID;
do not put alternative versions of the same track into a batch without accounting for this rule.

## How to Determine Successful Processing

A successful track has `metadata.json` with `status: success` and
`container_validated: true`, the actual SST, and an entry in `catalog.json`.
Track errors are written to `error.json`; the process may exit with code 0
despite errors. Check `Failed in this run` and the files created.
A data directory from previous runs may contain stale successful entries.

The encoder skips suitable completed results. Changing only
`--verify-first`/`--verify-depths` does not trigger reprocessing; `--force`
or a new output directory is required. The q16/q32 variants in metadata are calculated
estimates, while the recorded SST remains q64.

## Export and Diagnostics

The recommended path is described in [model-export.md](../docs/model-export.md).
`export_litert_core_v3.py` creates core models for C++/Flutter.
`export_decoder_assets.py` and `export_litert_assets.py` also contain
helper functions for preparing a SavedModel and codebooks.

Standalone ONNX/Flex experiments (`diagnose_onnx_decoder.py`,
`export_decoder_assets.py` as a CLI, the full `export_litert_assets.py` CLI)
are not required for the main C++ path. The old `export_litert_core.py` and
`export_litert_core_v2.py` are kept for reproducing research;
do not choose them as the main exporter for a new run.
