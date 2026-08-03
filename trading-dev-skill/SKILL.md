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

- 用户执行 `/trading-dev new` — 创建新 CTA 策略项目（交互模式）
- 用户执行 `/trading-dev new --from <source>` — 从指定来源自动开发策略（全自动模式）
- 用户说"新建策略项目"、"创建交易项目"、"开发新策略"
- 用户执行 `/trading-dev scaffold` — 只创建脚手架
- 用户执行 `/trading-dev develop` — 只生成策略代码
- 用户执行 `/trading-dev backtest` — 只跑回测
- 用户已有策略项目，想执行回测验证

## Commands

| 命令 | 模式 | 说明 |
|------|------|------|
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
| 策略目录 | `--from /path/to/cta_ict_v4/` | 读已有策略代码，逆向提取 spec |
| URL | `--from https://...` | WebFetch 抓取 |
| 自然语言 | `/trading-dev new 开发一个 EMA 交叉策略，4h，BTCUSDT` | 从描述提取 |
| 省略 | `/trading-dev new` | 进入多轮对话收集策略信息 |

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

# 4. K 线数据
KLINE_SRC="${KLINE_DATA_DIR:-${DATA_PATH:-./data}/strategies/1m}"
KLINE_READY="0"
if [ -d "$KLINE_SRC" ] && [ -f "$KLINE_SRC/BTCUSDT_1m.csv" ]; then
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
| K 线数据 | `KLINE_READY = 1` | 设置 `KLINE_DATA_DIR` 指向已有数据目录，或运行 `python utils/prepare_data.py --symbol BTCUSDT,ETHUSDT,SOLUSDT --start 20250101` |
| 磁盘空间 ≥ 2G | `DISK_OK = 1` | 清理空间或更换 `DATA_PATH` |

**阻塞 vs 非阻塞**：

| 检测项 | 不达标时 | 原因 |
|--------|----------|------|
| Python 3.10+ | **阻塞** — 无法创建 venv 和运行回测 | 核心依赖 |
| ta-lib C 库 | **非阻塞** — 降级安装，回测时部分指标不可用 | 可后续安装 |
| pip 可用 | **阻塞** — 无法安装依赖 | 核心依赖 |
| K 线数据 | **非阻塞** — Phase 1 自动 symlink/下载，仍无数据则自动运行 prepare_data.py | 可自动修复 |
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
    f"{strategy_dir}/strategy.py",        # STRATEGY_TYPE, STRATEGY_PREFIX, DEFAULT_TIMEFRAME
    f"{strategy_dir}/*_core.py",          # State fields, analyze() logic, check_realtime_exit()
    f"{strategy_dir}/config.yaml",        # symbols, timeframes, params
    f"{strategy_dir}/config.test.yaml",   # 回测参数
]

# 提取映射
STRATEGY_TYPE → strategy_name
STRATEGY_PREFIX → prefix
DEFAULT_TIMEFRAME → timeframes[0]
config.yaml → symbols, params, direction
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

### Step 2: 统一提取为策略规格

所有输入形态收敛到同一个结构：

```yaml
strategy_name: ema_rsi_pullback
prefix: EMA_RSI
direction: neutral
timeframes: [4h, 1h]
symbols: [BTCUSDT, ETHUSDT, SOLUSDT]

entry:
  description: "EMA 交叉 + RSI 回踩确认"
  conditions:
    - "快线上穿慢线"
    - "RSI 回踩至 40-60 区间后反弹"

exit:
  stop_loss: "2 倍 ATR"
  take_profit: "移动止盈，1.5 倍 ATR 回落平仓"

state_fields:
  - name: atr_at_entry
    type: float
    default: 0.0
    persist: true
  - name: trail_activated
    type: bool
    default: false
    persist: true

default_params: {}
```

### Step 3: 执行确认（按模式）

**全自动模式**：自动保存 `.strategy-spec.yaml`，直接进入 Phase 1。

```
📋 策略: cta_ict_v4 | CTA_ICT | neutral | [4h,1h] | [BTCUSDT,ETHUSDT,SOLUSDT]
🔧 环境: Python 3.12 ✅ | ta-lib ✅ | K线数据 ✅ | 磁盘 15G ✅
🚀 自动执行 loop-engineering 模式...
```

**交互/半交互模式**：展示完整信息，用户确认后执行。

```
📋 环境预检:
  Python 3.12: ✅
  ta-lib C 库: ❌ (回测指标计算需要，见下方安装命令)
  pip: ✅
  K 线数据: ✅ (symlink → /path/to/1m/)
  磁盘空间: ✅ (15G 可用)

📋 策略解析结果:
  名称: cta_ict_v4
  前缀: CTA_ICT
  方向: neutral
  时间框架: [4h, 1h]
  标的: [BTCUSDT, ETHUSDT, SOLUSDT]
  入场: FVG + Order Block + Breaker 确认
  出场: 止损 2x ATR, 移动止盈 1.5x ATR

🔧 环境变量（可修改）:
  KLINE_DATA_DIR = ./data/strategies/1m
  BENCHMARK_OUTPUT_PATH = ./benchmark_output
  DATA_PATH = ./data

⚠ ta-lib 未安装，回测中 ATR/RSI 等指标会失败。安装：
  wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
  tar -xzf ta-lib-0.4.0-src.tar.gz
  cd ta-lib && ./configure && make && sudo make install && ldconfig

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

从 skill 模板目录复制骨架代码到新项目：

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

**复制列表（全量）**：

| 源路径 | 说明 |
|--------|------|
| `templates/strategy_core/` | 基类框架（BaseStrategy/BaseState/BaseStrategyCore） |
| `templates/backtest/` | 回测引擎 |
| `templates/data_manager/` | K线数据管理 |
| `templates/scripts/` | 辅助脚本 |
| `templates/utils/` | 工具脚本（prepare_data.py 等） |
| `templates/config/settings.example.yaml` | 系统配置模板 |
| `templates/docs/strategy/` | 开发规范文档（QUICKSTART/DEVELOPMENT_GUIDE/AI_CONSTRAINTS/REVIEW_CHECKLIST/EXAMPLES） |
| `templates/requirements.txt` | 依赖清单 |
| `templates/.gitignore` | 排除规则 |
| `templates/.env.example` | 环境变量模板 |
| `templates/run_strategies_manager.py` | 策略管理器入口 |
| `templates/run_strategy.py` | 单策略运行入口 |
| `templates/start.sh` | 启动脚本 |
| `templates/stop.sh` | 停止脚本 |

**不复制**：

| 排除项 | 原因 |
|--------|------|
| `strategies/` 中真实策略 | 业务逻辑不进模板 |
| `backtest_output*/` | 运行产物 |
| `arbitrage/` | 套利模块，非 CTA 必需 |
| `signal_comparison/` | 高级功能，可后置 |
| `config/settings.yaml` | 含内网 IP，用 settings.example.yaml 替代 |
| `config/openviking_sync.yaml` | 含内网 IP，从 .env 生成 |
| `backtest/config/main.yaml` | 运行时文件，从 main.example.yaml 复制生成 |
| `backtest/config/strategies.yaml` | 运行时文件，从 strategies.example.yaml 复制生成 |

**复制命令**：

```bash
# 模板目录由上方自动检测逻辑确定
TEMPLATE_DIR="$TEMPLATE_DIR"  # 已在 Step 1 中设置
PROJECT_DIR="{project_path}"

# 复制核心模块
cp -r $TEMPLATE_DIR/strategy_core/ $PROJECT_DIR/strategy_core/
cp -r $TEMPLATE_DIR/backtest/ $PROJECT_DIR/backtest/
cp -r $TEMPLATE_DIR/data_manager/ $PROJECT_DIR/data_manager/
cp -r $TEMPLATE_DIR/scripts/ $PROJECT_DIR/scripts/
cp -r $TEMPLATE_DIR/utils/ $PROJECT_DIR/utils/

# 复制配置和文档
cp -r $TEMPLATE_DIR/config/ $PROJECT_DIR/config/
cp -r $TEMPLATE_DIR/docs/ $PROJECT_DIR/docs/

# 复制入口文件
cp $TEMPLATE_DIR/requirements.txt $PROJECT_DIR/
cp $TEMPLATE_DIR/.gitignore $PROJECT_DIR/
cp $TEMPLATE_DIR/.env.example $PROJECT_DIR/
cp $TEMPLATE_DIR/run_strategies_manager.py $PROJECT_DIR/
cp $TEMPLATE_DIR/run_strategy.py $PROJECT_DIR/
cp $TEMPLATE_DIR/start.sh $PROJECT_DIR/
cp $TEMPLATE_DIR/stop.sh $PROJECT_DIR/

# 从 .example 生成回测运行时配置
cp $TEMPLATE_DIR/backtest/config/main.example.yaml $PROJECT_DIR/backtest/config/main.yaml
cp $TEMPLATE_DIR/backtest/config/strategies.example.yaml $PROJECT_DIR/backtest/config/strategies.yaml

# 创建策略空壳目录
mkdir -p $PROJECT_DIR/strategies
```

> **模板规则**：`backtest/config/` 中的 `main.yaml` 和 `strategies.yaml` 是运行时文件，**不进模板**。
> 模板只保留 `.example.yaml` 变体。脚手架创建时从 `.example` 复制生成运行时文件。
> 这样用户修改运行时配置不会污染模板，新项目始终从干净的 `.example` 开始。

### Step 2: 初始化 Python 环境

**按 Phase 0 预检结果执行**。预检已确认 Python 版本和 ta-lib 状态，此处直接执行安装。

```bash
cd {project_path}

# 1. 创建 venv（Python 版本已在 Phase 0 预检确认）
$PYTHON_CMD -m venv .venv
source .venv/bin/activate
pip install --upgrade pip

# 2. 安装依赖
if pip install -r requirements.txt; then
    echo "✅ 依赖安装成功"
else
    echo "⚠ 部分依赖安装失败，降级安装核心依赖..."
    pip install pandas numpy pyyaml
    if [ "$TALIB_FOUND" = "0" ]; then
        echo "⚠ ta-lib C 库未安装，跳过 ta-lib Python 包"
        echo "  ATR/RSI 等指标回测不可用，安装 C 库后重跑: pip install ta-lib"
    fi
fi
```

> **ta-lib 处理逻辑**：Phase 0 预检已检测 C 库状态。C 库未安装时，pip install ta-lib 会失败，此处自动跳过并降级。用户可在安装 C 库后手动 `pip install ta-lib`。

### Step 3: 准备回测 K 线数据

回测引擎从 `data_dir/1m/{SYMBOL}_1m.csv` 读取 1m K 线数据。数据约 1.3G，**不复制**，用 symlink 指向共享数据源。

**数据格式**（CSV，带 header）：

```csv
timestamp,open,high,low,close,volume
2022-12-30 00:00:00+00:00,16630.3,16633.7,16629.2,16629.3,337.988
2022-12-30 00:01:00+00:00,16629.3,16629.3,16625.5,16625.5,77.129
```

**文件命名**：`{SYMBOL}_1m.csv`，如 `BTCUSDT_1m.csv`、`ETHUSDT_1m.csv`

**自动准备**（按优先级尝试，不询问用户）：

```bash
cd {project_path}
DATA_DIR="${DATA_PATH:-./data}"
KLINE_SRC="${KLINE_DATA_DIR:-${DATA_PATH:-./data}/strategies/1m}"

# 方式 1: symlink 到已有数据源（推荐，零拷贝）
if [ -d "$KLINE_SRC" ] && [ -f "$KLINE_SRC/BTCUSDT_1m.csv" ]; then
    mkdir -p "$DATA_DIR/strategies/1m"
    ln -sf "$KLINE_SRC"/*.csv "$DATA_DIR/strategies/1m/"
    echo "✅ 已 symlink 1m kline 数据: $KLINE_SRC → $DATA_DIR/strategies/1m/"

# 方式 2: 运行 prepare_data.py 从 Binance 下载（自动，约 30-60 分钟）
elif [ -f "utils/prepare_data.py" ]; then
    echo "📥 K 线数据未就绪，从 Binance Futures 下载..."
    echo "  时间范围: 20250101 → 今天"
    echo "  交易对: BTCUSDT,ETHUSDT,SOLUSDT（默认）"
    python utils/prepare_data.py \
        --symbol BTCUSDT,ETHUSDT,SOLUSDT \
        --start 20250101 \
        --output "$DATA_DIR/strategies/1m"

# 方式 3: 数据未就绪，记录警告（不阻塞流程，回测时会报错）
else
    echo "⚠ 1m kline 数据未就绪"
    echo "  需要路径: $DATA_DIR/strategies/1m/"
    echo "  文件格式: {SYMBOL}_1m.csv (timestamp,open,high,low,close,volume)"
    echo "  设置 KLINE_DATA_DIR 环境变量指向已有数据目录"
    echo "  或运行: python utils/prepare_data.py --symbol BTCUSDT,ETHUSDT,SOLUSDT --start 20250101"
fi
```

**验证数据就绪**：

```bash
if [ -f "$DATA_DIR/strategies/1m/BTCUSDT_1m.csv" ]; then
    lines=$(wc -l < "$DATA_DIR/strategies/1m/BTCUSDT_1m.csv")
    echo "✅ 1m kline 数据就绪: BTCUSDT ${lines} 行"
else
    echo "⚠ 1m kline 数据未就绪，回测将失败"
fi
```

### Step 4: 初始化 Git

```bash
cd {project_path}
git init
cp .env.example .env          # 创建本地 .env（从模板）
echo "data/" >> .gitignore    # K线数据不入库
git add .
git commit -m "init: scaffold from trading-dev-skill template"
```

### Step 5: 输出就绪报告

```
✅ 项目脚手架创建完成

项目路径: {project_path}
Python 环境: .venv (Python 3.x)
依赖安装: ✅ / ⚠️ (ta-lib 需手动安装)
1m K线数据: ✅ (symlink) / ✅ (下载) / ⚠️ (需手动准备)

项目结构:
  {strategy_name}/
  ├── strategy_core/              # 基类框架（BaseStrategy/BaseState/BaseStrategyCore）
  │   └── utils/                  # 工具（config_loader, log_handlers, strategy_loader...）
  ├── backtest/                   # 回测引擎
  │   ├── run_backtest.py         # 回测入口
  │   ├── analyzer.py             # 数据分析
  │   ├── html_generator/         # HTML 报告生成
  │   └── config/
  │       ├── main.example.yaml   # 回测配置模板
  │       ├── main.yaml           # 运行时配置（从 .example 生成）
  │       ├── strategies.example.yaml
  │       └── strategies.yaml     # 运行时配置（从 .example 生成）
  ├── data_manager/               # K线数据管理（DataManager, klines_loader）
  ├── scripts/                    # 辅助脚本
  ├── utils/                      # 工具脚本（prepare_data.py 等）
  ├── strategies/                 # 策略目录
  │   ├── __init__.py             # 策略注册（空壳，Phase 2 更新）
  │   └── {strategy_name}/        # ⬅ Phase 2 生成
  │       ├── strategy.py
  │       ├── {prefix}_core.py
  │       ├── __init__.py
  │       ├── config.yaml
  │       ├── config.dev.yaml
  │       ├── config.test.yaml
  │       ├── config/                # ⬅ Per-Symbol 回测配置
  │       │   ├── BTCUSDT.yaml
  │       │   ├── ETHUSDT.yaml
  │       │   └── SOLUSDT.yaml
  │       ├── .strategy-spec.yaml
  │       └── tests/
  ├── config/
  │   └── settings.example.yaml   # 系统配置模板
  ├── docs/strategy/              # 开发规范文档
  │   ├── QUICKSTART.md
  │   ├── DEVELOPMENT_GUIDE.md
  │   ├── AI_CONSTRAINTS.md
  │   ├── REVIEW_CHECKLIST.md
  │   └── EXAMPLES.md
  ├── data/strategies/1m/         # ⬅ 1m K线数据（symlink 或下载）
  │   ├── BTCUSDT_1m.csv
  │   ├── ETHUSDT_1m.csv
  │   └── SOLUSDT_1m.csv
  ├── .env                        # 环境变量（从 .env.example 生成）
  ├── .env.example                # 环境变量模板
  ├── .gitignore
  ├── requirements.txt
  ├── run_strategies_manager.py   # 策略管理器入口
  ├── run_strategy.py             # 单策略运行入口
  ├── start.sh                    # 启动脚本
  └── stop.sh                     # 停止脚本
```

---

## Phase 2: 策略开发

从 Phase 0 的策略规格直接生成代码。

### 模式行为差异

| 步骤 | 交互模式 | 全自动模式 | 半交互模式 |
|------|----------|-----------|-----------|
| 加载规范文档 | 静默加载 | 静默加载 | 静默加载 |
| 生成代码 | 展示生成的文件列表 | 静默生成 | 展示生成的文件列表 |
| 注册策略 | 静默执行 | 静默执行 | 静默执行 |
| 验证配置 | 展示验证结果 | 静默验证，失败自动修复 | 展示验证结果 |
| 审查检查表 | 展示审查结果 | 静默审查，不通过自动修复 | 展示审查结果 |

**单步模式**：`/trading-dev develop` 只执行 Phase 2（需要已有脚手架和 `.strategy-spec.yaml`）。

### Step 0: 加载规范文档（强制）

**必须先读取以下文档到上下文，确保生成的代码符合项目规范**：

```
docs/strategy/QUICKSTART.md         # 目录结构、命名规范
docs/strategy/DEVELOPMENT_GUIDE.md  # 基类功能、平仓方法、冷却机制
docs/strategy/AI_CONSTRAINTS.md     # 编码红线（14 条禁止 + 11 条必须）
docs/strategy/REVIEW_CHECKLIST.md   # 提交前检查项（8 类 68 项）
docs/strategy/EXAMPLES.md           # 代码模板与 FAQ
```

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
| 禁止入场用未闭合 K 线 | 用 `get_closed_data()` |
| 禁止 `datetime.now()` 做时间戳 | 用 K 线时间 |
| 禁止 Strategy 类算指标 | 指标在 Core.analyze() 内 |
| 禁止跳过数据不足检查 | `if df.empty or len(df) < min_rows` |
| 禁止可变默认值 | 用 `field(default_factory=list)` |
| 禁止缓存字段持久化 | 缓存不进 `to_persist_dict()` |

#### 1.3 __init__.py

```python
from .strategy import Strategy
from .{prefix}_core import {Prefix}Core, {Prefix}State

__all__ = ["Strategy", "{Prefix}Core", "{Prefix}State"]
```

#### 1.4 配置文件

生成三个配置文件，**必须有顶层策略名键**：

- `config.yaml` — 默认配置（trading_mode: paper）
- `config.dev.yaml` — 开发配置
- `config.test.yaml` — 回测配置（trading_mode: backtest, cooldown_bars: 0）

#### 1.5 Per-Symbol 回测配置

为每个交易对生成独立的回测配置文件，放在策略目录下的 `config/` 子目录：

**路径**：`strategies/{strategy_name}/config/{SYMBOL}.yaml`

**格式**（与 `config.test.yaml` 结构一致，但每个文件只包含单个 symbol）：

```yaml
{strategy_name}:
  enabled: true
  direction: {direction}
  symbols:
    - {SYMBOL}
  timeframes: {timeframes}
  params: {params}
  signal:
    min_strength: 0.5
    cooldown_ms: 60000
    order_type: 1
    slippage: 0
    exchange: binance
  capital:
    max_cash: 1000
    max_parts: 1
    leverage: 5
  risk:
    enabled: true
    fixed_stop_loss_pct: 2.0
    trailing_profit:
      enabled: true
      activation_pct: 2.0
      drawdown_pct: 20.0
    fixed_take_profit_pct: 0.0
```

**生成规则**：
- 为 `symbols` 列表中的每个交易对生成一个文件
- 文件名 = `{SYMBOL}.yaml`（如 `BTCUSDT.yaml`、`ETHUSDT.yaml`）
- `symbols` 字段只包含当前文件对应的单个交易对
- `params` 从策略规格的 `default_params` 填充，不同交易对可后续独立调参
- 回测时通过 `--config strategies/{strategy_name}/config/{SYMBOL}.yaml` 加载
- 回测引擎自动将使用的配置复制到 `backtest_output/{strategy}/{date}/{time}/{SYMBOL}/config.yaml`

**目录结构**：

```
strategies/{strategy_name}/
├── config/
│   ├── BTCUSDT.yaml
│   ├── ETHUSDT.yaml
│   └── SOLUSDT.yaml
├── strategy.py
├── {prefix}_core.py
├── __init__.py
├── config.yaml
├── config.dev.yaml
├── config.test.yaml
└── tests/
```

#### 1.6 测试文件

- `tests/test_{prefix}_core.py` — 核心逻辑测试
- `tests/test_strategy_logging.py` — 信号日志测试

### Step 2: 注册策略

更新 `strategies/__init__.py`，添加新策略的 import。

### Step 3: 验证配置

```bash
python3 -c "
import yaml
from pathlib import Path
config_path = Path('strategies/{strategy_name}/config.test.yaml')
with open(config_path) as f:
    full_config = yaml.safe_load(f)
if '{strategy_name}' not in full_config:
    print(f'ERROR: 配置文件缺少顶层键: {strategy_name}')
    exit(1)
config = full_config['{strategy_name}']
required = ['timeframes', 'symbols', 'params']
for key in required:
    if key not in config:
        print(f'ERROR: 配置缺少必需字段: {key}')
        exit(1)
print('✅ 配置文件格式正确')
"
```

### Step 4: 运行审查检查表

按 `docs/strategy/REVIEW_CHECKLIST.md` 逐项检查，输出结果。

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

### Step 1: 短期回测

```bash
python -m backtest.run_backtest --strategy {strategy_name} --start 20260601 --end 20260709 --symbol BTCUSDT --config strategies/{strategy_name}/config/BTCUSDT.yaml --log-level INFO
python -m backtest.run_backtest --strategy {strategy_name} --start 20260601 --end 20260709 --symbol ETHUSDT --config strategies/{strategy_name}/config/ETHUSDT.yaml --log-level INFO
python -m backtest.run_backtest --strategy {strategy_name} --start 20260601 --end 20260709 --symbol SOLUSDT --config strategies/{strategy_name}/config/SOLUSDT.yaml --log-level INFO
```

### Step 2: 中期回测

```bash
python -m backtest.run_backtest --strategy {strategy_name} --start 20260101 --end 20260709 --symbol BTCUSDT --config strategies/{strategy_name}/config/BTCUSDT.yaml --log-level INFO
python -m backtest.run_backtest --strategy {strategy_name} --start 20260101 --end 20260709 --symbol ETHUSDT --config strategies/{strategy_name}/config/ETHUSDT.yaml --log-level INFO
python -m backtest.run_backtest --strategy {strategy_name} --start 20260101 --end 20260709 --symbol SOLUSDT --config strategies/{strategy_name}/config/SOLUSDT.yaml --log-level INFO
```

### Step 3: 长期回测

```bash
python -m backtest.run_backtest --strategy {strategy_name} --start 20250101 --end 20260709 --symbol BTCUSDT --config strategies/{strategy_name}/config/BTCUSDT.yaml --log-level INFO
python -m backtest.run_backtest --strategy {strategy_name} --start 20250101 --end 20260709 --symbol ETHUSDT --config strategies/{strategy_name}/config/ETHUSDT.yaml --log-level INFO
python -m backtest.run_backtest --strategy {strategy_name} --start 20250101 --end 20260709 --symbol SOLUSDT --config strategies/{strategy_name}/config/SOLUSDT.yaml --log-level INFO
```

### Step 4: 手工命令行验证

策略自带回测代码可能将输出写到 `.tmp/` 目录，需重跑确认结果一致：

```bash
python -m backtest.run_backtest --strategy {strategy_name} --start 20250101 --end 20260710 --symbol BTCUSDT --config strategies/{strategy_name}/config/BTCUSDT.yaml --log-level INFO
python -m backtest.run_backtest --strategy {strategy_name} --start 20250101 --end 20260710 --symbol ETHUSDT --config strategies/{strategy_name}/config/ETHUSDT.yaml --log-level INFO
python -m backtest.run_backtest --strategy {strategy_name} --start 20250101 --end 20260710 --symbol SOLUSDT --config strategies/{strategy_name}/config/SOLUSDT.yaml --log-level INFO
```

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

解析 `{prefix}_core.py` 和 `config.yaml`，自动提取：

```python
# 从 config.yaml 的 params 段提取可调参数
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
| `max_drawdown > 30%` 且 `win_rate < 40%` | 连续亏损累积 | 增加冷却期 / 增加趋势过滤条件避免逆势 | 查看 `cooldown_bars` 和趋势判断逻辑 |
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
    1. 修改 strategies/{strategy_name}/config/{SYMBOL}.yaml: {具体参数变更}
    2. 修改 {prefix}_core.py: {具体代码变更}
    3. {其他修改}

  归因标记: 本轮修改维度 = {维度名，如"入场阈值"/"止损倍数"/"指标周期"}
```

#### 修改规则

1. **每轮只改一个主维度**，辅维度最多一个，确保可归因
2. **参数修改幅度**：首次调整步长为当前值的 ±20%（或参数合理范围的 1/3），后续轮次根据上轮效果缩放步长
3. **代码修改**：优先调参（改 config.yaml），其次调阈值（改 core.py 中的硬编码值），最后调逻辑（改 core.py 中的条件判断）
4. **禁止归因模糊**：如果连续 2 轮修改同维度无改善，换一个本质不同的维度
5. **回撤优先**：如果 `max_drawdown > 30%`，优先处理风控（止损/仓位/冷却），再处理收益

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

### 失败原因分析模板

每轮回测未达标时，按动态诊断流程输出：

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
    1. 修改 strategies/{strategy_name}/config/{SYMBOL}.yaml: {具体参数变更}
    2. 修改 {prefix}_core.py: {具体代码变更}
    3. {其他修改}

  归因标记: 本轮修改维度 = {维度名，如"入场阈值"/"止损倍数"/"指标周期"}

→ 进入第 {N+1} 轮
```

---

## 环境变量清单

开源项目所有部署相关配置走环境变量，不硬编码内网 IP 或个人路径。

### 必需配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DATA_PATH` | `./data` | K线数据存储路径 |
| `CTA_ENV` | `dev` | 运行环境（dev/test/prod） |
| `BENCHMARK_OUTPUT_PATH` | `./benchmark_output` | benchmark 报告输出路径 |
| `KLINE_DATA_DIR` | `${DATA_PATH}/strategies/1m` | 1m K线数据源目录（symlink 目标） |

### 服务配置（实盘模式需要）

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `FACTORY_ENDPOINT` | `http://127.0.0.1:8888` | 策略工厂服务地址 |
| `POSITION_PROXY_URL` | `http://127.0.0.1:8889` | 仓位代理服务地址 |
| `CALLBACK_PORT` | `8892` | 策略回调端口 |
| `CALLBACK_HOST` | `0.0.0.0` | 回调监听地址 |
| `KLINES_WS_URL` | `ws://127.0.0.1:17081/ws/klines` | K线 WebSocket 地址 |
| `KLINES_HTTP_URL` | `http://127.0.0.1:17081` | K线 HTTP 地址 |

### 可选服务配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `KAFKA_BROKERS` | `127.0.0.1:9092` | Kafka 集群地址 |
| `KAFKA_TOPIC` | `biance_klines` | Kafka 主题 |
| `SIGNAL_HUB_ENDPOINT` | `http://127.0.0.1:18888` | 信号推送中心 |
| `OPENVIKING_SERVER_URL` | `http://127.0.0.1:1933` | OpenViking 服务器 |
| `OPENVIKING_ROOT_API_KEY` | （空） | OpenViking API Key |
| `POLYMARKET_WALLET_KEY` | （空） | Polymarket 钱包私钥 |
| `POLYMARKET_FUNDER_ADDRESS` | （空） | Polymarket 资金方地址 |
| `DERIBIT_API_KEY` | （空） | Deribit API Key |
| `DERIBIT_API_SECRET` | （空） | Deribit API Secret |

### .env.example 模板

```bash
# ===== 必需配置 =====
DATA_PATH=./data
CTA_ENV=dev
BENCHMARK_OUTPUT_PATH=./benchmark_output
KLINE_DATA_DIR=./data/strategies/1m

# ===== 策略引擎（实盘模式） =====
FACTORY_ENDPOINT=http://127.0.0.1:8888
POSITION_PROXY_URL=http://127.0.0.1:8889
CALLBACK_PORT=8892
CALLBACK_HOST=0.0.0.0

# ===== K线数据 =====
KLINES_WS_URL=ws://127.0.0.1:17081/ws/klines
KLINES_HTTP_URL=http://127.0.0.1:17081

# ===== Kafka（可选） =====
KAFKA_BROKERS=127.0.0.1:9092
KAFKA_TOPIC=biance_klines

# ===== 信号推送（可选） =====
SIGNAL_HUB_ENDPOINT=http://127.0.0.1:18888

# ===== OpenViking（可选） =====
OPENVIKING_SERVER_URL=http://127.0.0.1:1933
OPENVIKING_ROOT_API_KEY=

# ===== 套利模块（可选） =====
POLYMARKET_WALLET_KEY=
POLYMARKET_FUNDER_ADDRESS=
DERIBIT_API_KEY=
DERIBIT_API_SECRET=
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
| **Bash: python3 -c** | 验证配置格式 | Phase 2 |
| **Write** | 写入策略代码、配置、spec、benchmark | Phase 2/3 |
| **Edit** | 修改 `strategies/__init__.py`、策略代码（loop 修改） | Phase 2 |
| **Read** | 读取策略文档、规范文档、回测输出 | 全流程 |

---

## 模板处理规范

模板代码经过以下处理，确保开源可用：

1. **替换硬编码 IP** — `192.168.x.x` → `${ENV_VAR}` 或 `127.0.0.1` 默认值
2. **替换个人路径** — 绝对路径 → `./data` 相对路径或 `DATA_PATH` 环境变量
3. **排除真实策略** — `strategies/` 只保留空壳 `__init__.py`
4. **排除运行产物** — `backtest_output*/`、`logs/`、`data/` 不进模板
5. **保留 .env.example** — 所有部署配置走环境变量

### 模板 vs 原始代码的差异

| 文件 | 原始代码 | 模板 |
|------|----------|------|
| `config/settings.yaml` | 含内网 IP | 用 `settings.example.yaml`，所有 IP 为 `127.0.0.1` |
| `data_manager/klines_loader.py` | `DATA_PATH` 默认值为绝对路径 | 默认值改为 `./data` |
| `strategies/__init__.py` | import 真实策略 | 只有 docstring，空壳 |
| `config/openviking_sync.yaml` | 含内网 IP | 用 `${OPENVIKING_SERVER_URL}` 占位 |
| `config/backtest.yaml` | 含内网 IP | 用 `${ENV_VAR}` 占位 |

---

## Critical Constraints

### 编码红线（来自 AI_CONSTRAINTS.md）

| # | 约束 | 原因 |
|---|------|------|
| 1 | 禁止入场用未闭合 K 线 | 未来函数，回测失真 |
| 2 | 禁止 `datetime.now()` 做时间戳 | 用 K 线时间，保证可重现 |
| 3 | 禁止 Strategy 类算指标 | 指标在 Core.analyze() 内用已闭合 K 线 |
| 4 | 禁止跳过数据不足检查 | 指标计算错误 |
| 5 | 禁止回测模式启用 K 线冷却 | 回测信号缺失 |
| 6 | 禁止可变默认值 | `[]`, `{}` 共享状态 |
| 7 | 禁止缓存字段持久化 | 缓存不进 `to_persist_dict()` |
| 8 | 禁止自定义止损计数字段 | 用 `BaseState.stop_loss_date` |
| 9 | 禁止直接用原始 K 线入场 | 多周期必须 `get_closed_data()` |

### 配置文件格式

| 规则 | 错误示例 | 正确示例 |
|------|----------|----------|
| 必须有顶层策略名键 | `name: xxx` 在顶层 | `{strategy_name}:\n  name: xxx` |
| 参数放在 params 下 | `obs_n: 20` 在顶层 | `params:\n  obs_n: 20` |
| symbols 用数组格式 | `symbol: BTCUSDT` | `symbols:\n  - BTCUSDT` |

### 开源约束

| # | 约束 |
|---|------|
| 1 | 禁止硬编码内网 IP（`192.168.x.x`），必须走环境变量 |
| 2 | 禁止硬编码个人路径（`/home/xxx`），用相对路径或 `DATA_PATH` 环境变量 |
| 3 | 禁止在代码中写入 API Key / Secret，用 `.env` + `.gitignore` |
| 4 | `config/settings.yaml` 不进模板，用 `settings.example.yaml` 替代 |
| 5 | 测试中 mock IP 可保留，但需加注释说明是假数据 |

---

## 执行顺序

```
用户输入:
  全自动: /trading-dev new --from <source>
  交互:   /trading-dev new
  单步:   /trading-dev scaffold | develop | backtest | benchmark
       ↓
Phase 0: 环境预检 + 策略信息获取
  ├── Step 0: 环境预检（Python/ta-lib/pip/K线数据/磁盘）
  ├── Step 1: 解析策略来源（文件/目录/URL/自然语言/多轮对话）
  ├── Step 2: 统一提取为策略规格
  └── Step 3: 执行确认（全自动→直接执行 / 交互→用户确认）
       ↓
Phase 1: 脚手架创建（一次性）
  ├── 复制模板代码
  ├── 创建 Python venv + 安装依赖（预检已知 Python 版本和 ta-lib 状态）
  ├── 准备 1m K 线数据（symlink/下载）
  ├── git init + 首次 commit
  └── 输出就绪报告
       ↓
┌─────────────────────────────────────────────┐
│ Loop (最多 5 轮)                             │
│                                             │
│   Phase 2: 生成/修改策略代码                  │
│     ├── 加载规范文档                          │
│     ├── 生成 strategy.py + core.py           │
│     ├── 生成配置 + 测试                       │
│     ├── 注册策略                              │
│     ├── 验证配置格式                          │
│     └── 运行审查检查表                        │
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
│   最大轮次 → 输出当前最佳 + 未达标标记         │
└─────────────────────────────────────────────┘
       ↓
完成: benchmark.md 路径 + 回测结果摘要
```

---

## Related Skills

- `zk_cta-strategy-dev`: 策略开发一站式（逻辑确认 + 代码生成）
- `zk_cta-strategy-logic-refine`: 策略逻辑确认
- `zk_cta-strategy-implement`: 策略代码生成
- `zk_cta-backtest-run`: 对话式回测
- `zk_cta-backtest-config`: 回测配置管理
