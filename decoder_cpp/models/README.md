# Exported runtime assets

Binary model files are **not stored in this repository**. Export them from the
original weights as described in [docs/model-export.md](../../docs/model-export.md):

- `spectrostream_decoder_core_fp32_f25.tflite`
- `spectrostream_decoder_core_fp32_f75.tflite`
- `spectrostream_decoder_core_fp16_f25.tflite`
- `spectrostream_decoder_core_fp16_f75.tflite`
- `spectrostream_decoder_core_fp16_f100.tflite`
- `rvq_codebooks.f32`
- `istft_window_f960.f32`

The expected checksums for the original release are in
[docs/runtime-assets.sha256](../../docs/runtime-assets.sha256).

For the Android app, copy these files into
`client_android/assets/spectrostream/` before building. The Flutter client
copies them into its private application directory at runtime.
