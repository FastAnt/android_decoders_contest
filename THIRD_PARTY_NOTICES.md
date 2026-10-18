# Third-party notices

This repository contains original integration code, documentation and a small
generated demo track. It does **not** redistribute model weights or exported
TFLite assets. The following upstream projects and licenses apply.

| Component | Use | License / terms |
|---|---|---|
| [Google Magenta RealTime](https://huggingface.co/google/magenta-realtime) | SpectroStream source models | Code Apache-2.0; model weights CC-BY-4.0 |
| [TensorFlow Lite](https://github.com/tensorflow/tensorflow) | C++ inference runtime | Apache-2.0 |
| [PocketFFT](https://github.com/mreineck/pocketfft) | iSTFT FFT | BSD-3-Clause |
| [XNNPACK](https://github.com/google/XNNPACK) | CPU kernels | BSD-3-Clause |
| [KleidiAI](https://gitlab.arm.com/kleidi/kleidiai) | Arm microkernels | Apache-2.0 |
| [SAGE](https://github.com/francescobrigante/SAGE) | SAGE model architecture and codec code | MIT |
| [Stable Audio 3](https://github.com/Stability-AI/stable-audio-3) | Upstream audio model code | MIT |
| [Flutter](https://flutter.dev) and Dart packages | Android client | Respective package licenses |

Notes:

- The SpectroStream model weights are published by Google under CC-BY-4.0.
  If you download and redistribute them, keep the attribution and license
  notice. The export scripts in this repository are original integration code.
- The SAGE checkpoint/model weights are **not** included here. Check the
  license of the checkpoint before redistributing an exported TFLite model.
- The demo MP3/SST/SAGE files are generated from the same source track and are
  included for demonstration. Replace them with content you have the rights to
  publish if you fork this repository.
- Flutter/Dart dependencies carry their own licenses; see `pubspec.lock` and
  the generated `NOTICES` bundle in a built app.
