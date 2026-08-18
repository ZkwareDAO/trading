#!/bin/bash
# deploy.sh — 策略部署主脚本 (Phase 0→5 编排)
#
# 对接模板 v3.7:
#   策略参数唯一来源: strategies/<name>/overrides/<SYMBOL>.yaml
#   编排登记表:       config/strategies.yaml（实盘回测共用）
#   实盘启动:         scripts/run_live_batch.sh --strategies N --symbols S --daemon --yes
#                     （内部转调 run_strategies_manager.py，共用 cta_strategy_core.pid）
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
# 是否为缺 overrides/<SYMBOL>.yaml 的代币创建配置（Phase 2.5）
INIT_CONFIGS="${INIT_CONFIGS:-false}"
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
        --init-configs) INIT_CONFIGS=true; shift ;;
        --python) PYTHON_CMD="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: deploy.sh --strategy NAME [--symbols S1,S2] [--trading-mode MODE]"
            echo "  --strategy NAME       Strategy directory name"
            echo "  --symbols S1,S2       Symbols to deploy (default: all overrides)"
            echo "  --project-dir DIR     CTA project root (default: .)"
            echo "  --trading-mode MODE   live | paper_trading | smoking"
            echo "  --register            Add to config/strategies.yaml roster"
            echo "  --skip-data-check     Skip Phase 3 K-line readiness loop"
            echo "  --init-configs        Create missing overrides/<SYMBOL>.yaml (Phase 2.5)"
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

# === Phase 2.5: per-symbol config init ===
# 必须排在 Phase 3 之前：K线需求是从 overrides/<SYMBOL>.yaml 的
# timeframes + 指标周期算出来的，缺配置则算不出要下载多少数据。
# 也必须排在 Phase 4 之前：Phase 4 的 --check 会因缺文件直接判 ISSUE 退出。
#
# 默认关闭（--init-configs 才开）：创建配置是写盘动作，新配置的参数需要
# 用户复核，不该在用户没要求时静默发生。
if [ "$INIT_CONFIGS" = true ] && [ -n "$SYMBOLS" ]; then
    log "=== Phase 2.5: Per-symbol Config Init ==="
    if [ -f "${SCRIPT_DIR}/init_overrides.py" ]; then
        $PYTHON_CMD "${SCRIPT_DIR}/init_overrides.py" \
            --strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" \
            --symbols "$SYMBOLS" 2>&1 | tee -a "$LOGS_DIR/deploy-${DEPLOY_DATE}.log" \
            || log "WARN: 部分配置创建失败"
        log "⚠ 新建配置一律 trading_mode=paper_trading；要上实盘须人工改对应文件"
    else
        log "WARN: init_overrides.py 不存在，跳过配置初始化"
    fi
fi

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

# 转调模板自带 scripts/run_live_batch.sh。
#
# 为什么不再自己 nohup run_strategy.py：
#   该 wrapper 用的 PID 文件是 cta_strategy_core.pid —— 与模板 start.sh /
#   stop.sh 同一个。自己起的进程不在 stop.sh 管辖范围内，一旦忘记手动 kill
#   就是"以为停了、实际还在下单"的孤儿进程。实盘场景下这是钱的问题。
#
# 行为差异（重要）：wrapper 是【整体重启】语义 ——
#   启动前会 kill 已有 manager 并 pkill run_strategies_manager.py，
#   然后用一个 run_strategies_manager.py 进程托管全部 (策略, 代币)。
#   所以本次部署会连带重启当前在跑的其它策略实例。
#
# --yes：跳过 wrapper 的任务数确认与 live 模式手输确认。deploy.sh 自己
#   在 Phase 4 已经做过 live 确认，此处重复交互在非 TTY 下会直接卡死。
LIVE_SCRIPT="${PROJECT_ABS}/scripts/run_live_batch.sh"
if [ ! -f "$LIVE_SCRIPT" ]; then
    log "FATAL: 模板实盘启动脚本不存在: $LIVE_SCRIPT"
    log "  说明: 本 skill 依赖模板 v3.7 的 scripts/run_live_batch.sh"
    exit 1
fi

# wrapper 没有 --trading-mode：v3.7 的 trading_mode 唯一来源是
# overrides/<SYMBOL>.yaml（或登记表）。若用户传了 --trading-mode，
# 只能当断言用 —— 与 overrides 实际值不符时报错，让用户去改唯一来源，
# 而不是在命令行悄悄覆盖（那正是"回测实盘不一致"的来源）。
if [ -n "$TRADING_MODE" ]; then
    MODE_MISMATCH=""
    IFS=',' read -ra CHECK_LIST <<< "$START_SYMBOLS"
    for sym in "${CHECK_LIST[@]}"; do
        [ -z "$sym" ] && continue
        ov="${STRATEGIES_DIR}/${STRATEGY_NAME}/overrides/${sym}.yaml"
        [ -f "$ov" ] || continue
        # grep 无匹配时退出码 1，set -e 下会直接终止脚本 —— 而"未声明
        # trading_mode"恰恰是最需要拦下的情况，必须 || true 兜住。
        actual=$( { grep -E '^[[:space:]]*trading_mode:' "$ov" || true; } \
            | head -1 | sed 's/.*trading_mode:[[:space:]]*//' | tr -d '"'"'"' \r')
        [ -z "$actual" ] && actual="live(默认未声明)"
        [ "$actual" = "$TRADING_MODE" ] || MODE_MISMATCH="${MODE_MISMATCH}\n    ${sym}: overrides=${actual} 期望=${TRADING_MODE}"
    done
    if [ -n "$MODE_MISMATCH" ]; then
        log "FATAL: --trading-mode ${TRADING_MODE} 与 overrides 声明不一致:"
        printf '%b\n' "$MODE_MISMATCH" | tee -a "$LOGS_DIR/deploy-${DEPLOY_DATE}.log"
        log "  v3.7 中 trading_mode 唯一来源是 overrides/<SYMBOL>.yaml。"
        log "  请直接修改对应 overrides 文件，而不是用命令行覆盖。"
        exit 1
    fi
    log "trading_mode 断言通过: 全部为 ${TRADING_MODE}"
fi

log "Starting ${STRATEGY_NAME} × ${START_SYMBOLS} via scripts/run_live_batch.sh ..."
log "NOTE: 该脚本为整体重启语义，会重启当前所有实盘策略实例。"

(cd "$PROJECT_ABS" && bash "$LIVE_SCRIPT" \
    --strategies "$STRATEGY_NAME" \
    --symbols "$START_SYMBOLS" \
    --daemon \
    --yes) 2>&1 | tee -a "$LOGS_DIR/deploy-${DEPLOY_DATE}.log"

log "=== Deployment complete ==="
log "PID 文件: ${PROJECT_ABS}/cta_strategy_core.pid（与 start.sh/stop.sh 共用）"
log "停止: cd ${PROJECT_ABS} && ./stop.sh"
