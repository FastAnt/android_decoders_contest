# Setup from a Clean Clone

All commands are run in Bash from the repository root on Linux.
Verified existing environment: Ubuntu 24.04 x86-64, Python 3.12.3,
TensorFlow 2.20.0, NumPy 2.4.6, GCC 13.3, CMake 3.28.3, FFmpeg 6.1.1.
A fresh installation of all packages and a download of dependencies from scratch
have not been repeated separately; the [validation limits](validation.md) are stated explicitly.

## 1. System Tools

Git, Python 3.12 with `venv`, and FFmpeg/ffprobe are required. Building C++ also requires
CMake 3.22+ and a C++20 compiler; Ninja can be used instead of Make.
Install these tools with your OS package manager. For the full Python path,
the source weight cache takes about 484 MiB, and the environment with dependencies —
several GiB; the C++ build and export add further GiB.

## 2. Python Environment

```bash
python3.12 -m venv encoder_service/.venv
source encoder_service/.venv/bin/activate
python -m pip install -r encoder_service/requirements.lock.txt
python -m pip check
source encoder_service/env.sh
export CUDA_VISIBLE_DEVICES=-1
```

The dependency list pins Magenta RealTime at revision
`04ebaa7da13701734281c630ffd13f7ee9893e45` (`v1_legacy`, package `magenta_rt` 0.3.0).
A separate checkout in `third_party/magenta-realtime/` is not required:
`pip` installs the pinned editable dependency from Git.
Do not replace this revision with the current upstream branch without separate verification.

`env.sh` **resets** `CUDA_VISIBLE_DEVICES`; therefore the CPU variable
must be set **after** sourcing the file. On a machine with a GPU, the combination
`--device cpu` without this variable may fail with
`Physical devices cannot be modified after being initialized`: Magenta
tries to change GPU memory growth after TensorFlow initialization.
For a GPU run, do not set the variable to `-1`; the GPU scenario has not been verified here.

The import check does not load the weights yet:

```bash
python -c 'import tensorflow as tf; from magenta_rt import spectrostream; print(tf.__version__)'
ffmpeg -version
```

## 3. SpectroStream Source Weights

Magenta uses the `encoder`, `decoder`, and `quantizer` from `ssv2_48k_stereo`.
The SavedModels themselves are **not included in Git**: they must be downloaded from Hugging Face.
Links, the pinned revision, and the license are in
[models/README.md](../models/README.md). After downloading, verify integrity:

```bash
sha256sum -c docs/source-model.sha256
```

If the check passes, proceed to the round-trip.
By default, `env.sh` sets the source to `hf` and the cache root to
`models/magenta_rt_cache/`. On the first run, Magenta may fetch
missing models itself, but this path does not pin the weights revision.

To re-download lost weights or use a different working directory,
use the Hugging Face revision recorded in the source cache metadata:

```bash
python - <<'PY'
import os
from pathlib import Path
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id='google/magenta-realtime',
    revision='c05f8d6d608afd588469b7a8ef0929d5a1f8f6bb',
    allow_patterns=['savedmodels/ssv2_48k_stereo/**'],
    local_dir=Path(os.environ['MAGENTA_RT_CACHE_DIR']) / 'assets',
)
PY
sha256sum -c docs/source-model.sha256
```

Expected structure: `models/magenta_rt_cache/assets/savedmodels/ssv2_48k_stereo/`,
containing `encoder/`, `decoder/`, and `quantizer/` with SavedModel and variables.
You can copy this complete directory from a prepared environment instead of
downloading it again. The checksum check above uses the standard location.

For a different cache, set `MAGENTA_RT_CACHE_DIR` before sourcing `env.sh`.
The cache and source variables must be set before importing Magenta.
Do not create empty model directories manually: Magenta may treat
an existing directory as an already downloaded asset.

After that, the [Python round-trip](roundtrip.md) is available. C++ and Android
are not needed for it.

## 4. C++ Dependencies — If Needed

TensorFlow Lite is **not downloaded automatically**: CMake expects local
TensorFlow sources. The confirmed local version is v2.18.0,
commit `6550e4bd80223cdb8be6c3afd1f81e86a4d433c3`.
The Python TensorFlow version is 2.20.0 — these are different components.

On a clean clone:

```bash
mkdir -p decoder_cpp/third_party
git clone --branch v2.18.0 --depth 1 \
  https://github.com/tensorflow/tensorflow.git \
  decoder_cpp/third_party/tensorflow
test "$(git -C decoder_cpp/third_party/tensorflow rev-parse HEAD)" = \
  6550e4bd80223cdb8be6c3afd1f81e86a4d433c3
```

CMake downloads additional dependencies, including PocketFFT. In CMake,
PocketFFT is pinned to the `cpp` branch; the observed working revision is
`c90e55b3d529f8efa40ed01a20de22405f45fc65`. To pin it explicitly:

```bash
git clone https://github.com/mreineck/pocketfft.git \
  decoder_cpp/third_party/pocketfft
git -C decoder_cpp/third_party/pocketfft checkout --detach \
  c90e55b3d529f8efa40ed01a20de22405f45fc65
cmake -S decoder_cpp -B decoder_cpp/build \
  -DCMAKE_BUILD_TYPE=Release \
  -DFETCHCONTENT_SOURCE_DIR_POCKETFFT="$PWD/decoder_cpp/third_party/pocketfft"
cmake --build decoder_cpp/build -j4
```

For an already configured working copy, the regular build commands from the
[decoder README](../decoder_cpp/README.md) are sufficient. Sources in `third_party/`
are excluded from Git. Decoding also requires
[exported assets](model-export.md) — they are **not included in Git**,
and the C++ build does not create them. They must be exported or downloaded separately.

Checksums for the source weight set and runtime assets are kept for
verification after download: `docs/source-model.sha256`,
`docs/runtime-assets.sha256`, and `docs/packaged-weights.sha256`.
