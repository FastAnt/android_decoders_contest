# Compress a Track and Reconstruct the WAV

Scenario: file → FFmpeg → SpectroStream → SST → independent C++ decoder → WAV.
A reference WAV can also be produced in Python. The codec is lossy;
the output is PCM16, 48000 Hz, stereo. Byte equality with the original is not expected.

## 1. Choose a Track and Prepare the Process

First complete the [Python and source weight setup](setup.md).
All blocks below are run from the repository root in a single Bash session.
Replace only `INPUT` with your path; a small generated demo track is
included at `client_android/assets/audio/demo.mp3`.

```bash
source encoder_service/.venv/bin/activate
source encoder_service/env.sh
export CUDA_VISIBLE_DEVICES=-1
export OMP_NUM_THREADS=4
export TF_NUM_INTRAOP_THREADS=4
export TF_NUM_INTEROP_THREADS=2

INPUT="/absolute/path/to/track.mp3"
RUN_DIR="media/roundtrip-$(date +%Y%m%d-%H%M%S)"
test -f "$INPUT"
mkdir -p "$RUN_DIR"
```

Set `CUDA_VISIBLE_DEVICES=-1` after `source env.sh`.
The other three variables limit the number of CPU threads for this run.
For a check against the existing local demo track, you can set
`INPUT="$PWD/client_android/assets/audio/demo.mp3"`.

## 2. Encode and Produce the Python Reference WAV

```bash
python encoder_service/batch_encode.py \
  --input "$INPUT" \
  --output "$RUN_DIR/encoded" \
  --reconstructed "$RUN_DIR/python" \
  --device cpu \
  --verify-first 1 \
  --verify-depths 64
```

For a first short run, add `--max-seconds 3`; without this option
the entire track is encoded. Model loading and warm-up may take longer
than processing a short fragment.

The following are created:

```text
RUN_DIR/
├── encoded/
│   ├── catalog.json
│   └── TRACK_ID/
│       ├── TRACK_ID.sst
│       └── metadata.json
└── python/
    └── TRACK_ID/
        └── TRACK_ID.q64.wav
```

If the source filename ends with a 32-character hex ID, that ID is used;
otherwise the ID is computed from the absolute path. Moving the source file can change the ID.
Do not substitute the demo track's identifier into commands for your own audio.

`--verify-first 1` decodes the tokens of the first **newly encoded** track
in the current process; this step does not read SST from disk. Independent SST reading
is verified by the C++ step below. Without `--verify-first`, no Python WAV is created.

When re-running into the same output directory, an already processed file may
be skipped. To re-encode it and repeat verification, add `--force`.
Changing only `--verify-depths` or `--verify-first` does not cancel the skip.

## 3. Verify Success and Locate the SST

The encoder catches per-track errors and writes `error.json`;
**an exit code of 0 alone does not mean successful encoding**.
The final counters, metadata, and actual files must agree.
The following command expects one track in a new output directory:

```bash
SST_FILE="$(python - "$RUN_DIR/encoded/catalog.json" <<'PY'
import json
import sys
from pathlib import Path

catalog = json.loads(Path(sys.argv[1]).read_text())
assert catalog['track_count'] == 1, 'Expected one successfully encoded track'
track = catalog['tracks'][0]
assert track['status'] == 'success' and track['container_validated']
assert len(track['verifications']) == 1, 'No reference decoding'
sst = Path(track['container_path'])
assert sst.is_file() and sst.stat().st_size == track['container_bytes']
assert Path(track['verifications'][0]['file']).is_file()
assert not (sst.parent / 'error.json').exists(), 'An error from the last run exists'
print(sst)
PY
)"
test -f "$SST_FILE"
```

On error, do not proceed to decoding: check the `FAILED` output,
`Failed in this run`, and `encoded/TRACK_ID/error.json`. Old metadata/catalog
may remain from previous runs; a new `RUN_DIR` removes this ambiguity.

## 4. Independently Decode the SST in C++

This requires the built runtime from [setup](setup.md) and three matching files
from the [export instructions](model-export.md). For the prepared local
set, verify their checksums:

```bash
sha256sum -c docs/decoder-f25.sha256
decoder_cpp/build/spectrostream_decode --inspect --input "$SST_FILE"

decoder_cpp/build/spectrostream_decode \
  --model decoder_cpp/models/spectrostream_decoder_core_fp32_f25.tflite \
  --codebooks decoder_cpp/models/rvq_codebooks.f32 \
  --window decoder_cpp/models/istft_window_f960.f32 \
  --input "$SST_FILE" \
  --output "$RUN_DIR/cpp.wav" \
  --threads 4
```

`--inspect` does not require models and checks the header, token range, and CRC;
`CRC status: OK` is expected. Full decoding requires the weights and exit
code 0. The SHA256 above refers to the distributed source set: verify your own
re-export against the report it produced; the bytes may differ.

## 5. Verify the WAV

```bash
python - "$RUN_DIR/encoded/catalog.json" "$RUN_DIR/cpp.wav" <<'PY'
import json
import sys
import wave
from pathlib import Path

track = json.loads(Path(sys.argv[1]).read_text())['tracks'][0]
for name in [track['verifications'][0]['file'], sys.argv[2]]:
    with wave.open(name) as wav:
        assert wav.getframerate() == 48000
        assert wav.getnchannels() == 2
        assert wav.getsampwidth() == 2
        assert wav.getnframes() == track['original_samples']
        print(name, wav.getnframes() / wav.getframerate(), 'seconds, PCM16 stereo')
PY
```

The check confirms format and length, but does not measure audio quality.
Python and C++ use different block decoding schemes, so
bit-for-bit equality between their WAVs is also not required.
For a visual check of the header, you can use `ffprobe`:

```bash
ffprobe -v error -show_entries stream=codec_name,sample_rate,channels \
  -show_entries format=duration,size -of json "$RUN_DIR/cpp.wav"
```

The SST file contains full q64: nominally 16 kbit/s plus headers.
`stream_variants.q16/q32` in metadata are estimates of transmission sizes at 4/8 kbit/s;
`--verify-depths 16,32,64` creates WAV variants, not three different SSTs.
With `--max-seconds`, do not compare the size of a short SST with the size of the whole MP3
as a compression ratio for the same fragment.

## Reproducing and Sharing the Result

Keep the commands, metadata/catalog, CLI log, tool versions, and checksums
of the model/codebooks/window. Metadata contains absolute paths; after
moving the data, check that they are still valid. Media are transferred separately
from Git; source and runtime weights are not included and must be downloaded
or exported as described above.
The current [run results](validation.md) show the completed checks.
