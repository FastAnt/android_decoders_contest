#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Defaults
ABI="arm64-v8a"
BUILD_TYPE="Release"
ANDROID_PLATFORM="android-26"
GPU_DELEGATE="OFF"
NNAPI="OFF"
JOBS="$(nproc)"

# NDK discovery
if [ -z "${ANDROID_NDK_HOME:-}" ]; then
    # Try common locations
    if [ -d "$HOME/Android/Sdk/ndk" ]; then
        # Use the latest NDK available
        ANDROID_NDK_HOME="$(ls -d "$HOME/Android/Sdk/ndk"/*/ 2>/dev/null | sort -V | tail -1)"
        ANDROID_NDK_HOME="${ANDROID_NDK_HOME%/}"
    fi
fi

if [ -z "${ANDROID_NDK_HOME:-}" ] || [ ! -d "$ANDROID_NDK_HOME" ]; then
    echo "ERROR: ANDROID_NDK_HOME not set or not found."
    echo "Set it to your NDK path, e.g.:"
    echo "  export ANDROID_NDK_HOME=\$HOME/Android/Sdk/ndk/28.2.13676358"
    exit 1
fi

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --abi)      ABI="$2"; shift 2 ;;
        --type)     BUILD_TYPE="$2"; shift 2 ;;
        --gpu)      GPU_DELEGATE="ON"; shift ;;
        --nnapi)    NNAPI="ON"; shift ;;
        --ndk)      ANDROID_NDK_HOME="$2"; shift 2 ;;
        --jobs|-j)  JOBS="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo "  --abi <ABI>       Target ABI (default: arm64-v8a)"
            echo "  --type <TYPE>     Build type (default: Release)"
            echo "  --gpu             Enable GPU delegate"
            echo "  --nnapi           Enable NNAPI delegate"
            echo "  --ndk <path>      Android NDK path"
            echo "  --jobs|-j <N>     Parallel jobs (default: nproc)"
            exit 0 ;;
        *)
            echo "Unknown argument: $1"; exit 1 ;;
    esac
done

BUILD_DIR="$PROJECT_DIR/build-android-${ABI}"
TOOLCHAIN="$ANDROID_NDK_HOME/build/cmake/android.toolchain.cmake"

if [ ! -f "$TOOLCHAIN" ]; then
    echo "ERROR: Toolchain not found: $TOOLCHAIN"
    exit 1
fi

# Ensure host flatc is built (needed for cross-compilation)
HOST_BUILD_DIR="$PROJECT_DIR/build"
if [ ! -f "$HOST_BUILD_DIR/flatbuffers-flatc/bin/flatc" ]; then
    echo "Host flatc not found. Building host tools first..."
    mkdir -p "$HOST_BUILD_DIR"
    cmake -S "$PROJECT_DIR" -B "$HOST_BUILD_DIR" \
        -G Ninja \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_SHARED_LIB=OFF \
        -DBUILD_CLI=OFF \
        -DBUILD_TESTS=OFF
    cmake --build "$HOST_BUILD_DIR" --target flatbuffers-flatc -j"$JOBS" || {
        echo "ERROR: Failed to build host flatc. Run a full Linux build first:"
        echo "  mkdir -p build && cd build && cmake .. && cmake --build . -j\$(nproc)"
        exit 1
    }
fi

# KleidiAI (required by XNNPACK for ARM)
KLEIDIAI_DIR="$PROJECT_DIR/third_party/kleidiai"
if [ ! -f "$KLEIDIAI_DIR/CMakeLists.txt" ]; then
    echo "Downloading KleidiAI..."
    mkdir -p "$KLEIDIAI_DIR"
    KLEIDIAI_COMMIT="cddf991af5de49fd34949fa39690e4e906e04074"
    wget -q "https://gitlab.arm.com/kleidi/kleidiai/-/archive/${KLEIDIAI_COMMIT}/kleidiai-${KLEIDIAI_COMMIT}.zip" -O /tmp/kleidiai.zip
    unzip -q -o /tmp/kleidiai.zip -d /tmp/kleidiai_tmp
    cp -r /tmp/kleidiai_tmp/kleidiai-${KLEIDIAI_COMMIT}/* "$KLEIDIAI_DIR/"
    rm -rf /tmp/kleidiai_tmp /tmp/kleidiai.zip
fi

echo "=== SpectroStream Android Build ==="
echo "NDK:        $ANDROID_NDK_HOME"
echo "ABI:        $ABI"
echo "Platform:   $ANDROID_PLATFORM"
echo "Build type: $BUILD_TYPE"
echo "GPU:        $GPU_DELEGATE"
echo "NNAPI:      $NNAPI"
echo "Build dir:  $BUILD_DIR"
echo ""

cmake -S "$PROJECT_DIR" -B "$BUILD_DIR" \
    -G Ninja \
    -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
    -DCMAKE_TOOLCHAIN_FILE="$TOOLCHAIN" \
    -DANDROID_ABI="$ABI" \
    -DANDROID_PLATFORM="$ANDROID_PLATFORM" \
    -DANDROID_STL=c++_shared \
    -DBUILD_SHARED_LIB=ON \
    -DBUILD_CLI=ON \
    -DBUILD_TESTS=ON \
    -DENABLE_SANITIZERS=OFF \
    -DENABLE_GPU_DELEGATE="$GPU_DELEGATE" \
    -DENABLE_NNAPI="$NNAPI" \
    -DTFLITE_HOST_TOOLS_DIR="$HOST_BUILD_DIR" \
    -DKLEIDIAI_SOURCE_DIR="$KLEIDIAI_DIR"

echo ""
echo "Building..."
cmake --build "$BUILD_DIR" -j"$JOBS"

echo ""
echo "=== Build Complete ==="
echo "Executable: $BUILD_DIR/spectrostream_decode"
echo "Library:    $BUILD_DIR/libspectrostream_decoder.so"

# Strip binaries for deployment
STRIP="$ANDROID_NDK_HOME/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip"
if [ -x "$STRIP" ]; then
    echo "Stripping binaries..."
    for bin in spectrostream_decode libspectrostream_decoder.so test_c_api; do
        if [ -f "$BUILD_DIR/$bin" ]; then
            "$STRIP" "$BUILD_DIR/$bin"
        fi
    done
fi

# Show binary size
if [ -f "$BUILD_DIR/spectrostream_decode" ]; then
    SIZE=$(stat --printf="%s" "$BUILD_DIR/spectrostream_decode" 2>/dev/null || stat -f%z "$BUILD_DIR/spectrostream_decode" 2>/dev/null)
    echo "CLI size:   $(echo "scale=1; $SIZE/1048576" | bc) MiB"
fi
if [ -f "$BUILD_DIR/libspectrostream_decoder.so" ]; then
    SIZE=$(stat --printf="%s" "$BUILD_DIR/libspectrostream_decoder.so" 2>/dev/null || stat -f%z "$BUILD_DIR/libspectrostream_decoder.so" 2>/dev/null)
    echo "SO size:    $(echo "scale=1; $SIZE/1048576" | bc) MiB"
fi
