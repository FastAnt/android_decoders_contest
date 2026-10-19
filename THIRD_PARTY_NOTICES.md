# Third-party notices

This repository contains original integration code, documentation, a small
generated demo track, and one **SAGE decoder weight file**. It does **not**
redistribute SpectroStream weights or exported SpectroStream TFLite models.
The following upstream projects and licenses apply.

| Component | Use | License / terms |
|---|---|---|
| [Google Magenta RealTime](https://huggingface.co/google/magenta-realtime) | SpectroStream source models (not included) | Code Apache-2.0; model weights CC-BY-4.0 |
| [TensorFlow Lite](https://github.com/tensorflow/tensorflow) | C++ inference runtime | Apache-2.0 |
| [PocketFFT](https://github.com/mreineck/pocketfft) | iSTFT FFT | BSD-3-Clause |
| [XNNPACK](https://github.com/google/XNNPACK) | CPU kernels | BSD-3-Clause |
| [KleidiAI](https://gitlab.arm.com/kleidi/kleidiai) | Arm microkernels | Apache-2.0 |
| [SAGE](https://github.com/francescobrigante/SAGE) | SAGE model architecture and codec code | MIT |
| [SAGE_FTe992 weights](https://huggingface.co/francescobrigante/SAGE) | Included TFLite decoder `dec_w8a8.tflite` | **CC BY-NC-SA 4.0** |
| [Stable Audio 3](https://github.com/Stability-AI/stable-audio-3) | Upstream audio model code | MIT |
| [Flutter](https://flutter.dev) and Dart packages | Android client | Respective package licenses |

Notes:

- The included SAGE weights are an adaptation of `SAGE_FTe992`: exported to
  LiteRT int8, fixed rung 128, with a sliced post-net. They are **not** covered
  by Apache-2.0. See [WEIGHTS.md](WEIGHTS.md) for attribution, modifications,
  checksum, and the exact scope.
- CC BY-NC-SA 4.0 is **non-commercial** and **share-alike**. Commercial use of
  the SAGE weights requires separate permission from the original rights
  holder; adaptations must remain under the same license.
- The SpectroStream model weights are published by Google under CC-BY-4.0.
  They are not included in this repository. If you download and redistribute
  them, keep the attribution and license notice. The export scripts in this
  repository are original integration code.
- The demo MP3/SST/SAGE files are generated from the same source track and are
  included for demonstration. Replace them with content you have the rights to
  publish if you fork this repository.
- Flutter/Dart dependencies carry their own licenses; see `pubspec.lock` and
  the generated `NOTICES` bundle in a built app.
