#!/usr/bin/env bash
set -euo pipefail

DEVICE_DIR="/data/local/tmp/spectrostream"
DURATION_MIN=5
MODEL="spectrostream_decoder_core_fp32_f75.tflite"
THREADS=4

while [[ $# -gt 0 ]]; do
    case "$1" in
        --device-dir) DEVICE_DIR="$2"; shift 2 ;;
        --duration)   DURATION_MIN="$2"; shift 2 ;;
        --model)      MODEL="$2"; shift 2 ;;
        --threads)    THREADS="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [options]"
            echo "  --duration <min>  Test duration in minutes (default: 5)"
            echo "  --model <file>    Model filename (default: fp32_f75)"
            echo "  --threads <N>     Thread count (default: 4)"
            exit 0 ;;
        *)
            echo "Unknown argument: $1"; exit 1 ;;
    esac
done

echo "=== Thermal Sustained Benchmark ==="
echo "Duration: ${DURATION_MIN} minutes"
echo "Model:    $MODEL"
echo "Threads:  $THREADS"
echo ""

# Push a loop script to the device
adb shell "cat > $DEVICE_DIR/thermal_loop.sh" << 'DEVICE_SCRIPT'
#!/system/bin/sh
DEVICE_DIR="$1"
MODEL="$2"
THREADS="$3"
DURATION_SEC="$4"

cd "$DEVICE_DIR"
export LD_LIBRARY_PATH=.

START=$(date +%s)
RUN=0

echo "=== Thermal Test Start ==="
echo "Target duration: ${DURATION_SEC}s"

# Get initial temperature
TEMP=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0)
echo "Initial temp: $(echo "$TEMP / 1000" | bc 2>/dev/null || echo $TEMP) mC"

# Get CPU frequencies
echo "CPU freq (kHz):"
for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq; do
    [ -f "$f" ] && echo "  $(basename $(dirname $(dirname $f))): $(cat $f)"
done 2>/dev/null || true

echo ""

while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START))
    if [ "$ELAPSED" -ge "$DURATION_SEC" ]; then
        break
    fi

    RUN=$((RUN + 1))

    # Decode
    OUTPUT=$(./spectrostream_decode \
        --model "models/$MODEL" \
        --codebooks models/rvq_codebooks.f32 \
        --window models/istft_window_f960.f32 \
        --input test.sst \
        --output /dev/null \
        --threads "$THREADS" 2>&1)

    RTF=$(echo "$OUTPUT" | grep "RTF:" | awk '{print $2}')
    INFER=$(echo "$OUTPUT" | grep "LiteRT infer:" | awk '{print $2}')
    TEMP=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0)
    TEMP_C=$(echo "$TEMP / 1000" | bc 2>/dev/null || echo "$TEMP")

    # Check throttling
    THROTTLE="no"
    for tz in /sys/class/thermal/thermal_zone*/trip_point_*_temp; do
        [ -f "$tz" ] && break
    done

    echo "Run $RUN: RTF=$RTF infer=${INFER}ms temp=${TEMP_C}C elapsed=${ELAPSED}s"
done

echo ""
echo "=== Thermal Test Complete ==="
echo "Total runs: $RUN"
echo "Elapsed: ${ELAPSED}s"

# Final temperature
TEMP=$(cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null || echo 0)
echo "Final temp: $(echo "$TEMP / 1000" | bc 2>/dev/null || echo $TEMP) mC"

# Final CPU frequencies
echo "Final CPU freq (kHz):"
for f in /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq; do
    [ -f "$f" ] && echo "  $(basename $(dirname $(dirname $f))): $(cat $f)"
done 2>/dev/null || true
DEVICE_SCRIPT

DURATION_SEC=$((DURATION_MIN * 60))

adb shell "chmod +x $DEVICE_DIR/thermal_loop.sh"
echo "Running on device for ${DURATION_MIN} minutes..."
echo ""
adb shell "$DEVICE_DIR/thermal_loop.sh '$DEVICE_DIR' '$MODEL' '$THREADS' '$DURATION_SEC'" | tee "thermal_${MODEL%.tflite}_t${THREADS}.txt"
