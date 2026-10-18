#!/usr/bin/env bash
set -euo pipefail

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

echo "=== Memory Profile ==="
echo "Model:   $MODEL"
echo "Threads: $THREADS"
echo ""

# Push a memory monitoring script to the device
adb shell "cat > $DEVICE_DIR/mem_monitor.sh" << 'DEVICE_SCRIPT'
#!/system/bin/sh
DEVICE_DIR="$1"
MODEL="$2"
THREADS="$3"

cd "$DEVICE_DIR"
export LD_LIBRARY_PATH=.

echo "=== Memory Profile ==="
echo "Model: $MODEL"
echo ""

# Get baseline memory
echo "--- System Memory ---"
cat /proc/meminfo | head -5
echo ""

# Start decode in background
./spectrostream_decode \
    --model "models/$MODEL" \
    --codebooks models/rvq_codebooks.f32 \
    --window models/istft_window_f960.f32 \
    --input test.sst \
    --output /dev/null \
    --threads "$THREADS" &
PID=$!

echo "Decoder PID: $PID"
echo ""

# Monitor memory in a loop
echo "--- Memory Timeline ---"
echo "time_s  VmRSS_kB  VmHWM_kB  VmSize_kB"
START=$(date +%s)
PEAK_RSS=0

while kill -0 $PID 2>/dev/null; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START))

    if [ -f "/proc/$PID/status" ]; then
        RSS=$(grep VmRSS /proc/$PID/status 2>/dev/null | awk '{print $2}')
        HWM=$(grep VmHWM /proc/$PID/status 2>/dev/null | awk '{print $2}')
        VSZ=$(grep VmSize /proc/$PID/status 2>/dev/null | awk '{print $2}')

        if [ -n "$RSS" ]; then
            echo "$ELAPSED  $RSS  $HWM  $VSZ"
            if [ "$RSS" -gt "$PEAK_RSS" ] 2>/dev/null; then
                PEAK_RSS=$RSS
            fi
        fi
    fi

    sleep 1
done

wait $PID 2>/dev/null
EXIT_CODE=$?

echo ""
echo "--- Summary ---"
echo "Exit code: $EXIT_CODE"
echo "Peak RSS observed: ${PEAK_RSS} kB ($(echo "$PEAK_RSS / 1024" | bc) MB)"
echo ""

# Final memory state
echo "--- System Memory After ---"
cat /proc/meminfo | head -5
DEVICE_SCRIPT

adb shell "chmod +x $DEVICE_DIR/mem_monitor.sh"
adb shell "$DEVICE_DIR/mem_monitor.sh '$DEVICE_DIR' '$MODEL' '$THREADS'"
