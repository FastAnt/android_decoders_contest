# Runtime model downloads

The two runtime TFLite decoders are **not stored in Git**. They are published as
GitHub Release assets so the repository stays small:

- Release: `models-v1`
- Base URL:
  <https://github.com/FastAnt/android_decoders_contest/releases/download/models-v1>

## One command

From the repository root:

```bash
./scripts/fetch_models.sh
```

The script downloads into the asset paths expected by the app and verifies the
SHA-256 checksums.

## Files

| Codec | Release asset | Destination | Size | SHA-256 |
|---|---|---|---:|---|
| SAGE r128 | `sage_r128_dec_w8a8.tflite` | `client_android/assets/sage/dec_w8a8.tflite` | 59,154,272 B | `d173b21e34b12e4be163741918bbd56870e16464f3d6d8592659d1855e88daa4` |
| SAME-S s128 | `same_s_s128_dec_w8a8.tflite` | `client_android/assets/same/dec_w8a8_s128.tflite` | 81,517,872 B | `7802697d21c67968974c117626da42e55bf0dd250126e0be9a4cfe86245e0ef6` |

Direct links:

- [SAGE r128 decoder](https://github.com/FastAnt/android_decoders_contest/releases/download/models-v1/sage_r128_dec_w8a8.tflite)
- [SAME-S s128 decoder](https://github.com/FastAnt/android_decoders_contest/releases/download/models-v1/same_s_s128_dec_w8a8.tflite)

## Licenses and provenance

The files are project exports/adaptations; do not treat them as Apache-2.0.

- **SAGE**: `SAGE_FTe992` by Francesco Brigante, **CC BY-NC-SA 4.0**.
  Original: <https://huggingface.co/francescobrigante/SAGE>
- **SAME-S**: Stability AI, **Stability AI Community License**.
  Original: <https://huggingface.co/stabilityai/SAME-S>
  (revision `63a63b7193ee9b6ee9836776c5f3c52a2f9600df`).

See [WEIGHTS.md](../WEIGHTS.md), [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md),
and the [license files](../LICENSES/README.md) for attribution, modification
details, and full terms.

The SAME-S release asset is a derivative of the original checkpoint: int8 W8A8
LiteRT export, sliced to the `s128` signature. The SAGE release asset is a
LiteRT int8 export with a sliced post-net. Both remain under their respective
upstream licenses.

If you already have the files, place them at the destinations above; the app
does not download models at runtime.
