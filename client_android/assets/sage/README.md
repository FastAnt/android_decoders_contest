# SAGE runtime model

`dec_w8a8.tflite` is the SAGE rung-128 decoder used by the Android client.
It is a LiteRT/TFLite export of `SAGE_FTe992` with int8 weights and a sliced
post-net.

The model is **not stored in Git**. It is distributed as a GitHub Release
asset under **CC BY-NC-SA 4.0**, not under the Apache-2.0 license of the code:

- Download: <https://github.com/FastAnt/android_decoders_contest/releases/download/models-v1/sage_r128_dec_w8a8.tflite>
- Original: `SAGE_FTe992` by Francesco Brigante
- Source: <https://huggingface.co/francescobrigante/SAGE>
- License: <https://creativecommons.org/licenses/by-nc-sa/4.0/>
- Local license text: [../../../LICENSES/CC-BY-NC-SA-4.0.txt](../../../LICENSES/CC-BY-NC-SA-4.0.txt)
- Attribution, modifications and checksum: [../../../WEIGHTS.md](../../../WEIGHTS.md)

Download it with `./scripts/fetch_models.sh` from the repository root, or place
it at `assets/sage/dec_w8a8.tflite`; `AssetInstaller` copies it to app storage.
`demo.sage` is a small generated demo track included in the repository.

This model is non-commercial and share-alike. For commercial use, obtain
separate permission from the original rights holder.
