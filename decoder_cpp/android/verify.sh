#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DEVICE_DIR="/data/local/tmp/spectrostream"

echo "=== Android Output Verification ==="
echo ""

# Pull the output WAV from device
echo "Pulling WAV from device..."
adb pull "$DEVICE_DIR/output_fp32_f75_t4.wav" /tmp/android_output.wav 2>/dev/null || \
    adb pull "$DEVICE_DIR/output.wav" /tmp/android_output.wav 2>/dev/null || {
    echo "No output WAV found on device. Run benchmark first."
    echo "Trying manual decode..."
    adb shell "cd $DEVICE_DIR && LD_LIBRARY_PATH=. ./spectrostream_decode \
        --model models/spectrostream_decoder_core_fp32_f75.tflite \
        --codebooks models/rvq_codebooks.f32 \
        --window models/istft_window_f960.f32 \
        --input test.sst \
        --output output.wav \
        --threads 4"
    adb pull "$DEVICE_DIR/output.wav" /tmp/android_output.wav
}

LINUX_REF="$PROJECT_DIR/../media/reconstructed/cpp/reconstructed_cpp_ctx.wav"
ANDROID_WAV="/tmp/android_output.wav"

if [ ! -f "$LINUX_REF" ]; then
    echo "WARNING: Linux reference not found at $LINUX_REF"
    echo "Run Linux decode first to produce reference."
    echo ""
    echo "Android WAV info:"
    if command -v soxi &>/dev/null; then
        soxi "$ANDROID_WAV"
    elif command -v ffprobe &>/dev/null; then
        ffprobe -hide_banner "$ANDROID_WAV" 2>&1 | head -20
    else
        file "$ANDROID_WAV"
        ls -la "$ANDROID_WAV"
    fi
    exit 0
fi

echo ""
echo "Comparing Android output vs Linux reference..."
echo "  Android: $ANDROID_WAV"
echo "  Linux:   $LINUX_REF"
echo ""

# Use Python for comparison if available
python3 - "$ANDROID_WAV" "$LINUX_REF" << 'PYTHON_SCRIPT'
import sys
import struct
import numpy as np

def read_wav_pcm16(path):
    with open(path, 'rb') as f:
        riff = f.read(4)
        assert riff == b'RIFF', f"Not a WAV file: {path}"
        f.read(4)  # file size
        wave = f.read(4)
        assert wave == b'WAVE'

        fmt_data = None
        data_bytes = None

        while True:
            chunk_id = f.read(4)
            if len(chunk_id) < 4:
                break
            chunk_size = struct.unpack('<I', f.read(4))[0]
            if chunk_id == b'fmt ':
                fmt_data = f.read(chunk_size)
            elif chunk_id == b'data':
                data_bytes = f.read(chunk_size)
                break
            else:
                f.read(chunk_size)

        assert fmt_data is not None and data_bytes is not None

        audio_format, channels, sr = struct.unpack('<HHI', fmt_data[:8])
        samples = np.frombuffer(data_bytes, dtype=np.int16).astype(np.float32) / 32767.0
        return samples, sr, channels

android_wav = sys.argv[1]
linux_wav = sys.argv[2]

a_pcm, a_sr, a_ch = read_wav_pcm16(android_wav)
l_pcm, l_sr, l_ch = read_wav_pcm16(linux_wav)

print(f"Android: {len(a_pcm)} samples, {a_sr} Hz, {a_ch} ch, {len(a_pcm)//a_ch} frames")
print(f"Linux:   {len(l_pcm)} samples, {l_sr} Hz, {l_ch} ch, {len(l_pcm)//l_ch} frames")
print()

if len(a_pcm) != len(l_pcm):
    print(f"WARNING: Sample count mismatch! Android={len(a_pcm)}, Linux={len(l_pcm)}")
    min_len = min(len(a_pcm), len(l_pcm))
    a_pcm = a_pcm[:min_len]
    l_pcm = l_pcm[:min_len]
else:
    print("Sample count: EXACT MATCH")

diff = a_pcm - l_pcm
max_abs_err = np.max(np.abs(diff))
rmse = np.sqrt(np.mean(diff**2))

# SNR
signal_power = np.mean(l_pcm**2)
noise_power = np.mean(diff**2)
if noise_power > 0:
    snr_db = 10 * np.log10(signal_power / noise_power)
else:
    snr_db = float('inf')

print(f"Max abs error:  {max_abs_err:.6f}")
print(f"RMSE:           {rmse:.8f}")
print(f"SNR:            {snr_db:.1f} dB")
print()

# Check for NaN/Inf
nan_count = np.sum(np.isnan(a_pcm))
inf_count = np.sum(np.isinf(a_pcm))
if nan_count > 0 or inf_count > 0:
    print(f"ERROR: Android output has {nan_count} NaN, {inf_count} Inf values!")
else:
    print("No NaN/Inf: OK")

# Check for boundary clicks (large jumps)
a_stereo = a_pcm.reshape(-1, a_ch)
for ch in range(a_ch):
    channel = a_stereo[:, ch]
    jumps = np.abs(np.diff(channel))
    max_jump = np.max(jumps)
    p99_jump = np.percentile(jumps, 99.9)
    if max_jump > 10 * p99_jump and max_jump > 0.1:
        idx = np.argmax(jumps)
        print(f"WARNING: Potential click in ch{ch} at sample {idx}: jump={max_jump:.4f}")
    else:
        print(f"Ch{ch} boundary check: OK (max_jump={max_jump:.5f})")

print()
if snr_db > 80:
    print("VERDICT: EXCELLENT - Android output matches Linux reference (SNR > 80 dB)")
elif snr_db > 56:
    print("VERDICT: GOOD - Minor numerical differences (expected for cross-platform)")
elif snr_db > 30:
    print("VERDICT: ACCEPTABLE - Noticeable differences, likely FP16 or GPU path")
else:
    print("VERDICT: CONCERNING - Large differences, investigate pipeline")
PYTHON_SCRIPT
