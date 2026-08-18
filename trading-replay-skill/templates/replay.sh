#!/bin/bash
# replay.sh — 每日回放回测
# 扫描 snapshot/{date}/ 目录，对每个 {strategy}-{model} 快照执行回测
#
# 用法:
#   replay.sh                          # 回测当天 snapshot，从 snapshot 日期前 30 天到今天
#   replay.sh --date 20260801          # 回测指定日期 snapshot
#   replay.sh --date 20260801 --start 20260101 --end 20260801  # 自定义回测时间范围
#   replay.sh --strategy ema_rsi       # 只回测指定策略
#   replay.sh --model product          # 只回测指定模型
#
# 依赖模板 v3.7 的回测入口:
#   python -m backtest.batch_runner --run name:symbol,... --start D --end D --profile P
# 每个快照是一份完整项目副本，回测在快照目录内运行，
# 策略参数读快照自带的 strategies/<name>/overrides/<SYMBOL>.yaml
# —— 这正是"回放当天实盘参数"的意义所在。

set -euo pipefail

# ===== 默认值（统一初始化，log 函数依赖部分变量） =====
REPLAY_DATE=""
BT_START=""
BT_END=""
CONFIG_FILE="config.yaml"
STRATEGY_FILTER=""
MODEL_FILTER=""
# Python 命令：默认留空，稍后按快照/项目 .venv → python3 → python 自动探测
PYTHON_CMD="${PYTHON_CMD:-}"
SNAPSHOT_DIR="${SNAPSHOT_DIR:-./snapshot}"
LOGS_DIR="${LOGS_DIR:-./logs}"
REPLAY_OUTPUTS_DIR="${REPLAY_OUTPUTS_DIR:-./replay_outputs}"
KLINE_DATA_DIR="${KLINE_DATA_DIR:-./data/klines}"
DATA_PATH="${DATA_PATH:-./data}"
SKIP_ANALYSIS="${SKIP_ANALYSIS:-false}"
# 回测回看天数（--start 未指定时用）
LOOKBACK_DAYS="${LOOKBACK_DAYS:-30}"
# run-profile 名：在每个快照目录内生成 config/<name>.yaml
PROFILE_NAME="${REPLAY_PROFILE:-replay}"
BT_CASH="${BT_CASH:-5000}"
BT_COMMISSION="${BT_COMMISSION:-0.0004}"
PARALLEL="${PARALLEL:-1}"
KEEP_PROFILE="${KEEP_PROFILE:-false}"

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
        --lookback-days)
            LOOKBACK_DAYS="$2"
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
            echo "用法: replay.sh [--date YYYYMMDD] [--start YYYYMMDD] [--end YYYYMMDD] [--strategy NAME] [--model TYPE]"
            echo ""
            echo "选项:"
            echo "  --date YYYYMMDD       snapshot 日期（默认: 当天）"
            echo "  --start YYYYMMDD      回测开始时间（默认: snapshot 日期前 ${LOOKBACK_DAYS} 天）"
            echo "  --end YYYYMMDD        回测结束时间（默认: 当天）"
            echo "  --lookback-days N     --start 未指定时的回看天数（默认: 30）"
            echo "  --config FILE         Replay 自身配置文件（默认: config.yaml）"
            echo "  --strategy NAME       只回测指定策略"
            echo "  --model TYPE          只回测指定模型 (product/smoking/paper)"
            echo "  --parallel N          并发回测数（写入 profile.max_workers，默认: 1）"
            echo "  --profile NAME        run-profile 名（默认: replay）"
            echo "  --keep-profile        保留生成的 config/<NAME>.yaml"
            echo "  --skip-analysis       跳过策略分析阶段 (Phase 2.5)"
            echo "  --python CMD          Python 命令（默认: 自动探测 .venv/bin/python）"
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

# ===== 探测 Python =====
# 模板依赖装在 .venv 里，且很多环境没有 python3 这个名字（EXIT 127）。
# 快照本身排除了 .venv，所以用本机 Replay 项目的 .venv 跑快照代码。
if [ -z "$PYTHON_CMD" ]; then
    if [ -x "${REPLAY_WORK_DIR}/.venv/bin/python" ]; then
        PYTHON_CMD="${REPLAY_WORK_DIR}/.venv/bin/python"
    elif command -v python3 &>/dev/null; then
        PYTHON_CMD="python3"
    elif command -v python &>/dev/null; then
        PYTHON_CMD="python"
    else
        log "❌ 未找到可用的 Python（尝试过 ${REPLAY_WORK_DIR}/.venv/bin/python, python3, python）"
        log "  用 --python /path/to/python 显式指定"
        exit 1
    fi
fi

if ! "$PYTHON_CMD" -c 'import sys' &>/dev/null; then
    log "❌ Python 命令不可用: $PYTHON_CMD"
    exit 1
fi

# ===== 从 config.yaml 读取配置（覆盖默认值） =====
# 用临时文件替代 eval，逐行 export 避免执行 YAML 值中的 shell 语法
if [ -f "$CONFIG_FILE" ]; then
    CONFIG_ENV_FILE=$(mktemp)
    trap 'rm -f $CONFIG_ENV_FILE' EXIT
    $PYTHON_CMD -c "
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

# ===== 回测时间范围默认值 =====
# --start: 默认为 snapshot 日期前 LOOKBACK_DAYS 天
# --end: 默认为当天
if [ -z "$BT_START" ]; then
    BT_START=$($PYTHON_CMD -c "
from datetime import datetime, timedelta
d = datetime.strptime('${REPLAY_DATE}', '%Y%m%d')
print((d - timedelta(days=${LOOKBACK_DAYS})).strftime('%Y%m%d'))
" 2>/dev/null || date -d "${REPLAY_DATE} - ${LOOKBACK_DAYS} days" +%Y%m%d 2>/dev/null || echo "")
    if [ -z "$BT_START" ]; then
        log "❌ 无法计算 ${LOOKBACK_DAYS} 天前日期，请手动指定 --start"
        exit 1
    fi
fi
if [ -z "$BT_END" ]; then
    BT_END=$(date +%Y%m%d)
fi

# ===== 创建目录 =====
# REPLAY_OUTPUTS_DIR 必须是绝对路径：回测在快照目录内运行，相对路径会落进快照里
if [[ "$REPLAY_OUTPUTS_DIR" != /* ]]; then
    REPLAY_OUTPUTS_DIR="${REPLAY_WORK_DIR}/${REPLAY_OUTPUTS_DIR#./}"
fi
mkdir -p "$LOGS_DIR"
mkdir -p "${REPLAY_OUTPUTS_DIR}/${REPLAY_DATE}"

# ===== 更新日志文件路径（REPLAY_DATE 已确定） =====
LOG_FILE="${LOGS_DIR}/replay-${REPLAY_DATE}.log"

# ===== 开始 =====
log "START replay.sh --date ${REPLAY_DATE}"
log "  回测范围: ${BT_START} - ${BT_END}"
log "  Python: ${PYTHON_CMD}"

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
        # 跳过 sync 中断留下的临时目录
        [[ "$basename_dir" == .tmp-* ]] && continue
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
        if [ -f "$ANALYSIS_JSON" ]; then
            FILTERED_SNAPSHOTS=$($PYTHON_CMD -c "
import json
with open('$ANALYSIS_JSON') as f:
    data = json.load(f)
proceed = [s for s in data.get('strategies', []) if s.get('status') in ('ready', 'partial')]
for s in proceed:
    name = s['strategy_name']
    model = s.get('model', '')
    print(f'{name}-{model}' if model else name)
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

if [ ! -f "${SCRIPT_DIR}/make_profile.py" ]; then
    log "❌ 缺少 make_profile.py（应与 replay.sh 同目录）"
    exit 1
fi

# ===== 执行回测 =====
# 每个快照是独立的项目副本，各自 cd 进去跑一次 batch_runner。
# 单快照内的多个 (策略, 代币) 由 profile.max_workers 并发，
# 快照之间串行 —— 每个快照有自己的 config/，并行会互相踩生成的 profile。
#
# 注意: 刻意不用 batch_runner --daemon —— 该模式重建子命令时会丢掉
# --run/--start/--end/--config，等于跑成空清单。需要后台请在外层 nohup 本脚本。
SUCCESS_COUNT=0
FAIL_COUNT=0
GENERATED_PROFILES=()

cleanup_profiles() {
    if [ "$KEEP_PROFILE" = false ]; then
        for pf in ${GENERATED_PROFILES[@]+"${GENERATED_PROFILES[@]}"}; do
            rm -f "$pf"
        done
    fi
}
trap cleanup_profiles EXIT

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

    SNAPSHOT_PROJECT_DIR="${SNAPSHOT_DAY_DIR}/${snapshot}"
    if [ ! -d "${SNAPSHOT_PROJECT_DIR}/backtest" ]; then
        log "⚠ ${snapshot}: 快照不含 backtest/ 模块，跳过"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        continue
    fi
    SNAPSHOT_ABS="$(cd "$SNAPSHOT_PROJECT_DIR" && pwd)"

    # 回测输出目录（在快照之外，避免污染快照）
    OUTPUT_DIR="${REPLAY_OUTPUTS_DIR}/${REPLAY_DATE}/${snapshot}"
    mkdir -p "$OUTPUT_DIR"

    # ===== 构建运行清单 =====
    # 策略参数来源: 快照自带的 strategies/<name>/overrides/<SYMBOL>.yaml
    # 该目录下的文件名即当天实盘跑的 symbol 全集。
    SNAPSHOT_STRATEGY_DIR="${SNAPSHOT_ABS}/strategies/${strategy_name}"
    OVERRIDES_DIR="${SNAPSHOT_STRATEGY_DIR}/overrides"

    if [ ! -d "$OVERRIDES_DIR" ]; then
        log "⚠ ${snapshot}: 缺少 strategies/${strategy_name}/overrides/，跳过"
        log "    说明: v3.7 策略参数唯一来源是 overrides/<SYMBOL>.yaml"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        continue
    fi

    # 若分析阶段跑过，剔除它判定为"无K线数据"的 symbol —— 这些必然回测失败，
    # 提交给 batch_runner 只会把整批的退出码染红，掩盖真正的异常。
    EXCLUDED_SYMBOLS=""
    if [ -n "$ANALYSIS_JSON" ] && [ -f "$ANALYSIS_JSON" ]; then
        EXCLUDED_SYMBOLS=$($PYTHON_CMD -c "
import json
with open('$ANALYSIS_JSON') as f:
    data = json.load(f)
for s in data.get('strategies', []):
    if s['strategy_name'] != '$strategy_name' or s.get('model', '') != '$model':
        continue
    bad = [
        sym for sym, st in (s.get('kline_data') or {}).items()
        if not st.get('csv_exists')
    ]
    print(','.join(sorted(bad)))
    break
" 2>/dev/null || true)
    fi

    RUN_LIST=""
    PAIR_COUNT=0
    NO_DATA_SYMBOLS=()
    for override_file in "$OVERRIDES_DIR"/*.yaml; do
        [ -f "$override_file" ] || continue
        sym="$(basename "$override_file" .yaml)"
        [[ "$sym" == .* ]] && continue
        if [ -n "$EXCLUDED_SYMBOLS" ] && [[ ",${EXCLUDED_SYMBOLS}," == *",${sym},"* ]]; then
            NO_DATA_SYMBOLS+=("$sym")
            continue
        fi
        if [ -z "$RUN_LIST" ]; then
            RUN_LIST="${strategy_name}:${sym}"
        else
            RUN_LIST="${RUN_LIST},${strategy_name}:${sym}"
        fi
        PAIR_COUNT=$((PAIR_COUNT + 1))
    done

    if [ ${#NO_DATA_SYMBOLS[@]} -gt 0 ]; then
        log "    ⚠ 跳过 ${#NO_DATA_SYMBOLS[@]} 个无K线数据的标的: ${NO_DATA_SYMBOLS[*]}"
    fi

    if [ -z "$RUN_LIST" ]; then
        log "⚠ ${snapshot}: 无可回测组合（overrides 为空或全部缺K线数据），跳过"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        continue
    fi

    log "    运行清单 (${PAIR_COUNT} 组合): ${RUN_LIST}"

    # ===== 在快照内生成 run-profile =====
    # data_dir 由 make_profile.py 照抄该快照 settings.yaml 的 csv_dir
    # （模板启动时强校验一致性）。快照的 data/ 被 rsync 排除时，
    # 需确保 csv_dir 指向的路径在本机可解析。
    PROFILE_PATH="${SNAPSHOT_ABS}/config/${PROFILE_NAME}.yaml"
    if [ ! -f "$PROFILE_PATH" ]; then
        GENERATED_PROFILES+=("$PROFILE_PATH")
    fi

    if ! $PYTHON_CMD "${SCRIPT_DIR}/make_profile.py" \
        --project-dir "$SNAPSHOT_ABS" \
        --name "$PROFILE_NAME" \
        --output-dir "$OUTPUT_DIR" \
        --cash "$BT_CASH" \
        --commission "$BT_COMMISSION" \
        --max-workers "$PARALLEL" \
        2>&1 | tee -a "$LOG_FILE"; then
        log "❌ ${snapshot}: 生成 run-profile 失败"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        continue
    fi

    # ===== 执行 =====
    BATCH_OK=true
    (cd "$SNAPSHOT_ABS" && $PYTHON_CMD -m backtest.batch_runner \
        --run "$RUN_LIST" \
        --start "$BT_START" \
        --end "$BT_END" \
        --profile "$PROFILE_NAME" \
        --log-level INFO) 2>&1 | tee -a "$LOG_FILE" || BATCH_OK=false

    # 检查回测结果（产物: {output_dir}/{strategy}/{date}/{time}/{symbol}/）
    RESULT_COUNT=$(find "$OUTPUT_DIR" -name "backtest_result.json" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$RESULT_COUNT" -gt 0 ]; then
        if [ "$BATCH_OK" = true ] && [ "$RESULT_COUNT" -ge "$PAIR_COUNT" ]; then
            log "✅ ${snapshot}: 回测完成 (${RESULT_COUNT}/${PAIR_COUNT} 个结果)"
            SUCCESS_COUNT=$((SUCCESS_COUNT + 1))
        else
            log "⚠ ${snapshot}: 部分完成 (${RESULT_COUNT}/${PAIR_COUNT} 个结果)"
            FAIL_COUNT=$((FAIL_COUNT + 1))
        fi
    else
        log "❌ ${snapshot}: 回测未产出结果"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi

    # ===== 生成该快照的对比报告 =====
    if [ -f "${SCRIPT_DIR}/generate_report.py" ]; then
        $PYTHON_CMD "${SCRIPT_DIR}/generate_report.py" \
            --output-dir "$OUTPUT_DIR" \
            --start "$BT_START" \
            --end "$BT_END" \
            --report-name "replay-report-${snapshot}.md" \
            --title "Replay 回测报告 — ${snapshot} (snapshot ${REPLAY_DATE})" \
            >/dev/null 2>&1 || log "⚠ ${snapshot}: 报告生成失败"
    fi
done

# ===== 汇总 =====
log "END replay.sh: ${#STRATEGY_SNAPSHOTS[@]} strategies, ${SUCCESS_COUNT} success, ${FAIL_COUNT} failed"

if [ $FAIL_COUNT -gt 0 ]; then
    exit 1
fi
