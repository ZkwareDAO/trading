#!/bin/bash
# replay.sh — 每日回放回测
# 扫描 snapshot/{date}/ 目录，对每个 {strategy}-{model} 执行回测
#
# 用法:
#   replay.sh                          # 回测当天 snapshot，从 snapshot 日期到今天
#   replay.sh --date 20260801          # 回测指定日期 snapshot
#   replay.sh --date 20260801 --start 20260101 --end 20260801  # 自定义回测时间范围
#   replay.sh --strategy ema_rsi       # 只回测指定策略
#   replay.sh --model product          # 只回测指定模型

set -euo pipefail

# ===== 默认值（统一初始化，log 函数依赖部分变量） =====
REPLAY_DATE=""
BT_START=""
BT_END=""
CONFIG_FILE="config.yaml"
STRATEGY_FILTER=""
MODEL_FILTER=""
PYTHON_CMD="${PYTHON_CMD:-python3}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-./snapshot}"
LOGS_DIR="${LOGS_DIR:-./logs}"
REPLAY_OUTPUTS_DIR="${REPLAY_OUTPUTS_DIR:-./replay_outputs}"
KLINE_DATA_DIR="${KLINE_DATA_DIR:-./data/strategies/1m}"
DATA_PATH="${DATA_PATH:-./data}"
SKIP_ANALYSIS="${SKIP_ANALYSIS:-false}"

# ===== 日志函数（需在参数解析前定义，因为解析中可能调用 log） =====
mkdir -p "$LOGS_DIR"
LOG_FILE="${LOGS_DIR}/replay-$(date +%Y%m%d).log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# ===== 参数解析 =====
while [[ $# -gt 0 ]]; do
    case $1 in
        --date)
            REPLAY_DATE="$2"
            shift 2
            ;;
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --strategy)
            STRATEGY_FILTER="$2"
            shift 2
            ;;
        --model)
            MODEL_FILTER="$2"
            shift 2
            ;;
        --start)
            BT_START="$2"
            shift 2
            ;;
        --end)
            BT_END="$2"
            shift 2
            ;;
        --python)
            PYTHON_CMD="$2"
            shift 2
            ;;
        --skip-analysis)
            SKIP_ANALYSIS=true
            shift
            ;;
        -h|--help)
            echo "用法: replay.sh [--date YYYYMMDD] [--start YYYYMMDD] [--end YYYYMMDD] [--config FILE] [--strategy NAME] [--model TYPE] [--python CMD]"
            echo ""
            echo "选项:"
            echo "  --date YYYYMMDD     snapshot 日期（默认: 当天）"
            echo "  --start YYYYMMDD    回测开始时间（默认: snapshot 日期前 30 天）"
            echo "  --end YYYYMMDD      回测结束时间（默认: 当天）"
            echo "  --config FILE       配置文件路径（默认: config.yaml）"
            echo "  --strategy NAME     只回测指定策略"
            echo "  --model TYPE        只回测指定模型 (product/smoking/paper)"
            echo "  --skip-analysis     跳过策略分析阶段 (Phase 2.5)"
            echo "  --python CMD        Python 命令（默认: python3）"
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

# 日期默认当天
REPLAY_DATE="${REPLAY_DATE:-$(date +%Y%m%d)}"

# 校验日期格式
if [[ ! "$REPLAY_DATE" =~ ^[0-9]{8}$ ]]; then
    log "❌ 日期格式错误: $REPLAY_DATE，应为 YYYYMMDD"
    exit 1
fi

# 回测时间范围默认值
# --start: 默认为 snapshot 日期前 30 天
# --end: 默认为当天
if [ -z "$BT_START" ]; then
    # 优先用 Python 计算（跨平台），fallback 用 GNU date
    BT_START=$($PYTHON_CMD -c "from datetime import datetime, timedelta; d=datetime.strptime('${REPLAY_DATE}','%Y%m%d'); print((d-timedelta(days=30)).strftime('%Y%m%d'))" 2>/dev/null || date -d "${REPLAY_DATE} - 30 days" +%Y%m%d 2>/dev/null || echo "${REPLAY_DATE}")
    if [ "$BT_START" = "$REPLAY_DATE" ]; then
        log "⚠ 无法计算 30 天前日期，回测窗口为 0 天。请手动指定 --start"
    fi
fi
if [ -z "$BT_END" ]; then
    BT_END=$(date +%Y%m%d)
fi

# ===== 加载 .env（逐行解析，避免直接 source 执行任意代码） =====
# 只从当前工作目录加载，不从 snapshot 等不可信目录加载
REPLAY_WORK_DIR="$(pwd)"
if [ -f "${REPLAY_WORK_DIR}/.env" ]; then
    while IFS= read -r line; do
        # 跳过注释和空行
        [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
        # 用参数展开分割，保留值中所有 = 号
        key="${line%%=*}"
        value="${line#*=}"
        key=$(echo "$key" | xargs)
        # 去除首尾引号
        value=$(echo "$value" | sed "s/^['\"]//;s/['\"]$//" | xargs)
        export "$key=$value"
    done < "${REPLAY_WORK_DIR}/.env"
fi

# ===== 从 config.yaml 读取配置（覆盖默认值） =====
# 用临时文件替代 eval，逐行 export 避免执行 YAML 值中的 shell 语法
if [ -f "$CONFIG_FILE" ] && command -v python3 &>/dev/null; then
    CONFIG_ENV_FILE=$(mktemp)
    trap 'rm -f $CONFIG_ENV_FILE' EXIT
    python3 -c "
import yaml, sys, shlex
with open(sys.argv[1]) as f:
    cfg = yaml.safe_load(f) or {}
paths = cfg.get('paths', {})
replay_cfg = cfg.get('replay', {})
bt_cfg = cfg.get('backtest', {})
with open(sys.argv[2], 'w') as out:
    for k, v in paths.items():
        out.write(f'{k.upper()}={shlex.quote(str(v))}\\n')
    for k, v in replay_cfg.items():
        if isinstance(v, str):
            out.write(f'REPLAY_{k.upper()}={shlex.quote(v)}\\n')
    for k, v in bt_cfg.items():
        if isinstance(v, str):
            out.write(f'BT_{k.upper()}={shlex.quote(v)}\\n')
" "$CONFIG_FILE" "$CONFIG_ENV_FILE" 2>/dev/null
    # 逐行读取并 export，不使用 source/eval 避免执行任意 shell 语法
    while IFS= read -r env_line; do
        [[ -z "$env_line" || "$env_line" =~ ^[[:space:]]*# ]] && continue
        key="${env_line%%=*}"
        value="${env_line#*=}"
        export "$key=$value"
    done < "$CONFIG_ENV_FILE"
    rm -f "$CONFIG_ENV_FILE"
fi

# ===== 创建目录 =====
mkdir -p "$LOGS_DIR"
mkdir -p "${REPLAY_OUTPUTS_DIR}/${REPLAY_DATE}"

# ===== 更新日志文件路径（REPLAY_DATE 已确定） =====
LOG_FILE="${LOGS_DIR}/replay-${REPLAY_DATE}.log"

# ===== 开始 =====
log "START replay.sh --date ${REPLAY_DATE}"

# ===== 检查 snapshot 目录 =====
SNAPSHOT_DAY_DIR="${SNAPSHOT_DIR}/${REPLAY_DATE}"
if [ ! -d "$SNAPSHOT_DAY_DIR" ]; then
    log "❌ snapshot 目录不存在: $SNAPSHOT_DAY_DIR"
    log "  请先执行 sync-exee.py 或指定有数据的日期"
    exit 1
fi

# ===== 扫描策略快照 =====
STRATEGY_SNAPSHOTS=()
for dir in "$SNAPSHOT_DAY_DIR"/*/; do
    if [ -d "$dir" ]; then
        basename_dir=$(basename "$dir")
        # 应用过滤
        if [ -n "$STRATEGY_FILTER" ]; then
            # 贪婪匹配：最后一个 - 分隔 strategy 和 model
            strategy_part="${basename_dir%-*}"
            if [ "$strategy_part" != "$STRATEGY_FILTER" ]; then
                continue
            fi
        fi
        if [ -n "$MODEL_FILTER" ]; then
            model_part="${basename_dir##*-}"
            if [ "$model_part" != "$MODEL_FILTER" ]; then
                continue
            fi
        fi
        STRATEGY_SNAPSHOTS+=("$basename_dir")
    fi
done

if [ ${#STRATEGY_SNAPSHOTS[@]} -eq 0 ]; then
    log "⚠ 未找到匹配的策略快照"
    exit 0
fi

log "📋 发现 ${#STRATEGY_SNAPSHOTS[@]} 个策略快照:"
for s in "${STRATEGY_SNAPSHOTS[@]}"; do
    log "  - $s"
done

# ===== Phase 2.5: 策略分析 =====
ANALYSIS_JSON=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$SKIP_ANALYSIS" = false ] && [ -f "${SCRIPT_DIR}/analyze_snapshot.py" ]; then
    log "📊 Phase 2.5: 策略分析..."

    ANALYSIS_JSON="${LOGS_DIR}/analysis-${REPLAY_DATE}.json"

    if $PYTHON_CMD "${SCRIPT_DIR}/analyze_snapshot.py" \
        --snapshot-dir "$SNAPSHOT_DAY_DIR" \
        --start "$BT_START" \
        --end "$BT_END" \
        --kline-data-dir "$KLINE_DATA_DIR" \
        --output "$ANALYSIS_JSON" \
        --strategy-filter "$STRATEGY_FILTER" \
        --model-filter "$MODEL_FILTER" \
        2>&1 | tee -a "$LOG_FILE"; then

        # 从 JSON 提取 ready/partial 策略，过滤 skip
        if [ -f "$ANALYSIS_JSON" ] && command -v python3 &>/dev/null; then
            FILTERED_SNAPSHOTS=$($PYTHON_CMD -c "
import json, sys
with open('$ANALYSIS_JSON') as f:
    data = json.load(f)
proceed = [s for s in data.get('strategies', []) if s.get('status') in ('ready', 'partial')]
for s in proceed:
    name = s['strategy_name']
    model = s.get('model', '')
    if model:
        print(f'{name}-{model}')
    else:
        print(name)
" 2>/dev/null || true)

            if [ -n "$FILTERED_SNAPSHOTS" ]; then
                # 替换 STRATEGY_SNAPSHOTS 为过滤后的列表
                STRATEGY_SNAPSHOTS=()
                while IFS= read -r line; do
                    [ -n "$line" ] && STRATEGY_SNAPSHOTS+=("$line")
                done <<< "$FILTERED_SNAPSHOTS"
                log "✅ 分析完成: ${#STRATEGY_SNAPSHOTS[@]} 个策略可回测"
            else
                log "⚠ 分析结果为空，回退到全量回测"
            fi
        else
            log "⚠ JSON 文件不存在，回退到全量回测"
        fi
    else
        log "⚠ 策略分析失败，回退到全量回测"
    fi
elif [ "$SKIP_ANALYSIS" = true ]; then
    log "⏭ 跳过策略分析 (--skip-analysis)"
else
    log "⚠ analyze_snapshot.py 不存在，跳过策略分析"
fi

# ===== 执行回测 =====
SUCCESS_COUNT=0
FAIL_COUNT=0

for snapshot in "${STRATEGY_SNAPSHOTS[@]}"; do
    # 解析 strategy 和 model（最后一个 - 分隔）
    if [[ "$snapshot" == *"-"* ]]; then
        strategy_name="${snapshot%-*}"
        model="${snapshot##*-}"
    else
        # 无 - 分隔符：整个名称作为 strategy，model 为空
        strategy_name="$snapshot"
        model=""
    fi

    log "🔄 回测: ${strategy_name} (${model:-all})"

    # 回测输出目录
    OUTPUT_DIR="${REPLAY_OUTPUTS_DIR}/${REPLAY_DATE}/${snapshot}"
    mkdir -p "$OUTPUT_DIR"

    # 策略配置文件路径（优先使用分析结果，fallback 原有逻辑）
    STRATEGY_CONFIG=""
    if [ -n "$ANALYSIS_JSON" ] && [ -f "$ANALYSIS_JSON" ]; then
        # 从分析 JSON 提取预解析的 config_path
        STRATEGY_CONFIG=$($PYTHON_CMD -c "
import json
with open('$ANALYSIS_JSON') as f:
    data = json.load(f)
for s in data.get('strategies', []):
    if s['strategy_name'] == '$strategy_name' and s.get('model', '') == '$model':
        print(s.get('config_path', ''))
        break
" 2>/dev/null || true)
    fi

    if [ -z "$STRATEGY_CONFIG" ] || [ ! -f "$STRATEGY_CONFIG" ]; then
        # Fallback: 原有配置解析逻辑
        STRATEGY_CONFIG="${SNAPSHOT_DAY_DIR}/${snapshot}/strategies/${strategy_name}/config.test.yaml"
        if [ ! -f "$STRATEGY_CONFIG" ]; then
            STRATEGY_CONFIG="${SNAPSHOT_DAY_DIR}/${snapshot}/strategies/${strategy_name}/config.yaml"
        fi
        if [ ! -f "$STRATEGY_CONFIG" ]; then
            ALT_CONFIG=$(find "${SNAPSHOT_DAY_DIR}/${snapshot}/strategies/${strategy_name}" -name "config*.yaml" -type f 2>/dev/null | head -1)
            if [ -n "$ALT_CONFIG" ]; then
                STRATEGY_CONFIG="$ALT_CONFIG"
            else
                log "⚠ ${snapshot}: 未找到策略配置文件，跳过"
                FAIL_COUNT=$((FAIL_COUNT + 1))
                continue
            fi
        fi
    fi

    # 执行回测（从快照目录运行，快照包含完整项目）
    SNAPSHOT_PROJECT_DIR="${SNAPSHOT_DAY_DIR}/${snapshot}"

    # cd 到快照目录，确保 backtest/strategy_core/ 等模块可被找到
    if (cd "$SNAPSHOT_PROJECT_DIR" && $PYTHON_CMD -m backtest.run_backtest \
        --strategy "$strategy_name" \
        --start "$BT_START" \
        --end "$BT_END" \
        --config "$STRATEGY_CONFIG" \
        --output "$OUTPUT_DIR" \
        --log-level INFO) \
        2>&1 | tee -a "$LOG_FILE"; then

        # 检查回测结果
        RESULT_COUNT=$(find "$OUTPUT_DIR" -name "backtest_result.json" 2>/dev/null | wc -l)
        if [ "$RESULT_COUNT" -gt 0 ]; then
            log "✅ ${snapshot}: 回测完成 (${RESULT_COUNT} 个结果)"
            SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
        else
            log "⚠ ${snapshot}: 回测执行成功但未产出结果文件"
            FAIL_COUNT=$((FAIL_COUNT + 1))
        fi
    else
        log "❌ ${snapshot}: 回测执行失败"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done

# ===== 汇总 =====
log "END replay.sh: ${#STRATEGY_SNAPSHOTS[@]} strategies, ${SUCCESS_COUNT} success, ${FAIL_COUNT} failed"

if [ $FAIL_COUNT -gt 0 ]; then
    exit 1
fi
