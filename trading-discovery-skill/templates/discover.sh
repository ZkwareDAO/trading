#!/bin/bash
# discover.sh — 指定代币/策略/时间范围的回测探索
# 对每个 (策略, 代币) 组合执行回测，输出对比报告
#
# 用法:
#   discover.sh --symbols BTCUSDT,ETHUSDT --strategies ema_rsi,ict_v4 --start 20260601 --end 20260701
#   discover.sh --symbols BTCUSDT --strategies ema_rsi --start 1748736000 --end 1751328000
#   discover.sh --all-strategies --symbols BTCUSDT,ETHUSDT --start 20260101
#   discover.sh --symbols BTCUSDT --strategies ema_rsi --start 20260601 --parallel 3

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
PYTHON_CMD="${PYTHON_CMD:-python3}"
PARALLEL="${PARALLEL:-1}"
SKIP_ANALYSIS="${SKIP_ANALYSIS:-false}"

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
            echo "  --config FILE           配置文件路径（默认: config.yaml）"
            echo "  --output-dir DIR        输出目录（默认: ./discovery_outputs）"
            echo "  --parallel N            并行回测数（默认: 1）"
            echo "  --skip-analysis         跳过策略分析阶段 (Phase 1.5)"
            echo "  --python CMD            Python 命令（默认: python3）"
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

# ===== 自动发现策略 =====
if [ "$ALL_STRATEGIES" = true ]; then
    STRATEGIES=""
    for dir in "${STRATEGIES_DIR}"/*/; do
        if [ -d "$dir" ]; then
            name=$(basename "$dir")
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

# ===== 验证项目目录 =====
if [ ! -d "${PROJECT_DIR}/backtest" ]; then
    echo "❌ 项目目录不包含 backtest/ 模块: $PROJECT_DIR"
    echo "  请设置 PROJECT_DIR 指向完整的 CTA 项目根目录"
    echo "  如: export PROJECT_DIR=/path/to/your/cta_project"
    exit 1
fi

# 解析 STRATEGIES_DIR 为绝对路径（基于 PROJECT_DIR，避免 cd 后相对路径断裂）
if [[ "$STRATEGIES_DIR" != /* ]]; then
    STRATEGIES_DIR="$(cd "$PROJECT_DIR" 2>/dev/null && pwd)/${STRATEGIES_DIR#./}"
fi

# ===== 创建目录 =====
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
        if [ -f "$ANALYSIS_JSON" ] && command -v python3 &>/dev/null; then
            # 更新 STRATEGY_LIST（过滤 skip）和 SYMBOLS（从配置读取或保持用户指定）
            ANALYSIS_RESULT=$($PYTHON_CMD -c "
import json
with open('$ANALYSIS_JSON') as f:
    data = json.load(f)
proceed = [s for s in data.get('strategies', []) if s.get('status') in ('ready', 'partial')]
# 输出: strategy_name,symbol1|symbol2
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
                    if [ -n "$ssyms" ]; then
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

# ===== 列出回测组合 =====
if [ -n "$ANALYSIS_JSON" ] && [ -f "$ANALYSIS_JSON" ]; then
    # 从分析结果计算组合数
    TOTAL_COMBINATIONS=$($PYTHON_CMD -c "
import json
with open('$ANALYSIS_JSON') as f:
    data = json.load(f)
total = sum(len(s.get('symbols', [])) for s in data.get('strategies', []) if s.get('status') in ('ready', 'partial'))
print(total)
" 2>/dev/null || echo "0")
else
    TOTAL_COMBINATIONS=$((${#STRATEGY_LIST[@]} * ${#SYMBOL_LIST[@]}))
fi

log "📋 Discovery 回测计划:"
log "  代币: ${SYMBOLS}"
log "  策略: ${STRATEGIES}"
log "  时间: ${START_DATE} - ${END_DATE}"
log "  回测组合: ${TOTAL_COMBINATIONS}"

# ===== 执行回测 =====
log "START discover.sh"

# 临时文件记录并行结果
RESULTS_DIR=$(mktemp -d)
trap "rm -rf $RESULTS_DIR" EXIT

COMBINATION_INDEX=0

# run_backtest: 执行单个 (策略, 代币) 回测
# 全局依赖: START_DATE, END_DATE, PYTHON_CMD, PROJECT_DIR, LOG_FILE, RESULTS_DIR, TOTAL_COMBINATIONS
run_backtest() {
    local strategy="$1"
    local symbol="$2"
    local bt_output_dir="$3"
    local strategy_config="$4"
    local idx="$5"

    log "🔄 [${idx}/${TOTAL_COMBINATIONS}] ${strategy} × ${symbol}"

    mkdir -p "$bt_output_dir"

    # 在项目根目录下运行回测，确保 backtest/strategy_core 等模块可被找到
    if (cd "$PROJECT_DIR" && $PYTHON_CMD -m backtest.run_backtest \
        --strategy "$strategy" \
        --start "$START_DATE" \
        --end "$END_DATE" \
        --symbol "$symbol" \
        --config "$strategy_config" \
        --output "$bt_output_dir" \
        --log-level INFO) \
        2>&1 | tee -a "$LOG_FILE"; then

        if [ -f "${bt_output_dir}/backtest_result.json" ]; then
            log "✅ ${strategy} × ${symbol}: 回测完成"
            echo "success" > "${RESULTS_DIR}/${idx}.result"
            return 0
        else
            log "⚠ ${strategy} × ${symbol}: 未产出结果"
            echo "fail" > "${RESULTS_DIR}/${idx}.result"
            return 1
        fi
    else
        log "❌ ${strategy} × ${symbol}: 回测失败"
        echo "fail" > "${RESULTS_DIR}/${idx}.result"
        return 1
    fi
}

for strategy in "${STRATEGY_LIST[@]}"; do
    # 确定当前策略的 symbols 列表
    if [ -n "$ANALYSIS_JSON" ] && [ -f "$ANALYSIS_JSON" ]; then
        # 从分析 JSON 提取该策略的 symbols
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
        COMBINATION_INDEX=$((COMBINATION_INDEX + 1))

        BT_OUTPUT_DIR="${OUTPUT_DIR}/${strategy}/${symbol}/${START_DATE}-${END_DATE}"

        STRATEGY_CONFIG=""
        # 优先使用分析结果中的 config_path
        if [ -n "$ANALYSIS_JSON" ] && [ -f "$ANALYSIS_JSON" ]; then
            STRATEGY_CONFIG=$($PYTHON_CMD -c "
import json
with open('$ANALYSIS_JSON') as f:
    data = json.load(f)
for s in data.get('strategies', []):
    if s['strategy_name'] == '$strategy':
        print(s.get('config_path', ''))
        break
" 2>/dev/null || true)
        fi
        if [ -z "$STRATEGY_CONFIG" ] || [ ! -f "$STRATEGY_CONFIG" ]; then
            # Fallback: 原有配置解析逻辑
            STRATEGY_CONFIG="${STRATEGIES_DIR}/${strategy}/config/${symbol}.yaml"
            if [ ! -f "$STRATEGY_CONFIG" ]; then
                STRATEGY_CONFIG="${STRATEGIES_DIR}/${strategy}/config.test.yaml"
            fi
        fi

        if [ "$PARALLEL" -gt 1 ]; then
            run_backtest "$strategy" "$symbol" "$BT_OUTPUT_DIR" "$STRATEGY_CONFIG" "$COMBINATION_INDEX" &
            # 严格控制并发数：等待任意一个后台任务完成
            while [ $(jobs -r | wc -l) -ge "$PARALLEL" ]; do
                wait -n 2>/dev/null || sleep 1
            done
        else
            run_backtest "$strategy" "$symbol" "$BT_OUTPUT_DIR" "$STRATEGY_CONFIG" "$COMBINATION_INDEX"
        fi
    done
done

# 等待所有后台任务完成
wait

# 统计结果
SUCCESS_COUNT=$(find "$RESULTS_DIR" -name "*.result" -exec cat {} \; 2>/dev/null | grep -c "success" || echo 0)
FAIL_COUNT=$(find "$RESULTS_DIR" -name "*.result" -exec cat {} \; 2>/dev/null | grep -c "fail" || echo 0)

# ===== 汇总 =====
log "END discover.sh: ${TOTAL_COMBINATIONS} combinations, ${SUCCESS_COUNT} success, ${FAIL_COUNT} failed"

# ===== 生成对比报告 =====
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPORT_FILE="${OUTPUT_DIR}/discovery-report-${START_DATE}-${END_DATE}.md"

if [ -f "${SCRIPT_DIR}/generate_report.py" ]; then
    $PYTHON_CMD "${SCRIPT_DIR}/generate_report.py" \
        --output-dir "$OUTPUT_DIR" \
        --start "$START_DATE" \
        --end "$END_DATE" \
        2>/dev/null || log "⚠ 报告生成失败"
    log "📊 报告已输出: ${REPORT_FILE}"
else
    log "⚠ generate_report.py 不存在，跳过报告生成"
fi

if [ $FAIL_COUNT -gt 0 ]; then
    exit 1
fi
