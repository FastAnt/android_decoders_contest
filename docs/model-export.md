# Prepare Models for C++ and Flutter

To reconstruct SST, the runtime needs a matching TFLite core model,
RVQ codebooks, and an iSTFT window. The source Magenta weights and the TensorFlow package
are needed at the export stage; the prebuilt C++ runtime does not use Python.

## Prebuilt Set or Custom Export

Prebuilt f25/f75/f100 core models in FP32/FP16, codebooks, and the window are **not
stored in Git**. They must be exported from the source Magenta weights or
downloaded separately. The files the C++ runtime expects:

- `spectrostream_decoder_core_fp32_f25.tflite` — 142784864 bytes;
- `rvq_codebooks.f32` — 67108864 bytes;
- `istft_window_f960.f32` — 3840 bytes.

Links to the source weights are in [models/README.md](../models/README.md).
After preparing the set, verify the checksums:

```bash
sha256sum -c docs/decoder-f25.sha256
```

The recipe below is used to reproduce and modify the models. On re-export,
the TFLite bytes may differ: keep your own report, checksums, and numerical
verification results.

Reports of the original exports are kept in Git:
[f25](model-reports/decoder_core_export_f25.json),
[f75](model-reports/decoder_core_export_f75.json), and
[f100](model-reports/decoder_core_export_f100.json), along with
`runtime-assets.sha256` for all six available core models, codebooks,
and the window. In the reports, paths are normalized relative to the project root.
Re-exporting f25 FP32 and FP16 produced the same SHA256 as the project's original set.
Intermediate exported SavedModels, ONNX, and Flex experiments
remain local; the source and runtime weights are not stored in Git.

## 1. Prepare SavedModels and Codebooks

Complete the [Python setup and source weight download](setup.md).
All commands below are run from the repository root.
The `MODEL_DIR` directory must be new or must not contain results from a previous
export. Example export to a new directory without overwriting source weights:

```bash
source encoder_service/.venv/bin/activate
source encoder_service/env.sh
export CUDA_VISIBLE_DEVICES=-1
export OMP_NUM_THREADS=4
export TF_NUM_INTRAOP_THREADS=4
export TF_NUM_INTEROP_THREADS=2
export MODEL_DIR="media/model-export-f25-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$MODEL_DIR"

python - <<'PY'
import os
from pathlib import Path
import tensorflow as tf
from magenta_rt import spectrostream
from encoder_service.export_decoder_assets import (
    create_input_spec,
    export_codebooks,
    export_wrapped_savedmodel,
)
from encoder_service.export_litert_assets import export_fixed_savedmodel, load_signature

models = Path(os.environ['MODEL_DIR']).resolve()
codec = spectrostream.SpectroStream(max_rvq_depth=64, lazy=True)
export_codebooks(codec, models)
export_wrapped_savedmodel(codec, models, create_input_spec(None), force=False)
model, input_key, output_key = load_signature(tf, models / 'decoder_savedmodel')
export_fixed_savedmodel(
    tf=tf,
    source_model=model,
    input_key=input_key,
    output_key=output_key,
    frames=25,
    destination=models / 'decoder_savedmodel_f25',
    force=False,
)
PY
```

This recipe uses the existing exporter functions and creates
`rvq_codebooks.npy`, `rvq_codebooks.f32`, `rvq_codebooks.json`,
`decoder_savedmodel/`, and `decoder_savedmodel_f25/`.
It does not perform the optional ONNX and Flex conversions.
To reproduce, choose a new `MODEL_DIR`; do not add forced
overwriting of working models unless necessary.

## 2. Export the Core and iSTFT Window

```bash
python encoder_service/export_litert_core_v3.py \
  --models-dir "$MODEL_DIR" \
  --frames 25 \
  --threads 4 \
  --runs 1
```

FP32 and FP16 core models, `decoder_core_savedmodel_f25/`,
`istft_window_f960.f32` with metadata, and `decoder_core_export_f25.json` are created.
`--runs 1` reduces the number of inference measurements; for benchmarks, use
a larger number. The script checks numerical equivalence against TensorFlow itself;
`FP32 validation PASSED` and exit code 0 are expected.

FP32 core model input: `[1, 25, 256]` float32 embeddings.
Output: `[1, 2, 100, 481, 2]` float32, real/imag STFT.
C++ performs iSTFT separately. A full model with PCM output or a file with Flex
operators is not a replacement for the core model.

Check the report and SHA256 of the created models:

```bash
python - <<'PY'
import hashlib
import json
import os
from pathlib import Path

root = Path(os.environ['MODEL_DIR'])
report = json.loads((root / 'decoder_core_export_f25.json').read_text())
for precision, model in report['models'].items():
    path = Path(model['path'])
    assert model['operator_mode'] == 'builtin_only'
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    assert digest == model['sha256']
    print(precision, path.name, path.stat().st_size, digest)
for filename in ['rvq_codebooks.f32', 'istft_window_f960.f32']:
    assert (root / filename).is_file()
PY
```

Now you can perform the [C++ part of the round-trip](roundtrip.md).
If you exported to a non-standard directory, pass its files
to `--model`, `--codebooks`, `--window` instead of the standard paths.

## Other Models and Research Scripts

For f75/f100, prepare a fixed SavedModel with the same
`export_fixed_savedmodel` call, changing `frames` and the directory name, then run
the core export with the corresponding `--frames`. Verify f25 first;
additional variants are needed by Flutter and separate experiments.

The full `export_decoder_assets.py` CLI also converts ONNX and requires
`tf2onnx`, `onnx`, and `onnxruntime`, which are not in the main frozen list.
In the research environment, versions 1.17.0, 1.22.0, and 1.27.0 were observed
respectively; the recommended path above does not need these packages.
After saving a fixed SavedModel, the `export_litert_assets.py` CLI
attempts to convert the full model with Complex/IRFFT and may use
Flex or fail numerical validation. Therefore the main recipe
calls only its SavedModel preparation function.

The old `export_litert_core.py` and `export_litert_core_v2.py` are previous
experiments. The ONNX model, the full TFLite/Flex model, and the builtin-only core
have different contracts and are not interchangeable.

[Verified steps and limitations](validation.md).
