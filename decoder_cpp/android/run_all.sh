#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DEVICE_DIR="/data/local/tmp/spectrostream"

echo "=============================================="
echo "  SpectroStream Android Full Pipeline"
echo "=============================================="
echo ""

# Step 1: Build
echo "[1/5] Building for arm64-v8a..."
"$SCRIPT_DIR/build.sh" "$@"
echo ""

# Step 2: Deploy
echo "[2/5] Deploying to device..."
"$SCRIPT_DIR/deploy.sh"
echo ""

# Step 3: C ABI smoke test (use f25 for speed)
echo "[3/5] Running C ABI smoke test..."
adb shell "cd $DEVICE_DIR && LD_LIBRARY_PATH=. ./test_c_api \
    models/spectrostream_decoder_core_fp32_f25.tflite \
    models/rvq_codebooks.f32 \
    models/istft_window_f960.f32 \
    test.sst" || echo "WARNING: C API test failed or not available"
echo ""

# Step 4: Quick decode (f25 for fast correctness check)
echo "[4/5] Quick decode (f25, 4 threads)..."
adb shell "cd $DEVICE_DIR && LD_LIBRARY_PATH=. ./spectrostream_decode \
    --model models/spectrostream_decoder_core_fp32_f25.tflite \
    --codebooks models/rvq_codebooks.f32 \
    --window models/istft_window_f960.f32 \
    --input test.sst \
    --output output.wav \
    --threads 4"
echo ""

# Step 5: Benchmark
echo "[5/5] Running benchmark..."
"$SCRIPT_DIR/benchmark.sh" --runs 2
echo ""

echo "=============================================="
echo "  Pipeline Complete"
echo "=============================================="
echo ""
echo "Pull output: adb pull $DEVICE_DIR/output.wav"
echo "Verify:      $SCRIPT_DIR/verify.sh"
