# Original SpectroStream weights

Model weights are **not stored in this repository**. The cache expected by
`encoder_service/env.sh` is `models/magenta_rt_cache/`.

Download the original SavedModels from Hugging Face:

- Model: <https://huggingface.co/google/magenta-realtime>
- Pinned revision: `c05f8d6d608afd588469b7a8ef0929d5a1f8f6bb`
- Code: Apache-2.0; model weights: CC-BY-4.0 (Google DeepMind)

The setup guide uses:

```python
from huggingface_hub import snapshot_download

snapshot_download(
    repo_id="google/magenta-realtime",
    revision="c05f8d6d608afd588469b7a8ef0929d5a1f8f6bb",
    allow_patterns=["savedmodels/ssv2_48k_stereo/**"],
    local_dir="models/magenta_rt_cache/assets",
)
```

Then follow [docs/setup.md](../docs/setup.md) and
[docs/model-export.md](../docs/model-export.md) to export the LiteRT runtime
assets. Checksums of the source bundle are in
[docs/source-model.sha256](../docs/source-model.sha256).

Do not commit downloaded weights or generated `.tflite` files.
