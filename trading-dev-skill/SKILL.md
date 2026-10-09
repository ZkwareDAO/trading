---
name: trading-dev
description: CTA 策略开发全生命周期 skill。支持交互/全自动/单步三种模式。一句话输入策略逻辑 → 自动脚手架 → 策略编码 → 回测验证 → benchmark 输出。loop-engineering 跨 Phase 大闭环。
origin: trading
---

# Trading Dev — CTA 策略开发全生命周期

从项目脚手架 → 策略编码 → 回测验证 → benchmark 输出，一条链路闭环。

**支持三种模式**：全自动（一句话跑到底）/ 交互（逐步确认）/ 单步（只跑指定步骤）。

**核心行为：loop-engineering**。Phase 2（策略开发）和 Phase 3（回测验证）形成跨 Phase 大闭环——回测不达标时自动回到 Phase 2 修改策略逻辑，再跑 Phase 3，循环直到达标或达到最大轮次。

## When to Activate

- 用户执行 `/trading-dev`（无参数）-> **进入交互式引导**
- 用户执行 `/trading-dev new` — 创建新 CTA 策略项目（交互模式）
- 用户执行 `/trading-dev new --from <source>` — 从指定来源自动开发策略（全自动模式）
- 用户说"新建策略项目"、"创建交易项目"、"开发新策略"
- 用户执行 `/trading-dev scaffold` — 只创建脚手架
- 用户执行 `/trading-dev develop` — 只生成策略代码
- 用户执行 `/trading-dev backtest` — 只跑回测
- 用户已有策略项目，想执行回测验证

**首要原则：无参数或子命令不明确时，必须一步一步引导用户，不要报错让用户自己补命令。**

## Commands

| 命令 | 模式 | 说明 |
|------|------|------|
| `/trading-dev` | 引导 | 无参数 -> 进入交互式引导 |
| `/trading-dev new` | 交互 | 逐步确认策略信息、环境变量、每步执行 |
| `/trading-dev new --from <source>` | 全自动 | 从文件/目录/URL/描述提取策略信息，零交互跑到底 |
| `/trading-dev new <描述文本>` | 全自动 | 从自然语言提取策略信息，零交互跑到底 |
| `/trading-dev new --interactive --from <source>` | 半交互 | 自动解析策略信息，但每步前确认 |
| `/trading-dev scaffold` | 单步 | 只创建脚手架（Phase 1） |
| `/trading-dev develop` | 单步 | 只生成策略代码（Phase 2） |
| `/trading-dev backtest` | 单步 | 只跑回测验证（Phase 3） |
| `/trading-dev benchmark` | 单步 | 只输出 benchmark 报告（Phase 3 Step 5） |

### `--from` 支持的输入形态

| 输入形态 | 示例 | 解析策略 |
|----------|------|----------|
| 文件路径 | `--from /path/to/strategy_doc.md` | Read 文件，解析内容 |
| 策略目录 | `--from /path/to/example_ma_cross/` | 读已有策略代码，逆向提取 spec |
| URL | `--from https://...` | WebFetch 抓取 |
| 自然语言 | `/trading-dev new 开发一个 EMA 交叉策略，4h，BTCUSDT` | 从描述提取 |
| 省略 | `/trading-dev new` | 进入多轮对话收集策略信息 |

---

## Phase -1: 交互式引导（无参数时）

### 触发条件

| 条件 | 说明 |
|------|------|
| 无任何参数 | 用户只敲了 `/trading-dev` |

**不进入引导**（直接走原流程）：

- `/trading-dev new [参数]` / `scaffold` / `develop` / `backtest` / `benchmark`（子命令明确）
- 参数齐全的单步命令

### 引导核心原则

1. **缺啥补啥**：用户已经给的参数跳过不问，只问缺失项
2. **一步一问**：每次只问一个问题，给默认值 + 示例
3. **每步可改**：用户随时能修改前面给过的值
4. **不报错**：宁可多问一轮，也不要扔"参数不全"给用户
5. **引导完汇总**：参数收齐后输出执行计划让用户确认，确认后才进 Phase 0

### 引导顺序

```
Step 1: 问子命令（new / scaffold / develop / backtest / benchmark）
        -> 给默认：new
       ↓
Step 2: 问策略来源（new 子命令）
        -> 已有项目？-> 引导单步子命令（develop / backtest）
        -> 无项目？-> 问策略描述 / 文件路径 / URL / 已有策略目录
       ↓
Step 3: 汇总确认 -> 用户确认后进 Phase 0
```

### Step 1 话术模板：问子命令

```
🧭 交互式引导 - 第 1 步（共 3 步）：要执行什么操作？

  1. new        ← 新策略全流程（脚手架->编码->回测->benchmark）
  2. scaffold   ← 只创建脚手架
  3. develop    ← 只生成策略代码（需已有项目）
  4. backtest   ← 只跑回测验证（需已有项目）
  5. benchmark  ← 只输出 benchmark 报告（需已有项目）

请选择（输入编号或命令名）。默认：1（new）
```

### Step 2 话术模板：问策略来源（new 子命令）

```
🧭 交互式引导 - 第 2 步（共 3 步）：策略来源

请描述新策略（任选一种方式）：
  1. 直接描述   ← 一句话策略逻辑，如"EMA20/EMA60 交叉，4h，BTCUSDT"
  2. 文件路径   ← 如 --from /path/to/strategy_doc.md
  3. 已有策略   ← 如 --from /path/to/example_ma_cross/（逆向提取 spec）
  4. URL        ← 如 --from https://...

请输入（默认进入多轮对话逐步收集）：
```

**若用户选了 2/3/4 之一**：按 `--from <source>` 全自动模式执行。
**若用户选 1 或直接描述**：按自然语言提取执行。**若回车**：进交互模式多轮收集（Phase 0 Step 1）。

**单步子命令（develop/backtest/benchmark）时**：列出当前目录下候选项目（含 `strategy_core/` 的目录）供选择；无候选则提示先跑 `new`。

### Step 3 话术模板：汇总确认

```
📋 引导完成 - 执行计划确认

  操作:     new（全流程）
  模式:     交互 / 全自动
  策略来源: <描述或 --from 来源>

确认执行？
  > y / 回车   ← 进 Phase 0
  > n          ← 取消
  > 改 XX      ← 修改某项
```

### 引导收尾

用户确认后：把引导参数组装成等效命令行 -> **进入 Phase 0 环境预检 + 策略信息获取**。

---

## Phase 0: 环境预检 + 策略信息获取

### 模式行为差异

| 步骤 | 交互模式 | 全自动模式 | 半交互模式 |
|------|----------|-----------|-----------|
| 环境预检 | 展示结果，用户确认 | 自动执行，仅阻塞项报错 | 展示结果，用户确认 |
| 策略信息获取 | 多轮对话逐步收集 | 从 `--from` 自动解析 | 从 `--from` 自动解析 |
| 策略规格 | 展示后用户确认 | 自动保存，直接执行 | 展示后用户确认 |
| 环境变量 | 展示后用户可修改 | 全部使用默认值 | 展示后用户可修改 |
| 进入下一 Phase | 用户确认后 | 自动进入 | 用户确认后 |

### Step 0: 环境预检（自动检测，自动修复）

```bash
# 1. Python 版本（需要 3.10+）
PYTHON_CMD=""
PYTHON_VERSION=""
for cmd in python3.12 python3.11 python3.10 python3; do
    if command -v $cmd &>/dev/null; then
        version=$($cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        major=$(echo $version | cut -d. -f1)
        minor=$(echo $version | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON_CMD=$cmd
            PYTHON_VERSION=$($cmd --version 2>&1)
            break
        fi
    fi
done

# 2. ta-lib C 库
TALIB_FOUND=$(ldconfig -p 2>/dev/null | grep -c libta_lib || echo "0")

# 3. pip 可用
PIP_AVAILABLE=$(command -v pip &>/dev/null && echo "1" || echo "0")

# 4. K 线数据（路径约定：{csv_dir}/{interval}/{SYMBOL}_{interval}.csv）
KLINE_SRC="${KLINE_DATA_DIR:-${DATA_PATH:-./data}/klines}"
KLINE_READY="0"
if [ -d "$KLINE_SRC/1m" ] && [ -f "$KLINE_SRC/1m/BTCUSDT_1m.csv" ]; then
    KLINE_READY="1"
fi

# 5. 磁盘空间（需要 ≥ 2G）
DISK_AVAIL=$(df -h . 2>/dev/null | awk 'NR==2{print $4}')
DISK_GB=$(df -BG . 2>/dev/null | awk 'NR==2{print int($4)}')
DISK_OK="0"
[ "${DISK_GB:-0}" -ge 2 ] && DISK_OK="1"
```

**预检结果映射**：

| 检测项 | ✅ 条件 | ❌ 时的提示 |
|--------|---------|------------|
| Python 3.10+ | `PYTHON_CMD` 非空 | Ubuntu: `sudo apt install python3.12 python3.12-venv` / macOS: `brew install python@3.12` |
| ta-lib C 库 | `TALIB_FOUND ≥ 1` | `wget ...ta-lib... && ./configure && make && sudo make install && ldconfig` |
| pip 可用 | `PIP_AVAILABLE = 1` | `python3 -m ensurepip` |
| K 线数据 | `KLINE_READY = 1` | 运行 `python scripts/download_data.py --symbol BTCUSDT,ETHUSDT,SOLUSDT --interval 1m --days 600`（脚手架创建后） |
| 磁盘空间 ≥ 2G | `DISK_OK = 1` | 清理空间或更换 `DATA_PATH` |

**阻塞 vs 非阻塞**：

| 检测项 | 不达标时 | 原因 |
|--------|----------|------|
| Python 3.10+ | **阻塞** — 无法创建 venv 和运行回测 | 核心依赖 |
| ta-lib C 库 | **非阻塞** — 降级安装；模板参考实现为纯 pandas，无 talib 依赖 | 可后续安装 |
| pip 可用 | **阻塞** — 无法安装依赖 | 核心依赖 |
| K 线数据 | **非阻塞** — Phase 1 自动 symlink/下载 | 可自动修复 |
| 磁盘空间 | **非阻塞** — 警告，可能回测输出空间不足 | 可后续清理 |

**阻塞项处理**：Python/pip 不可用 → 报错退出，提示安装命令。这是唯一需要用户干预的情况。

**非阻塞项处理**：ta-lib 缺失 → 降级安装核心依赖；K 线数据缺失 → Phase 1 自动下载；磁盘不足 → 警告继续。

### Step 1: 策略信息获取

**工作目录**：项目在用户当前工作目录下创建。项目路径 = `{cwd}/{strategy_name}`。

根据输入形态自动选择解析方式：

**a. 文件路径** → Read 文件 → 解析策略规格 → 项目路径: `{cwd}/{strategy_name}`

**b. 策略目录** → 逆向提取（从已有代码提取 spec）→ 项目路径: `{cwd}/{strategy_name}`

```python
# 读取策略目录中的关键文件
strategy_dir = source_path
files_to_read = [
    f"{strategy_dir}/strategy.py",          # STRATEGY_TYPE, STRATEGY_PREFIX, DEFAULT_TIMEFRAME
    f"{strategy_dir}/*_core.py",            # State fields, analyze() logic, check_realtime_exit()
    f"{strategy_dir}/.strategy-spec.yaml",  # 已有规格文件则直接读
    f"{strategy_dir}/overrides/*.yaml",     # per-symbol 参数（v3.7 单一事实来源）
]

# 提取映射
STRATEGY_TYPE → strategy_name
STRATEGY_PREFIX → prefix
DEFAULT_TIMEFRAME → timeframes[0]
overrides/<SYMBOL>.yaml → symbols(取文件名全集), params, direction
*_core.py → State fields, entry/exit logic (从 analyze() 代码逆向)
```

**c. URL** → WebFetch → 解析 → 项目路径: `{cwd}/{strategy_name}`

**d. 自然语言** → 从描述提取策略规格 → 项目路径: `{cwd}/{strategy_name}`

**e. 无输入** → 多轮对话收集：

```
1. 项目路径？（默认: ./{strategy_name}）
2. 策略名称？（如 ema_rsi_pullback，将作为 strategies/{name}/ 目录名）
3. 策略前缀？（如 EMA_RSI，用于 {prefix}_core.py 命名）
4. 交易方向？（long / short / neutral）
5. 主时间框架？（如 4h）
6. 交易标的？（如 BTCUSDT）
7. 入场条件描述？（自然语言）
8. 出场条件描述？（止损/止盈/移动止盈）
```

> **项目路径规则**：默认 `{cwd}/{strategy_name}`。如果目录已存在，追加 `_v2`、`_v3` 等后缀避免覆盖。

### Step 2: 统一提取为策略规格（.strategy-spec.yaml）

所有输入形态收敛到同一个结构。**字段 schema 见模板 `docs/strategy/STRATEGY_SPEC.md`**（生成前必须先读它）：

```yaml
strategy_name: ema_rsi_pullback
prefix: EMA_RSI
direction: neutral
timeframes: [4h, 1h]          # [0] 必须是触发主周期
extra_timeframes: [1d]        # 可选：除主周期外订阅的其他周期
symbols: [BTCUSDT, ETHUSDT, SOLUSDT]

entry:
  description: "EMA 交叉 + RSI 回踩确认"
  conditions:                  # 条件逐条列，生成代码时一条对应一个判断
    - "快线上穿慢线"
    - "RSI 回踩至 40-60 区间后反弹"

exit:
  stop_loss: "2 倍 ATR"        # 硬止损规则；不做空字符串
  trailing_stop: ""            # 没有就留空字符串
  signal_reversal: ""
  note: "回落止盈/固定止盈由 overrides 的 risk 段统一风控兜底，策略内不实现"

state_fields:                  # 策略特有状态字段（BaseState 已有字段不要列）
  - name: atr_at_entry
    type: float                # float / int / bool / str / date
    default: 0.0
    persist: true              # true=进 to_persist_dict；false=每根 K 线重算的缓存
  - name: trail_activated
    type: bool
    default: false
    persist: true

default_params:                # Core.__init__ 从 params 读取的参数及默认值
  ema_fast_period: 20
  ema_slow_period: 60
```

> **参考范例**：模板自带两个参考实现的 spec——
> `strategies/example_ma_cross/.strategy-spec.yaml`（单周期）、
> `strategies/example_mtf_trend/.strategy-spec.yaml`（多周期）。

### Step 3: 执行确认（按模式）

**全自动模式**：自动保存 `.strategy-spec.yaml`，直接进入 Phase 1。

```
📋 策略: ema_rsi_pullback | EMA_RSI | neutral | [4h,1h] | [BTCUSDT,ETHUSDT,SOLUSDT]
🔧 环境: Python 3.12 ✅ | ta-lib ⚠(不阻塞) | K线数据 ✅ | 磁盘 15G ✅
🚀 自动执行 loop-engineering 模式...
```

**交互/半交互模式**：展示完整信息，用户确认后执行。

```
📋 环境预检:
  Python 3.12: ✅
  ta-lib C 库: ⚠ 未装（参考实现为纯 pandas，不阻塞；需要 talib 指标时再装）
  pip: ✅
  K 线数据: ✅ (symlink → /path/to/data/klines/)
  磁盘空间: ✅ (15G 可用)

📋 策略解析结果:
  名称: ema_rsi_pullback
  前缀: EMA_RSI
  方向: neutral
  时间框架: [4h, 1h]
  标的: [BTCUSDT, ETHUSDT, SOLUSDT]
  入场: EMA 交叉 + RSI 回踩确认
  出场: 止损 2x ATR, 统一风控兜底

确认执行？(y/n)
```

**阻塞项失败时**（所有模式相同）：报错退出，提示安装命令。

```
❌ 环境预检失败，无法继续:
  Python 3.10+: 未找到
  安装: sudo apt install python3.12 python3.12-venv
```

用户确认后，保存 `.strategy-spec.yaml` 到 `strategies/{strategy_name}/`，进入 Phase 1。

---

## Phase 1: 项目脚手架创建

### 模式行为差异

| 步骤 | 交互模式 | 全自动模式 | 半交互模式 |
|------|----------|-----------|-----------|
| 复制模板 | 执行后展示文件列表 | 静默执行 | 执行后展示文件列表 |
| Python 环境 | 展示安装结果 | 静默执行，失败时自动降级 | 展示安装结果 |
| K 线数据 | 展示准备方式（symlink/下载/跳过） | 自动选择最佳方式 | 展示准备方式 |
| Git init | 展示首次 commit | 静默执行 | 静默执行 |
| 就绪报告 | 展示完整报告 | 展示单行摘要 | 展示完整报告 |

**单步模式**：`/trading-dev scaffold` 只执行 Phase 1，执行后退出。

### Step 1: 复制模板代码

从 skill 模板目录复制骨架代码到新项目。

**模板根目录**：自动检测，优先级：

1. 环境变量 `TRADING_DEV_TEMPLATE_DIR`（如有设置）
2. `~/.claude/skills/trading-dev/templates/`（默认安装位置）
3. 当前 SKILL.md 所在目录的 `templates/` 子目录

```bash
# 自动检测模板目录
if [ -n "$TRADING_DEV_TEMPLATE_DIR" ]; then
    TEMPLATE_DIR="$TRADING_DEV_TEMPLATE_DIR"
elif [ -d "$HOME/.claude/skills/trading-dev/templates" ]; then
    TEMPLATE_DIR="$HOME/.claude/skills/trading-dev/templates"
else
    # SKILL.md 同级目录
    TEMPLATE_DIR="$(dirname "$(find "$HOME/.claude/skills" -name SKILL.md -path "*/trading-dev/*" 2>/dev/null | head -1)")/templates"
fi
```

**复制列表（全量镜像）**：模板即完整可运行项目，整体复制：

| 源路径 | 说明 |
|--------|------|
| `templates/strategy_core/` | 基类框架（BaseStrategy/BaseState/BaseStrategyCore + 统一风控） |
| `templates/backtest/` | 回测引擎（run_backtest / batch_runner） |
| `templates/data_manager/` | K线数据管理（CSV + WS + 多时间框架聚合） |
| `templates/scripts/` | `download_data.py` / `run_backtest_batch.sh` / `run_live_batch.sh` / `resample_1m_to_multi_tf.py` |
| `templates/config/` | 三层配置（settings.yaml / strategies.yaml / backtest.yaml run-profile），全部入库 |
| `templates/strategies/` | 参考实现（example_ma_cross 单周期、example_mtf_trend 多周期）+ README |
| `templates/tests/` | 根级测试 |
| `templates/docs/` | 全部文档（strategy/ 五件套 + STRATEGY_SPEC.md 等） |
| `templates/requirements*.txt` | 依赖清单 |
| `templates/.gitignore` / `.env.example` | 排除规则 / 环境变量模板 |
| `templates/run_strategies_manager.py` / `run_strategy.py` | 入口 |
| `templates/start.sh` / `stop.sh` | 启停脚本 |
| `templates/CLAUDE.md` / `README.md` / `ARCHITECTURE.md` | 项目文档 |

**不复制**（模板中已排除，此处列出原因）：

| 排除项 | 原因 |
|--------|------|
| `.env` | 含真实凭证，只保留 `.env.example` |
| `strategies/sar_snt3_v3/` 类真实策略 | 业务逻辑与真实资金参数不进模板 |
| `data/ logs/ backtest_output*/` | 运行时生成 |

**复制命令**：

```bash
TEMPLATE_DIR="{已检测的模板目录}"
PROJECT_DIR="{project_path}"

# 整体镜像复制（模板已是干净的开源子集，无需再挑拣）
cp -r $TEMPLATE_DIR/. $PROJECT_DIR/

# 创建本地 .env（从模板）
cp $PROJECT_DIR/.env.example $PROJECT_DIR/.env
```

> **与旧版差异**：v3.7 模板即完整可运行项目（单体模式，直连 Binance 公共行情），
> 无需再从 `.example` 生成运行时配置——`config/` 三层全部入库，
> 新策略登记进 `config/strategies.yaml` 即可。

### Step 2: 初始化 Python 环境

**按 Phase 0 预检结果执行**。预检已确认 Python 版本和 ta-lib 状态，此处直接执行安装。

```bash
cd {project_path}

# 1. 创建 venv（Python 版本已在 Phase 0 预检确认）
$PYTHON_CMD -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# 2. 安装依赖
if pip install -r requirements.txt -r requirements-dev.txt; then
    echo "✅ 依赖安装成功"
else
    echo "⚠ 部分依赖安装失败，降级安装核心依赖..."
    pip install pandas numpy pyyaml
    if [ "$TALIB_FOUND" = "0" ]; then
        echo "⚠ ta-lib C 库未安装，跳过 ta-lib Python 包"
        echo "  参考实现为纯 pandas 不受影响；需要 talib 指标时安装 C 库后重跑: pip install ta-lib"
    fi
fi
```

> **ta-lib 处理逻辑**：Phase 0 预检已检测 C 库状态。C 库未安装时，pip install ta-lib 会失败，此处自动跳过并降级。模板参考实现（example_ma_cross / example_mtf_trend）是纯 pandas，不影响跑通链路。

### Step 3: 准备回测 K 线数据

**数据路径约定**（回测/实盘/下载脚本三方一致，见 `backtest/run_backtest.py` 的 `_kline_csv_path`）：

```
{csv_dir}/{interval}/{SYMBOL}_{interval}.csv
例: ./data/klines/1m/BTCUSDT_1m.csv
```

回测按 1m 驱动，大周期由框架自动聚合（也可用 `scripts/resample_1m_to_multi_tf.py` 预生成）。数据约 1.3G/代币/600天，**不复制**，用 symlink 指向共享数据源。

**数据格式**（CSV，带 header）：

```csv
timestamp,open,high,low,close,volume
2022-12-30 00:00:00+00:00,16630.3,16633.7,16629.2,16629.3,337.988
2022-12-30 00:01:00+00:00,16629.3,16629.3,16625.5,16625.5,77.129
```

**自动准备**（按优先级尝试，不询问用户）：

```bash
cd {project_path}
DATA_DIR="${DATA_PATH:-./data/klines}"
KLINE_SRC="${KLINE_DATA_DIR:-$DATA_DIR}"

# 方式 1: symlink 到已有数据源（推荐，零拷贝）
if [ -d "$KLINE_SRC" ] && [ -f "$KLINE_SRC/1m/BTCUSDT_1m.csv" ]; then
    mkdir -p "$DATA_DIR"
    # 按周期子目录逐个链接（路径约定 {csv_dir}/{interval}/）
    for tf_dir in "$KLINE_SRC"/*/; do
        tf=$(basename "$tf_dir")
        mkdir -p "$DATA_DIR/$tf"
        ln -sf "$tf_dir"*.csv "$DATA_DIR/$tf/" 2>/dev/null
    done
    echo "✅ 已 symlink kline 数据: $KLINE_SRC → $DATA_DIR"

# 方式 2: 运行 scripts/download_data.py 从 Binance 公共数据源下载（无需 API key）
#   输出路径 {data_dir}/{interval}/{SYMBOL}_{interval}.csv，与回测/实盘一致
#   CSV 已存在时自动增量 merge，不销毁历史
elif [ -f "scripts/download_data.py" ]; then
    echo "📥 K 线数据未就绪，从 Binance 下载..."
    echo "  回看天数: 600 天"
    echo "  交易对: BTCUSDT,ETHUSDT,SOLUSDT（默认）"
    $PYTHON_CMD scripts/download_data.py \
        --symbol BTCUSDT,ETHUSDT,SOLUSDT \
        --interval 1m \
        --days 600 \
        --data-dir "$DATA_DIR"

# 方式 3: 数据未就绪，记录警告（不阻塞流程，回测时会报错）
else
    echo "⚠ kline 数据未就绪"
    echo "  需要路径: $DATA_DIR/1m/，文件格式 {SYMBOL}_1m.csv (timestamp,open,high,low,close,volume)"
    echo "  或运行: python scripts/download_data.py --symbol BTCUSDT,ETHUSDT,SOLUSDT --interval 1m --days 600"
fi
```

**验证数据就绪**：

```bash
if [ -f "$DATA_DIR/1m/BTCUSDT_1m.csv" ]; then
    lines=$(wc -l < "$DATA_DIR/1m/BTCUSDT_1m.csv")
    echo "✅ 1m kline 数据就绪: BTCUSDT ${lines} 行"
else
    echo "⚠ 1m kline 数据未就绪，回测将失败"
fi
```

### Step 4: 初始化 Git

```bash
cd {project_path}
git init
echo "data/" >> .gitignore    # K线数据不入库
git add .
git commit -m "init: scaffold from trading-dev-skill template"
```

> `.env` 已在模板 `.gitignore` 中排除，不会误提交。

### Step 5: 输出就绪报告

```
✅ 项目脚手架创建完成

项目路径: {project_path}
Python 环境: .venv (Python 3.x)
依赖安装: ✅ / ⚠️ (ta-lib 需手动安装)
kline 数据: ✅ (symlink) / ✅ (下载) / ⚠️ (需手动准备)

项目结构:
  {strategy_name}/
  ├── strategy_core/              # 基类框架（BaseStrategy/BaseState/BaseStrategyCore）
  │   ├── base/                   # 基类 + 统一风控
  │   ├── signal_logging/         # CSV 持久化 + 交易所直连下单（binance_trader）
  │   └── utils/                  # strategies_loader / log_handlers / env_placeholders
  ├── backtest/                   # 回测引擎
  │   ├── run_backtest.py         # 回测入口（CLI 已收敛为 7 参数）
  │   ├── batch_runner.py         # 批量回测执行器
  │   └── analyzer.py             # 指标解析
  ├── data_manager/               # K线数据管理（DataManager, kline_repository, klines_loader）
  ├── scripts/                    # download_data.py / run_backtest_batch.sh / run_live_batch.sh
  ├── strategies/                 # 参考实现 + 新策略目录
  │   ├── README.md
  │   ├── example_ma_cross/       # ⬅ 单周期参考实现（先完整读一遍再写新策略）
  │   ├── example_mtf_trend/      # ⬅ 多周期参考实现
  │   └── {strategy_name}/        # ⬅ Phase 2 生成
  │       ├── strategy.py
  │       ├── {prefix}_core.py
  │       ├── __init__.py
  │       ├── overrides/             # ⬅ 策略参数唯一来源（实盘回测共用）
  │       │   ├── BTCUSDT.yaml
  │       │   ├── ETHUSDT.yaml
  │       │   └── SOLUSDT.yaml
  │       ├── .strategy-spec.yaml
  │       └── tests/
  ├── config/                     # ⬅ 三层配置模型，全部入库
  │   ├── settings.yaml           # 系统层（数据/信号日志/直连下单开关）
  │   ├── strategies.yaml         # 编排层（实盘回测共用登记表）
  │   ├── backtest.yaml           # 回测 run-profile（--profile 默认值）
  │   └── quick.example.yaml      # 调参用 profile 示例
  ├── tests/                      # 根级测试（strategies_loader / run_strategy 等）
  ├── docs/                       # 全部规范文档
  │   └── strategy/               # QUICKSTART / DEVELOPMENT_GUIDE / AI_CONSTRAINTS
  │                               # / REVIEW_CHECKLIST / EXAMPLES / STRATEGY_SPEC
  ├── data/klines/                # ⬅ K线数据（{csv_dir}/{interval}/{SYMBOL}_{interval}.csv）
  │   └── 1m/BTCUSDT_1m.csv
  ├── .env                        # 环境变量（从 .env.example 生成，不入库）
  ├── .env.example
  ├── requirements.txt / requirements-dev.txt
  ├── run_strategies_manager.py   # 策略管理器入口
  ├── run_strategy.py             # 单策略运行入口
  ├── start.sh / stop.sh
  └── CLAUDE.md / README.md / ARCHITECTURE.md
```

---

## Phase 2: 策略开发

从 Phase 0 的策略规格直接生成代码。

### 模式行为差异

| 步骤 | 交互模式 | 全自动模式 | 半交互模式 |
|------|----------|-----------|-----------|
| 加载规范文档 | 静默加载 | 静默加载 | 静默加载 |
| 生成代码 | 展示生成的文件列表 | 静默生成 | 展示生成的文件列表 |
| 登记策略 | 静默执行 | 静默执行 | 静默执行 |
| 验证配置 | 展示验证结果 | 静默验证，失败自动修复 | 展示验证结果 |
| 审查检查表 | 展示审查结果 | 静默审查，不通过自动修复 | 展示审查结果 |
| README 重写/同步 | 展示更新内容 | 静默执行 | 展示更新内容 |

**单步模式**：`/trading-dev develop` 只执行 Phase 2（需要已有脚手架和 `.strategy-spec.yaml`）。

### Step 0: 加载规范文档 + 参考实现（强制）

**必须先读取以下文档与参考代码到上下文，确保生成的代码符合项目规范**：

```
docs/strategy/QUICKSTART.md           # Step 0 要求先读参考实现；目录结构、命名规范、代码模板
docs/strategy/DEVELOPMENT_GUIDE.md    # 基类功能、平仓方法、冷却机制
docs/strategy/AI_CONSTRAINTS.md       # 编码红线（14 条禁止 + 11 条必须）
docs/strategy/REVIEW_CHECKLIST.md     # 提交前检查项（10 类）
docs/strategy/EXAMPLES.md             # 常见问题与踩坑
docs/strategy/STRATEGY_SPEC.md        # spec 字段 schema

strategies/example_ma_cross/          # ⬅ 单周期参考实现（必读，QUICKSTART Step 0 强制）
  ├── strategy.py                     # Strategy 接口层（最简形态）
  ├── example_ma_cross_core.py        # Core 逻辑层（★ 注释是框架契约重点）
  ├── overrides/BTCUSDT.yaml          # per-symbol 配置逐字段注释
  └── tests/                          # 测试写法
```

**多周期策略额外必读**：`strategies/example_mtf_trend/`（1d 定方向 + 4h 触发 + 1h 确认，
演示每个周期分别 `get_closed_data()` + 单独数据检查的标准写法）。

### Step 1: 生成策略代码

按 QUICKSTART.md 规范生成以下文件：

#### 1.1 strategy.py（~35 行）

```python
#!/usr/bin/env python3
"""{策略名称} — Strategy 接口类"""

from strategy_core.base import BaseStrategy
from .{prefix}_core import {Prefix}Core


class Strategy(BaseStrategy):
    """{策略名称}"""

    STRATEGY_TYPE = "{strategy_name}"
    STRATEGY_PREFIX = "{PREFIX}"
    DEFAULT_TIMEFRAME = "{主时间框架}"

    def _create_core(self):
        return {Prefix}Core(
            symbols=self.symbols,
            timeframes=self.timeframes,
            params=self.params,
        )

    def _get_indicator_timeframes(self) -> set:
        tf_set = set(self.timeframes)
        p = self.params or {}
        # 为每个指标添加 *_timeframes
        # tf_set.add(p.get("xxx_timeframes", "4h"))
        return tf_set
```

#### 1.2 {prefix}_core.py

包含：
- `{Prefix}State(BaseState)` — 策略特有状态字段
- `{Prefix}Core(BaseStrategyCore)` — 实现 `analyze()` + `check_realtime_exit()`

**必须遵守 AI_CONSTRAINTS.md 的编码红线**（关键几条）：

| 红线 | 说明 |
|------|------|
| 禁止入场用未闭合 K 线 | 多周期必须 `get_closed_data()` |
| 禁止 `datetime.now()` 做时间戳 | 用 K 线时间 |
| 禁止 Strategy 类算指标 | 指标在 Core.analyze() 内 |
| 禁止跳过数据不足检查 | `get_closed_data(min_rows=N)` 后再判一次 `len()` |
| 禁止可变默认值 | 用 `field(default_factory=list)` |
| 禁止缓存字段持久化 | 缓存不进 `to_persist_dict()` |
| 入场必须调 `_notify_position_enter()` | 漏了仓位不落盘，进程重启即丢 |
| 平仓必须走 `_notify_exit_and_clear()` | 不要自己调 `clear_position()` |

**参考实现里的框架契约**（QUICKSTART 代码地图，写错不报错只会静默不发信号）：
- `action` 合法取值：入场 `buy`/`sell`，平仓用 `_notify_exit_and_clear()` 返回值（全集 `buy`/`sell`/`buy_close`/`sell_close`）
- 入场 state 必填字段：`position`/`position_id`/`entry_price`/`entry_time`/`entry_timestamp`/`stop_price`/`peak_price` + 特有字段
- 下单量：`metadata["target_notional"] = (current_cash or 0) * self.leverage`；杠杆从 `params.leverage` 读（`capital.leverage` 不会传给 Core）

#### 1.3 __init__.py

```python
from .strategy import Strategy
from .{prefix}_core import {Prefix}Core, {Prefix}State

__all__ = ["Strategy", "{Prefix}Core", "{Prefix}State"]
```

> **无需全局注册**：框架按 `strategies.{name}.strategy` 模块路径直接 import
> `Strategy` 类，不存在中心注册表。只要目录名 = 配置里的策略名即可被加载。

#### 1.4 策略参数配置（per-symbol overrides）

v3.7 每个 (策略, 代币) 一份参数文件，**这是唯一事实来源** ——
实盘 `run_strategy.py` 与回测 `run_backtest.py` 读的都是它。
不再生成 `config.yaml` / `config.dev.yaml` / `config.test.yaml`：
那套按环境分文件的做法会让回测与实盘读到两份参数（回测失真的根源），v3.7 已删除。

**路径**：`strategies/{strategy_name}/overrides/{SYMBOL}.yaml`

**格式**（顶层必须是策略名键；完整字段说明照抄参考实现 `strategies/example_ma_cross/overrides/BTCUSDT.yaml` 的逐字段注释）：

```yaml
{strategy_name}:
  enabled: true
  version: '1'
  # 运行模式：live / paper_trading / smoking
  # ⚠ 缺省时框架按 live 处理（会下真单），新策略务必显式写 paper_trading
  trading_mode: "paper_trading"
  direction: {direction}
  symbols:
    - {SYMBOL}
  timeframes: {timeframes}
  params: {params}          # 从 .strategy-spec.yaml 的 default_params 填充
  signal:
    min_strength: 0.5
    cooldown_ms: 0
    order_type: 1
    slippage: 0
    exchange: binance       # 直连下单模式下必须与执行器一致（binance）
  capital:
    max_cash: 1000
    max_parts: 1
    leverage: 1
  risk:
    enabled: true
    fixed_stop_loss_pct: 2.0
    trailing_profit:
      enabled: true
      activation_pct: 2.0
      drawdown_pct: 20.0
    fixed_take_profit_pct: 0.0
  # 注意：cooldown_timeframe / cooldown_bars / cooldown_ms 是死配置，不要写
  user_id: 1
```

**生成规则**：
- 为 `symbols` 列表中每个代币生成一个文件，文件名 = `{SYMBOL}.yaml`
- `symbols` 字段只含当前文件对应的那一个代币
- `params` 从 `.strategy-spec.yaml` 的 `default_params` 填充；
  不同代币可各自独立调参（这正是拆成 per-symbol 的目的）
- 每个指标必须配置 `*_timeframes` 并在 `Strategy._get_indicator_timeframes()` 收集
- `interval` 与 `version` 由框架从本文件的 `timeframes[0]` / `version` 自动读取
- 回测通过 `--strategies {strategy_name}:{SYMBOL}` 自动定位本文件，不需要 `--config` 参数
- 回测引擎会把实际生效的配置复制到 `{output_dir}/{strategy}/{date}/{time}/{SYMBOL}/config.yaml` 供复现

#### 1.5 编排登记（config/strategies.yaml）

参数文件只描述"某个代币怎么跑"，还需在**编排层**登记"跑哪些"：

```yaml
strategies:
  {strategy_name}:
    trading_mode: "paper_trading"
    symbols:
      - BTCUSDT
      - ETHUSDT
      - SOLUSDT
```

该文件实盘回测共用：`./start.sh` 按它拉起全部策略，
`batch_runner` 不带 `--run` 时也按它批量回测。

**目录结构**：

```
strategies/{strategy_name}/
├── overrides/                  # ⬅ 策略参数唯一来源
│   ├── BTCUSDT.yaml
│   ├── ETHUSDT.yaml
│   └── SOLUSDT.yaml
├── strategy.py
├── {prefix}_core.py
├── __init__.py
├── .strategy-spec.yaml         # 策略规格（供逆向提取与再生成）
└── tests/
    └── test_{prefix}_core.py
```

#### 1.6 测试文件

- `tests/test_{prefix}_core.py` — 核心逻辑测试（照参考实现 `strategies/example_ma_cross/tests/` 的写法）

### Step 2: 验证配置

```bash
python3 -c "
import yaml
from pathlib import Path
config_path = Path('strategies/{strategy_name}/overrides/BTCUSDT.yaml')
with open(config_path) as f:
    full_config = yaml.safe_load(f)
if '{strategy_name}' not in full_config:
    print(f'ERROR: 配置文件缺少顶层键: {strategy_name}')
    exit(1)
config = full_config['{strategy_name}']
required = ['timeframes', 'symbols', 'params', 'trading_mode']
for key in required:
    if key not in config:
        print(f'ERROR: 配置缺少必需字段: {key}')
        exit(1)
# trading_mode 缺省时框架按 live 处理（会下真单），新策略必须显式声明
if config.get('trading_mode') == 'live':
    print('⚠ WARNING: trading_mode=live 会下真单，新策略建议 paper_trading')
print('✅ 配置文件格式正确')
"
```

再跑一遍新策略的测试，确认加载无误：

```bash
source .venv/bin/activate
python3 -m pytest strategies/{strategy_name}/tests/ -v
```

### Step 3: 运行审查检查表

按 `docs/strategy/REVIEW_CHECKLIST.md` 逐项检查，输出结果。

### Step 4: 重写/同步 README.md（强制）

策略开发完成后，项目根目录 `README.md` 必须与开发的策略保持一致。按场景处理：

#### 场景 A：新项目（Phase 1 刚创建，本次开发的是项目主策略）→ **重写**

脚手架复制出来的 README 是模板视角（主角是 `example_ma_cross` 参考实现），
新项目的主角是本次开发的策略，必须重写策略相关段落：

```markdown
# {strategy_name} — {一句话策略定位}

> {direction} 策略 | 主周期 {timeframes[0]} | 标的 {symbols} | 前缀 {PREFIX}

## 策略概述

- 入场：{spec.entry.description}（完整条件清单见 strategies/{name}/.strategy-spec.yaml）
- 出场：{spec.exit 摘要} + overrides 的 risk 段统一风控兜底
- 参数：per-symbol overrides（strategies/{name}/overrides/<SYMBOL>.yaml，实盘回测共用）

## 快速开始

python -m backtest.run_backtest --strategies {strategy_name}:{SYMBOL} --start 20260601 --end 20260709
（替换模板里的 example_ma_cross 示例命令）

## 项目结构
（模板结构保留，strategies/ 段把 {strategy_name} 列为主策略，
  example_ma_cross / example_mtf_trend 标注为"框架参考实现"）

## 配置体系 / 文档导航 / 免责声明
（框架通用段落原样保留）
```

**重写规则**：
- 主角换成开发策略；参考实现降级为"框架参考实现"一节，不占快速开始
- 策略参数不复制进 README——参数细节留在 overrides YAML 的注释里
- 框架通用段落（配置体系三层模型、免责声明、文档导航、测试命令）保留不动

#### 场景 B：已有项目追加新策略 → **增量同步**

| 位置 | 更新内容 |
|------|----------|
| `## 项目结构` 的 `strategies/` 段 | 追加新策略目录（与参考实现同级的注释格式） |
| `## 参考策略` 表格 | 追加一行：策略名 / 一句话说明 / 基类架构 / 时间周期 / 多标的 |
| `## 快速开始` 的示例命令 | 若新策略更适合作演示，可替换现有示例 |

**规则**：README 只描述"有什么"，不复制策略参数。参考实现级别的通用范例才写进
"参考策略"表；一次性业务策略只在项目结构里出现目录名即可。

---

## Phase 3: 回测验证

解析回测输出，自动判断是否达标。

### 模式行为差异

| 步骤 | 交互模式 | 全自动模式 | 半交互模式 |
|------|----------|-----------|-----------|
| 短期回测 | 每个代币跑完展示结果 | 静默执行 | 每个代币跑完展示结果 |
| 中期回测 | 同上 | 静默执行 | 同上 |
| 长期回测 | 同上 | 静默执行 | 同上 |
| 命令行验证 | 展示对比结果 | 静默验证 | 展示对比结果 |
| benchmark 输出 | 展示报告摘要 | 展示报告路径 | 展示报告摘要 |
| 调参 | 每次调参前展示原因 | 自动调参，展示轮次摘要 | 每次调参前展示原因 |

**单步模式**：
- `/trading-dev scaffold` — 执行 Phase 1 Step 1-5（脚手架创建），前置：无
- `/trading-dev develop` — 执行 Phase 2（策略代码生成），前置：已有脚手架 + `.strategy-spec.yaml`
- `/trading-dev backtest` — 执行 Phase 3 Step 1-4（回测 + 验证），前置：已有策略代码 + K 线数据
- `/trading-dev benchmark` — 只输出 benchmark 报告（Phase 3 Step 5），前置：已有回测结果

### 回测验收标准

| 周期 | 时间范围 | 验收标准 |
|------|----------|----------|
| 短期 | 20260601-20260709 | 至少一个代币费后收益 ≥ 20% |
| 中期 | 20260101-20260709 | 至少一个代币费后收益 ≥ 20% |
| 长期 | 20250101-20260709 | 至少一个代币费后收益 ≥ 20% |

三个周期都用同一条批量命令，只换 `--start` / `--end`。
经项目自带的 `scripts/run_backtest_batch.sh` 调用（它负责 overrides 预检、
笛卡尔积展开、`PYTHONPATH`，再转调 `backtest.batch_runner`）。
并发由 `config/backtest.yaml` 的 `max_workers` 控制；策略参数自动读
`strategies/{strategy_name}/overrides/<SYMBOL>.yaml`。

`--yes` 跳过任务数 > 6 时的交互确认，非交互环境必须带。

### Step 1: 短期回测

```bash
bash scripts/run_backtest_batch.sh \
    --strategies {strategy_name} --symbols BTCUSDT,ETHUSDT,SOLUSDT \
    --start 20260601 --end 20260709 --log-level INFO --yes
```

### Step 2: 中期回测

```bash
bash scripts/run_backtest_batch.sh \
    --strategies {strategy_name} --symbols BTCUSDT,ETHUSDT,SOLUSDT \
    --start 20260101 --end 20260709 --log-level INFO --yes
```

### Step 3: 长期回测

```bash
bash scripts/run_backtest_batch.sh \
    --strategies {strategy_name} --symbols BTCUSDT,ETHUSDT,SOLUSDT \
    --start 20250101 --end 20260709 --log-level INFO --yes
```

### Step 4: 单标的复核

`batch_runner` 是 `run_backtest` 的批量外壳。要单独复核某个代币、
或需要看完整 stdout 时用单次入口：

```bash
python -m backtest.run_backtest \
    --strategies {strategy_name}:BTCUSDT \
    --start 20250101 --end 20260710 --log-level INFO
```

`run_backtest` CLI 共 7 个参数：`--strategies`（name:symbol）、`--start`、`--end`、
`--profile`、`--config-path`、`--overrides`、`--log-level`。
symbol 唯一来源是 `--strategies` 的 `name:symbol`，参数来源是
`overrides/<SYMBOL>.yaml`，输出目录与资金费率由 `--profile`（默认 `config/backtest.yaml`）提供。

要换一套回测参数而不改动入库文件，复制 `config/quick.example.yaml`
成 `config/<名字>.yaml`，用 `--profile <名字>` 运行。

**⚠ 不要用 `--daemon`**：batch_runner 的 daemon 模式重建子命令时只传
`--profile` 与 `--batch-id`，会丢掉 `--run/--start/--end`，等于跑成空清单。
需要后台执行请在外层 `nohup`。

**产物路径**：`{output_dir}/{strategy}/{date}/{time}/{symbol}/`，
指标在 `backtest_result.json` 的 `metrics` 段（不在顶层）。

### Step 5: 输出 benchmark.md

综合三个代币的回测结果，生成 benchmark 报告。

**输出路径**：环境变量 `BENCHMARK_OUTPUT_PATH`，默认 `./benchmark_output`。

```bash
# 输出路径解析
BENCHMARK_DIR="${BENCHMARK_OUTPUT_PATH:-./benchmark_output}"
BENCHMARK_FILE="$BENCHMARK_DIR/{strategy_name}/benchmark/{YYYY-MM-DD}-benchmark.md"
mkdir -p "$(dirname "$BENCHMARK_FILE")"
```

> 如需输出到 Obsidian 笔记库，在 `.env` 中设置：
> `BENCHMARK_OUTPUT_PATH=/path/to/obsidian_vault/quant_research`

报告格式：

```markdown
# {strategy_name} Benchmark

## 回测参数
- 策略: {strategy_name}
- 时间范围: 20250101 - 20260709
- 代币: BTCUSDT, ETHUSDT, SOLUSDT

## 短期回测 (20260601-20260709)

| 代币 | 费后收益 | 最大回撤 | 交易次数 | 胜率 |
|------|---------|---------|---------|------|
| BTCUSDT | ... | ... | ... | ... |
| ETHUSDT | ... | ... | ... | ... |
| SOLUSDT | ... | ... | ... | ... |

## 中期回测 (20260101-20260709)
...

## 长期回测 (20250101-20260709)
...

## 结论
- 短期最佳: {symbol} ({return}%)
- 中期最佳: {symbol} ({return}%)
- 长期最佳: {symbol} ({return}%)
- 是否通过验收: ✅ / ❌
```

---

## Loop-Engineering: 跨 Phase 大闭环

Phase 2 和 Phase 3 形成跨 Phase 大闭环。回测不达标时，自动回到 Phase 2 修改策略逻辑，再跑 Phase 3。

### Loop 行为定义

```
最大轮次: 5
每轮:
  Phase 2: 生成/修改策略代码
  Phase 3: 回测验证
  判断:
    - 长期回测至少一个代币费后收益 ≥ 20% → 通过，输出 benchmark
    - 未达标 → 分析失败原因，修改策略逻辑/参数，进入下一轮
    - 达到最大轮次 → 输出当前最佳结果 + 未达标标记
```

### 调参策略（动态诊断式）

回测不达标时，**先诊断再开方**——从回测结果、策略逻辑、K线特征三个维度交叉分析，推导出可调维度和具体修改方案。

#### Step 1: 解析回测输出，提取诊断数据

从 `{output_dir}/{strategy_name}/{date}/{time}/{symbol}/backtest_result.json` 提取：

```python
# 回测输出中的关键诊断字段
metrics = {
    "total_return": float,       # 总收益率（小数，如 0.15 = 15%）
    "max_drawdown": float,       # 最大回撤（小数，如 0.25 = 25%）
    "win_rate": float,           # 胜率（小数，如 0.35 = 35%）
    "profit_factor": float,      # 盈亏比
    "total_trades": int,         # 总交易次数
    "avg_win": float,            # 平均盈利（USDT）
    "avg_loss": float,           # 平均亏损（USDT）
    "largest_win": float,        # 最大单笔盈利
    "largest_loss": float,       # 最大单笔亏损
    "sharpe_ratio": float,       # 夏普比率
    "sortino_ratio": float,      # 索提诺比率
    "trading_days": int,         # 回测天数
    "daily_return_std": float,   # 日波动率
}

# 分币对交易统计（从 trades 列表聚合）
per_symbol_stats = {
    "{SYMBOL}": {
        "trades": int,
        "win_rate": float,
        "total_pnl": float,
        "avg_pnl": float,
    }
}
```

#### Step 2: 读取策略代码，提取可调参数清单

解析 `{prefix}_core.py` 和 `overrides/<SYMBOL>.yaml`，自动提取：

```python
# 从 overrides/<SYMBOL>.yaml 的 params 段提取可调参数
adjustable_params = {
    "{param_name}": {
        "current": float/int/str,   # 当前值
        "role": str,                 # 参数作用（从代码注释/上下文推断）
        "affects": str,              # 影响的阶段：entry / exit / risk / filter
        "adjustable_range": str,     # 合理调整范围（从策略逻辑推断）
    }
}

# 从 *_core.py 的 analyze() / check_realtime_exit() 提取硬编码阈值
hardcoded_thresholds = [
    {
        "location": "line X",
        "code": "if rsi > 70:",
        "parameter": "RSI overbought threshold",
        "current": 70,
        "suggested_range": "60-80",
        "affects": "entry",
    }
]
```

#### Step 3: 综合诊断——回测症状 × 策略逻辑 × K线特征

根据回测指标的模式匹配诊断表，结合策略代码上下文推导具体修改：

| 症状模式 | 诊断 | 可能的调整方向 | 需结合策略验证 |
|----------|------|---------------|---------------|
| `total_trades < 10` 且 `trading_days > 90` | 入场条件过严或信号稀疏 | 放宽入场阈值 / 增加辅助确认指标 / 缩短指标周期 | 查看 `analyze()` 入场逻辑，确认是哪个条件过滤了大部分机会 |
| `total_trades < 5` 且 `trading_days > 90` | 几乎没有触发信号 | 多周期条件互斥 / 指标周期过长导致永远不满足 | 查看 `get_closed_data()` 调用的时间框架是否与入场条件匹配 |
| `win_rate < 30%` 且 `profit_factor < 1.0` | 入场逻辑方向性错误 | 检查信号方向（long/short 是否反了）/ 入场条件逻辑是否取反 | 查看 `analyze()` 中 open_long/open_short 的触发条件 |
| `win_rate < 30%` 且 `profit_factor > 1.5` | 少数大赢覆盖多数小亏，但胜率低 | 收紧止损减少小亏损 / 加宽止盈让大赢跑更远 | 查看 `check_realtime_exit()` 止损逻辑 |
| `max_drawdown > 30%` 且 `win_rate > 50%` | 单笔亏损过大 | 收紧止损倍数 / 减小单笔仓位 | 查看 ATR 止损倍数和仓位计算 |
| `max_drawdown > 30%` 且 `win_rate < 40%` | 连续亏损累积 | 增加趋势过滤条件避免逆势（基类没有入场冷却，需要冷却须重写 `on_kline()` 且回测模式跳过） | 查看趋势判断逻辑 |
| `profit_factor < 1.0` 且 `total_trades > 30` | 频繁交易但平均亏损 | 提高入场门槛减少交易 / 加大止盈空间 | 查看 `avg_win / avg_loss` 比值，确认盈亏比 |
| `total_return < 0` 且手续费占比 > 50% | 手续费吃掉利润 | 减少交易频率 / 提高单笔最低收益要求 | 计算 `总手续费 / |总盈亏|`，确认手续费占比 |
| `短期好长期差` | 策略过拟合或市场结构变化 | 放宽参数减少过拟合 / 增加市场状态识别 | 对比短期/长期的 per_symbol_stats，找出哪个币种长期拖累 |
| `单币种好其他差` | 参数只适配特定品种 | 分币种调参 / 增加品种自适应逻辑 | 查看该策略对波动率的依赖，是否只在高波动品种有效 |

#### Step 4: 生成具体修改方案

基于 Step 3 诊断，结合 Step 2 提取的可调参数，生成修改方案：

```
📊 第 {N} 轮回测诊断:

  回测指标:
    总收益率: {total_return:.2f}% | 最大回撤: {max_drawdown:.2f}%
    胜率: {win_rate:.2f}% | 盈亏比: {profit_factor:.2f}
    交易次数: {total_trades} | 平均盈利: {avg_win:.2f} | 平均亏损: {avg_loss:.2f}
    夏普: {sharpe:.2f} | 索提诺: {sortino:.2f}

  分币对:
    {SYMBOL_1}: {trades}笔 | 胜率 {wr:.1f}% | PnL {pnl:.2f}
    {SYMBOL_2}: {trades}笔 | 胜率 {wr:.1f}% | PnL {pnl:.2f}
    {SYMBOL_3}: {trades}笔 | 胜率 {wr:.1f}% | PnL {pnl:.2f}

  诊断结论:
    主因: {诊断描述，如"入场条件过严导致交易次数不足"}
    辅因: {次要问题，如"止损偏宽导致回撤较大"}

  策略可调参数:
    {param_1}: {current} → {suggested}（{reason}）
    {param_2}: {current} → {suggested}（{reason}）
    硬编码阈值:
      {threshold_1}: {current} → {suggested}（{reason}）

  修改方案:
    1. 修改 strategies/{strategy_name}/overrides/{SYMBOL}.yaml: {具体参数变更}
    2. 修改 {prefix}_core.py: {具体代码变更}
    3. {其他修改}

  归因标记: 本轮修改维度 = {维度名，如"入场阈值"/"止损倍数"/"指标周期"}
```

#### 修改规则

1. **每轮只改一个主维度**，辅维度最多一个，确保可归因
2. **参数修改幅度**：首次调整步长为当前值的 ±20%（或参数合理范围的 1/3），后续轮次根据上轮效果缩放步长
3. **代码修改优先级**：优先调参（改 overrides YAML）→ 调阈值（改 core.py 硬编码）→ 调逻辑（改 core.py 条件判断）
4. **禁止归因模糊**：连续 2 轮修改同维度无改善，换一个本质不同的维度
5. **回撤优先**：`max_drawdown > 30%` 时优先处理风控（止损/仓位/冷却），再处理收益

### Loop 流程图

```
Phase 0: 环境预检 + 策略信息获取
  ↓
Phase 1: 脚手架创建（一次性）
  ↓
┌─────────────────────────────────────────────┐
│ Loop (最多 5 轮)                             │
│                                             │
│   Phase 2: 生成/修改策略代码                  │
│     ├── 首轮: 从 spec 生成完整代码            │
│     └── 后续轮: 根据诊断结果修改代码           │
│         ↓                                   │
│   Phase 3: 回测验证                          │
│     ├── 短期 → 中期 → 长期                   │
│     └── 解析 backtest_result.json            │
│         ↓                                   │
│   达标？ ── 是 ──→ 输出 benchmark.md         │
│     │                                       │
│     否 → 动态诊断:                           │
│       1. 解析回测 metrics + trades           │
│       2. 读取策略代码提取可调参数              │
│       3. 症状模式匹配 → 诊断结论              │
│       4. 生成修改方案 → 下一轮                │
│                                             │
│   达到最大轮次 → 输出当前最佳 + 未达标标记     │
└─────────────────────────────────────────────┘
```

---

## 环境变量清单

开源项目所有部署相关配置走环境变量，不硬编码内网 IP 或个人路径。

### 必需配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DATA_PATH` | `./data/klines` | K线数据存储路径（= settings.yaml 的 csv_dir） |
| `CTA_ENV` | `dev` | 运行环境（dev/test/prod） |
| `BENCHMARK_OUTPUT_PATH` | `./benchmark_output` | benchmark 报告输出路径 |
| `KLINE_DATA_DIR` | `./data/klines` | 共享 K线数据源目录（symlink 目标） |

### 直连下单配置（live/smoking 模式必填）

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `BINANCE_API_KEY` | （空） | 币安合约 API Key（只勾合约交易权限，勿开提现） |
| `BINANCE_API_SECRET` | （空） | 币安合约 API Secret |

> **单体模式无外部服务**：行情直连 Binance 公共源（WS 实时 + fapi 历史），
> 信号存储后由策略进程直接下单。旧版的 FACTORY_ENDPOINT / POSITION_PROXY_URL /
> KLINES_WS_URL / KAFKA 等服务地址在 v3.7 单体模式下已不存在。
> 凭证缺失且 `direct_trading.enabled=true` 时，策略进程启动即失败（不静默降级）。

### 其他可选配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `HTTPS_PROXY` / `HTTP_PROXY` | （空=直连） | 访问 Binance 公共源的代理（国内网络通常需要） |
| `LOG_LEVEL` | `INFO` | 策略进程日志级别（manager 透传） |

### .env.example 模板

以模板文件为准：`templates/.env.example`。关键字段：

```bash
DATA_PATH=./data/klines
CTA_ENV=dev
BENCHMARK_OUTPUT_PATH=./benchmark_output

# ---- 直连交易所下单（settings.yaml 的 direct_trading.enabled=true 时必填）----
BINANCE_API_KEY=
BINANCE_API_SECRET=

# ---- 代理（可选，国内网络通常需要）----
# HTTPS_PROXY=http://127.0.0.1:7890
# HTTP_PROXY=http://127.0.0.1:7890
```

---

## Claude Code 权限需求

Skill 执行时需要以下权限，应在项目 `.claude/settings.json` 中预配置：

```json
{
  "permissions": {
    "allow": [
      "Bash(cp:*)",
      "Bash(mkdir:*)",
      "Bash(ln:*)",
      "Bash(python3:*)",
      "Bash(python:*)",
      "Bash(pip:*)",
      "Bash(git init:*)",
      "Bash(git add:*)",
      "Bash(git commit:*)",
      "Bash(wc:*)",
      "Bash(ldconfig:*)",
      "Bash(source:*)",
      "Read(*)",
      "Write(*)",
      "Edit(*)"
    ]
  }
}
```

| 权限类别 | 具体操作 | 使用阶段 |
|----------|----------|----------|
| **Bash: cp/mkdir/ln** | 复制模板、创建目录、symlink K线数据 | Phase 1 |
| **Bash: python3 -m venv** | 创建虚拟环境 | Phase 1 |
| **Bash: pip install** | 安装依赖 | Phase 1 |
| **Bash: git init/add/commit** | 初始化仓库 | Phase 1 |
| **Bash: python -m backtest** | 运行回测 | Phase 3 |
| **Bash: python3 -m pytest** | 跑策略测试 | Phase 2 |
| **Bash: python3 -c** | 验证配置格式 | Phase 2 |
| **Write** | 写入策略代码、配置、spec、benchmark | Phase 2/3 |
| **Edit** | 修改策略代码与 overrides（loop 修改） | Phase 2 |
| **Read** | 读取策略文档、参考实现、回测输出 | 全流程 |

---

## Critical Constraints

### 编码红线（来自 AI_CONSTRAINTS.md，14 条禁止 + 11 条必须）

| # | 约束 | 原因 |
|---|------|------|
| 1 | 禁止入场用未闭合 K 线 | 未来函数，回测失真 |
| 2 | 禁止 `datetime.now()` 做时间戳/冷却判断 | 用 K 线时间，保证可重现 |
| 3 | 禁止 Strategy 类算指标 | 指标在 Core.analyze() 内用已闭合 K 线 |
| 4 | 禁止跳过数据不足检查 | 指标计算错误 |
| 5 | 禁止假设基类做了入场 K 线冷却 | 基类**没有**；自己实现的冷却必须在回测模式跳过 |
| 6 | 禁止自定义止损计数字段 | 用 `BaseState.stop_loss_date` |
| 7 | 禁止移动止盈记录止损日期 | 非止损，次日应可开仓 |
| 8 | 禁止外部数据注入方法/依赖外部传入指标值 | 指标从 klines_data 参数计算 |
| 9 | 禁止直接用原始 K 线入场 | 多周期必须对每个时间框架 `get_closed_data()` |
| 10 | 禁止缓存字段持久化 | 缓存不进 `to_persist_dict()` |
| 必须 | 平仓走 `_notify_exit_and_clear(..., is_stop_loss=...)` | 不要自己调 `clear_position()` |
| 必须 | 入场调 `_notify_position_enter(symbol, state)` | 漏了仓位不落盘 |
| 必须 | overrides 的 `params` 配置 `*_timeframes` | 否则该周期无数据 |

### 配置文件格式

| 规则 | 错误示例 | 正确示例 |
|------|----------|----------|
| 必须有顶层策略名键 | `name: xxx` 在顶层 | `{strategy_name}:\n  name: xxx` |
| 参数放在 params 下 | `obs_n: 20` 在顶层 | `params:\n  obs_n: 20` |
| symbols 用数组格式 | `symbol: BTCUSDT` | `symbols:\n  - BTCUSDT` |
| trading_mode 必须显式 | （缺省） | `trading_mode: "paper_trading"`（缺省按 live，会下真单） |
| 死配置不要写 | `cooldown_timeframe: 4h` | （删除——代码不读取，写了不生效） |

### 开源约束

| # | 约束 |
|---|------|
| 1 | 禁止硬编码内网 IP（`192.168.x.x`），必须走环境变量 |
| 2 | 禁止硬编码个人路径（`/home/xxx`），用相对路径或 `DATA_PATH` 环境变量 |
| 3 | 禁止在代码中写入 API Key / Secret，用 `.env` + `.gitignore` |
| 4 | 真实策略（含真实资金/风控参数）不进模板，只保留 example 参考实现 |
| 5 | 测试中 mock IP 可保留，但需加注释说明是假数据 |

---

## 执行顺序

```
用户输入:
  无参数: /trading-dev                        ← 进引导
  全自动: /trading-dev new --from <source>
  交互:   /trading-dev new
  单步:   /trading-dev scaffold | develop | backtest | benchmark
       ↓
Phase -1: 交互式引导（仅无参数时）
  ├── Step 1: 问子命令（默认 new）
  ├── Step 2: 问策略来源（new 子命令）
  └── Step 3: 汇总确认 -> 进 Phase 0
       ↓
Phase 0: 环境预检 + 策略信息获取
  ├── Step 0: 环境预检（Python/ta-lib/pip/K线数据/磁盘）
  ├── Step 1: 解析策略来源（文件/目录/URL/自然语言/多轮对话）
  ├── Step 2: 统一提取为 .strategy-spec.yaml（schema 见 docs/strategy/STRATEGY_SPEC.md）
  └── Step 3: 执行确认（全自动→直接执行 / 交互→用户确认）
       ↓
Phase 1: 脚手架创建（一次性）
  ├── 镜像复制模板（含两个参考实现）
  ├── 创建 Python venv + 安装依赖
  ├── 准备 K 线数据（symlink / download_data.py 下载，路径 {csv_dir}/{interval}/）
  ├── git init + 首次 commit
  └── 输出就绪报告
       ↓
┌─────────────────────────────────────────────┐
│ Loop (最多 5 轮)                             │
│                                             │
│   Phase 2: 生成/修改策略代码                  │
│     ├── 读规范文档 + 参考实现 example_ma_cross │
│     ├── 生成 strategy.py + {prefix}_core.py  │
│     ├── 生成 overrides/<SYMBOL>.yaml + 测试   │
│     ├── 登记 config/strategies.yaml          │
│     ├── 验证配置格式 + 跑测试                  │
│     ├── 运行审查检查表                        │
│     └── 重写/同步 README.md（场景A重写/B增量） │
│         ↓                                   │
│   Phase 3: 回测验证                          │
│     ├── 短期 → 中期 → 长期（run_backtest_batch.sh）│
│     └── 解析 backtest_result.json 的 metrics │
│         ↓                                   │
│   达标？ ── 是 ──→ 输出 benchmark.md         │
│     │                                       │
│     否 → 动态诊断:                           │
│       1. 解析回测 metrics + trades           │
│       2. 读取策略代码提取可调参数              │
│       3. 症状模式匹配 → 诊断结论              │
│       4. 生成修改方案 → 下一轮                │
│                                             │
│   最大轮次 → 输出当前最佳 + 未达标标记         │
└─────────────────────────────────────────────┘
       ↓
完成: benchmark.md 路径 + 回测结果摘要
```

---

## Related Skills

- `trading-discovery`: 指定代币/策略/时间范围的回测探索（git clone 拉策略 → 批量回测）
- `trading-replay`: 实盘信号与回测信号对比回放
- `trading-deploy`: 策略部署
