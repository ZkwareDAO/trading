#!/bin/bash
# discover.sh — 指定代币/策略/时间范围的回测探索
# 对每个 (策略, 代币) 组合执行回测，输出对比报告
#
# 用法:
#   discover.sh --symbols BTCUSDT,ETHUSDT --strategies ema_rsi,ict_v4 --start 20260601 --end 20260701
#   discover.sh --symbols BTCUSDT --strategies ema_rsi --start 1748736000 --end 1751328000
#   discover.sh --all-strategies --symbols BTCUSDT,ETHUSDT --start 20260101
#   discover.sh --symbols BTCUSDT --strategies ema_rsi --start 20260601 --parallel 3
#
# 依赖模板 v3.7 的回测入口:
#   python -m backtest.batch_runner --run name:symbol,... --start D --end D --profile P
# 策略参数唯一来源: strategies/<name>/overrides/<SYMBOL>.yaml
# 回测运行参数（输出目录/并发/资金/费率）: config/<profile>.yaml，本脚本自动生成

set -euo pipefail

# ===== 默认值 =====
SYMBOLS=""
STRATEGIES=""
ALL_STRATEGIES=false
START_DATE=""
END_DATE=""
CONFIG_FILE="config.yaml"
OUTPUT_DIR="${DISCOVERY_OUTPUTS_DIR:-./discovery_outputs}"
LOGS_DIR="${LOGS_DIR:-./logs}"
# 项目根目录（含 backtest/strategy_core/data_manager 等）
PROJECT_DIR="${PROJECT_DIR:-.}"
# 策略目录（相对于 PROJECT_DIR 或绝对路径）
STRATEGIES_DIR="${STRATEGIES_DIR:-./strategies}"
# Python 命令：默认留空，稍后按 PROJECT_DIR/.venv → python3 → python 自动探测
PYTHON_CMD="${PYTHON_CMD:-}"
PARALLEL="${PARALLEL:-1}"
SKIP_ANALYSIS="${SKIP_ANALYSIS:-false}"
# K 线数据目录（analyze_strategies.py 用于数据可用性检查）
KLINE_DATA_DIR="${KLINE_DATA_DIR:-./data/klines}"
# run-profile 名：生成 PROJECT_DIR/config/<name>.yaml
PROFILE_NAME="${DISCOVERY_PROFILE:-discovery}"
# 回测资金与费率（写入 profile，不影响策略参数）
BT_CASH="${BT_CASH:-5000}"
BT_COMMISSION="${BT_COMMISSION:-0.0004}"
# 是否保留生成的 profile 文件（调试用）
KEEP_PROFILE="${KEEP_PROFILE:-false}"

# ===== 参数解析 =====
while [[ $# -gt 0 ]]; do
    case $1 in
        --symbols)
            SYMBOLS="$2"
            shift 2
            ;;
        --strategies)
            STRATEGIES="$2"
            shift 2
            ;;
        --all-strategies)
            ALL_STRATEGIES=true
            shift
            ;;
        --start)
            START_DATE="$2"
            shift 2
            ;;
        --end)
            END_DATE="$2"
            shift 2
            ;;
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --output-dir)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --parallel)
            PARALLEL="$2"
            shift 2
            ;;
        --profile)
            PROFILE_NAME="$2"
            shift 2
            ;;
        --keep-profile)
            KEEP_PROFILE=true
            shift
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
            echo "用法: discover.sh --symbols S1,S2 --strategies ST1,ST2 --start DATE [--end DATE]"
            echo ""
            echo "选项:"
            echo "  --symbols S1,S2         代币列表（逗号分隔）"
            echo "  --strategies ST1,ST2    策略列表（逗号分隔）"
            echo "  --all-strategies        使用策略目录下所有策略"
            echo "  --start DATE            回测开始时间（YYYYMMDD 或时间戳）"
            echo "  --end DATE              回测结束时间（默认: 当天）"
            echo "  --config FILE           Discovery 自身配置文件（默认: config.yaml）"
            echo "  --output-dir DIR        输出目录（默认: ./discovery_outputs）"
            echo "  --parallel N            并发回测数（写入 profile.max_workers，默认: 1）"
            echo "  --profile NAME          run-profile 名（默认: discovery）"
            echo "  --keep-profile          保留生成的 config/<NAME>.yaml（默认运行后删除）"
            echo "  --skip-analysis         跳过策略分析阶段 (Phase 1.5)"
            echo "  --python CMD            Python 命令（默认: 自动探测 .venv/bin/python）"
            exit 0
            ;;
        *)
            echo "未知参数: $1"
            exit 1
            ;;
    esac
done

# ===== 参数验证 =====
if [ -z "$SYMBOLS" ] && [ "$SKIP_ANALYSIS" = true ]; then
    echo "❌ 缺少 --symbols 参数（--skip-analysis 模式下必须指定）"
    exit 1
fi

if [ -z "$STRATEGIES" ] && [ "$ALL_STRATEGIES" = false ]; then
    echo "❌ 缺少 --strategies 参数或 --all-strategies 标志"
    exit 1
fi

if [ -z "$START_DATE" ]; then
    echo "❌ 缺少 --start 参数"
    exit 1
fi

# ===== 加载 .env（逐行解析，避免直接 source 执行任意代码） =====
# 只从当前工作目录加载，不从不可信目录加载
DISCOVER_WORK_DIR="$(pwd)"
if [ -f "${DISCOVER_WORK_DIR}/.env" ]; then
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
    done < "${DISCOVER_WORK_DIR}/.env"
fi

# ===== 验证项目目录 =====
if [ ! -d "${PROJECT_DIR}/backtest" ]; then
    echo "❌ 项目目录不包含 backtest/ 模块: $PROJECT_DIR"
    echo "  请设置 PROJECT_DIR 指向完整的 CTA 项目根目录"
    echo "  如: export PROJECT_DIR=/path/to/your/cta_project"
    exit 1
fi

PROJECT_ABS="$(cd "$PROJECT_DIR" && pwd)"

# ===== 探测 Python =====
# 模板依赖装在 .venv 里，且很多环境没有 python3 这个名字（EXIT 127）。
# 优先级: --python/$PYTHON_CMD > PROJECT_DIR/.venv/bin/python > python3 > python
if [ -z "$PYTHON_CMD" ]; then
    if [ -x "${PROJECT_ABS}/.venv/bin/python" ]; then
        PYTHON_CMD="${PROJECT_ABS}/.venv/bin/python"
    elif command -v python3 &>/dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &>/dev/null; then
        PYTHON_CMD="python"
    else
        echo "❌ 未找到可用的 Python（尝试过 ${PROJECT_ABS}/.venv/bin/python, python3, python）"
        echo "  用 --python /path/to/python 显式指定"
        exit 1
    fi
fi

if ! "$PYTHON_CMD" -c 'import sys' &>/dev/null; then
    echo "❌ Python 命令不可用: $PYTHON_CMD"
    exit 1
fi

# ===== 时间格式转换 =====
parse_date() {
    local date_str="$1"
    # 优先用 Python（跨平台），fallback 用 GNU date
    if [[ ${#date_str} -eq 10 && "$date_str" =~ ^[0-9]+$ ]]; then
        $PYTHON_CMD -c "from datetime import datetime; print(datetime.fromtimestamp(int('${date_str}')).strftime('%Y%m%d'))" 2>/dev/null \
            || date -d "@${date_str}" +%Y%m%d 2>/dev/null || echo "$date_str"
    elif [[ ${#date_str} -eq 8 && "$date_str" =~ ^[0-9]+$ ]]; then
        echo "$date_str"
    else
        echo "❌ 无法识别的时间格式: $date_str" >&2
        exit 1
    fi
}

START_DATE=$(parse_date "$START_DATE")
END_DATE="${END_DATE:-$(date +%Y%m%d)}"
END_DATE=$(parse_date "$END_DATE")

# 解析 STRATEGIES_DIR 为绝对路径（基于 PROJECT_DIR，避免 cd 后相对路径断裂）
if [[ "$STRATEGIES_DIR" != /* ]]; then
    STRATEGIES_DIR="${PROJECT_ABS}/${STRATEGIES_DIR#./}"
fi

# ===== 自动发现策略 =====
if [ "$ALL_STRATEGIES" = true ]; then
    STRATEGIES=""
    for dir in "${STRATEGIES_DIR}"/*/; do
        if [ -d "$dir" ]; then
            name=$(basename "$dir")
            # 跳过非策略目录
            [[ "$name" == "__pycache__" || "$name" == .* ]] && continue
            if [ -z "$STRATEGIES" ]; then
                STRATEGIES="$name"
            else
                STRATEGIES="${STRATEGIES},${name}"
            fi
        fi
    done
    if [ -z "$STRATEGIES" ]; then
        echo "❌ 策略目录为空: $STRATEGIES_DIR"
        exit 1
    fi
fi

# ===== 创建目录 =====
# OUTPUT_DIR 必须是绝对路径：回测在 PROJECT_DIR 下运行，相对路径会落错地方
if [[ "$OUTPUT_DIR" != /* ]]; then
    OUTPUT_DIR="${DISCOVER_WORK_DIR}/${OUTPUT_DIR#./}"
fi
mkdir -p "$OUTPUT_DIR"
mkdir -p "$LOGS_DIR"

# ===== 日志 =====
LOG_FILE="${LOGS_DIR}/discovery-${START_DATE}.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# ===== 验证策略存在性 =====
IFS=',' read -ra STRATEGY_LIST <<< "$STRATEGIES"
IFS=',' read -ra SYMBOL_LIST <<< "$SYMBOLS"

for strategy in "${STRATEGY_LIST[@]}"; do
    if [ ! -d "${STRATEGIES_DIR}/${strategy}" ]; then
        log "❌ 策略不存在: ${strategy}"
        exit 1
    fi
done

# ===== Phase 1.5: 策略分析 =====
ANALYSIS_JSON=""
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$SKIP_ANALYSIS" = false ] && [ -f "${SCRIPT_DIR}/analyze_strategies.py" ]; then
    log "📊 Phase 1.5: 策略分析..."

    ANALYSIS_JSON="${LOGS_DIR}/discovery-analysis-${START_DATE}.json"

    ANALYSIS_SYMBOLS_ARG=""
    if [ -n "$SYMBOLS" ]; then
        ANALYSIS_SYMBOLS_ARG="--symbols $SYMBOLS"
    fi

    if $PYTHON_CMD "${SCRIPT_DIR}/analyze_strategies.py" \
        --strategies "$STRATEGIES" \
        --strategies-dir "$STRATEGIES_DIR" \
        $ANALYSIS_SYMBOLS_ARG \
        --start "$START_DATE" \
        --end "$END_DATE" \
        --kline-data-dir "$KLINE_DATA_DIR" \
        --output "$ANALYSIS_JSON" \
        2>&1 | tee -a "$LOG_FILE"; then

        # 从 JSON 提取 ready/partial 策略及其 symbols
        if [ -f "$ANALYSIS_JSON" ]; then
            # 更新 STRATEGY_LIST（过滤 skip）和 SYMBOLS（从配置读取或保持用户指定）
            ANALYSIS_RESULT=$($PYTHON_CMD -c "
import json
with open('$ANALYSIS_JSON') as f:
    data = json.load(f)
proceed = [s for s in data.get('strategies', []) if s.get('status') in ('ready', 'partial')]
# 输出: strategy_name,symbol1,symbol2
for s in proceed:
    syms = s.get('symbols', [])
    print(f\"{s['strategy_name']},{','.join(syms)}\")
" 2>/dev/null || true)

            if [ -n "$ANALYSIS_RESULT" ]; then
                # 重建 STRATEGY_LIST 和 per-strategy symbols
                NEW_STRATEGY_LIST=()
                declare -A STRATEGY_SYMBOLS_MAP

                while IFS= read -r line; do
                    [ -z "$line" ] && continue
                    sname="${line%%,*}"
                    ssyms="${line#*,}"
                    NEW_STRATEGY_LIST+=("$sname")
                    if [ -n "$ssyms" ] && [ "$ssyms" != "$sname" ]; then
                        STRATEGY_SYMBOLS_MAP["$sname"]="$ssyms"
                    fi
                done <<< "$ANALYSIS_RESULT"

                if [ ${#NEW_STRATEGY_LIST[@]} -gt 0 ]; then
                    STRATEGY_LIST=("${NEW_STRATEGY_LIST[@]}")
                    # 如果用户未指定 symbols，从分析结果构建
                    if [ -z "$SYMBOLS" ]; then
                        ALL_SYMBOLS=""
                        for s in "${STRATEGY_LIST[@]}"; do
                            syms="${STRATEGY_SYMBOLS_MAP[$s]:-}"
                            if [ -n "$syms" ]; then
                                IFS=',' read -ra sym_arr <<< "$syms"
                                for sym in "${sym_arr[@]}"; do
                                    if [[ ",$ALL_SYMBOLS," != *",$sym,"* ]]; then
                                        [ -n "$ALL_SYMBOLS" ] && ALL_SYMBOLS="$ALL_SYMBOLS,$sym" || ALL_SYMBOLS="$sym"
                                    fi
                                done
                            fi
                        done
                        SYMBOLS="$ALL_SYMBOLS"
                        IFS=',' read -ra SYMBOL_LIST <<< "$SYMBOLS"
                    fi
                    log "✅ 分析完成: ${#STRATEGY_LIST[@]} 个策略可回测, symbols: $SYMBOLS"
                else
                    log "⚠ 分析结果为空，回退到全量回测"
                fi
            else
                log "⚠ 分析结果解析失败，回退到全量回测"
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
    log "⚠ analyze_strategies.py 不存在，跳过策略分析"
fi

# ===== 构建 batch_runner 运行清单 =====
# 格式: name:symbol,name:symbol —— 与实盘 run_strategies_manager.py --run 一致。
# batch_runner 自动按 strategies/<name>/overrides/<SYMBOL>.yaml 解析策略参数，
# 文件不存在直接报错（显式清单不静默跳过），因此这里预先校验并给出可读提示。
RUN_LIST=""
SKIPPED_PAIRS=()
TOTAL_COMBINATIONS=0

for strategy in "${STRATEGY_LIST[@]}"; do
    # 确定当前策略的 symbols 列表
    if [ -n "$ANALYSIS_JSON" ] && [ -f "$ANALYSIS_JSON" ]; then
        STRATEGY_SYMBOLS=$($PYTHON_CMD -c "
import json
with open('$ANALYSIS_JSON') as f:
    data = json.load(f)
for s in data.get('strategies', []):
    if s['strategy_name'] == '$strategy':
        print(','.join(s.get('symbols', [])))
        break
" 2>/dev/null || echo "")
        if [ -n "$STRATEGY_SYMBOLS" ]; then
            IFS=',' read -ra CURRENT_SYMBOL_LIST <<< "$STRATEGY_SYMBOLS"
        else
            CURRENT_SYMBOL_LIST=("${SYMBOL_LIST[@]}")
        fi
    else
        CURRENT_SYMBOL_LIST=("${SYMBOL_LIST[@]}")
    fi

    for symbol in "${CURRENT_SYMBOL_LIST[@]}"; do
        [ -z "$symbol" ] && continue
        # v3.7 单一事实来源: strategies/<name>/overrides/<SYMBOL>.yaml
        OVERRIDE_FILE="${STRATEGIES_DIR}/${strategy}/overrides/${symbol}.yaml"
        if [ ! -f "$OVERRIDE_FILE" ]; then
            SKIPPED_PAIRS+=("${strategy}:${symbol} (缺 overrides/${symbol}.yaml)")
            continue
        fi
        if [ -z "$RUN_LIST" ]; then
            RUN_LIST="${strategy}:${symbol}"
        else
            RUN_LIST="${RUN_LIST},${strategy}:${symbol}"
        fi
        TOTAL_COMBINATIONS=$((TOTAL_COMBINATIONS + 1))
    done
done

if [ ${#SKIPPED_PAIRS[@]} -gt 0 ]; then
    log "⚠ 跳过 ${#SKIPPED_PAIRS[@]} 个组合（缺少 per-symbol overrides）:"
    for p in "${SKIPPED_PAIRS[@]}"; do
        log "    - $p"
    done
    log "  说明: v3.7 策略参数唯一来源是 strategies/<name>/overrides/<SYMBOL>.yaml"
fi

if [ -z "$RUN_LIST" ]; then
    log "❌ 无可回测组合（全部缺少 overrides 文件）"
    exit 1
fi

log "📋 Discovery 回测计划:"
log "  代币: ${SYMBOLS}"
log "  策略: ${STRATEGIES}"
log "  时间: ${START_DATE} - ${END_DATE}"
log "  回测组合: ${TOTAL_COMBINATIONS}"
log "  运行清单: ${RUN_LIST}"

# ===== 生成 run-profile =====
# v3.7 把 output_dir/cash/commission/并发数下放到 config/<profile>.yaml。
# data_dir 由 make_profile.py 照抄 settings.yaml 的 csv_dir（模板启动时强校验）。
PROFILE_PATH="${PROJECT_ABS}/config/${PROFILE_NAME}.yaml"
PROFILE_PREEXISTED=false
[ -f "$PROFILE_PATH" ] && PROFILE_PREEXISTED=true

if [ ! -f "${SCRIPT_DIR}/make_profile.py" ]; then
    log "❌ 缺少 make_profile.py（应与 discover.sh 同目录）"
    exit 1
fi

if ! $PYTHON_CMD "${SCRIPT_DIR}/make_profile.py" \
    --project-dir "$PROJECT_ABS" \
    --name "$PROFILE_NAME" \
    --output-dir "$OUTPUT_DIR" \
    --cash "$BT_CASH" \
    --commission "$BT_COMMISSION" \
    --max-workers "$PARALLEL" \
    2>&1 | tee -a "$LOG_FILE"; then
    log "❌ 生成 run-profile 失败: $PROFILE_PATH"
    exit 1
fi

log "🧩 run-profile: ${PROFILE_PATH} (output_dir=${OUTPUT_DIR}, max_workers=${PARALLEL})"

# 运行结束后清理生成的 profile（除非用户要求保留或文件本来就存在）
cleanup_profile() {
    if [ "$KEEP_PROFILE" = false ] && [ "$PROFILE_PREEXISTED" = false ]; then
        rm -f "$PROFILE_PATH"
    fi
}
trap cleanup_profile EXIT

# ===== 执行回测 =====
# 单次 batch_runner 调用：并发由 profile.max_workers 控制（ProcessPoolExecutor），
# 不再用 shell 后台任务手工控制并发。
# 注意: 刻意不用 batch_runner --daemon —— 该模式重建子命令时会丢掉
# --run/--start/--end/--config，等于跑成空清单。需要后台请在外层 nohup 本脚本。
log "START discover.sh"

BATCH_EXIT=0
(cd "$PROJECT_ABS" && $PYTHON_CMD -m backtest.batch_runner \
    --run "$RUN_LIST" \
    --start "$START_DATE" \
    --end "$END_DATE" \
    --profile "$PROFILE_NAME" \
    --log-level INFO) 2>&1 | tee -a "$LOG_FILE" || BATCH_EXIT=1

# ===== 统计结果 =====
# 产物结构（backtest_reporter.py）: {output_dir}/{strategy}/{date}/{time}/{symbol}/
SUCCESS_COUNT=$(find "$OUTPUT_DIR" -name "backtest_result.json" -newermt "-1 day" 2>/dev/null | wc -l | tr -d ' ')
FAIL_COUNT=$((TOTAL_COMBINATIONS - SUCCESS_COUNT))
[ "$FAIL_COUNT" -lt 0 ] && FAIL_COUNT=0

log "END discover.sh: ${TOTAL_COMBINATIONS} combinations, ${SUCCESS_COUNT} results, ${FAIL_COUNT} missing"

# ===== 生成对比报告 =====
REPORT_FILE="${OUTPUT_DIR}/discovery-report-${START_DATE}-${END_DATE}.md"

if [ -f "${SCRIPT_DIR}/generate_report.py" ]; then
    $PYTHON_CMD "${SCRIPT_DIR}/generate_report.py" \
        --output-dir "$OUTPUT_DIR" \
        --start "$START_DATE" \
        --end "$END_DATE" \
        2>&1 | tee -a "$LOG_FILE" || log "⚠ 报告生成失败"
    log "📊 报告已输出: ${REPORT_FILE}"
else
    log "⚠ generate_report.py 不存在，跳过报告生成"
fi

if [ "$BATCH_EXIT" -ne 0 ] || [ "$FAIL_COUNT" -gt 0 ]; then
    exit 1
fi
