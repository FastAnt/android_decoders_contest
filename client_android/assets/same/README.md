# SAME-S runtime assets

`dec_w8a8_s128.tflite` is the SAME-S decoder used by the Android client.
It is a LiteRT/TFLite export of Stability AI's SAME-S model with int8 W8A8
weights and only the `s128` signature (rung 128), which is the decoder window
size used by the app.

- Original model: [`stabilityai/SAME-S`](https://huggingface.co/stabilityai/SAME-S),
  revision `63a63b7193ee9b6ee9836776c5f3c52a2f9600df`.
- Upstream code: [Stability-AI/stable-audio-3](https://github.com/Stability-AI/stable-audio-3).
- Source TFLite export: `dec_w8a8.tflite` (89,329,616 bytes,
  SHA-256 `90cad5ef81e6b18eb205012aee03bc53ed59e1c17033b79a84a4612674b1e03a`).
- App model: `dec_w8a8_s128.tflite` (81,517,872 bytes,
  SHA-256 `7802697d21c67968974c117626da42e55bf0dd250126e0be9a4cfe86245e0ef6`).
  It is the `s128` signature sliced out of the source export; on the same
  input window its output is bit-identical to the source export's `s128`
  signature (measured maxdiff 0.0).

`demo.same` is a small generated demo track encoded from
`assets/audio/demo.mp3` with the SAME-S encoder:

```bash
SAME_CODEC=/path/to/same_codec
REPO_ROOT=/path/to/spectrum_stream_codec
cd "$SAME_CODEC"
.venv/bin/python encoder/encode.py \
  --input "$REPO_ROOT/client_android/assets/audio/demo.mp3" \
  --output "$REPO_ROOT/client_android/assets/same/demo.same" \
  --precision int8-pc --entropy --backend tflite-w8a8 --threads 8
```

Container properties: SAME-S v1, 44,100 Hz stereo, 5,892,096 original samples
(133.607619 s), 1,440 stored / 1,439 valid latent frames, 12 chunks,
343,565 bytes (20.57 kbit/s), SHA-256
`5c325eae0147d2895448a4c24545a8c2a59727bb0897c1dd02db472d82ed839b`.

## License

The SAME-S model weights and this TFLite export are **not** covered by the
Apache-2.0 license of the code. They are distributed under the
**Stability AI Community License**:

- Local license text:
  [STABILITY-AI-COMMUNITY-LICENSE.txt](STABILITY-AI-COMMUNITY-LICENSE.txt)
- Upstream license:
  <https://huggingface.co/stabilityai/SAME-S/raw/main/LICENSE.md>

This Stability AI Model is licensed under the Stability AI Community License,
Copyright © Stability AI Ltd. All Rights Reserved.

**Powered by Stability AI.**

The TFLite export is a derivative work: the original checkpoint was converted
to LiteRT with int8 weights and the decoder graph was sliced to the `s128`
signature for this project. See [../../../WEIGHTS.md](../../../WEIGHTS.md)
for the repository-level attribution and scope.

This is a research/non-commercial test bed. Commercial use of the weights
requires registration with Stability AI under the Community License, and
above the license's revenue threshold a separate commercial license.
