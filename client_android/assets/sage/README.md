# SAGE runtime model

`demo.sage` is a small generated demo track included in this repository. The
SAGE decoder model `dec_w8a8.tflite` is **not stored here**.

The SAGE decoder is a LiteRT export of the `SAGE_FTe992` Swin-V2 decoder. The
original model and export tooling are available from the upstream SAGE
project:

- <https://github.com/francescobrigante/SAGE>
- Code license: MIT (Francesco Brigante)

Place the exported `dec_w8a8.tflite` (rung 128) in this directory before
building the Android app. The app's `SageBridge` expects it at
`assets/sage/dec_w8a8.tflite`; `AssetInstaller` copies it to app storage.

Check the license of the checkpoint/model weights before redistributing them.
