#!/bin/bash
# run_strategy.sh — 策略启动脚本 (Phase 5)
set -euo pipefail

STRATEGY=""
CONFIG=""
LOG_DIR="${LOGS_DIR:-./logs}"
PYTHON_CMD="${PYTHON_CMD:-python3}"
BACKGROUND=false
PID_FILE=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --strategy) STRATEGY="$2"; shift 2 ;;
        --config) CONFIG="$2"; shift 2 ;;
        --log-dir) LOG_DIR="$2"; shift 2 ;;
        --background) BACKGROUND=true; shift ;;
        --python) PYTHON_CMD="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: run_strategy.sh --strategy NAME --config PATH [--background]"
            echo "  --strategy NAME   Strategy name"
            echo "  --config PATH     Runtime config YAML"
            echo "  --background      Run in background (nohup)"
            echo "  --log-dir DIR     Log directory (default: ./logs)"
            echo "  --python CMD      Python command (default: python3)"
            exit 0 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

[ -z "$STRATEGY" ] && { echo "ERROR: --strategy required"; exit 1; }
[ -z "$CONFIG" ] && { echo "ERROR: --config required"; exit 1; }
[ ! -f "$CONFIG" ] && { echo "ERROR: config not found: $CONFIG"; exit 1; }

mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/${STRATEGY}-$(date +%Y%m%d).log"

echo "Strategy:  $STRATEGY"
echo "Config:    $CONFIG"
echo "Log:       $LOG_FILE"

# Build python command
CMD="$PYTHON_CMD -m backtest.run_strategy --strategy $STRATEGY --config $CONFIG --log-level INFO"

if [ "$BACKGROUND" = true ]; then
    nohup $CMD >> "$LOG_FILE" 2>&1 &
    PID=$!
    echo "PID:       $PID"
    echo ""
    echo "Strategy started in background."
    echo "  Monitor: tail -f $LOG_FILE"
    echo "  Stop:    kill $PID"
else
    echo "Starting in foreground (Ctrl+C to stop)..."
    exec $CMD 2>&1 | tee -a "$LOG_FILE"
fi
