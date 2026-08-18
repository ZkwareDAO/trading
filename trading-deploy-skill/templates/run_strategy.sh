#!/bin/bash
# run_strategy.sh — 单策略单标的启动（调试用途）
#
# ⚠ 正式部署不走这里。deploy.sh 的 Phase 5 转调模板自带的
#   scripts/run_live_batch.sh —— 那条路径共用 cta_strategy_core.pid，
#   能被模板 stop.sh 正常停掉。
#
#   本脚本用 --background 起的进程【不在 stop.sh 管辖范围内】，
#   忘记手动 kill 就会变成继续下单的孤儿进程。因此仅建议：
#     - 前台运行（不加 --background），观察单个标的的日志
#     - 排查某个 symbol 单独启动是否报错
#   实盘请用: cd <项目> && bash scripts/run_live_batch.sh --strategies N --symbols S --daemon
#
# 对接模板 v3.7 的实盘入口:
#   单策略单标的: python run_strategy.py --name NAME --symbol SYMBOL
#   全量编排:     ./start.sh（读 config/strategies.yaml，由 run_strategies_manager 拉起）
#
# 策略参数唯一来源: strategies/<name>/overrides/<SYMBOL>.yaml
# interval / version / trading_mode 均从该文件自动读取，无需显式传入。
set -euo pipefail

STRATEGY=""
SYMBOL=""
CONFIG_PATH=""
TRADING_MODE=""
LOG_DIR="${LOGS_DIR:-./logs}"
PYTHON_CMD="${PYTHON_CMD:-}"
PROJECT_DIR="${PROJECT_DIR:-.}"
BACKGROUND=false
LOG_LEVEL="${LOG_LEVEL:-INFO}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --strategy|--name) STRATEGY="$2"; shift 2 ;;
        --symbol) SYMBOL="$2"; shift 2 ;;
        --config-path) CONFIG_PATH="$2"; shift 2 ;;
        --trading-mode) TRADING_MODE="$2"; shift 2 ;;
        --log-dir) LOG_DIR="$2"; shift 2 ;;
        --log-level) LOG_LEVEL="$2"; shift 2 ;;
        --project-dir) PROJECT_DIR="$2"; shift 2 ;;
        --background) BACKGROUND=true; shift ;;
        --python) PYTHON_CMD="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: run_strategy.sh --strategy NAME --symbol SYMBOL [--background]"
            echo "  --strategy NAME       Strategy directory name (alias: --name)"
            echo "  --symbol SYMBOL       Trading pair, e.g. BTCUSDT"
            echo "  --config-path PATH    Override the default overrides/<SYMBOL>.yaml path"
            echo "  --trading-mode MODE   live | paper_trading | smoking"
            echo "                        (default: read from overrides, falls back to live)"
            echo "  --project-dir DIR     CTA project root (default: .)"
            echo "  --background          Run in background (nohup)"
            echo "  --log-dir DIR         Log directory (default: ./logs)"
            echo "  --log-level LEVEL     DEBUG | INFO | WARNING | ERROR (default: INFO)"
            echo "  --python CMD          Python command (default: auto-detect .venv/bin/python)"
            exit 0 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

[ -z "$STRATEGY" ] && { echo "ERROR: --strategy required"; exit 1; }
[ -z "$SYMBOL" ] && { echo "ERROR: --symbol required"; exit 1; }

# ===== Validate project root =====
if [ ! -f "${PROJECT_DIR}/run_strategy.py" ]; then
    echo "ERROR: run_strategy.py not found under: $PROJECT_DIR"
    echo "  Set --project-dir (or \$PROJECT_DIR) to the CTA project root."
    exit 1
fi
PROJECT_ABS="$(cd "$PROJECT_DIR" && pwd)"

# ===== Detect Python =====
# The template's deps live in .venv, and many hosts have no `python3` on PATH.
if [ -z "$PYTHON_CMD" ]; then
    if [ -x "${PROJECT_ABS}/.venv/bin/python" ]; then
        PYTHON_CMD="${PROJECT_ABS}/.venv/bin/python"
    elif command -v python3 &>/dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &>/dev/null; then
        PYTHON_CMD="python"
    else
        echo "ERROR: no usable Python found (tried ${PROJECT_ABS}/.venv/bin/python, python3, python)"
        exit 1
    fi
fi

# ===== Resolve strategy params file =====
# v3.7 single source of truth. run_strategy.py derives this same path,
# but checking here turns a stack trace into a readable message.
RESOLVED_CONFIG="${CONFIG_PATH:-${PROJECT_ABS}/strategies/${STRATEGY}/overrides/${SYMBOL}.yaml}"
if [ ! -f "$RESOLVED_CONFIG" ]; then
    echo "ERROR: strategy params not found: $RESOLVED_CONFIG"
    echo "  v3.7 reads per-symbol params from strategies/<name>/overrides/<SYMBOL>.yaml"
    AVAILABLE=$(ls "${PROJECT_ABS}/strategies/${STRATEGY}/overrides/" 2>/dev/null | sed 's/\.yaml$//' | tr '\n' ' ')
    [ -n "$AVAILABLE" ] && echo "  Configured symbols: $AVAILABLE"
    exit 1
fi

# ===== Surface the effective trading mode =====
# run_strategy.py defaults trading_mode to "live" when neither the CLI nor the
# overrides file specifies it. Starting a real-money process by accident is the
# worst failure mode here, so always print what will actually be used.
EFFECTIVE_MODE="$TRADING_MODE"
if [ -z "$EFFECTIVE_MODE" ]; then
    EFFECTIVE_MODE=$($PYTHON_CMD -c "
import sys
try:
    import yaml
except ImportError:
    print('unknown'); sys.exit(0)
try:
    with open('$RESOLVED_CONFIG') as f:
        cfg = yaml.safe_load(f) or {}
except Exception:
    print('unknown'); sys.exit(0)
section = cfg.get('$STRATEGY') if isinstance(cfg.get('$STRATEGY'), dict) else cfg
print(section.get('trading_mode') or 'live (default)')
" 2>/dev/null || echo "unknown")
fi

mkdir -p "$LOG_DIR"
LOG_FILE="${LOG_DIR}/${STRATEGY}-${SYMBOL}-$(date +%Y%m%d).log"

echo "Strategy:      $STRATEGY"
echo "Symbol:        $SYMBOL"
echo "Params:        $RESOLVED_CONFIG"
echo "Trading mode:  $EFFECTIVE_MODE"
echo "Project:       $PROJECT_ABS"
echo "Log:           $LOG_FILE"

case "$EFFECTIVE_MODE" in
    live*)
        echo ""
        echo "!!! WARNING: trading_mode is LIVE — this places real orders."
        echo "    Use --trading-mode paper_trading (or smoking) to dry-run."
        ;;
esac

# Build python command. run_strategy.py must run from the project root so that
# strategy_core / data_manager / strategies are importable.
CMD=("$PYTHON_CMD" "run_strategy.py" "--name" "$STRATEGY" "--symbol" "$SYMBOL" "--log-level" "$LOG_LEVEL")
[ -n "$CONFIG_PATH" ] && CMD+=("--config-path" "$CONFIG_PATH")
[ -n "$TRADING_MODE" ] && CMD+=("--trading-mode" "$TRADING_MODE")

echo ""
if [ "$BACKGROUND" = true ]; then
    (cd "$PROJECT_ABS" && PYTHONPATH="$PROJECT_ABS" nohup "${CMD[@]}" >> "$LOG_FILE" 2>&1 &
     echo "$!" > "${LOG_DIR}/${STRATEGY}-${SYMBOL}.pid")
    PID=$(cat "${LOG_DIR}/${STRATEGY}-${SYMBOL}.pid")
    echo "PID:           $PID"
    echo ""
    echo "Strategy started in background."
    echo "  Monitor: tail -f $LOG_FILE"
    echo "  Stop:    kill $PID"
    echo ""
    echo "Note: this starts ONE (strategy, symbol) process."
    echo "  To run the full roster from config/strategies.yaml, use ./start.sh instead."
else
    echo "Starting in foreground (Ctrl+C to stop)..."
    cd "$PROJECT_ABS"
    PYTHONPATH="$PROJECT_ABS" exec "${CMD[@]}" 2>&1 | tee -a "$LOG_FILE"
fi
