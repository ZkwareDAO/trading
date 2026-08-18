#!/bin/bash
# deploy.sh — 策略部署主脚本 (Phase 0→5 编排)
#
# 对接模板 v3.7:
#   策略参数唯一来源: strategies/<name>/overrides/<SYMBOL>.yaml
#   编排登记表:       config/strategies.yaml（实盘回测共用）
#   单进程启动:       run_strategy.py --name NAME --symbol SYMBOL
#   全量启动:         ./start.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DATE=$(date +%Y%m%d_%H%M%S)

# defaults
PROJECT_DIR="${PROJECT_DIR:-.}"
STRATEGIES_DIR="${STRATEGIES_DIR:-./strategies}"
LOGS_DIR="${LOGS_DIR:-./logs}"
DEPLOY_OUTPUTS_DIR="${DEPLOY_OUTPUTS_DIR:-./deploy_outputs}"
KLINE_DATA_DIR="${KLINE_DATA_DIR:-./data/klines}"
PYTHON_CMD="${PYTHON_CMD:-}"
STRATEGY_NAME="${STRATEGY_NAME:-}"
SYMBOLS="${SYMBOLS:-}"
GIT_URL="${STRATEGIES_GIT_URL:-}"
GIT_BRANCH="${GIT_BRANCH:-main}"
MAX_DATA_RETRIES="${MAX_DATA_RETRIES:-5}"
SKIP_DATA_CHECK="${SKIP_DATA_CHECK:-false}"
# 上线模式：必须显式选择，否则 overrides 缺省会按 live 下真单
TRADING_MODE="${TRADING_MODE:-}"
# 是否把策略登记进 config/strategies.yaml
REGISTER="${REGISTER:-false}"

while [[ $# -gt 0 ]]; do
    case $1 in
        --strategy|--name) STRATEGY_NAME="$2"; shift 2 ;;
        --symbols) SYMBOLS="$2"; shift 2 ;;
        --project-dir) PROJECT_DIR="$2"; shift 2 ;;
        --trading-mode) TRADING_MODE="$2"; shift 2 ;;
        --register) REGISTER=true; shift ;;
        --skip-data-check) SKIP_DATA_CHECK=true; shift ;;
        --python) PYTHON_CMD="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: deploy.sh --strategy NAME [--symbols S1,S2] [--trading-mode MODE]"
            echo "  --strategy NAME       Strategy directory name"
            echo "  --symbols S1,S2       Symbols to deploy (default: all overrides)"
            echo "  --project-dir DIR     CTA project root (default: .)"
            echo "  --trading-mode MODE   live | paper_trading | smoking"
            echo "  --register            Add to config/strategies.yaml roster"
            echo "  --skip-data-check     Skip Phase 3 K-line readiness loop"
            echo "  --python CMD          Python command (default: auto-detect)"
            exit 0 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

mkdir -p "$LOGS_DIR" "$DEPLOY_OUTPUTS_DIR/$DEPLOY_DATE"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGS_DIR/deploy-${DEPLOY_DATE}.log"; }

# === Phase 0: preflight ===
log "=== Phase 0: Preflight ==="

if [ ! -f "${PROJECT_DIR}/run_strategy.py" ]; then
    log "FATAL: run_strategy.py not found under ${PROJECT_DIR}"
    log "  Set --project-dir (or \$PROJECT_DIR) to the CTA project root."
    exit 1
fi
PROJECT_ABS="$(cd "$PROJECT_DIR" && pwd)"

# The template's deps live in .venv, and many hosts have no `python3` on PATH.
if [ -z "$PYTHON_CMD" ]; then
    if [ -x "${PROJECT_ABS}/.venv/bin/python" ]; then
        PYTHON_CMD="${PROJECT_ABS}/.venv/bin/python"
    elif command -v python3 &>/dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &>/dev/null; then
        PYTHON_CMD="python"
    else
        log "FATAL: no usable Python found"
        exit 1
    fi
fi
$PYTHON_CMD -c 'import sys' &>/dev/null || { log "FATAL: Python unusable: $PYTHON_CMD"; exit 1; }
git --version &>/dev/null || { log "FATAL: git not found"; exit 1; }
log "OK: python ($PYTHON_CMD) + git available"
log "OK: project root $PROJECT_ABS"

# === Phase 1: config ===
log "=== Phase 1: Config Init ==="
if [ -f ".env" ]; then
    while IFS= read -r line; do
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        key="${line%%=*}"; value="${line#*=}"
        key=$(echo "$key" | xargs); value=$(echo "$value" | xargs | sed "s/^['\"]//;s/['\"]$//")
        export "$key=$value"
    done < .env
fi
log "Config loaded"

# === Phase 2: git pull + analyze ===
log "=== Phase 2: Git Pull + Analyze ==="
if [ -n "$GIT_URL" ]; then
    $PYTHON_CMD "${SCRIPT_DIR}/git_pull.py" \
        --git-url "$GIT_URL" \
        --strategies-dir "$STRATEGIES_DIR" \
        --branch "$GIT_BRANCH"
else
    log "STRATEGIES_GIT_URL not set — using strategies already on disk"
fi

# List strategies (symbols come from overrides/ file names)
$PYTHON_CMD "${SCRIPT_DIR}/git_pull.py" --strategies-dir "$STRATEGIES_DIR" --list

[ -z "$STRATEGY_NAME" ] && { log "FATAL: --strategy required"; exit 1; }

$PYTHON_CMD "${SCRIPT_DIR}/git_pull.py" \
    --strategies-dir "$STRATEGIES_DIR" \
    --strategy "$STRATEGY_NAME" --analyze || log "WARN: analysis reported issues"

# Confirm
echo ""
echo -n "Continue with deployment? (y/n): "; read -r CONFIRM
[ "$CONFIRM" != "y" ] && { log "Cancelled"; exit 0; }

# === Phase 3: data readiness loop ===
log "=== Phase 3: K-line Data Readiness ==="

# Calculate requirements (use shared calc_data_requirements.py if available)
CALC_SCRIPT="${SCRIPT_DIR}/calc_data_requirements.py"
if [ ! -f "$CALC_SCRIPT" ]; then
    # fallback to discovery skill's copy
    CALC_SCRIPT="$(dirname "$SCRIPT_DIR")/../trading-discovery-skill/templates/calc_data_requirements.py"
fi

REQUIRED_DAYS=30
if [ -f "$CALC_SCRIPT" ]; then
    REQ_OUTPUT=$($PYTHON_CMD "$CALC_SCRIPT" \
        --strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" \
        --kline-data-dir "$KLINE_DATA_DIR" --json 2>/dev/null || echo '{"recommended_data_days":30}')
    REQUIRED_DAYS=$(echo "$REQ_OUTPUT" | $PYTHON_CMD -c "import sys,json; print(json.load(sys.stdin).get('recommended_data_days',30))" 2>/dev/null || echo 30)
fi
log "Required data days: $REQUIRED_DAYS"

if [ "$SKIP_DATA_CHECK" = false ]; then
    RETRY=0
    while [ $RETRY -lt "$MAX_DATA_RETRIES" ]; do
        $PYTHON_CMD "${SCRIPT_DIR}/data_readiness_check.py" \
            --strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" \
            --symbols "$SYMBOLS" \
            --kline-data-dir "$KLINE_DATA_DIR" \
            --required-days "$REQUIRED_DAYS" \
            --max-retries "$MAX_DATA_RETRIES" && break

        RETRY=$((RETRY + 1))
        log "Data not ready (attempt $RETRY/$MAX_DATA_RETRIES)"

        if [ $RETRY -ge "$MAX_DATA_RETRIES" ]; then
            echo -n "Max retries reached. Skip data check? (y/n): "
            read -r SKIP_ANS
            [ "$SKIP_ANS" = "y" ] && break || { log "Aborted"; exit 1; }
        fi

        echo -n "Attempt download missing data? (y/n): "
        read -r DL_ANS
        [ "$DL_ANS" != "y" ] && { echo -n "Skip and continue? (y/n): "; read -r S; [ "$S" = "y" ] && break || exit 1; }

        # 模板自带下载脚本: scripts/download_data.py
        if [ -f "${PROJECT_ABS}/scripts/download_data.py" ]; then
            log "Downloading via scripts/download_data.py ..."
            (cd "$PROJECT_ABS" && $PYTHON_CMD scripts/download_data.py) 2>&1 | tee -a "$LOGS_DIR/deploy-${DEPLOY_DATE}.log" || log "WARN: download failed"
        else
            log "No scripts/download_data.py found — download data manually, then retry"
            sleep 2
        fi
    done
fi
log "Data readiness check complete"

# === Phase 4: config validation / registration ===
# v3.7 不生成 runtime config：真正生效的是 overrides/<SYMBOL>.yaml。
# 这一步只做校验，并可选地把策略登记进 config/strategies.yaml。
log "=== Phase 4: Config Validation ==="

CHECK_ARGS=(--strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" --check)
[ -n "$SYMBOLS" ] && CHECK_ARGS+=(--symbols "$SYMBOLS")
[ -n "$TRADING_MODE" ] && CHECK_ARGS+=(--trading-mode "$TRADING_MODE")
if [ "$REGISTER" = true ]; then
    CHECK_ARGS+=(--register --project-dir "$PROJECT_ABS")
fi

CHECK_REPORT="${DEPLOY_OUTPUTS_DIR}/${DEPLOY_DATE}/${STRATEGY_NAME}-check.json"
$PYTHON_CMD "${SCRIPT_DIR}/create_config.py" "${CHECK_ARGS[@]}" || {
    log "FATAL: deployment check failed — fix overrides/<SYMBOL>.yaml first"
    exit 1
}
$PYTHON_CMD "${SCRIPT_DIR}/create_config.py" \
    --strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" \
    ${SYMBOLS:+--symbols "$SYMBOLS"} --check --json > "$CHECK_REPORT" 2>/dev/null || true
log "Check report: $CHECK_REPORT"

echo -n "Start strategy now? (y/n): "; read -r START_CONFIRM
[ "$START_CONFIRM" != "y" ] && { log "Not starting. Run: /trading-deploy start --strategy ${STRATEGY_NAME}"; exit 0; }

# === Phase 5: start strategy ===
log "=== Phase 5: Start Strategy ==="

# Determine which symbols to start
START_SYMBOLS="$SYMBOLS"
if [ -z "$START_SYMBOLS" ]; then
    START_SYMBOLS=$(ls "${STRATEGIES_DIR}/${STRATEGY_NAME}/overrides/" 2>/dev/null \
        | sed 's/\.yaml$//' | paste -sd, -)
fi
[ -z "$START_SYMBOLS" ] && { log "FATAL: no symbols to start"; exit 1; }

# Optional: websocket test on the first symbol
FIRST_SYMBOL=$(echo "$START_SYMBOLS" | cut -d',' -f1)
if [ -f "${SCRIPT_DIR}/subscribe_websocket.py" ]; then
    log "Testing WebSocket for $FIRST_SYMBOL..."
    $PYTHON_CMD "${SCRIPT_DIR}/subscribe_websocket.py" \
        --symbol "$FIRST_SYMBOL" --test --timeout 15 || log "WARN: websocket test failed"
fi

# One process per (strategy, symbol) — matches run_strategy.py's contract.
# For the whole roster in a single supervised process, use ./start.sh instead.
IFS=',' read -ra START_LIST <<< "$START_SYMBOLS"
for sym in "${START_LIST[@]}"; do
    [ -z "$sym" ] && continue
    log "Starting ${STRATEGY_NAME} × ${sym} ..."
    bash "${SCRIPT_DIR}/run_strategy.sh" \
        --strategy "$STRATEGY_NAME" \
        --symbol "$sym" \
        --project-dir "$PROJECT_ABS" \
        ${TRADING_MODE:+--trading-mode "$TRADING_MODE"} \
        --log-dir "$LOGS_DIR" \
        --python "$PYTHON_CMD" \
        --background
done

log "=== Deployment complete ==="
log "Started ${#START_LIST[@]} process(es). Alternative: ./start.sh runs the full config/strategies.yaml roster."
