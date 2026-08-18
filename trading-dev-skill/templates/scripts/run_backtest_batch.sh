#!/bin/bash
#
# run_backtest_batch.sh - 批量回测一键执行（多策略 × 多代币）
#
# 用法:
#   ./scripts/run_backtest_batch.sh --strategies sar_snt3_v3 --symbols BTCUSDT --start 20260610
#   ./scripts/run_backtest_batch.sh --strategies a,b --symbols BTCUSDT,ETHUSDT --start 20260610 --end 20260708
#   ./scripts/run_backtest_batch.sh --help
#
# 说明:
#   本脚本只做「策略 × 代币」笛卡尔积展开 + overrides 预检，随后转调
#   backtest.batch_runner 执行。并发、结果汇总、退出码判定全部由 Python
#   负责，shell 不重复实现（否则与 Python 侧形成两套执行路径）。
#
# 注意 --strategies 的语义差异:
#   本脚本  : 纯策略名列表          sar_snt3_v3,obv_atr_v2
#   Python 侧: name:symbol 清单     sar_snt3_v3:BTCUSDT
#   本脚本负责把前者展开成后者。
#

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# shellcheck source=scripts/lib/expand_pairs.sh
source "$SCRIPT_DIR/lib/expand_pairs.sh"

STRATEGIES=""
SYMBOLS=""
CONFIG=""
START=""
END=""
PROFILE=""
LOG_LEVEL=""
DAEMON=0
ASSUME_YES=0

usage() {
    cat <<'EOF'
用法:
  A) 登记表模式（多策略各配不同代币，推荐）
     ./scripts/run_backtest_batch.sh --config my_backtest.yaml --start DATE

  B) 笛卡尔积模式（单一组合快速试跑）
     ./scripts/run_backtest_batch.sh --strategies NAMES --symbols SYMBOLS --start DATE

登记表模式（--config）:
  每个策略独立声明自己的代币，适合"策略 A 跑 2 个币、策略 B 跑 5 个币"。
  格式与 config/strategies.yaml 一致，实盘/回测共用同一份清单：

    strategies:
      sar_snt3_v3:
        trading_mode: "paper_trading"
        symbols: [BTCUSDT, ETHUSDT]
      obv_atr_v2:
        trading_mode: "paper_trading"
        symbols: [SOLUSDT, XRPUSDT, DOGEUSDT]

  symbols 也支持对象格式，给单个币指定不同模式:
    symbols:
      - name: BTCUSDT
        trading_mode: "paper_trading"
      - name: ETHUSDT
        trading_mode: "live"

笛卡尔积模式（--strategies + --symbols）:
  两个列表交叉组合（2 策略 × 3 币 = 6 个任务），适合同一批币试多个策略。
  --strategies 只写策略名（sar_snt3_v3），不是 name:symbol —— 后者由脚本拼出。

参数:
  --config PATH        登记表路径（与 --strategies/--symbols 互斥）
  --strategies NAMES   策略名列表，逗号分隔
  --symbols SYMBOLS    代币列表，逗号分隔，自动转大写
  --start DATE         回测开始日期 YYYYMMDD（必需）
  --end DATE           回测结束日期 YYYYMMDD（默认取 profile 配置）
  --profile NAME       run-profile 名（默认 backtest，读 config/<name>.yaml）
  --log-level LEVEL    DEBUG/INFO/WARNING/ERROR，透传给每个回测子进程
  --daemon             后台运行
  --yes, -y            跳过任务数确认，用于 CI/crontab 非交互场景
  --help, -h           显示本帮助

共同行为:
  展开后校验每个组合的 strategies/<name>/overrides/<SYMBOL>.yaml 是否存在，
  任一缺失即拒绝启动（下游对显式清单缺配置是直接报错，不会跳过）。

示例:
  # 登记表：多策略各配不同币
  ./scripts/run_backtest_batch.sh --config my_backtest.yaml --start 20260610 --end 20260708

  # 笛卡尔积：一个策略两个币
  ./scripts/run_backtest_batch.sh --strategies sar_snt3_v3 --symbols BTCUSDT,ETHUSDT --start 20260610

  # 非交互（CI）
  ./scripts/run_backtest_batch.sh --config my_backtest.yaml --start 20260610 --yes
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --help|-h)
            usage
            exit 0
            ;;
        --strategies)
            [[ $# -ge 2 ]] || { echo "错误：--strategies 缺少值" >&2; exit 1; }
            STRATEGIES="$2"
            shift 2
            ;;
        --config)
            [[ $# -ge 2 ]] || { echo "错误：--config 缺少值" >&2; exit 1; }
            CONFIG="$2"
            shift 2
            ;;
        --symbols)
            [[ $# -ge 2 ]] || { echo "错误：--symbols 缺少值" >&2; exit 1; }
            SYMBOLS="$2"
            shift 2
            ;;
        --start)
            [[ $# -ge 2 ]] || { echo "错误：--start 缺少值" >&2; exit 1; }
            START="$2"
            shift 2
            ;;
        --end)
            [[ $# -ge 2 ]] || { echo "错误：--end 缺少值" >&2; exit 1; }
            END="$2"
            shift 2
            ;;
        --profile)
            [[ $# -ge 2 ]] || { echo "错误：--profile 缺少值" >&2; exit 1; }
            PROFILE="$2"
            shift 2
            ;;
        --log-level)
            [[ $# -ge 2 ]] || { echo "错误：--log-level 缺少值" >&2; exit 1; }
            LOG_LEVEL="$2"
            shift 2
            ;;
        --daemon)
            DAEMON=1
            shift
            ;;
        --yes|-y)
            ASSUME_YES=1
            shift
            ;;
        *)
            echo "未知参数: $1，使用 --help 查看用法" >&2
            exit 1
            ;;
    esac
done

# 两种模式互斥：同时给会产生"哪个说了算"的歧义，宁可报错
if [[ -n "$CONFIG" && ( -n "$STRATEGIES" || -n "$SYMBOLS" ) ]]; then
    echo "错误：--config 与 --strategies/--symbols 互斥，请择一使用" >&2
    echo "      登记表模式用 --config，笛卡尔积模式用 --strategies + --symbols" >&2
    exit 1
fi
if [[ -z "$CONFIG" ]]; then
    [[ -n "$STRATEGIES" ]] || { echo "错误：缺少 --config 或 --strategies，使用 --help 查看用法" >&2; exit 1; }
    [[ -n "$SYMBOLS" ]] || { echo "错误：缺少 --symbols，使用 --help 查看用法" >&2; exit 1; }
fi
[[ -n "$START" ]] || { echo "错误：缺少 --start，使用 --help 查看用法" >&2; exit 1; }

PYTHON_CMD="python3"
if [[ -d ".venv" ]]; then
    PYTHON_CMD=".venv/bin/python3"
fi

echo "======================================"
echo "批量回测"
echo "======================================"

if [[ -n "$CONFIG" ]]; then
    [[ -f "$CONFIG" ]] || { echo "错误：登记表文件不存在: $CONFIG" >&2; exit 1; }
    # 登记表交给 StrategiesLoader 展开：symbols 两种格式、symbol 级 trading_mode
    # 覆盖、缺省回退等优先级只有那一处实现，shell 不重复解析 YAML
    PAIRS="$(registry_pairs "$CONFIG" "$REPO_ROOT" "$PYTHON_CMD")" || {
        echo "错误：登记表解析失败: $CONFIG" >&2
        exit 1
    }
    [[ -n "$PAIRS" ]] || { echo "错误：登记表中无启用的策略实例: $CONFIG" >&2; exit 1; }
    TASK_COUNT="$(count_pairs "$PAIRS")"
    echo "  模式: 登记表 $CONFIG"
    echo "  任务数: $TASK_COUNT"
    echo "  清单:"
    describe_registry "$CONFIG" "$REPO_ROOT" "$PYTHON_CMD" | while IFS=$'\t' read -r p m; do
        echo "    $p"
    done
else
    PAIRS="$(expand_pairs "$STRATEGIES" "$SYMBOLS")" || exit 1
    TASK_COUNT="$(count_pairs "$PAIRS")"
    echo "  模式: 笛卡尔积"
    echo "  策略: $STRATEGIES"
    echo "  代币: $SYMBOLS"
    echo "  任务数: $TASK_COUNT"
fi
echo "  区间: $START ~ ${END:-<profile 默认>}"
echo ""

precheck_overrides "$PAIRS" "$REPO_ROOT" || exit 1

# 任务数较多时确认，避免误输入 14 个币后才发现跑了几十个回测
if [[ $ASSUME_YES -eq 0 && $TASK_COUNT -gt 6 ]]; then
    read -r -p "共 $TASK_COUNT 个回测任务，继续? [y/N] " reply
    [[ "$reply" == "y" || "$reply" == "Y" ]] || { echo "已取消"; exit 1; }
fi

# 统一用 --run 传展开后的清单：无论哪种模式，下游看到的都是同一种入参，
# 避免登记表模式走 --config、笛卡尔积走 --run 两条不同的下游路径。
CMD=("$PYTHON_CMD" -m backtest.batch_runner --run "$PAIRS" --start "$START")
[[ -n "$END" ]] && CMD+=(--end "$END")
[[ -n "$PROFILE" ]] && CMD+=(--profile "$PROFILE")
[[ -n "$LOG_LEVEL" ]] && CMD+=(--log-level "$LOG_LEVEL")
[[ $DAEMON -eq 1 ]] && CMD+=(--daemon)

echo "执行: ${CMD[*]}"
echo ""

# exec 移交进程：batch_runner 的退出码即本脚本退出码，
# 失败不能被 shell 吞掉（crontab 依赖退出码判定）
PYTHONPATH="$REPO_ROOT" exec "${CMD[@]}"
