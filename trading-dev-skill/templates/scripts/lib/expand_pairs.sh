#!/bin/bash
#
# lib/expand_pairs.sh - 策略 × 代币 笛卡尔积展开与前置校验
#
# 被 scripts/run_backtest_batch.sh 与 scripts/run_live_batch.sh source。
#
# 设计约束：本文件只做参数展开与校验，不执行回测/实盘。执行一律下沉到
# Python（backtest.batch_runner / run_strategies_manager.py），避免 shell
# 里出现第二套并发、汇总、退出码判定 —— 那会与 Python 侧形成配置分叉。
#
# 展开的必要性：parse_explicit_strategies()（run_strategies_manager.py:107）
# 被三个入口共用，但只解析格式不做组合展开，所以 2 策略 × 5 币今天得手写
# 10 个 name:symbol 对。本文件补的就是这一层。
#

# 拆分逗号分隔串，去空白、丢空项，每行输出一个元素。
# 空白全部删除（而非仅首尾）：策略名与代币都不含内部空格，宽松处理可容忍
# "a, b" 这类手输格式。
_split_csv() {
    local csv="$1" item
    local -a arr=()
    IFS=',' read -r -a arr <<< "$csv"
    for item in "${arr[@]}"; do
        item="$(printf '%s' "$item" | tr -d '[:space:]')"
        [[ -n "$item" ]] && printf '%s\n' "$item"
    done
    return 0
}

# expand_pairs <策略CSV> <代币CSV>
#
# 输出逗号分隔的 name:symbol 清单，可直接喂给下游 --run。
# 代币统一转大写，对齐 parse_explicit_strategies:136 的 symbol.upper()，
# 避免同一标的因大小写产生两份任务与两份输出目录。
# 重复组合去重：重复项会让同一回测跑两遍并覆盖输出，属纯浪费。
expand_pairs() {
    local names_csv="$1" symbols_csv="$2"
    local -a names=() symbols=()
    mapfile -t names < <(_split_csv "$names_csv")
    mapfile -t symbols < <(_split_csv "$symbols_csv")

    if [[ ${#names[@]} -eq 0 ]]; then
        echo "错误：策略列表为空" >&2
        return 1
    fi
    if [[ ${#symbols[@]} -eq 0 ]]; then
        echo "错误：代币列表为空" >&2
        return 1
    fi

    local -a out=()
    local -A seen=()
    local n s pair
    for n in "${names[@]}"; do
        for s in "${symbols[@]}"; do
            s="$(printf '%s' "$s" | tr '[:lower:]' '[:upper:]')"
            pair="${n}:${s}"
            if [[ -z "${seen[$pair]:-}" ]]; then
                seen[$pair]=1
                out+=("$pair")
            fi
        done
    done

    local IFS=','
    printf '%s\n' "${out[*]}"
    return 0
}

# count_pairs <清单CSV> —— 任务数，用于展开后向用户交代规模
count_pairs() {
    local pairs_csv="$1"
    _split_csv "$pairs_csv" | wc -l | tr -d '[:space:]'
    return 0
}

# precheck_overrides <清单CSV> [仓库根目录]
#
# 校验每个组合的 strategies/<name>/overrides/<SYMBOL>.yaml 是否存在。
#
# 为什么必须前置校验：显式运行清单（--run）缺 overrides 时下游是**直接报错**
# 而非跳过（batch_runner.py:78-88 的注释说明了这个刻意的差异 —— 既然点名
# 指定，静默跳过等于骗人）。笛卡尔积很容易生成不存在的组合（如 14 个币的
# overrides 只属于某一个策略），若不拦截，整批任务会在启动后才崩，且已启动
# 的部分留下"部分成功"的残局。
precheck_overrides() {
    local pairs_csv="$1"
    local repo_root="${2:-.}"
    local -a pairs=()
    mapfile -t pairs < <(_split_csv "$pairs_csv")

    local -a missing=()
    local p name symbol path
    for p in "${pairs[@]}"; do
        name="${p%%:*}"
        symbol="${p#*:}"
        path="${repo_root}/strategies/${name}/overrides/${symbol}.yaml"
        [[ -f "$path" ]] || missing+=("${name}:${symbol} → ${path}")
    done

    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "错误：${#missing[@]}/${#pairs[@]} 个组合缺少 overrides 配置，已拒绝启动：" >&2
        for path in "${missing[@]}"; do
            echo "  缺失 $path" >&2
        done
        echo "" >&2
        echo "下游对显式清单缺配置是直接报错（不跳过），故在此提前拦截，" >&2
        echo "避免整批任务启动后失败或留下部分成功的残局。" >&2
        return 1
    fi
    return 0
}

# describe_registry <登记表路径> [仓库根目录] [python 命令]
#
# 逐行输出 "name:symbol<TAB>trading_mode"，供调用方展示与统计。
#
# 为什么复用 StrategiesLoader 而不在 shell 里解析 YAML：登记表支持
# symbols 字符串数组与对象数组两种格式、symbol 级 trading_mode 覆盖策略级、
# 缺省回退 live。这套优先级只有一处实现（strategies_loader.py:333-340），
# shell 再写一遍必然走偏 —— 那正是配置分叉。
#
# 注意与 overrides 路径的差异：登记表模式下 trading_mode 由登记表声明，
# 不读 strategies/<name>/overrides/<symbol>.yaml 的同名字段。
describe_registry() {
    local config="$1"
    local repo_root="${2:-.}"
    local py="${3:-python3}"

    PYTHONPATH="$repo_root" "$py" -c '
import sys
sys.path.insert(0, sys.argv[2])
from strategy_core.utils.strategies_loader import StrategiesLoader

loader = StrategiesLoader(sys.argv[1]).load()
for inst in loader.filter(enabled_only=True):
    print(f"{inst.name}:{inst.symbol}\t{inst.trading_mode}")
' "$config" "$repo_root"
}

# registry_pairs <登记表路径> [仓库根目录] [python 命令]
#
# 输出逗号分隔的 name:symbol 清单（仅 enabled 实例）。
registry_pairs() {
    local out
    out="$(describe_registry "$1" "${2:-.}" "${3:-python3}")" || return 1
    printf '%s\n' "$out" | cut -f1 | paste -sd, -
    return 0
}

#
# 读取 overrides 里的 trading_mode，未声明则回显 live。
#
# 为什么必须显式解析：trading_mode 缺省值就是 "live"
# （run_strategies_manager.py:252、factory_client.py:394），而 overrides 里
# 普遍不写这一项。批量脚本做笛卡尔积展开时，一条命令就可能把十几个标的
# 拉进实盘下真单，且屏幕上看不出来。故展开后必须把解析结果摆到用户面前。
resolve_trading_mode() {
    local name="$1" symbol="$2"
    local repo_root="${3:-.}"
    local py="${4:-python3}"
    local path="${repo_root}/strategies/${name}/overrides/${symbol}.yaml"

    "$py" -c '
import sys, yaml
path, name = sys.argv[1], sys.argv[2]
try:
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
except Exception:
    print("unknown"); sys.exit(0)
sect = cfg.get(name) if isinstance(cfg.get(name), dict) else cfg
mode = (sect or {}).get("trading_mode")
# 缺省即 live，与 Python 侧默认值保持一致
print(mode if mode else "live")
' "$path" "$name" 2>/dev/null || echo "unknown"
    return 0
}

