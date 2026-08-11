#!/bin/bash
# deploy.sh — 策略部署主脚本 (Phase 0→5 编排)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DATE=$(date +%Y%m%d_%H%M%S)

# defaults
STRATEGIES_DIR="${STRATEGIES_DIR:-./strategies}"
LOGS_DIR="${LOGS_DIR:-./logs}"
DEPLOY_OUTPUTS_DIR="${DEPLOY_OUTPUTS_DIR:-./deploy_outputs}"
KLINE_DATA_DIR="${KLINE_DATA_DIR:-./data/strategies/1m}"
PYTHON_CMD="${PYTHON_CMD:-python3}"
STRATEGY_NAME="${STRATEGY_NAME:-}"
SYMBOLS="${SYMBOLS:-}"
GIT_URL="${STRATEGIES_GIT_URL:-}"
GIT_BRANCH="${GIT_BRANCH:-main}"
MAX_DATA_RETRIES="${MAX_DATA_RETRIES:-5}"
SKIP_DATA_CHECK="${SKIP_DATA_CHECK:-false}"

mkdir -p "$LOGS_DIR" "$DEPLOY_OUTPUTS_DIR/$DEPLOY_DATE"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOGS_DIR/deploy-${DEPLOY_DATE}.log"; }

# === Phase 0: preflight ===
log "=== Phase 0: Preflight ==="
$PYTHON_CMD --version &>/dev/null || { log "FATAL: python3 not found"; exit 1; }
git --version &>/dev/null || { log "FATAL: git not found"; exit 1; }
log "OK: python3 + git available"

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
if [ -z "$GIT_URL" ]; then
    log "STRATEGIES_GIT_URL not set. Prompting..."
    echo -n "Enter git URL for strategies: "; read -r GIT_URL
fi

$PYTHON_CMD "${SCRIPT_DIR}/git_pull.py" \
    --git-url "$GIT_URL" \
    --strategies-dir "$STRATEGIES_DIR" \
    --branch "$GIT_BRANCH"

# List strategies
$PYTHON_CMD "${SCRIPT_DIR}/git_pull.py" --strategies-dir "$STRATEGIES_DIR" --list

# Analyze if strategy specified
if [ -n "$STRATEGY_NAME" ]; then
    $PYTHON_CMD "${SCRIPT_DIR}/git_pull.py" \
        --strategies-dir "$STRATEGIES_DIR" \
        --strategy "$STRATEGY_NAME" --analyze
fi

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
if [ -n "$STRATEGY_NAME" ] && [ -f "$CALC_SCRIPT" ]; then
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

        log "Downloading data... (implement based on your data pipeline)"
        # Placeholder: call your data download script here
        sleep 2
    done
fi
log "Data readiness check complete"

# === Phase 4: config generation ===
log "=== Phase 4: Config Generation ==="
RUNTIME_CONFIG="${DEPLOY_OUTPUTS_DIR}/${DEPLOY_DATE}/${STRATEGY_NAME:-strategy}-runtime.yaml"

$PYTHON_CMD "${SCRIPT_DIR}/create_config.py" \
    --strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" \
    --symbols "$SYMBOLS" \
    --output "$RUNTIME_CONFIG"

log "Config: $RUNTIME_CONFIG"

echo -n "Start strategy with this config? (y/n): "; read -r START_CONFIRM
[ "$START_CONFIRM" != "y" ] && { log "Config saved, not starting. Run: /trading-deploy start --strategy ${STRATEGY_NAME}"; exit 0; }

# === Phase 5: start strategy ===
log "=== Phase 5: Start Strategy ==="

# Optional: websocket test
if command -v websockets &>/dev/null 2>&1; then
    FIRST_SYMBOL=$(echo "$SYMBOLS" | cut -d',' -f1)
    log "Testing WebSocket for $FIRST_SYMBOL..."
    $PYTHON_CMD "${SCRIPT_DIR}/subscribe_websocket.py" \
        --symbol "${FIRST_SYMBOL:-BTCUSDT}" --test --timeout 15 || true
fi

bash "${SCRIPT_DIR}/run_strategy.sh" \
    --strategy "${STRATEGY_NAME}" \
    --config "$RUNTIME_CONFIG" \
    --log-dir "$LOGS_DIR" \
    --background

log "=== Deployment complete ==="
