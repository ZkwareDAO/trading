---
name: trading-dev
description: CTA 策略开发全生命周期 skill（Python/Rust；crypto/期货，期货仅 Rust）。支持交互/全自动/单步三种模式。一句话输入策略逻辑 → 自动脚手架 → 策略编码 → 回测验证 → benchmark 输出。loop-engineering 跨 Phase 大闭环。期货策略不提供下载，K 线路径必须由用户提供。
origin: trading
---

# Trading Dev — CTA 策略开发全生命周期

从项目脚手架 → 策略编码 → 回测验证 → benchmark 输出，一条链路闭环。

**支持三种模式**：全自动（一句话跑到底）/ 交互（逐步确认）/ 单步（只跑指定步骤）。

**核心行为：loop-engineering**。Phase 2（策略开发）和 Phase 3（回测验证）形成跨 Phase 大闭环——回测不达标时自动回到 Phase 2 修改策略逻辑，再跑 Phase 3，循环直到达标或达到最大轮次。

## 语言与市场分流（先定，再进 Phase）

两个正交维度，必须在 Phase 0 之前确定；后续所有命令、目录、配置都按这两个取值分叉。

| 维度 | 取值 | 环境变量 | 决定 |
|------|------|----------|------|
| 语言 | `python`（默认）/ `rust` | `STRATEGY_LANG` | 模板仓库、脚手架结构、代码文件、回测命令 |
| 市场 | `crypto`（默认）/ `futures` | `STRATEGY_MARKET` | K 线获取方式、配置体系、合约口径、验收口径 |

| 组合 | 模板 | 关键差异 |
|------|------|----------|
| python + crypto | `ZkwareDAO/strategy-template` | venv + `strategies/{name}/overrides/{SYMBOL}.yaml` |
| python + futures | 不支持 | Python 模板没有 `contracts.yaml`/整数手/交易时段能力；期货只能用 Rust |
| rust + crypto | `ZkwareDAO/strategy-template-rs` | workspace crates + `config/<group>/strategy.yaml` + `download` |
| rust + futures | 同上 | 不下载数据；`roll_build` 或用户 1m CSV；`contracts.yaml` 必配 |

**硬规则**：
- 用户明确说"期货"时，`STRATEGY_LANG=rust`、`STRATEGY_MARKET=futures`；**绝不执行任何下载命令**，必须先拿到用户提供的 K 线路径（见 Phase 0 Step 0C）。
- 用户说期货但要求 Python 时：说明当前 Python 模板不支持期货撮合/合约口径，
  要么切 Rust，要么明确降级为"crypto 兼容模式"（结果不可信，不进入验收）。
- 市场未明确时按 crypto 处理，但要在执行确认里写明假设；用户后续可改。
- Rust 模式的权威参考是模板仓库的 `docs/strategy/` 与 `crates/strategies/src/`，本 skill 的命令与字段必须与其保持一致。

## When to Activate

- 用户执行 `/trading-dev`（无参数）-> **进入交互式引导**
- 用户执行 `/trading-dev new` — 创建新 CTA 策略项目（交互模式）
- 用户执行 `/trading-dev new --from <source>` — 从指定来源自动开发策略（全自动模式）
- 用户说"新建策略项目"、"创建交易项目"、"开发新策略"
- 用户说"开发期货策略"（自动进入 rust + futures 分支，先索要 K 线路径）
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

**单步子命令（develop/backtest/benchmark）时**：列出当前目录下候选项目（含 `strategy_core/` 或 `crates/strategies/` 的目录）供选择；无候选则提示先跑 `new`。

### Step 2.5 话术模板：语言与市场

```
🧭 交互式引导 - 第 2.5 步：开发语言与市场

  1. Python + crypto（默认） ← 适合快速验证，直接用 Binance 公共数据
  2. Rust + crypto           ← 模板 workspace，回测性能好
  3. Rust + futures          ← 国内期货；需你提供 K 线路径，不自动下载

请选择（默认：1）
（Python + 期货当前模板不支持；需要期货请选 3）
```

**期货选择后必须追问（阻塞项，拿不到就不进 Phase 1）**：

```
期货回测需要你提供 1m K 线，二选一：
  A. 逐合约原始 CSV 目录（文件名如 CU2612.csv；列 symbol,bob|open_time,open,high,low,close,volume,position）
  B. 已生成的 1m CSV 绝对路径（标准 10 列，timestamp 含 UTC 偏移）
交易所（SHFE/DCE/CZCE/INE）、品种代码（如 CU）、初始权益（元，够开 ≥1 手）？
```

### Step 3 话术模板：汇总确认

```
📋 引导完成 - 执行计划确认

  操作:     new（全流程）
  模式:     交互 / 全自动
  语言:     python / rust
  市场:     crypto / futures
  策略来源: <描述或 --from 来源>
  数据位置: crypto 默认下载 / futures <用户提供路径>
  （仅期货）交易所/品种/初始权益: SHFE / CU / 1000000

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

### Step 0: 环境预检（按语言/市场分叉）

#### 0A Python 模式（`STRATEGY_LANG=python`）

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

# 4. 磁盘空间（需要 ≥ 2G）
DISK_AVAIL=$(df -h . 2>/dev/null | awk 'NR==2{print $4}')
DISK_GB=$(df -BG . 2>/dev/null | awk 'NR==2{print int($4)}')
DISK_OK="0"
[ "${DISK_GB:-0}" -ge 2 ] && DISK_OK="1"
```

#### 0B Rust 模式（`STRATEGY_LANG=rust`）

**Phase 0 只做主机级预检**：项目目录此时还不存在，workspace 与 `config/contracts.yaml`
只能在 Phase 1 复制模板后检查（见 Phase 1 Step 2）。

```bash
# 1. Rust 工具链：模板 rust-toolchain.toml 钉死版本，rustup 会在项目目录自动切换
cargo --version
rustc --version
rustup show active-toolchain 2>/dev/null || true

# 2. 磁盘空间（需要 ≥ 2G，target/ 编译产物较大）
DISK_GB=$(df -BG . 2>/dev/null | awk 'NR==2{print int($4)}')
[ "${DISK_GB:-0}" -ge 2 ] && DISK_OK="1" || DISK_OK="0"
```

> Rust 版本以模板 `rust-toolchain.toml` 为准（当前 1.98.1），不要用浮动 stable 覆盖，
> 否则 `cargo fmt --check` / clippy 会因版本漂移产生无因 diff。

#### 0C K 线数据预检（按市场分叉）

**crypto**（可自动下载，Phase 0 不做项目内检查）：

项目内的 `data/klines/` 目录在 Phase 1 Step 1 复制模板后才存在，Phase 0 只记录计划、
不检查文件（非阻塞）。数据准备与落位统一在 Phase 1 Step 3 执行：

| 语言 | Phase 1 Step 3 落位路径 |
|------|------------------------|
| Python | `{project_path}/data/klines/{interval}/{SYMBOL}_{interval}.csv` |
| Rust | `{project_path}/data/klines/1m/{exchange}/{market}/{SYMBOL}_1m.csv` |

**futures**（仅 Rust 模式；禁止下载，阻塞项）：

```bash
# 期望落位：data/klines/1m/<EXCHANGE>/cn_futures/<SYMBOL>_1m.csv
# 或用户数据根目录，回测时用 --data-dir 指向
FUT_KLINE="${FUTURES_KLINES_DIR:-}"
FUT_EXCHANGE="${FUTURES_EXCHANGE:-SHFE}"
FUT_SYMBOL="${FUTURES_SYMBOL:-CU}"
if [ -n "$FUT_KLINE" ] && [ -e "$FUT_KLINE" ]; then
    echo "✅ 用户已提供期货 K 线: $FUT_KLINE"
else
    echo "❌ 期货 K 线未提供：不进入 Phase 1/3"
fi
```

**期货数据缺失时的标准处理**：

1. 若用户给逐合约 CSV 目录（文件名 `{PRODUCT}{YYMM}.csv`，列
   `symbol,bob|open_time,open,high,low,close,volume,position`），执行：

   ```bash
   cargo run -p strategy-data --bin roll_build -- \
     --in <用户目录> --product <PRODUCT> --out <临时输出目录>
   cp <临时输出目录>/1m/<PRODUCT>_CONT_1m.csv \
      data/klines/1m/<EXCHANGE>/cn_futures/<PRODUCT>_1m.csv
   ```

   `roll_build` 按持仓量选主、只在下一交易日生效（因果口径），不做复权。
2. 若用户给已生成的 1m CSV，确认是标准 10 列（`timestamp` 带 UTC 偏移）后放到
   上述路径，或回测时 `--data-dir <用户数据根>`。
3. 两者都没有：**停止，不得回测**。禁止用 mock、合成、其他品种或其他区间数据顶替；
   禁止把"没跑"写成"跑通"。

**预检结果映射**：

| 检测项 | 阶段 | ✅ 条件 | ❌ 时的提示 |
|--------|------|---------|------------|
| Python 3.10+（仅 Python） | Phase 0 | `PYTHON_CMD` 非空 | Ubuntu: `sudo apt install python3.12 python3.12-venv` / macOS: `brew install python@3.12` |
| pip（仅 Python） | Phase 0 | `PIP_AVAILABLE = 1` | `python3 -m ensurepip` |
| ta-lib C 库（仅 Python） | Phase 0 | `TALIB_FOUND ≥ 1` | `wget ...ta-lib... && ./configure && make && sudo make install && ldconfig` |
| Rust 工具链（仅 Rust） | Phase 0 | `cargo --version` 成功 | `curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh` |
| 磁盘空间 ≥ 2G | Phase 0 | `DISK_OK = 1` | 清理空间或更换数据目录 |
| futures K 线（用户路径） | Phase 0 | 用户路径非空且存在 | **阻塞**：按上面二选一索要，拿不到就停 |
| workspace 可解析（仅 Rust） | Phase 1 Step 2 | `cargo metadata` 成功 | 检查 `rust-toolchain.toml`、网络与 `Cargo.lock` |
| `config/contracts.yaml`（仅期货） | Phase 1 Step 2 | 文件存在且 symbol 已声明 | **阻塞**：先补合约参数，否则会静默退化成 crypto 兼容模式 |
| crypto K 线 | Phase 1 Step 3 | symlink 或下载完成 | 自动准备（非阻塞） |

**阻塞项处理**：
- **Phase 0（主机级）**：Python/pip（Python 模式）、Rust 工具链（Rust 模式）、
  期货用户 K 线路径不达标 → 报错退出，不进入 Phase 1。
- **Phase 1 Step 2（项目级）**：workspace 不可解析、期货 `contracts.yaml` 缺失或未声明
  symbol → 报错退出，不进入 Phase 2。

**非阻塞项处理**：ta-lib 缺失 → 降级安装核心依赖；crypto K 线缺失 → Phase 1 Step 3
自动下载；磁盘不足 → 警告继续。

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

**Rust 策略目录**读取位置：

```python
files_to_read = [
    f"{strategy_dir}/crates/strategies/src/*.rs",   # strategy_type/timeframes/入场出场逻辑
    f"{strategy_dir}/config/*/strategy.yaml",       # universe/timeframes/params/risk/sizing
    f"{strategy_dir}/config/contracts.yaml",        # 期货合约参数（market=futures 判据）
    f"{strategy_dir}/docs/strategy/specs/*.strategy-spec.yaml",
]
# 提取映射
# strategy_type() / register_strategy! name → strategy_name
# universe.exchange / contracts.yaml → market（binance/bybit=crypto；SHFE/DCE/CZCE/INE=futures）
# timeframes[0] → 主周期；params → default_params；entry/exit/stop → spec 条件
```

**c. URL** → WebFetch → 解析 → 项目路径: `{cwd}/{strategy_name}`

**d. 自然语言** → 从描述提取策略规格 → 项目路径: `{cwd}/{strategy_name}`

**e. 无输入** → 多轮对话收集：

```
1. 项目路径？（默认: ./{strategy_name}）
2. 开发语言？（python / rust）
3. 市场？（crypto / futures）
4. 策略名称？（如 ema_rsi_pullback；Rust 时同时是 crates/strategies/src/{name}.rs 与注册名）
5. 策略前缀？（如 EMA_RSI；Rust 可留空）
6. 交易方向？（long / short / neutral）
7. 主时间框架？（如 4h；期货常用 15m / 1h）
8. 交易标的与交易所？（crypto: BTCUSDT/binance；futures: CU/SHFE）
9. 期货专属：1m K 线路径（逐合约目录或已生成的 CSV）、初始权益（元）
10. 入场条件描述？（自然语言）
11. 出场条件描述？（止损/止盈/移动止盈；不许静默发明止损）
```

> 期货未拿到 K 线路径时，只收集信息、不生成脚手架、不进入 Phase 1。

> **项目路径规则**：默认 `{cwd}/{strategy_name}`。如果目录已存在，追加 `_v2`、`_v3` 等后缀避免覆盖。

### Step 2: 统一提取为策略规格（.strategy-spec.yaml）

所有输入形态收敛到同一个结构。**字段 schema 见模板 `docs/strategy/STRATEGY_SPEC.md`**（生成前必须先读它）：

```yaml
strategy_name: ema_rsi_pullback
rust_module: ema_rsi_pullback   # Rust: crates/strategies/src/{rust_module}.rs；Python 可省略
prefix: EMA_RSI
market: crypto                 # crypto / futures；缺省按 exchange 推断
direction: neutral
timeframes: [4h, 1h]          # [0] 必须是触发主周期（Rust 不写 1m，框架强制含 M1）
extra_timeframes: [1d]        # 可选：除主周期外订阅的其他周期
symbols: [BTCUSDT, ETHUSDT, SOLUSDT]
data_source:                   # 期货必填；crypto 可写默认路径/下载命令
  dir: data/klines             # 或 files: [/abs/path/CU_1m.csv]
  note: "期货目标路径 data/klines/1m/SHFE/cn_futures/CU_1m.csv"
backtest:                      # 回测区间；期货必须给 initial_cash
  start: "20260601"
  end: "20260709"
  initial_cash: 1000000

entry:
  description: "EMA 交叉 + RSI 回踩确认"
  conditions:                  # 条件逐条列，生成代码时一条对应一个判断
    - "快线上穿慢线"
    - "RSI 回踩至 40-60 区间后反弹"

exit:
  stop_loss: "2 倍 ATR"        # 硬止损规则；不做空字符串；未指定止损先问用户
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

default_params:                # Core.__init__ / Params::default() 读取的参数及默认值
  ema_fast_period: 20
  ema_slow_period: 60
```

> **参考范例**：
> - Rust：`docs/strategy/specs/*.strategy-spec.yaml`（含 `futures_single_trend`、
>   `futures_xsec_trend` 期货样例）；schema 见 `docs/strategy/STRATEGY_SPEC.md`。
> - Python：`strategies/example_ma_cross/.strategy-spec.yaml`（单周期）、
>   `strategies/example_mtf_trend/.strategy-spec.yaml`（多周期）。
>
> **期货硬约束**：`data_source` 必须来自用户；`default_params` 不得出现乘数/保证金率/
> 手续费/交易时段（这些属于 `config/contracts.yaml`）；`backtest.initial_cash` 必填。

### Step 3: 执行确认（按模式）

**全自动模式**：按下方语言分叉路径自动保存 `.strategy-spec.yaml`，直接进入 Phase 1。

```
📋 策略: ema_rsi_pullback | EMA_RSI | neutral | [4h,1h] | [BTCUSDT,ETHUSDT,SOLUSDT]
📋 语言/市场: {python|rust} / {crypto|futures}
🔧 环境: 工具链 ✅ | 数据 ✅(crypto 自动下载 / futures 用户路径) | 磁盘 15G ✅
🚀 自动执行 loop-engineering 模式...
```

**交互/半交互模式**：展示完整信息，用户确认后执行。

```
📋 环境预检:
  语言: Rust (cargo 1.x / rust-toolchain.toml) 或 Python 3.12
  市场: crypto / futures
  Python 3.12: ✅（仅 Python）
  ta-lib C 库: ⚠ 未装（参考实现为纯 pandas，不阻塞；需要 talib 指标时再装）
  Rust 工具链: ✅（cargo/rustc；workspace 与 contracts.yaml 在 Phase 1 校验）
  K 线数据: ✅ (crypto Phase 1 自动下载) / ✅ (futures 用户路径: <path>)
  contracts.yaml: Phase 1 模板复制后校验（仅期货）
  磁盘空间: ✅ (15G 可用)

📋 策略解析结果:
  名称: ema_rsi_pullback
  语言/市场: rust / futures
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

用户确认后，保存 `.strategy-spec.yaml` 到项目内的最终路径（按语言分叉）：

| 语言 | 落盘路径 |
|------|----------|
| Python | `{project_path}/strategies/{strategy_name}/.strategy-spec.yaml` |
| Rust | `{project_path}/docs/strategy/specs/{strategy_name}.strategy-spec.yaml` |

项目目录此时可能尚不存在：先 `mkdir -p` 目标目录再写文件；Phase 1 Step 1 用
`tar` 镜像复制（排除 `.git`），合并写入不会删除已落盘的 spec。保存后进入 Phase 1。

---

## Phase 1: 项目脚手架创建

### 模式行为差异

| 步骤 | 交互模式 | 全自动模式 | 半交互模式 |
|------|----------|-----------|-----------|
| 复制模板 | 执行后展示文件列表 | 静默执行 | 执行后展示文件列表 |
| Python 环境 / Rust 工具链 | 展示安装或自检结果 | 静默执行，失败时降级/报错 | 展示结果 |
| K 线数据 | 展示准备方式（crypto symlink/下载；futures 用户路径） | crypto 自动下载；futures 只用用户路径 | 展示准备方式 |
| Git init | 展示首次 commit | 静默执行 | 静默执行 |
| 就绪报告 | 展示完整报告 | 展示单行摘要 | 展示完整报告 |

**单步模式**：`/trading-dev scaffold` 只执行 Phase 1，执行后退出。

### Step 1: 复制模板代码

从 GitHub 仓库克隆模板代码到新项目。

**模板来源**：
- Python: `https://github.com/ZkwareDAO/strategy-template.git`
- Rust: `https://github.com/ZkwareDAO/strategy-template-rs.git`

```bash
# 根据 STRATEGY_LANG 选择仓库
STRATEGY_LANG="${STRATEGY_LANG:-python}"
if [ "$STRATEGY_LANG" = "rust" ]; then
    TEMPLATE_REPO="https://github.com/ZkwareDAO/strategy-template-rs.git"
    # Rust 默认跟 main：strategy.yaml / 期货模板尚未打进 v1.0.0 tag
    TEMPLATE_TAG="${STRATEGY_TEMPLATE_TAG:-}"
else
    TEMPLATE_REPO="https://github.com/ZkwareDAO/strategy-template.git"
    TEMPLATE_TAG="${STRATEGY_TEMPLATE_TAG:-v1.0.0}"
fi
TEMPLATE_TMP=""
CLONE_FAILED="0"

# 本机已有最新模板（如 /home/qpw/workspace/strategy-template-rs）时优先用本地，
# 避免 GitHub tag 落后于当前开发线
if [ -n "${TRADING_DEV_TEMPLATE_DIR:-}" ] && [ -d "${TRADING_DEV_TEMPLATE_DIR:-}" ]; then
    TEMPLATE_DIR="$TRADING_DEV_TEMPLATE_DIR"
else
    TEMPLATE_TMP=$(mktemp -d)
    TEMPLATE_DIR="$TEMPLATE_TMP"
    if [ -n "$TEMPLATE_TAG" ]; then
        git clone --depth 1 --branch "$TEMPLATE_TAG" "$TEMPLATE_REPO" "$TEMPLATE_DIR" || CLONE_FAILED="1"
    else
        git clone --depth 1 "$TEMPLATE_REPO" "$TEMPLATE_DIR" || CLONE_FAILED="1"
    fi
fi

if [ "$CLONE_FAILED" = "1" ]; then
    rm -rf "$TEMPLATE_TMP"
    echo "❌ 模板克隆失败：检查网络，或设置 TRADING_DEV_TEMPLATE_DIR 指向本地模板"
    exit 1
fi
```

**复制列表（全量镜像）**：模板即完整可运行项目，整体复制：

| 源路径 | 说明 |
|--------|------|
| `strategy_core/` | 基类框架（BaseStrategy/BaseState/BaseStrategyCore + 统一风控） |
| `backtest/` | 回测引擎（run_backtest / batch_runner） |
| `data_manager/` | K线数据管理（CSV + WS + 多时间框架聚合） |
| `scripts/` | `download_data.py` / `run_backtest_batch.sh` / `run_live_batch.sh` / `resample_1m_to_multi_tf.py` |
| `config/` | 三层配置（settings.yaml / strategies.yaml / backtest.yaml run-profile），全部入库 |
| `strategies/` | 参考实现（example_ma_cross 单周期、example_mtf_trend 多周期）+ README |
| `tests/` | 根级测试 |
| `docs/` | 全部文档（strategy/ 五件套 + STRATEGY_SPEC.md 等） |
| `requirements*.txt` | 依赖清单 |
| `.gitignore` / `.env.example` | 排除规则 / 环境变量模板 |
| `run_strategies_manager.py` / `run_strategy.py` | 入口 |
| `start.sh` / `stop.sh` | 启停脚本 |
| `CLAUDE.md` / `README.md` / `ARCHITECTURE.md` | 项目文档 |

**Rust 模式复制列表（全量镜像 workspace）**：

| 源路径 | 说明 |
|--------|------|
| `Cargo.toml` / `Cargo.lock` / `rust-toolchain.toml` / `rustfmt.toml` | workspace 定义、依赖锁、钉死工具链 |
| `crates/core/` | Candle/Timeframe、Signal/订单状态机、Strategy trait、风控 |
| `crates/engine/` | 回测/live 共用引擎、策略端口 `CrossSectionalStrategyPort`、配置校验 |
| `crates/strategies/` | 策略插件 + `build.rs` 自动发现 + 6 个参考实现；新策略只加 `.rs` |
| `crates/data/` | CSV 存储、1m 聚合、`roll_build`（期货主力连续）、归档下载 |
| `crates/signals/` / `crates/positions/` / `crates/store/` | 信号状态机、仓位账本、统一 Store |
| `crates/broker/` / `crates/indicators/` | trading-service 客户端/回测撮合、指标库 |
| `crates/app/` | CLI（`backtest` / `run` / `download` / `inspect`）与报告输出 |
| `config/` | `contracts.yaml` + 各 `config/<group>/strategy.yaml` + `_global.yaml` 样例 |
| `scripts/` | `run_backtest_matrix.sh`（批量矩阵）、`collect_reports.py`、`prepare_ctp_1m.py` |
| `docs/` | `docs/strategy/` 规范集 + `docs/design-package/` 架构 + `RUNBOOK.md` |
| `contracts/` | trading-service 消息契约 |
| `.gitignore` / `README.md` / `CHANGELOG.md` | 排除规则 / 项目说明 |

**不复制**（模板中已排除，或复制时显式排除，此处列出原因）：

| 排除项 | 原因 |
|--------|------|
| `.git/` | 模板仓库历史与 origin 会污染新项目；新项目由 Step 4 重新 `git init` |
| `.env` | 含真实凭证/HMAC 密钥，只保留本地副本或由用户创建 |
| `target/`、`backtest_output/`、`data/state*`、`logs/` | 编译/运行产物 |
| `data/klines/` 下的真实行情 | 体积大且按市场授权，不随模板分发 |
| `strategy.config.yaml` | 本地联调配置（含密钥） |

> Rust 模板的 `config/_global.yaml` 在 `.gitignore` 中（含 HMAC 密钥），
> 脚手架必须从 `config/_global.example.yaml` 复制生成，并提醒用户填写
> `services.trading`；缺失会在 `run` 时 fail-fast（`backtest` 不依赖它）。

**复制命令**：

```bash
TEMPLATE_DIR="{克隆的模板目录}"
PROJECT_DIR="{project_path}"
mkdir -p "$PROJECT_DIR"

# 整体镜像复制，排除模板自身的 .git：新项目不继承模板 history/origin，
# 首个 commit 由 Step 4 的 git init 产生
tar --exclude=.git -C "$TEMPLATE_DIR" -cf - . | tar -C "$PROJECT_DIR" -xf - \
    || { echo "❌ 模板复制失败"; exit 1; }

if [ "$STRATEGY_LANG" = "rust" ]; then
    # Rust 模板的 _global.yaml/.env 不入库，需从 example 生成本地副本
    [ -f "$PROJECT_DIR/config/_global.example.yaml" ] && \
        cp "$PROJECT_DIR/config/_global.example.yaml" "$PROJECT_DIR/config/_global.yaml"
    # .env 由用户按需创建（STRATEGY_SECRET / 代理等），不要写入密钥
    echo "⚠ 请自行创建 .env 并填写 STRATEGY_SECRET / HTTP(S)_PROXY（勿入库）"
else
    # Python 模板保留 .env.example → .env
    cp $PROJECT_DIR/.env.example $PROJECT_DIR/.env
fi

# spec 已在 Phase 0 落盘；镜像复制只写入模板文件，不删除它，这里只校验路径正确
if [ "$STRATEGY_LANG" = "rust" ]; then
    SPEC_FILE="$PROJECT_DIR/docs/strategy/specs/{strategy_name}.strategy-spec.yaml"
else
    SPEC_FILE="$PROJECT_DIR/strategies/{strategy_name}/.strategy-spec.yaml"
fi
test -f "$SPEC_FILE" || { echo "❌ spec 缺失或路径错误: $SPEC_FILE"; exit 1; }

# 只清理本次自行克隆的临时目录；本地模板（TRADING_DEV_TEMPLATE_DIR）绝不删除
if [ -n "$TEMPLATE_TMP" ]; then
    rm -rf "$TEMPLATE_TMP"
fi
```

> **与旧版差异**：v3.7 模板即完整可运行项目（单体模式，直连 Binance 公共行情），
> 无需再从 `.example` 生成运行时配置——`config/` 三层全部入库，
> 新策略登记进 `config/strategies.yaml` 即可。
> **Rust 版差异**：`config/_global.yaml` 与 `.env` 是 gitignore 的本地文件，
> 必须显式生成；`strategy.yaml` 才是入库的策略级配置。

### Step 2: 初始化开发环境（按语言分叉）

#### Python 模式（`STRATEGY_LANG=python`）

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

#### Rust 模式（`STRATEGY_LANG=rust`）

无 venv、无 pip；依赖由 cargo 解析，工具链由 `rust-toolchain.toml` 钉死。

```bash
cd {project_path}

# 1. 工具链与依赖就绪（首次较慢）
rustup show active-toolchain

# 2. workspace 可解析（Phase 0 无法检查：项目当时还不存在；失败即阻塞）
cargo metadata --no-deps --format-version 1 >/dev/null
cargo fetch

# 3. 基线自检：必须全绿，失败不进入 Phase 2
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test --workspace

# 4. 期货额外确认：合约参数已声明
#    config/contracts.yaml 必须包含目标 symbol（CU/AU/AG/RB/RU/I 等）
grep -q "^\s*${FUTURES_SYMBOL}:" config/contracts.yaml && echo "✅ contracts OK"
```

> Rust 模式不安装 Python 依赖，也不跑 ta-lib 检测；若 `cargo test --workspace`
> 失败，先修模板基线，不要带着红灯写新策略。

### Step 3: 准备回测 K 线数据（按市场分叉）

#### Python + crypto

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

#### Rust + crypto

Rust 的加载器只认 `{data_dir}/1m/{exchange}/{market}/{SYMBOL}_1m.csv`，
crypto 的 exchange=`binance`、market=`crypto_perpetual`：

```bash
cd {project_path}
DATA_DIR="${DATA_PATH:-./data/klines}"

mkdir -p "$DATA_DIR/1m/binance/crypto_perpetual"
# 已有共享数据 → symlink（零拷贝）；路径必须是 1m/<exchange>/<market>/<SYM>_1m.csv
if [ -f "${KLINE_DATA_DIR:-}/1m/binance/crypto_perpetual/BTCUSDT_1m.csv" ]; then
    ln -sf "$KLINE_DATA_DIR"/1m/binance/crypto_perpetual/*.csv \
           "$DATA_DIR/1m/binance/crypto_perpetual/" 2>/dev/null
else
    # 无共享数据 → 下载（Binance 公共归档/fapi，无需 API key）
    cargo run -p strategy-app -- download \
        --symbol BTCUSDT --symbol ETHUSDT --symbol SOLUSDT \
        --interval 1m --days 365 --data-dir "$DATA_DIR"
fi
```

> 手工放置的 CSV 需标准 10 列
> `timestamp,open,high,low,close,volume,quote_volume,trade_num,active_buy_volume,active_buy_quote_volume`
> （旧 6 列兼容，扩展列缺省 0）；`timestamp` 必须带 UTC 偏移。

#### 期货（仅 Rust 模式，禁止下载）

模板**不附带期货行情**，也没有自动下载命令。必须由用户二选一提供：

```bash
# A. 逐合约原始 CSV 目录 → 生成主力连续 1m
cargo run -p strategy-data --bin roll_build -- \
    --in <用户目录> --product <PRODUCT> --out <临时输出目录>
# 输出 {out}/1m/{PRODUCT}_CONT_1m.csv 与 {out}/roll_events.csv
cp <临时输出目录>/1m/<PRODUCT>_CONT_1m.csv \
   data/klines/1m/<EXCHANGE>/cn_futures/<PRODUCT>_1m.csv

# B. 用户已生成的 1m CSV → 直接落位（或回测时 --data-dir 指向其根目录）
mkdir -p data/klines/1m/<EXCHANGE>/cn_futures
cp <用户CSV路径> data/klines/1m/<EXCHANGE>/cn_futures/<SYMBOL>_1m.csv
```

**硬规则**：
- 期货 symbol 必须已在仓库根 `config/contracts.yaml` 声明；未声明会静默退化为
  crypto 兼容模式（小数数量 + `fee_rate`），结果不可信。
- 回测区间必须落在用户数据覆盖范围内；不足时先向用户要更长数据，不得用其他
  品种/区间顶替。
- `_global.yaml` 必须显式 `initial_cash`（元），且按 universe 等分后仍够开 ≥1 手。
- 禁止 mock/合成/占位文件回测；没数据就停在 Phase 1，并把缺口写进交付说明。

**验证数据就绪**：

```bash
if [ "$STRATEGY_MARKET" = "futures" ]; then
    FUT_FILE="data/klines/1m/${FUTURES_EXCHANGE:-SHFE}/cn_futures/${FUTURES_SYMBOL:-CU}_1m.csv"
    [ -f "$FUT_FILE" ] && echo "✅ 期货 1m 数据就绪: $FUT_FILE ($(wc -l < "$FUT_FILE") 行)" \
                      || echo "❌ 期货 1m 数据缺失，禁止回测: $FUT_FILE"
elif [ "$STRATEGY_LANG" = "rust" ]; then
    RUST_FILE="${DATA_PATH:-./data/klines}/1m/binance/crypto_perpetual/BTCUSDT_1m.csv"
    [ -f "$RUST_FILE" ] && echo "✅ 1m kline 数据就绪: $RUST_FILE ($(wc -l < "$RUST_FILE") 行)" \
                       || echo "⚠ 1m kline 数据未就绪，回测将报「区间无 1m 数据」"
else
    PY_FILE="${DATA_PATH:-./data/klines}/1m/BTCUSDT_1m.csv"
    [ -f "$PY_FILE" ] && echo "✅ 1m kline 数据就绪: BTCUSDT $(wc -l < "$PY_FILE") 行" \
                      || echo "⚠ 1m kline 数据未就绪，回测将失败"
fi
```

### Step 4: 初始化 Git

```bash
cd {project_path}
git init
# 模板 .git 已在 Step 1 排除，此处生成全新仓库；.gitignore 来自模板（含 data/、.env 排除规则）
git add .
git commit -m "init: scaffold from strategy-template"
```

> `.env` 已在模板 `.gitignore` 中排除，不会误提交。

### Step 5: 输出就绪报告

```
✅ 项目脚手架创建完成

项目路径: {project_path}
语言/市场: {STRATEGY_LANG} / {STRATEGY_MARKET}
Python 环境: .venv (Python 3.x) / Rust: cargo + rust-toolchain.toml
依赖安装: ✅ / ⚠️ (ta-lib 需手动安装；Rust 基线 cargo test 结果)
kline 数据: ✅ (crypto symlink/下载) / ✅ (futures 用户路径) / ⚠️ (需用户补数据)

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

**Rust 模式项目结构（就绪报告用）**：

```
{strategy_name}/
├── Cargo.toml / Cargo.lock / rust-toolchain.toml
├── crates/
│   ├── core/ engine/ signals/ positions/ store/ data/
│   ├── broker/ indicators/ app/
│   └── strategies/
│       ├── build.rs                    # 自动发现 src/*.rs，无需手改
│       ├── src/
│       │   ├── registry.rs             # 冻结：register_strategy! 宏
│       │   ├── example_dual_ma.rs      # crypto 单标参考
│       │   ├── xsec_template.rs        # 横截面模板
│       │   ├── futures_single_trend.rs # 期货 1:1 参考
│       │   ├── futures_xsec_trend.rs   # 期货 1:N 参考
│       │   └── {strategy_name}.rs      # ⬅ Phase 2 生成
│       └── tests/
├── config/
│   ├── contracts.yaml                  # 期货乘数/保证金/费率/时段（唯一来源）
│   ├── _global.yaml                    # 本地生成（gitignore），运行模式/权益/services
│   └── {strategy_name}/
│       ├── strategy.yaml               # ⬅ Phase 2 生成（策略级配置）
│       └── _global.yaml                # 可选：本组权益/初始资金
├── docs/strategy/
│   ├── AI_WORKFLOW.md / AI_CONSTRAINTS.md / CONFIG_REFERENCE.md
│   ├── CRYPTO_VS_FUTURES.md / REVIEW_CHECKLIST.md
│   └── specs/{strategy_name}.strategy-spec.yaml
├── scripts/run_backtest_matrix.sh
├── data/klines/1m/<exchange>/<market>/<SYMBOL>_1m.csv
├── backtest_output/                    # 运行产物
└── README.md / CHANGELOG.md
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

**单步模式**：`/trading-dev develop` 只执行 Phase 2（需要已有脚手架和 `.strategy-spec.yaml`：
Python `strategies/{name}/.strategy-spec.yaml`；Rust `docs/strategy/specs/{name}.strategy-spec.yaml`）。

### Step 0: 加载规范文档 + 参考实现（强制）

**必须先读取以下文档与参考代码到上下文，确保生成的代码符合项目规范**：

```
docs/strategy/QUICKSTART.md           # Step 0 要求先读参考实现；目录结构、命名规范、代码模板
docs/strategy/DEVELOPMENT_GUIDE.md    # 基类功能、平仓方法、冷却机制
docs/strategy/AI_CONSTRAINTS.md       # 编码红线（14 条禁止 + 11 条必须）
docs/strategy/REVIEW_CHECKLIST.md     # 提交前检查项（10 类）
docs/strategy/EXAMPLES.md             # 常见问题与踩坑
docs/strategy/STRATEGY_SPEC.md        # spec 字段 schema

# Python 模式参考实现
strategies/example_ma_cross/          # ⬅ 单周期参考实现（必读，QUICKSTART Step 0 强制）
  ├── strategy.py                     # Strategy 接口层（最简形态）
  ├── example_ma_cross_core.py        # Core 逻辑层（★ 注释是框架契约重点）
  ├── overrides/BTCUSDT.yaml          # per-symbol 配置逐字段注释
  └── tests/                          # 测试写法

# Rust 模式规范文档（模板 docs/strategy/）
docs/strategy/AI_WORKFLOW.md         # 从用户逻辑到可回测策略的流程 + 开工信息清单
docs/strategy/AI_CONSTRAINTS.md      # 23 条禁止 + 12 条必须（含期货红线）
docs/strategy/CONFIG_REFERENCE.md    # strategy.yaml/_global.yaml/contracts.yaml 字段
docs/strategy/CRYPTO_VS_FUTURES.md   # crypto/期货五层差异
docs/strategy/DEVELOPMENT_GUIDE.md   # StrategyBase / 策略端口 / 仓位模型
docs/strategy/XSEC_GUIDE.md          # 横截面（1 策略 → 1 总仓 → N 子仓）
docs/strategy/POSITION_MODEL.md      # 仓位与容量口径
docs/strategy/REVIEW_CHECKLIST.md    # 提交前检查单
docs/strategy/STRATEGY_SPEC.md       # spec 字段 schema
docs/strategy/specs/*.strategy-spec.yaml  # 6 个模板 spec（含期货）

# Rust 模式参考实现（按市场/形态选一个复制）
crates/strategies/src/example_dual_ma.rs      # crypto 单标（直接 port，最小）
crates/strategies/src/example_mtf_trend.rs    # crypto 多周期
crates/strategies/src/xsec_template.rs        # crypto 横截面模板
crates/strategies/src/xsec_momentum.rs        # crypto 横截面示例
crates/strategies/src/futures_single_trend.rs # 期货 1:1（整数手 + 时段）
crates/strategies/src/futures_xsec_trend.rs   # 期货 1:N（乘数 + top_k）
config/example_dual_ma/strategy.yaml          # crypto 单标配置样例
config/example_dual_ma_cu/strategy.yaml       # 同一代码跑 CU 期货
config/ctp_single_cu/strategy.yaml            # 期货单标（组内 _global 配 initial_cash）
config/ctp_multi_xsec/strategy.yaml           # 期货多标（merge_positions + rebalance）
```

**Rust 选型决策树**（照 `docs/strategy/AI_WORKFLOW.md` §3）：

```text
单标 N=1：crypto → example_dual_ma；futures → futures_single_trend
多标 N>1：crypto → xsec_momentum；futures → futures_xsec_trend
只写五个钩子 → 用 StrategyBase（common/mod.rs），实现 name/top_k/score/entry_allowed/stop
```

**多周期策略额外必读**：
- Python：`strategies/example_mtf_trend/`（1d 定方向 + 4h 触发 + 1h 确认）
- Rust：`crates/strategies/src/example_mtf_trend.rs`（演示多周期 `series.closed(tf)` 只读已闭合序列的标准写法）

### Step 1: 生成策略代码

**Python 模式**按 `docs/strategy/QUICKSTART.md` 规范生成 1.1–1.6 文件；
**Rust 模式**跳到 §1.7，生成策略 `.rs` + `strategy.yaml` + spec，不生成 Python 文件。

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

**两个核心方法的完整签名**（必须照抄，参数名错了基类调用即 TypeError）：

```python
def analyze(self, symbol, klines_data, current_time=None,
            realtime_price=None, current_cash=None) -> Dict[str, Any]:
    # klines_data: {timeframe: DataFrame}，由基类 _fetch_multi_timeframe_data()
    #   按 _get_indicator_timeframes() 收集的周期从 data_manager 取出
    ...

def check_realtime_exit(self, symbol, current_price, current_time=None,
                        bar_high=None, bar_low=None) -> Dict[str, Any]:
    # 注意：出场侧不传 klines_data！指标性出场需要数据时无法在 Core 内取
    # （Core 不持有 data_manager）。照参考实现只做价格止损；指标性出场
    # 放 analyze() 的反向信号，通用风控（回落止盈/固定止盈）由 overrides
    # 的 risk 段兜底。出场开头必须调 state.update_pnl_extremes(current_price)。
    ...
```

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

#### 1.7 Rust 模式：生成策略文件（替代 1.1–1.6）

Rust 模式只生成 3 类文件，**不改** `build.rs` / `registry.rs` / `lib.rs`（接线区冻结）：

| 文件 | 内容 |
|------|------|
| `crates/strategies/src/{strategy_name}.rs` | `Params` + 策略实现 + `register_strategy!` + `#[cfg(test)]` |
| `config/{group}/strategy.yaml` | 策略级配置（`strategy_type` 对齐注册名） |
| `docs/strategy/specs/{strategy_name}.strategy-spec.yaml` | Phase 0 产出的 spec 落盘 |

按市场/形态从决策树复制模板后，只改：类型名、`Params`、打分/入场/止损逻辑、
`register_strategy!` 的 name。最小骨架（单标示例，N>1 在
`on_cross_section_bars` 里遍历快照即可，同一份代码不分叉）：

```rust
//! {strategy_name} — {一句话策略逻辑}
//! 入场：{user entry}；出场：{user exit}；止损：{user stop}
use serde::Deserialize;
use strategy_core::candle::Timeframe;
use strategy_core::signal::Side;
use strategy_engine::bridge::CandleSeries;
use strategy_engine::core::bar::Timeframe as EngineTimeframe;
use strategy_engine::strategy::port::{
    CrossSectionalStrategyPort, InstrumentAction, InstrumentSnapshot, PortfolioContext,
};

/// 私有参数；deny_unknown_fields 让配置写错字段名在启动时即报错
#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields, default)]
pub struct Params {
    pub fast_period: usize,
    pub slow_period: usize,
    pub stop_loss_pct: f64,
}

impl Default for Params {
    fn default() -> Self {
        Self { fast_period: 20, slow_period: 60, stop_loss_pct: 2.0 }
    }
}

pub struct MyStrategy {
    params: Params,
    main_tf: Timeframe,
}

impl CrossSectionalStrategyPort for MyStrategy {
    fn strategy_type(&self) -> &str { "{strategy_name}" }

    // M1 必须保留：引擎据此聚合；其余是用户周期
    fn timeframes(&self) -> Vec<EngineTimeframe> {
        vec![EngineTimeframe::M1, EngineTimeframe::from(self.main_tf)]
    }

    fn on_cross_section_bars(
        &mut self,
        _newly_closed: &[EngineTimeframe],
        snapshots: &[InstrumentSnapshot],
        _portfolio: &PortfolioContext,
    ) -> Vec<InstrumentAction> {
        let mut out = Vec::new();
        for s in snapshots {
            // 数据过期只跳过本标的；有仓时的出场不能被 entry_eligible 门控
            if s.stale {
                continue;
            }
            let Some(series) = s.closed.as_ref() else { continue };
            // 只读已闭合：series.closed(tf) → Option<&[Candle]>，长度不足直接 return
            let Some(candles) = series.closed(self.main_tf) else { continue };
            if candles.len() < self.params.slow_period + 1 {
                continue;
            }

            // ① 有仓（s.position 为 Some）：
            //    先判 pos.stop_price 硬止损，再判用户反向出场；命中则 push
            //    InstrumentAction::Close { is_stop_loss: true/false, ... }，然后 continue。
            // ② 空仓：先看 s.entry_eligible，再判用户入场条件；满足才 push
            //    InstrumentAction::Open { side, price, stop_price, ... }。
            //    止损价示例：price ∓ price * stop_loss_pct / 100；Open 必须带 stop_price。
        }
        out
    }
}

// 文件尾唯一必须的接线；name 必须 == strategy_type() == 配置文件 strategy_type
crate::register_strategy! {
    name: "{strategy_name}",
    factory: |args| {
        let main_tf = Timeframe::parse(args.timeframe)?;
        let params: Params = crate::registry::params_or_default(args.params)?;
        Ok(Box::new(MyStrategy { params, main_tf }))
    }
}
```

**Rust 策略文件必须包含**：

- `Params` 的 `deny_unknown_fields + Default`，且默认值与 `strategy.yaml` 的 `params` 一致。
- `timeframes()` 含 `EngineTimeframe::M1`（配置里不写 1m）。
- `Open` 必须带 `stop_price`；没有止损时先问用户或显式写明假设，不得静默发明。
- 期货：目标数量从 `portfolio.multipliers` 取乘数，不写死；不要自己算手数/保证金/手续费/时段。
- `#[cfg(test)]`：至少入场（多/空）+ 出场；期货补 `multiplier != 1`、整数手取整、
  时段聚合用例。测试用 `CandleSeries::from_closed` 喂合成已闭合 K 线。

**配置样例（期货单标；crypto 把 universe 换成 `{BTCUSDT, binance}`、去掉 initial_cash）**：

```yaml
# config/{group}/strategy.yaml
strategy_type: {strategy_name}
strategy_id: {strategy_name}:{symbol_lower}
universe:
  - { symbol: {SYMBOL}, exchange: {EXCHANGE} }
timeframes: [{base_tf}, {higher_tf}]
indicators: {}
entry:  { default: [] }
exit:   { default: [] }
portfolio_exit: { stop_loss_pct: 8 }
risk:   { max_total_notional: 1.0 }
sizing: { per_position_pct: 1.0 }
params: { ...与 Params::default() 一致... }
```

```yaml
# config/{group}/_global.yaml（期货必须有 initial_cash；crypto 可省）
mode: paper_trading
warmup_days: 60
initial_cash: 1000000   # 元；按 universe 等分后仍需够开 ≥1 手
services:
  trading: { exchange: {EXCHANGE}, account: demo }
```

> `strategy.yaml` **没有** `deny_unknown_fields`，字段名拼错会被 serde 静默忽略；
> 写完必须用回测实际验证字段生效。`_global.yaml` 与旧 per-symbol 则严格校验。

### Step 2: 验证配置

**Python 模式**：

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

**Rust 模式验证**：

```bash
cd {project_path}

# 1. 命名一致性：strategy_type() == register name == 文件名 == 配置 strategy_type
grep -n 'fn strategy_type' -A 1 crates/strategies/src/{strategy_name}.rs
grep -n 'register_strategy!' -A 2 crates/strategies/src/{strategy_name}.rs
grep -n '^strategy_type:' config/{group}/strategy.yaml

# 2. 格式/静态检查/测试（必须全绿）
cargo fmt --check
cargo clippy --all-targets -- -D warnings
cargo test --workspace

# 3. 配置能被加载（跑一次短区间回测；数据未就绪时至少确认配置解析不报错）
cargo run -p strategy-app -- backtest \
  --config config/{group}/strategy.yaml --start {start} --end {end}
```

**期货额外校验**：

```bash
# symbol 已在 contracts.yaml 声明（否则会静默退化为 crypto 兼容模式）
grep -n "^\s*${FUTURES_SYMBOL}:" config/contracts.yaml

# _global.yaml 有 initial_cash，且不存在策略 params 里写费率/乘数的情况
grep -n 'initial_cash' config/{group}/_global.yaml
grep -inE 'multiplier|margin_rate|commission|session_open' crates/strategies/src/{strategy_name}.rs \
  config/{group}/strategy.yaml
```

### Step 3: 运行审查检查表

按 `docs/strategy/REVIEW_CHECKLIST.md` 逐项检查，输出结果。

**Rust 模式必查**（对照 `docs/strategy/AI_CONSTRAINTS.md` 23 禁 + 12 必）：
- 无 `now()`/系统时间；无策略内 IO；只读 `snapshot.closed`；`closed(tf)` 长度门控。
- 未改 `build.rs`/`registry.rs`/`lib.rs`；`Params` 严格反序列化；`M1` 在 `timeframes()`。
- 主路径无 `unwrap()/expect()`；未自持仓位状态；指标全量重算。
- 等权目标乘 `portfolio.max_total_notional`；组合平仓用 `CloseMaster`。
- 期货：symbol 已在 `contracts.yaml`；`initial_cash` 够开 1 手；未假设 7x24；
  未自行模拟平今/平昨；`params` 无乘数/保证金/费率/时段；K 线位置已由用户确认。

### Step 4: 重写/同步 README.md（强制，Phase 3 前置条件）

策略开发完成后，项目根目录 `README.md` 必须与开发的策略保持一致。
**未完成此步骤不得进入 Phase 3。**

#### 触发时机

Phase 2 执行顺序：
```
Step 0: 加载规范文档
Step 1: 生成策略代码
Step 2: 验证配置
Step 3: 运行审查检查表
Step 4: 重写/同步 README.md  ← 必须完成后才能进 Phase 3
```

#### 场景判断

```bash
# 场景 A：新项目（git 只有 1 个 commit = Phase 1 刚创建）
# 场景 B：已有项目（git 有多个 commit）
COMMIT_COUNT=$(git -C {project_path} rev-list --count HEAD 2>/dev/null || echo "0")
if [ "$COMMIT_COUNT" -le 1 ]; then
    SCENE="A"  # 重写
else
    SCENE="B"  # 增量同步
fi
```

#### 场景 A：新项目 → **重写**

脚手架复制出来的 README 是模板视角（主角是参考实现），
新项目的主角是本次开发的策略，必须重写策略相关段落。

**双语言模板**：

```markdown
# {strategy_name} — {一句话策略定位}

> {direction} 策略 | 主周期 {timeframes[0]} | 标的 {symbols} | 前缀 {PREFIX}

## 策略概述

- 入场：{spec.entry.description}
- 出场：{spec.exit 摘要}
- 参数：Python per-symbol overrides（实盘回测共用）/ Rust `config/<group>/strategy.yaml` 的 `params`

## 快速开始

### Python 模式
```bash
python -m backtest.run_backtest --strategies {strategy_name}:{SYMBOL} --start 20260601 --end 20260709
```

### Rust 模式
```bash
cargo run -p strategy-app -- backtest \
  --config config/{group}/strategy.yaml \
  --start 20260601 --end 20260709
# 期货需先按用户数据落位 1m CSV；可加 --data-dir / --output-dir / --initial-cash
```

## 项目结构

（模板结构保留，strategies/ 段把 {strategy_name} 列为主策略，
  Python 参考实现：example_ma_cross / example_mtf_trend
  Rust 参考实现：example_dual_ma / xsec_template / futures_single_trend（位于 crates/strategies/src/）

## 配置体系 / 文档导航 / 免责声明

（框架通用段落原样保留）
```

**重写规则**：
- 主角换成开发策略；参考实现降级为"框架参考实现"一节，不占快速开始
- 策略参数不复制进 README——参数细节留在配置文件（Python: `strategies/{name}/overrides/<SYMBOL>.yaml` / Rust: `config/{group}/strategy.yaml`）的注释里
- 框架通用段落（配置体系、免责声明、文档导航、测试命令）保留不动
- 根据 `STRATEGY_LANG` 只保留对应语言的快速开始命令：
  - `python` → 只保留 `### Python 模式` 段
  - `rust` → 只保留 `### Rust 模式` 段

#### 场景 B：已有项目 → **增量同步**

| 位置 | 更新内容 |
|------|----------|
| `## 项目结构` 的策略段 | Python: `strategies/` 追加目录；Rust: `crates/strategies/src/` 追加文件行 |
| `## 参考策略` 表格 | 追加一行：策略名 / 一句话说明 / 基类架构 / 时间周期 / 多标的 |
| `## 快速开始` 的示例命令 | 若新策略更适合作演示，可替换现有示例 |

**规则**：README 只描述"有什么"，不复制策略参数。参考实现级别的通用范例才写进
"参考策略"表；一次性业务策略只在项目结构里出现目录名即可。

#### 验证（强制）

更新完成后，**必须验证** README 确实被更新了：

```bash
cd {project_path}

# 验证 1：README 包含策略名
if grep -q "{strategy_name}" README.md; then
    echo "✅ README 已更新：包含策略名 {strategy_name}"
else
    echo "❌ README 未更新：未找到策略名 {strategy_name}"
    echo "   请重新执行场景 $SCENE 的更新"
    # 不进入 Phase 3
fi

# 验证 2：README 不包含模板残留（仅场景 A）
if [ "$SCENE" = "A" ]; then
    if [ "$STRATEGY_LANG" = "rust" ]; then REF_NAME="example_dual_ma"; else REF_NAME="example_ma_cross"; fi
    if grep -q "$REF_NAME" README.md && ! grep -q "框架参考实现" README.md; then
        echo "❌ README 仍为模板视角：$REF_NAME 未标注为参考实现"
        # 不进入 Phase 3
    fi
fi
```

#### 失败处理

| 情况 | 处理 |
|------|------|
| 用户明确说"跳过 README" | 记录警告，允许进入 Phase 3，但最终 benchmark 报告中注明"README 未更新" |
| 验证不通过 | 阻止进入 Phase 3，提示重新更新 |
| README 文件不存在 | 从模板复制一份，按场景 A 处理 |

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
- `/trading-dev develop` — 执行 Phase 2（策略代码生成），前置：已有脚手架 +
  `.strategy-spec.yaml`（Python `strategies/{name}/`；Rust `docs/strategy/specs/`）
- `/trading-dev backtest` — 执行 Phase 3 Step 1-4（回测 + 验证），前置：已有策略代码 + K 线数据
- `/trading-dev benchmark` — 只输出 benchmark 报告（Phase 3 Step 5），前置：已有回测结果

### 回测验收标准

| 周期 | 时间范围（crypto 默认） | 验收标准 |
|------|----------|----------|
| 短期 | 20260601-20260709 | 至少一个标的费后收益 ≥ 20% |
| 中期 | 20260101-20260709 | 至少一个标的费后收益 ≥ 20% |
| 长期 | 20250101-20260709 | 至少一个标的费后收益 ≥ 20% |

**期货的区间与标的**：
- 标的来自 `config/<group>/strategy.yaml` 的 `universe`（不是 crypto 固定三币）。
- 三个窗口必须落在用户提供的 1m 数据覆盖范围内；覆盖不足时改用可用区间的
  短/中/长三段（或等分三段），并在 benchmark 中写明"区间按数据可用性调整"。
- 不得用其他品种/区间顶替，也不得因数据不足跳过回测后仍宣称达标。

**回测命令根据 `STRATEGY_LANG` 选择**：

#### Python 模式回测

三个周期都用同一条批量命令，只换 `--start` / `--end`。
经项目自带的 `scripts/run_backtest_batch.sh` 调用（它负责 overrides 预检、
笛卡尔积展开、`PYTHONPATH`，再转调 `backtest.batch_runner`）。
并发由 `config/backtest.yaml` 的 `max_workers` 控制；策略参数自动读
`strategies/{strategy_name}/overrides/<SYMBOL>.yaml`。

```bash
# Step 1: 短期回测
bash scripts/run_backtest_batch.sh \
    --strategies {strategy_name} --symbols BTCUSDT,ETHUSDT,SOLUSDT \
    --start 20260601 --end 20260709 --log-level INFO --yes

# Step 2: 中期回测
bash scripts/run_backtest_batch.sh \
    --strategies {strategy_name} --symbols BTCUSDT,ETHUSDT,SOLUSDT \
    --start 20260101 --end 20260709 --log-level INFO --yes

# Step 3: 长期回测
bash scripts/run_backtest_batch.sh \
    --strategies {strategy_name} --symbols BTCUSDT,ETHUSDT,SOLUSDT \
    --start 20250101 --end 20260709 --log-level INFO --yes

# Step 4: 单标的复核
python -m backtest.run_backtest \
    --strategies {strategy_name}:BTCUSDT \
    --start 20250101 --end 20260710 --log-level INFO
```

#### Rust 模式回测

统一入口是 `strategy-app` 的 `backtest` 子命令；策略/标的/仓位/风险都在
`config/<group>/strategy.yaml` 里，`--strategy/--symbol/--cash` 不会覆盖它们。

```bash
# Step 1-3: 短期/中期/长期回测（只换 --start/--end）
cargo run -p strategy-app -- backtest \
    --config config/{group}/strategy.yaml \
    --start 20260601 --end 20260709 \
    --data-dir ./data/klines --output-dir ./backtest_output

# Step 4: 单区间复核（更长窗口）
cargo run -p strategy-app -- backtest \
    --config config/{group}/strategy.yaml \
    --start 20250101 --end 20260710
```

**批量矩阵**（多个配置/品种，期货与 crypto 可同批混跑）：

```bash
scripts/run_backtest_matrix.sh \
    --start 20260101 --end 20260630 \
    --data-dir ./data/klines --out ./reports \
    config/{group}/strategy.yaml
```

> `strategy.yaml` 的标的由 `universe` 决定，`--symbol/--strategy/--cash` 不覆盖；
> `--symbols` 只对旧 per-symbol `<SYMBOL>.yaml` 目录有效。

**期货专用参数**：
- `--initial-cash` 可覆盖配置里的初始权益；期货建议显式给（元），并确认够开 ≥1 手。
- 配置目录模式（`--config <set_dir>`）仅 `run` 支持；`backtest` 逐组传
  `<group>/strategy.yaml`。
- 跨换月回测要注意：主力连续**不复权**，换月处价格断档是数据事实；
  benchmark 里必须注明回测是否跨换月、回测窗口末尾是否有未平仓单
  （`accounts[].position_count`）。

> **Rust 回测输出**：`{output_dir}/{strategy_type}/{YYYYMMDD}/{HHMMSS}/{strategy_id 的 ':' 替换为 '_'}/`
> - `backtest_result.json`：指标在 `metrics` 段（不在顶层）
> - `backtest_report.txt`：人类可读摘要
> - `backtest_analysis_report.md`：分析报告（注意"最大回撤（滚动峰谷）"与
>   "权益振幅（全局峰谷差）"是两个口径，验收用最大回撤）
> - `charts/*.png`：净值/回撤/分时净值
> - `config.yaml`：本次实际生效配置快照（复现用）
>
> `metrics` 字段名（验收/诊断统一用这些）：
> `total_return`、`roe`、`annualized_return`、`sharpe_ratio`、`sortino_ratio`、
> `max_drawdown`、`win_rate`、`profit_factor`、`total_trades`、`winning_trades`、
> `losing_trades`、`avg_trade_pnl`、`largest_win`、`largest_loss`、`avg_win`、
> `avg_loss`、`trading_days`、`daily_return_mean`、`daily_return_std`。
> 期货年化按 `365/交易日数` 计算，跨市场比较需自行换算。

### Step 5: 输出 benchmark.md

综合本次所有标的的回测结果（crypto 默认三币；期货取配置 `universe`），生成 benchmark 报告。
Python 读 `backtest_result.json` 的 `metrics`；Rust 读
`{output_dir}/{strategy_type}/{YYYYMMDD}/{HHMMSS}/{strategy_id 的 ':'→'_'}/backtest_result.json` 的 `metrics`。

**期货额外写入 benchmark**：
- 交易所/品种/`initial_cash`/数据路径来源（用户提供，非下载）
- 数据覆盖区间与实际回测区间（若与默认窗口不同必须注明）
- 是否跨换月、是否含未平仓单、手续费口径（`contracts.yaml` 中 rate/per_lot）

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
- 标的: BTCUSDT, ETHUSDT, SOLUSDT（期货取 universe，如 CU/RB/I）

## 短期回测 (20260601-20260709)

| 标的 | 费后收益 | 最大回撤 | 交易次数 | 胜率 |
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

**产物路径按语言分叉**：
- Python：`{output_dir}/{strategy_name}/{date}/{time}/{symbol}/backtest_result.json`
- Rust：`{output_dir}/{strategy_type}/{YYYYMMDD}/{HHMMSS}/{strategy_id 的 ':' 替换为 '_'}/backtest_result.json`
  （目录名形如 `{name}_{symbol_lower}`；多标横截面一次运行只产出一个
  `strategy_id` 目录）

从对应 `backtest_result.json` 的 `metrics` 段提取：

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

> **Rust 注意**：横截面配置一次运行只产出一个组合 `accounts` 条目，没有现成的
> per-symbol 统计。需要分品种归因时，复制一份只含单标的 `universe` 的配置重跑，
> 或从引擎 `state/` 的仓位/成交快照聚合；**不得自行编造**未产出的分币种数字。

#### Step 2: 读取策略代码，提取可调参数清单

**Python**：解析 `{prefix}_core.py` 和 `overrides/<SYMBOL>.yaml`，自动提取：

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

**Rust**：解析 `crates/strategies/src/{strategy_name}.rs` 与
`config/<group>/strategy.yaml`，自动提取：

```python
# 1) 配置 params（策略私有参数唯一入口）
adjustable_params = {
    "{param}": {
        "current": config["params"]["{param}"],
        "role": "从 Params 字段注释/使用处推断",
        "affects": "entry / exit / risk / filter",
        "suggested_range": "由策略逻辑与指标周期推导",
        "source": "config/{group}/strategy.yaml",
    }
}

# 2) 源码硬编码阈值（Params 之外的常量）
hardcoded_thresholds = [
    {
        "location": "crates/strategies/src/{name}.rs:LINE",
        "code": "if price <= pos.stop_price {",
        "parameter": "hard stop 判定",
        "current": "ATR mult / pct",
        "suggested_range": "按 ATR 周期与波动推导",
        "affects": "exit",
    }
]

# 3) 结构参数（不在 params，但影响行为；只诊断不建议乱改）
structural = ["timeframes[0] base TF", "rebalance.top_k/every_bars", "sizing/risk 比例"]

# 4) 期货不可调项（属于 contracts.yaml，禁止写进 params）
forbidden = ["multiplier", "margin_rate", "commission", "session_opens/closes"]
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
    Python:
      1. 修改 strategies/{strategy_name}/overrides/{SYMBOL}.yaml: {具体参数变更}
      2. 修改 {prefix}_core.py: {具体代码变更}
    Rust:
      1. 修改 config/{group}/strategy.yaml 的 params: {具体参数变更}
      2. 修改 crates/strategies/src/{strategy_name}.rs: {具体代码变更}
      3. cargo test --workspace 后重跑 backtest

  归因标记: 本轮修改维度 = {维度名，如"入场阈值"/"止损倍数"/"指标周期"}
```

#### 修改规则

1. **每轮只改一个主维度**，辅维度最多一个，确保可归因
2. **参数修改幅度**：首次调整步长为当前值的 ±20%（或参数合理范围的 1/3），后续轮次根据上轮效果缩放步长
3. **代码修改优先级**：优先调参（Python 改 overrides YAML / Rust 改 `strategy.yaml` 的 `params`）→ 调阈值（改 `{prefix}_core.py` / `{name}.rs` 常量）→ 调逻辑（改条件判断）；Rust 每次改完先 `cargo test --workspace`
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
| `STRATEGY_LANG` | `python` | 策略开发语言：`python` 或 `rust` |
| `STRATEGY_MARKET` | `crypto` | 市场：`crypto` 或 `futures`（futures 仅 rust 模式） |
| `DATA_PATH` | `./data/klines` | K 线数据根目录（Python: csv_dir；Rust: `--data-dir`） |
| `CTA_ENV` | `dev` | 运行环境（dev/test/prod） |
| `BENCHMARK_OUTPUT_PATH` | `./benchmark_output` | benchmark 报告输出路径 |
| `KLINE_DATA_DIR` | `./data/klines` | 共享 K 线数据源目录（symlink 目标） |
| `FUTURES_EXCHANGE` | `SHFE` | 期货交易所：`SHFE` / `DCE` / `CZCE` / `INE` |
| `FUTURES_SYMBOL` | `CU` | 期货品种代码（必须已在 `config/contracts.yaml` 声明） |
| `FUTURES_KLINES_DIR` | （空） | 用户提供的期货 K 线根目录或 1m CSV 路径（**必填，不下载**） |
| `FUTURES_INITIAL_CASH` | （空） | 期货初始权益（元）；也可写在 `_global.yaml` 的 `initial_cash` |

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
| `STRATEGY_TEMPLATE_TAG` | Python `v1.0.0` / Rust 空（跟 main） | 指定模板仓库 tag；Rust 期货模板尚未打 tag |
| `TRADING_DEV_TEMPLATE_DIR` | （空） | 本地模板目录；设置后优先使用（如最新 `strategy-template-rs`） |

### .env.example 模板

以模板文件为准：`.env.example`（从对应语言模板仓库获取）。关键字段：

```bash
DATA_PATH=./data/klines
CTA_ENV=dev
BENCHMARK_OUTPUT_PATH=./benchmark_output

# ---- 直连交易所下单（direct_trading.enabled=true 时必填）----
BINANCE_API_KEY=
BINANCE_API_SECRET=

# ---- 代理（可选，国内网络通常需要）----
# HTTPS_PROXY=http://127.0.0.1:7890
# HTTP_PROXY=http://127.0.0.1:7890
```

> **Rust 模式**：配置体系与 Python 不同——
> - 策略级：`config/<group>/strategy.yaml`（`strategy_type`/`universe`/`timeframes`/
>   `indicators`/`entry`/`exit`/`portfolio_exit`/`rebalance`/`risk`/`sizing`/`params`）
> - 组级运行基线：`config/<group>/_global.yaml`（`mode`/`warmup_days`/`cash`/
>   `initial_cash`/`services.trading`）；模板里是 gitignore 文件，从
>   `config/_global.example.yaml` 生成
> - 合约参数：仓库根 `config/contracts.yaml`（期货**唯一**来源）
> - Rust 模板没有 `.env.example`；需要时自建 `.env`（`STRATEGY_SECRET`、代理），不入库。

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
      "Bash(cargo:*)",
      "Bash(rustup:*)",
      "Bash(scripts/run_backtest_matrix.sh:*)",
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
| **Bash: python3 -m venv** | 创建虚拟环境（仅 Python） | Phase 1 |
| **Bash: pip install** | 安装依赖（仅 Python） | Phase 1 |
| **Bash: cargo fetch/test/fmt/clippy** | Rust 依赖、基线自检、测试 | Phase 1/2 |
| **Bash: cargo run -p strategy-app** | Rust 回测/下载/数据命令 | Phase 1/3 |
| **Bash: cargo run -p strategy-data --bin roll_build** | 期货逐合约 CSV → 主力连续 1m | Phase 1 |
| **Bash: git init/add/commit** | 初始化仓库 | Phase 1 |
| **Bash: python -m backtest** | 运行回测 | Phase 3 |
| **Bash: python3 -m pytest** | 跑策略测试 | Phase 2 |
| **Bash: python3 -c** | 验证配置格式 | Phase 2 |
| **Write** | 写入策略代码、配置、spec、benchmark | Phase 2/3 |
| **Edit** | 修改策略代码与 overrides（loop 修改） | Phase 2 |
| **Read** | 读取策略文档、参考实现、回测输出 | 全流程 |

---

## Critical Constraints

### Python 编码红线（来自模板 AI_CONSTRAINTS.md，14 条禁止 + 11 条必须）

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

### Rust 编码红线（来自模板 AI_CONSTRAINTS.md，23 禁 + 12 必，摘要）

| # | 约束 | 原因 |
|---|------|------|
| 1 | 禁 `now()`/系统时间；只用 `snapshot.bar.open_time` | 回测逐字节可复现 |
| 2 | 禁读未闭合 K 线/绕过 `snapshot.closed`；只用 `closed(tf)` | 类型层隔离未来函数 |
| 3 | 禁策略内 IO（文件/网络/日志落盘） | 策略是纯计算 |
| 4 | 禁改 `build.rs`/`registry.rs`/`lib.rs` 接线区 | 注册机制冻结 |
| 5 | `Params` 必须 `deny_unknown_fields + default` | 参数拼错启动即报错 |
| 6 | 指标 NaN/warmup 必须显式长度检查 | 数据不足不得出信号 |
| 7 | `timeframes()` 必须含 `M1` | 聚合器据此注册 |
| 8 | `on_cross_section_bars` 主路径禁 `unwrap()/expect()` | 用 `Option`/`?` 静默降级 |
| 9 | 禁自持 `master_id`/子仓/总仓状态 | 账本由引擎 `MasterPosition`/`SubPosition` 持有 |
| 10 | 禁 `strategy_type()` / 注册名 / 配置名不一致 | signal_id 与报表路径会分裂 |
| 11 | 禁 `Params::default()` 与配置 `params` 不一致 | 文档即契约 |
| 12 | 禁无测试新增策略；至少覆盖入场 + 出场 | 行为不可验证 |
| 13 | 禁在 `portfolio.master.state == Closing` 时开/加/调仓 | `StrategyBase` 已内置门控 |
| 14 | 等权目标必须乘 `portfolio.max_total_notional`，不用全额 NAV | 否则目标高于执行容量，产生拒单 |
| 15 | 组合级退出用 `CloseMaster`，不逐标的 `Close` 模拟 | 总仓状态机不成立 |
| 16 | 禁在策略/`params` 写死乘数/手数/保证金/手续费 | 唯一来源 `config/contracts.yaml` |
| 17 | 禁期货 symbol 未在 `contracts.yaml` 声明就回测 | 会静默退化为 crypto 兼容模式 |
| 18 | 禁自行拼日盘/夜盘/午休或按 UTC 断交易日 | 引擎 `SessionWindowPolicy` 负责 |
| 19 | 禁在策略内模拟平今/平昨 | `offset` 由执行层生成；只发 `Close`/`CloseMaster`/`Adjust` |
| 20 | 禁用户未提供期货 K 线就回测/用 mock 顶替 | 结果不可信 |
| 必须 | 文件尾 `register_strategy!` 恰好一次；文件名 == 注册名 | 注册表自动发现 |
| 必须 | 期货配置显式 `initial_cash`，等分后够开 1 手 | 否则部分品种永远开不出仓 |
| 必须 | 期货用例覆盖 `multiplier != 1`、整数手取整、时段聚合 | 换品种即错的最常见来源 |

### 期货数据与市场规则（仅 Rust 模式）

| # | 规则 |
|---|------|
| 1 | 用户说"期货"时**不提供下载**，先索要 K 线路径（逐合约目录或已生成 1m CSV） |
| 2 | 期货数据落位 `data/klines/1m/<EXCHANGE>/cn_futures/<SYMBOL>_1m.csv`（Rust）或模板约定路径（Python） |
| 3 | 回测区间必须落在数据覆盖范围内；不足先要数据，不得换品种/换区间顶替 |
| 4 | `config/contracts.yaml` 是乘数/保证金/费率/时段的唯一来源，策略 `params` 禁止出现 |
| 5 | 主力连续不复权；跨换月回测需在 benchmark 注明断档与偏差 |
| 6 | 没跑通回测不得写"已跑通"；缺数据就停在 Phase 1 并在交付说明列出缺口 |

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
  ├── Step 2.5: 问语言/市场（期货追问 K 线路径/交易所/初始权益）
  └── Step 3: 汇总确认 -> 进 Phase 0
       ↓
Phase 0: 主机级环境预检 + 策略信息获取
  ├── Step 0: 主机级预检（Python/Rust 工具链、磁盘；期货用户 K 线路径）
  ├── Step 1: 解析策略来源（文件/目录/URL/自然语言/多轮对话）
  ├── Step 2: 统一提取为 .strategy-spec.yaml（按语言落盘；含 market/data_source/backtest）
  └── Step 3: 执行确认（全自动→直接执行 / 交互→用户确认）
       ↓
Phase 1: 脚手架创建（一次性）
  ├── 镜像复制模板（含参考实现），校验 Phase 0 落盘的 spec
  ├── Rust: cargo metadata + contracts.yaml（期货）→ cargo fetch + 基线自检
  ├── Python: venv + 依赖
  ├── 准备 K 线数据（crypto 自动下载；futures 必须用户提供，禁止下载）
  ├── git init + 首次 commit
  └── 输出就绪报告
       ↓
┌─────────────────────────────────────────────┐
│ Loop (最多 5 轮)                             │
│                                             │
│   Phase 2: 生成/修改策略代码                  │
│     ├── 读规范文档 + 对应市场/形态参考实现      │
│     ├── Python: strategy.py + core + overrides │
│     │   Rust: crates/strategies/src/{name}.rs  │
│     │         + config/{group}/strategy.yaml   │
│     ├── 生成测试                              │
│     ├── 验证配置 + 跑测试                      │
│     ├── 运行审查检查表                        │
│     └── 重写/同步 README.md（场景A重写/B增量） │
│         ↓                                   │
│   Phase 3: 回测验证                          │
│     ├── 短期 → 中期 → 长期                   │
│     │   Python: run_backtest_batch.sh        │
│     │   Rust: cargo run -p strategy-app --   │
│     │         backtest / run_backtest_matrix │
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
