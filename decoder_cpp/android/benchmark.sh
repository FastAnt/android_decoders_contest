#!/usr/bin/env bash
set -euo pipefail

DEVICE_DIR="/data/local/tmp/spectrostream"
RUNS=3
OUTPUT_DIR="benchmark_results"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --device-dir) DEVICE_DIR="$2"; shift 2 ;;
        --runs)       RUNS="$2"; shift 2 ;;
        --output)     OUTPUT_DIR="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo "  --device-dir <path>  Device directory (default: /data/local/tmp/spectrostream)"
            echo "  --runs <N>           Benchmark runs per config (default: 3)"
            echo "  --output <dir>       Local output directory for results"
            exit 0 ;;
        *)
            echo "Unknown argument: $1"; exit 1 ;;
    esac
done

mkdir -p "$OUTPUT_DIR"

DEVICE_NAME=$(adb shell getprop ro.product.model 2>/dev/null | tr -d '\r')
SOC=$(adb shell getprop ro.hardware.chipname 2>/dev/null | tr -d '\r')
ANDROID_VER=$(adb shell getprop ro.build.version.release 2>/dev/null | tr -d '\r')
CPU_INFO=$(adb shell cat /proc/cpuinfo 2>/dev/null | grep -c "^processor" || echo "?")

echo "=== SpectroStream Android Benchmark ==="
echo "Device:   $DEVICE_NAME"
echo "SoC:      $SOC"
echo "Android:  $ANDROID_VER"
echo "CPU cores: $CPU_INFO"
echo "Runs/cfg: $RUNS"
echo ""

# Function to get device temperature
get_temp() {
    # Try common thermal zone paths
    local temp
    temp=$(adb shell "cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null" | tr -d '\r')
    if [ -n "$temp" ] && [ "$temp" -gt 0 ] 2>/dev/null; then
        echo "scale=1; $temp/1000" | bc
    else
        echo "N/A"
    fi
}

# Function to get peak RSS after a run
get_peak_rss() {
    # Run with /usr/bin/time equivalent on Android: use /proc/self/status
    # We'll parse the output which includes timing info
    echo "N/A"
}

# Run a single configuration
run_config() {
    local model="$1"
    local threads="$2"
    local label="$3"
    local gpu_flag="${4:-}"

    echo "--- Config: $label (threads=$threads) ---"

    local temp_before
    temp_before=$(get_temp)

    local cmd="cd $DEVICE_DIR && LD_LIBRARY_PATH=. ./spectrostream_decode"
    cmd+=" --model models/$model"
    cmd+=" --codebooks models/rvq_codebooks.f32"
    cmd+=" --window models/istft_window_f960.f32"
    cmd+=" --input test.sst"
    cmd+=" --output output_${label}_t${threads}.wav"
    cmd+=" --threads $threads"
    cmd+=" --benchmark $RUNS"
    if [ -n "$gpu_flag" ]; then
        cmd+=" --gpu"
    fi

    local result_file="$OUTPUT_DIR/${label}_t${threads}.txt"
    echo "Command: $cmd" > "$result_file"
    echo "Temp before: ${temp_before}°C" >> "$result_file"
    echo "" >> "$result_file"

    # Run and capture output
    adb shell "$cmd" 2>&1 | tee -a "$result_file"

    local temp_after
    temp_after=$(get_temp)
    echo "" >> "$result_file"
    echo "Temp after: ${temp_after}°C" >> "$result_file"

    # Get memory info
    echo "" >> "$result_file"
    echo "=== Memory (last run) ===" >> "$result_file"
    # Run one more time and check /proc/self/status
    adb shell "cd $DEVICE_DIR && LD_LIBRARY_PATH=. ./spectrostream_decode \
        --model models/$model \
        --codebooks models/rvq_codebooks.f32 \
        --window models/istft_window_f960.f32 \
        --input test.sst \
        --output /dev/null \
        --threads $threads $gpu_flag &
        PID=\$!; sleep 5; cat /proc/\$PID/status 2>/dev/null | grep -E 'VmPeak|VmRSS|VmHWM'; wait \$PID 2>/dev/null" \
        >> "$result_file" 2>&1 || true

    echo "  Temp: ${temp_before}°C → ${temp_after}°C"
    echo ""
}

# Check available models
HAS_F75=$(adb shell "test -f $DEVICE_DIR/models/spectrostream_decoder_core_fp32_f75.tflite && echo yes" | tr -d '\r')
HAS_F25=$(adb shell "test -f $DEVICE_DIR/models/spectrostream_decoder_core_fp32_f25.tflite && echo yes" | tr -d '\r')
HAS_F16_F25=$(adb shell "test -f $DEVICE_DIR/models/spectrostream_decoder_core_fp16_f25.tflite && echo yes" | tr -d '\r')

echo "Available models:"
echo "  FP32 f75: ${HAS_F75:-no}"
echo "  FP32 f25: ${HAS_F25:-no}"
echo "  FP16 f25: ${HAS_F16_F25:-no}"
echo ""

# Thread configurations to test
THREAD_COUNTS=(1 2 4 6)

# FP32 f75 benchmark
if [ "${HAS_F75:-}" = "yes" ]; then
    echo "=========================================="
    echo "  FP32 f75 (context-aware) Benchmark"
    echo "=========================================="
    for t in "${THREAD_COUNTS[@]}"; do
        run_config "spectrostream_decoder_core_fp32_f75.tflite" "$t" "fp32_f75"
    done
fi

# FP32 f25 benchmark
if [ "${HAS_F25:-}" = "yes" ]; then
    echo "=========================================="
    echo "  FP32 f25 (no context) Benchmark"
    echo "=========================================="
    for t in "${THREAD_COUNTS[@]}"; do
        run_config "spectrostream_decoder_core_fp32_f25.tflite" "$t" "fp32_f25"
    done
fi

# FP16 f25 benchmark
if [ "${HAS_F16_F25:-}" = "yes" ]; then
    echo "=========================================="
    echo "  FP16 f25 (no context) Benchmark"
    echo "=========================================="
    for t in "${THREAD_COUNTS[@]}"; do
        run_config "spectrostream_decoder_core_fp16_f25.tflite" "$t" "fp16_f25"
    done
fi

echo ""
echo "=== Benchmark Complete ==="
echo "Results saved to: $OUTPUT_DIR/"
ls -la "$OUTPUT_DIR/"
