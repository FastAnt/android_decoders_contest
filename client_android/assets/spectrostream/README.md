# SpectroStream runtime assets

The `.tflite`, `.f32` and `.npy` model files are **not stored in this
repository**. They are intentionally ignored by Git to keep the public
repository small.

Export them from the original Magenta RealTime weights (see
[models/README.md](../../../models/README.md) and
[docs/model-export.md](../../../docs/model-export.md)), then copy the exported
files here:

- `spectrostream_decoder_core_fp32_f25.tflite`
- `spectrostream_decoder_core_fp32_f75.tflite`
- `spectrostream_decoder_core_fp16_f25.tflite`
- `spectrostream_decoder_core_fp16_f75.tflite`
- `spectrostream_decoder_core_fp16_f100.tflite`
- `rvq_codebooks.f32`
- `istft_window_f960.f32`

`demo.sst` is a small generated demo track included in this repository. It is
encoded with the 64-layer SpectroStream model from the same source audio as the
MP3, SAGE, and SAME-S demos.
