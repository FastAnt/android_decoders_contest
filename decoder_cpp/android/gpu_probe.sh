#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DEVICE_DIR="/data/local/tmp/spectrostream"
MODEL="spectrostream_decoder_core_fp32_f75.tflite"
THREADS=4

while [[ $# -gt 0 ]]; do
    case "$1" in
        --model)   MODEL="$2"; shift 2 ;;
        --threads) THREADS="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--model <file>] [--threads <N>]"
            exit 0 ;;
        *)
            echo "Unknown argument: $1"; exit 1 ;;
    esac
done

echo "=== GPU Delegate Probe ==="
echo "Model:   $MODEL"
echo "Threads: $THREADS"
echo ""

# Check if GPU build exists
if ! adb shell "test -f $DEVICE_DIR/spectrostream_decode" 2>/dev/null; then
    echo "ERROR: spectrostream_decode not deployed. Run deploy.sh first."
    exit 1
fi

# Check GPU info on device
echo "--- Device GPU Info ---"
adb shell "dumpsys SurfaceFlinger 2>/dev/null | grep -i 'GLES' | head -5" || true
adb shell "getprop ro.hardware.egl 2>/dev/null" | tr -d '\r'
adb shell "ls /vendor/lib64/egl/ 2>/dev/null" || true
echo ""

# CPU baseline
echo "--- CPU Baseline (XNNPACK) ---"
adb shell "cd $DEVICE_DIR && LD_LIBRARY_PATH=. ./spectrostream_decode \
    --model models/$MODEL \
    --codebooks models/rvq_codebooks.f32 \
    --window models/istft_window_f960.f32 \
    --input test.sst \
    --output /dev/null \
    --threads $THREADS 2>&1" | grep -E "RTF:|LiteRT infer:|Model \+ assets"
echo ""

# GPU attempt
echo "--- GPU Delegate ---"
GPU_OUTPUT=$(adb shell "cd $DEVICE_DIR && LD_LIBRARY_PATH=. ./spectrostream_decode \
    --model models/$MODEL \
    --codebooks models/rvq_codebooks.f32 \
    --window models/istft_window_f960.f32 \
    --input test.sst \
    --output /dev/null \
    --threads $THREADS \
    --gpu 2>&1" || true)

echo "$GPU_OUTPUT"
echo ""

if echo "$GPU_OUTPUT" | grep -q "RTF:"; then
    GPU_RTF=$(echo "$GPU_OUTPUT" | grep "RTF:" | awk '{print $2}')
    echo "GPU decode succeeded! RTF=$GPU_RTF"
else
    echo "GPU delegate FAILED or not compiled in."
    echo ""
    echo "To build with GPU support:"
    echo "  ./android/build.sh --gpu"
    echo ""
    echo "Common reasons for GPU delegate failure:"
    echo "  - Build not compiled with ENABLE_GPU_DELEGATE=ON"
    echo "  - Model has operations unsupported by GPU delegate"
    echo "  - GPU driver too old or incompatible"
fi
