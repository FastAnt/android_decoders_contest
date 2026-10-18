#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

ABI="arm64-v8a"
DEVICE_DIR="/data/local/tmp/spectrostream"
BUILD_DIR="$PROJECT_DIR/build-android-${ABI}"

# Models and test data
MODEL_DIR="$PROJECT_DIR/models"
SST_FILE="$PROJECT_DIR/../media/data/encoded/069569e7525fdd1e462b9f5b1a394a9f/069569e7525fdd1e462b9f5b1a394a9f.sst"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --abi)       ABI="$2"; BUILD_DIR="$PROJECT_DIR/build-android-${ABI}"; shift 2 ;;
        --device-dir) DEVICE_DIR="$2"; shift 2 ;;
        --sst)       SST_FILE="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo "  --abi <ABI>         Target ABI (default: arm64-v8a)"
            echo "  --device-dir <path> Device directory (default: /data/local/tmp/spectrostream)"
            echo "  --sst <path>        Local SST file to push"
            exit 0 ;;
        *)
            echo "Unknown argument: $1"; exit 1 ;;
    esac
done

echo "=== Deploy to Android Device ==="
echo "Device dir: $DEVICE_DIR"
echo ""

# Check adb
if ! command -v adb &>/dev/null; then
    echo "ERROR: adb not found in PATH"
    exit 1
fi

# Check device
if ! adb get-state &>/dev/null; then
    echo "ERROR: No Android device connected"
    exit 1
fi

DEVICE_NAME=$(adb shell getprop ro.product.model 2>/dev/null | tr -d '\r')
ANDROID_VER=$(adb shell getprop ro.build.version.release 2>/dev/null | tr -d '\r')
echo "Device: $DEVICE_NAME (Android $ANDROID_VER)"
echo ""

# Create device directory
adb shell "mkdir -p $DEVICE_DIR/models"

# Push executable
echo "Pushing executable..."
adb push "$BUILD_DIR/spectrostream_decode" "$DEVICE_DIR/"
adb shell "chmod +x $DEVICE_DIR/spectrostream_decode"

# Push shared library
if [ -f "$BUILD_DIR/libspectrostream_decoder.so" ]; then
    adb push "$BUILD_DIR/libspectrostream_decoder.so" "$DEVICE_DIR/"
fi

# Push libc++_shared.so (needed for c++_shared STL)
if [ -z "${ANDROID_NDK_HOME:-}" ]; then
    if [ -d "$HOME/Android/Sdk/ndk" ]; then
        ANDROID_NDK_HOME="$(ls -d "$HOME/Android/Sdk/ndk"/*/ 2>/dev/null | sort -V | tail -1)"
        ANDROID_NDK_HOME="${ANDROID_NDK_HOME%/}"
    fi
fi
LIBCXX="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/lib/aarch64-linux-android/libc++_shared.so"
if [ -f "$LIBCXX" ]; then
    echo "Pushing libc++_shared.so..."
    adb push "$LIBCXX" "$DEVICE_DIR/"
fi

# Push models
echo "Pushing models..."
for model_file in \
    "spectrostream_decoder_core_fp32_f75.tflite" \
    "spectrostream_decoder_core_fp32_f25.tflite" \
    "spectrostream_decoder_core_fp16_f25.tflite" \
    "rvq_codebooks.f32" \
    "istft_window_f960.f32"; do
    if [ -f "$MODEL_DIR/$model_file" ]; then
        echo "  $model_file"
        adb push "$MODEL_DIR/$model_file" "$DEVICE_DIR/models/"
    fi
done

# Push test SST
if [ -f "$SST_FILE" ]; then
    echo "Pushing test SST..."
    adb push "$SST_FILE" "$DEVICE_DIR/test.sst"
fi

# Push test executables
if [ -f "$BUILD_DIR/test_c_api" ]; then
    echo "Pushing test_c_api..."
    adb push "$BUILD_DIR/test_c_api" "$DEVICE_DIR/"
    adb shell "chmod +x $DEVICE_DIR/test_c_api"
fi

echo ""
echo "=== Deploy Complete ==="
echo ""
echo "Run decode on device:"
echo "  adb shell \"cd $DEVICE_DIR && LD_LIBRARY_PATH=. ./spectrostream_decode \\"
echo "    --model models/spectrostream_decoder_core_fp32_f75.tflite \\"
echo "    --codebooks models/rvq_codebooks.f32 \\"
echo "    --window models/istft_window_f960.f32 \\"
echo "    --input test.sst \\"
echo "    --output output.wav \\"
echo "    --threads 4\""
echo ""
echo "Run C ABI smoke test:"
echo "  adb shell \"cd $DEVICE_DIR && LD_LIBRARY_PATH=. ./test_c_api \\"
echo "    models/spectrostream_decoder_core_fp32_f25.tflite \\"
echo "    models/rvq_codebooks.f32 \\"
echo "    models/istft_window_f960.f32 \\"
echo "    test.sst\""
