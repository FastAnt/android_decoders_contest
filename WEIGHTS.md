# Model weights and licenses

This repository contains **code** and **one model weight file** with different
licenses. The root [LICENSE](LICENSE) (Apache-2.0) covers the original code and
documentation only. It does **not** cover the SAGE model weights.

## Included: SAGE rung-128 decoder

| Field | Value |
|---|---|
| File | `client_android/assets/sage/dec_w8a8.tflite` |
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

## Not included: SpectroStream weights

The Google Magenta RealTime / SpectroStream model weights are **not stored in
this repository**. They are published by Google under **CC-BY-4.0**:

- <https://huggingface.co/google/magenta-realtime>
- Export instructions: [docs/model-export.md](docs/model-export.md)

If you download and redistribute those weights, keep the attribution and the
CC-BY-4.0 notice. The integration and export code in this repository is
original work under Apache-2.0; the Google weights remain under their own
license.
