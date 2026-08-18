#!/bin/bash
#
# run_live_batch.sh - 批量实盘一键启动（多策略 × 多代币）
#
# 用法:
#   ./scripts/run_live_batch.sh --strategies sar_snt3_v3 --symbols BTCUSDT
#   ./scripts/run_live_batch.sh --strategies a,b --symbols BTCUSDT,ETHUSDT --daemon
#   ./scripts/run_live_batch.sh --help
#
# 停止:
#   ./stop.sh        （本脚本复用根目录同一个 PID 文件，故 stop.sh 通用）
#
# 说明:
#   本脚本只做「策略 × 代币」展开 + overrides 预检，随后转调
#   run_strategies_manager.py --run。每个策略独立进程由 manager 管理，
#   shell 不参与进程编排。
#
#   与根目录 start.sh 的分工：
#     start.sh            读 config/strategies.yaml 登记表启动（长期清单）
#     run_live_batch.sh   命令行指定策略×代币启动（临时组合，覆盖登记表）
#

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# shellcheck source=scripts/lib/expand_pairs.sh
source "$SCRIPT_DIR/lib/expand_pairs.sh"

# 必须与 start.sh:18 / stop.sh:19 保持一致。
# 若此处另起一个文件名，stop.sh 将读不到 PID，只能靠 pkill 兜底，
# 极易留下孤儿策略子进程（run_strategy.py）继续下单。
PID_FILE="cta_strategy_core.pid"

STRATEGIES=""
SYMBOLS=""
REGISTRY=""
CONFIG="config/settings.yaml"
LOG_LEVEL="INFO"
DAEMON=0
ASSUME_YES=0

usage() {
    cat <<'EOF'
用法:
  A) 登记表模式（多策略各配不同代币，推荐）
     ./scripts/run_live_batch.sh --registry my_live.yaml

  B) 笛卡尔积模式（单一组合快速启动）
     ./scripts/run_live_batch.sh --strategies NAMES --symbols SYMBOLS

登记表模式（--registry）:
  每个策略独立声明自己的代币与运行模式，格式与 config/strategies.yaml 一致，
  实盘/回测共用同一份清单：

    strategies:
      sar_snt3_v3:
        trading_mode: "paper_trading"
        symbols: [BTCUSDT, ETHUSDT]
      obv_atr_v2:
        trading_mode: "live"
        symbols: [SOLUSDT, XRPUSDT]

  也可给单个币指定不同模式（symbol 级覆盖策略级）:
    symbols:
      - name: BTCUSDT
        trading_mode: "paper_trading"
      - name: ETHUSDT
        trading_mode: "live"

参数:
  --registry PATH      登记表路径（与 --strategies/--symbols 互斥）
  --strategies NAMES   策略名列表，逗号分隔（不是 name:symbol）
  --symbols SYMBOLS    代币列表，逗号分隔，自动转大写
  --config PATH        系统配置文件（默认 config/settings.yaml）
  --log-level LEVEL    DEBUG/INFO/WARNING/ERROR（默认 INFO）
  --dev                开发模式，等价 --log-level DEBUG
  --daemon             后台运行（nohup），默认前台运行便于观察
  --yes, -y            跳过确认，用于非交互场景
  --help, -h           显示本帮助

运行模式（重要）:
  **未声明 trading_mode 时默认为 live，即使用真实资金下单。**
  两种模式的 trading_mode 来源不同，与 Python 侧一致：
    --registry           取自登记表（symbol 级覆盖策略级）
    --strategies/--symbols  取自 strategies/<name>/overrides/<SYMBOL>.yaml
  启动前脚本会逐个解析并展示，含 live 实例时需手动输入 live 确认。

停止:
  ./stop.sh            本脚本与 start.sh 共用 PID 文件，stop.sh 通用

示例:
  # 登记表，多策略各配不同币
  ./scripts/run_live_batch.sh --registry my_live.yaml --daemon

  # 前台单策略两个币（Ctrl-C 停止）
  ./scripts/run_live_batch.sh --strategies sar_snt3_v3 --symbols BTCUSDT,ETHUSDT
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
        --symbols)
            [[ $# -ge 2 ]] || { echo "错误：--symbols 缺少值" >&2; exit 1; }
            SYMBOLS="$2"
            shift 2
            ;;
        --config)
            [[ $# -ge 2 ]] || { echo "错误：--config 缺少值" >&2; exit 1; }
            CONFIG="$2"
            shift 2
            ;;
        --registry)
            [[ $# -ge 2 ]] || { echo "错误：--registry 缺少值" >&2; exit 1; }
            REGISTRY="$2"
            shift 2
            ;;
        --log-level)
            [[ $# -ge 2 ]] || { echo "错误：--log-level 缺少值" >&2; exit 1; }
            LOG_LEVEL="$2"
            shift 2
            ;;
        --dev)
            LOG_LEVEL="DEBUG"
            shift
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
if [[ -n "$REGISTRY" && ( -n "$STRATEGIES" || -n "$SYMBOLS" ) ]]; then
    echo "错误：--registry 与 --strategies/--symbols 互斥，请择一使用" >&2
    echo "      登记表模式用 --registry，笛卡尔积模式用 --strategies + --symbols" >&2
    exit 1
fi
if [[ -z "$REGISTRY" ]]; then
    [[ -n "$STRATEGIES" ]] || { echo "错误：缺少 --registry 或 --strategies，使用 --help 查看用法" >&2; exit 1; }
    [[ -n "$SYMBOLS" ]] || { echo "错误：缺少 --symbols，使用 --help 查看用法" >&2; exit 1; }
fi

if ! command -v python3 &>/dev/null; then
    echo "错误：未找到 python3" >&2
    exit 1
fi

if [[ ! -f "$CONFIG" ]]; then
    echo "错误：系统配置文件不存在: $CONFIG" >&2
    exit 1
fi

PYTHON_CMD="python3"
if [[ -d ".venv" ]]; then
    echo "检测到 .venv，使用虚拟环境..."
    PYTHON_CMD=".venv/bin/python3"
fi

echo "======================================"
echo "批量实盘启动"
echo "======================================"

# MODE_LINES: 每行 "name:symbol<TAB>trading_mode"，两种模式共用下游的警示逻辑。
#
# 两条路径的 trading_mode 来源刻意不同，与 Python 侧保持一致：
#   登记表模式   → 登记表声明（strategies_loader.py:333-340，symbol 级覆盖策略级）
#   笛卡尔积模式 → 读 strategies/<name>/overrides/<symbol>.yaml
# 若在此统一成一种，会与实际运行时读到的值不符，等于骗人。
if [[ -n "$REGISTRY" ]]; then
    [[ -f "$REGISTRY" ]] || { echo "错误：登记表文件不存在: $REGISTRY" >&2; exit 1; }
    MODE_LINES="$(describe_registry "$REGISTRY" "$REPO_ROOT" "$PYTHON_CMD")" || {
        echo "错误：登记表解析失败: $REGISTRY" >&2
        exit 1
    }
    [[ -n "$MODE_LINES" ]] || { echo "错误：登记表中无启用的策略实例: $REGISTRY" >&2; exit 1; }
    PAIRS="$(printf '%s\n' "$MODE_LINES" | cut -f1 | paste -sd, -)"
    TASK_COUNT="$(count_pairs "$PAIRS")"
    echo "  模式: 登记表 $REGISTRY"
else
    PAIRS="$(expand_pairs "$STRATEGIES" "$SYMBOLS")" || exit 1
    TASK_COUNT="$(count_pairs "$PAIRS")"
    MODE_LINES=""
    IFS=',' read -r -a _pairs_arr <<< "$PAIRS"
    for p in "${_pairs_arr[@]}"; do
        _n="${p%%:*}"; _s="${p#*:}"
        _m="$(resolve_trading_mode "$_n" "$_s" "$REPO_ROOT" "$PYTHON_CMD")"
        MODE_LINES+="${p}	${_m}"$'\n'
    done
    MODE_LINES="${MODE_LINES%$'\n'}"
    echo "  模式: 笛卡尔积"
    echo "  策略: $STRATEGIES"
    echo "  代币: $SYMBOLS"
fi

echo "  实例数: $TASK_COUNT"
echo "  系统配置: $CONFIG"
echo "  日志级别: $LOG_LEVEL"
echo ""

precheck_overrides "$PAIRS" "$REPO_ROOT" || exit 1

# 展示每个实例的运行模式。
# trading_mode 缺省值就是 live（run_strategies_manager.py:252、
# strategies_loader.py DEFAULT_CONFIG），而配置里普遍不写这一项 ——
# 批量展开一条命令就可能把十几个标的拉进实盘下真单，屏幕上却看不出来。
echo "运行模式:"
LIVE_PAIRS=()
while IFS=$'\t' read -r p m; do
    [[ -z "$p" ]] && continue
    if [[ "$m" == "live" ]]; then
        echo "  $p → $m  ⚠️  真实下单"
        LIVE_PAIRS+=("$p")
    else
        echo "  $p → $m"
    fi
done <<< "$MODE_LINES"
echo ""

if [[ ${#LIVE_PAIRS[@]} -gt 0 ]]; then
    echo "⚠️  警告：${#LIVE_PAIRS[@]}/${TASK_COUNT} 个实例为 live 模式，将使用真实资金下单。"
    echo "   （未声明 trading_mode 时默认即 live）"
    if [[ -n "$REGISTRY" ]]; then
        echo "   如需模拟盘，在 $REGISTRY 中设置 trading_mode: paper_trading"
    else
        echo "   如需模拟盘，在对应 overrides 中设置 trading_mode: paper_trading"
    fi
    echo ""
    if [[ $ASSUME_YES -eq 0 ]]; then
        read -r -p "确认以实盘模式启动? 输入 live 继续: " reply
        [[ "$reply" == "live" ]] || { echo "已取消"; exit 1; }
    else
        echo "   --yes 已指定，跳过实盘确认"
    fi
    echo ""
fi

# 实盘要下真单，进程数确认阈值比回测更低
if [[ $ASSUME_YES -eq 0 && $TASK_COUNT -gt 3 ]]; then
    read -r -p "将启动 $TASK_COUNT 个实盘策略实例，继续? [y/N] " reply
    [[ "$reply" == "y" || "$reply" == "Y" ]] || { echo "已取消"; exit 1; }
fi

# 停止已有进程：沿用 start.sh:81-98 的逻辑。
# 不这样做会出现两个 manager 同时跑同一策略、重复下单。
if [[ -f "$PID_FILE" ]]; then
    OLD_PID=$(cat "$PID_FILE")
    if kill -0 "$OLD_PID" 2>/dev/null; then
        echo "正在停止已有进程 (PID: $OLD_PID)..."
        kill -TERM "$OLD_PID" 2>/dev/null || true
        sleep 2
        if kill -0 "$OLD_PID" 2>/dev/null; then
            kill -9 "$OLD_PID" 2>/dev/null || true
            sleep 1
        fi
    fi
    rm -f "$PID_FILE"
fi
pkill -9 -f "python.*run_strategies_manager.py" 2>/dev/null || true
sleep 1

mkdir -p "$REPO_ROOT/logs"

# 登记表模式把登记表本身交给 manager（--strategies 收的是文件路径），
# 而非展开后的 --run 清单：manager 走 --run 时会改从 overrides 读 trading_mode，
# 与上面按登记表展示的模式不一致 —— 那等于屏幕显示 paper、实际跑 live。
if [[ -n "$REGISTRY" ]]; then
    CMD=("$PYTHON_CMD" -u run_strategies_manager.py
         --config "$CONFIG" --strategies "$REGISTRY" --log-level "$LOG_LEVEL")
else
    CMD=("$PYTHON_CMD" -u run_strategies_manager.py
         --config "$CONFIG" --run "$PAIRS" --log-level "$LOG_LEVEL")
fi

echo "执行: ${CMD[*]}"
echo ""

if [[ $DAEMON -eq 1 ]]; then
    # 日志由 Python 的 DailyDirectoryFileHandler 管理，stdout 丢弃（对齐 start.sh:141）
    PYTHONPATH="$REPO_ROOT" nohup "${CMD[@]}" >/dev/null 2>&1 &
    CORE_PID=$!
    echo "   PID: $CORE_PID"
    sleep 2

    if kill -0 "$CORE_PID" 2>/dev/null; then
        echo "   ✓ 启动成功"
        echo "$CORE_PID" > "$PID_FILE"
    else
        echo "   ✗ 启动失败" >&2
        LATEST_LOG=$(ls -td "$REPO_ROOT/logs"/*/ 2>/dev/null | head -1)
        if [[ -n "$LATEST_LOG" ]]; then
            echo "   最新日志:" >&2
            cat "${LATEST_LOG}strategies_runtime.log" 2>/dev/null || true
        fi
        exit 1
    fi

    echo ""
    echo "查看日志:"
    echo "  tail -f logs/\$(date -u +%Y-%m-%d)/strategies_runtime.log"
    echo "  tail -f logs/strategies/\$(date -u +%Y-%m-%d)/*.log"
    echo ""
    echo "停止服务:"
    echo "  ./stop.sh"
else
    # 前台运行。用 exec 让 Python 顶替本 shell 进程，而非"后台起 Python + wait"：
    #
    # 1. exec 后 $$ 即 manager 的真实 PID，写进 PID 文件后 stop.sh 的 SIGTERM
    #    直达 manager，走它自己的优雅停止路径（会一并停掉策略子进程）。
    #    若写 wrapper shell 的 PID，杀壳不会连带停 Python，会留下继续下单的孤儿进程。
    # 2. Ctrl-C 直接送到 Python，无需 trap 转发。此前用 `... & wait` 的写法在
    #    实测中 SIGINT 不生效 —— bash 执行 wait 内建命令期间不响应 trap，
    #    manager 与策略子进程都停不下来。exec 没有这个中间层，故无此问题。
    #
    # 代价：exec 后无法再执行清理，PID 文件由 stop.sh 负责删除（它本就会 rm）。
    echo "前台运行中，Ctrl-C 停止（或另开终端执行 ./stop.sh）"
    echo ""
    echo $$ > "$PID_FILE"
    PYTHONPATH="$REPO_ROOT" exec "${CMD[@]}"
fi
