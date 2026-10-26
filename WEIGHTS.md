# Model weights and licenses

This repository contains **code** and **two downloadable model weight files**
with different licenses. The root [LICENSE](LICENSE) (Apache-2.0) covers the original code and
documentation only. It does **not** cover the SAGE or SAME-S model weights.

## Download: SAGE rung-128 decoder

| Field | Value |
|---|---|
| File | `client_android/assets/sage/dec_w8a8.tflite` |
| Download | [GitHub Release `models-v1`](https://github.com/FastAnt/android_decoders_contest/releases/download/models-v1/sage_r128_dec_w8a8.tflite) |
| Size | 59,154,272 bytes |
| SHA-256 | `d173b21e34b12e4be163741918bbd56870e16464f3d6d8592659d1855e88daa4` |
| Original work | `SAGE_FTe992` by Francesco Brigante |
| Original source | <https://huggingface.co/francescobrigante/SAGE> |
| License | [CC BY-NC-SA 4.0](https://creativecommons.org/licenses/by-nc-sa/4.0/) |
| Local license text | [LICENSES/CC-BY-NC-SA-4.0.txt](LICENSES/CC-BY-NC-SA-4.0.txt) |

**Modifications:** the original `SAGE_FTe992` checkpoint was exported to a
LiteRT/TFLite inference model for this project: int8 weights, fixed rung 128,
and a sliced post-net for the Android decoder. The TFLite export is an
adaptation of the original model and is distributed under the same
CC BY-NC-SA 4.0 terms.

Download with `./scripts/fetch_models.sh` or from the release link above. The
file is not stored in Git.

### What the license means for these weights

- **Attribution:** credit Francesco Brigante / SAGE, link the original source
  and the CC BY-NC-SA 4.0 license, and indicate that changes were made.
- **NonCommercial:** you may not use the weights for commercial purposes
  without separate permission from the licensor.
- **ShareAlike:** if you remix, transform, or build upon the weights, you must
  distribute your contribution under CC BY-NC-SA 4.0.
- **No endorsement:** do not suggest that the original author endorses this
  project or its use of the model.

This is a summary for repository hygiene, not legal advice. For a commercial
use case, obtain the appropriate permission from the original rights holder.

## Download: SAME-S s128 decoder

| Field | Value |
|---|---|
| File | `client_android/assets/same/dec_w8a8_s128.tflite` |
| Download | [GitHub Release `models-v1`](https://github.com/FastAnt/android_decoders_contest/releases/download/models-v1/same_s_s128_dec_w8a8.tflite) |
| Size | 81,517,872 bytes |
| SHA-256 | `7802697d21c67968974c117626da42e55bf0dd250126e0be9a4cfe86245e0ef6` |
| Original work | SAME-S by Stability AI |
| Original source | <https://huggingface.co/stabilityai/SAME-S> (revision `63a63b7193ee9b6ee9836776c5f3c52a2f9600df`) |
| Upstream code | <https://github.com/Stability-AI/stable-audio-3> |
| License | Stability AI Community License |
| Local license text | [LICENSES/STABILITY-AI-COMMUNITY-LICENSE.txt](LICENSES/STABILITY-AI-COMMUNITY-LICENSE.txt) |

**Modifications:** the original checkpoint was exported to LiteRT/TFLite with
int8 W8A8 weights (`dec_w8a8.tflite`, 89,329,616 bytes, SHA-256
`90cad5ef81e6b18eb205012aee03bc53ed59e1c17033b79a84a4612674b1e03a`), and the
`s128` decoder signature was sliced out for the Android client. On the same
input window the sliced model's output is bit-identical to the full export's
`s128` signature (measured maxdiff 0.0). The TFLite export and the slice are
adaptations of the original model and remain under the Stability AI Community
License.

This Stability AI Model is licensed under the Stability AI Community License,
Copyright © Stability AI Ltd. All Rights Reserved.

**Powered by Stability AI.**

Download with `./scripts/fetch_models.sh` or from the release link above. The
file is not stored in Git.

### What the license means for these weights

- **Research / non-commercial:** free use, including evaluation and testing.
- **Commercial:** allowed under the Community License up to the stated annual
  revenue threshold, but registration with Stability AI is required; above the
  threshold a separate commercial license is needed.
- **Distribution:** provide a copy of the agreement, retain the attribution
  notice above, and prominently display “Powered by Stability AI” in the UI or
  product documentation.
- **Derivative works:** indicate that the model was changed and how (here:
  LiteRT W8A8 export and s128 slice).
- **Trademarks:** do not use Stability AI names or marks except as required by
  the license.

This is a summary for repository hygiene, not legal advice. See the full
license text and <https://stability.ai/community-license> for the authoritative
terms.

## Not included: SpectroStream weights

The Google Magenta RealTime / SpectroStream model weights are **not stored in
this repository**. They are published by Google under **CC-BY-4.0**:

- <https://huggingface.co/google/magenta-realtime>
- Export instructions: [docs/model-export.md](docs/model-export.md)

If you download and redistribute those weights, keep the attribution and the
CC-BY-4.0 notice. The integration and export code in this repository is
original work under Apache-2.0; the Google weights remain under their own
license.
