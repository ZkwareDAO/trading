# Trading Dev Skill — 安装指南

## 环境要求

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Claude Code | 最新版 | CLI / Desktop / IDE 扩展均可 |
| Python | 3.10+ | Python 模式策略运行环境 |
| Rust | 以模板 `rust-toolchain.toml` 为准（当前 1.98.1） | Rust 模式策略运行环境（rustc + cargo + rustup）；浮动 stable 会导致 fmt/clippy 漂移 |
| ta-lib C 库 | 0.4.0 | 回测指标计算（可选，缺则回测不可用；仅 Python 模式需要） |
| 期货 1m K 线 | — | **期货模式必需**：用户提供逐合约 CSV 目录或已生成的 1m CSV；模板不附带、不下载 |

## 安装方式

### 方式 1：Claude Code Plugin Marketplace（推荐）

```bash
# 添加 marketplace 源
claude plugin marketplace add ZkwareDAO/trading

# 安装 trading-dev skill
claude plugin install trading-dev@trading-skills
```

**更新：**

```bash
claude plugin marketplace update
claude plugin update trading-dev@trading-skills
```

### 方式 2：本地路径安装（开发迭代）

```bash
claude plugin marketplace add /path/to/trading --scope local
claude plugin install trading-dev@trading-skills --scope local
```

改完代码后需 `claude plugin marketplace update trading-skills` 重新拉取。

### 方式 3：symlink（最快开发模式）

```bash
ln -s /home/qpw/workspace/trading/trading-dev-skill ~/.claude/skills/trading-dev
```

源目录改动即时生效，无需重启。symlink 模式不注册斜杠命令，需 `/trading-dev` 时用方式 1/2。

## 验证安装

在 Claude Code 中输入 `/trading-dev`，应看到 skill 被激活。

## 自定义配置

### 模板来源

根据 `STRATEGY_LANG` 选择模板仓库：

| 语言 | 仓库 | 默认 Tag |
|------|------|----------|
| Python（默认） | `https://github.com/ZkwareDAO/strategy-template.git` | `v1.0.0` |
| Rust | `https://github.com/ZkwareDAO/strategy-template-rs.git` | 空（跟 `main`；`strategy.yaml` 与期货模板尚未打 tag） |

**选择语言与市场**：
```bash
# 默认 Python + crypto
export STRATEGY_LANG=python
export STRATEGY_MARKET=crypto

# Rust 模式（crypto 或 futures）
export STRATEGY_LANG=rust
export STRATEGY_MARKET=futures

# 期货模式必须提供 K 线位置（不下载）
export FUTURES_EXCHANGE=SHFE
export FUTURES_SYMBOL=CU
export FUTURES_KLINES_DIR=/path/to/klines   # 或 /path/to/CU_1m.csv
export FUTURES_INITIAL_CASH=1000000
```

**指定版本（tag）**：
```bash
# Python 默认 v1.0.0；Rust 默认跟 main，可显式覆盖
export STRATEGY_TEMPLATE_TAG=v1.0.0
```

**离线回退（本地缓存）**：
```bash
# 设置后优先使用本地模板（如当前最新开发线）
export TRADING_DEV_TEMPLATE_DIR=/home/qpw/workspace/strategy-template-rs
```

### 期货模式前置（仅 Rust 模板，硬要求）

Python 模板没有 `contracts.yaml`、整数手/乘数、日盘夜盘时段与平今语义，
**不能用于期货**；期货必须用 `STRATEGY_LANG=rust` + `strategy-template-rs`。

模板**不提供期货行情下载**，也没有自动下载命令。必须先拿到用户数据：

```bash
# A. 逐合约原始 CSV 目录（文件名 {PRODUCT}{YYMM}.csv，列
#    symbol,bob|open_time,open,high,low,close,volume,position）
cargo run -p strategy-data --bin roll_build -- \
  --in <用户目录> --product CU --out <临时目录>
cp <临时目录>/1m/CU_CONT_1m.csv data/klines/1m/SHFE/cn_futures/CU_1m.csv

# B. 用户已有标准 10 列 1m CSV：直接落位，或回测时 --data-dir 指向数据根
```

同时确认：

- 品种已在仓库根 `config/contracts.yaml` 声明（乘数/保证金/费率/时段），
  否则会静默退化为 crypto 兼容模式（结果不可信）。
- `_global.yaml` 显式 `initial_cash`（元），按 universe 等分后仍够开 ≥1 手。
- 回测区间落在数据覆盖范围内；不足时向用户索要，不得用 mock/其他品种顶替。

### Benchmark 输出路径

默认输出到 `./benchmark_output`。如需输出到 Obsidian 笔记库：

```bash
# 在项目 .env 中设置
BENCHMARK_OUTPUT_PATH=/path/to/obsidian_vault/quant_research
```

## ta-lib C 库安装

回测依赖 ta-lib Python 包，该包需要系统级 C 库：

**Ubuntu/Debian：**
```bash
wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz
tar -xzf ta-lib-0.4.0-src.tar.gz
cd ta-lib && ./configure && make && sudo make install
ldconfig
```

**macOS：**
```bash
brew install ta-lib
```

**Windows (WSL)：** 同 Ubuntu 步骤。

## 目录结构

```
trading/
├── plugin.json                  # 根 manifest（claude plugin install 入口）
├── .claude-plugin/
│   ├── plugin.json              # Claude Code 专用 manifest
│   └── marketplace.json         # marketplace 注册（支持多 skill）
├── commands/
│   └── trading-dev.md           # /trading-dev 命令入口
├── trading-dev-skill/
│   ├── SKILL.md                 # Skill 定义（Claude Code 读取）
│   └── references/
│       ├── INSTALL.md           # 本文件
│       └── ANALYSIS.md          # 流程/时序分析
└── cta_volume_resonance/        # 未来 skill 示例
```

> **项目模板**已从 skill 目录中移除，改为从 `https://github.com/ZkwareDAO/strategy-template.git` 自动克隆。

## 新增 Skill 流程

在 trading 项目下新增 skill 只需 3 步：

1. **创建 skill 目录**：如 `cta_volume_resonance/`，内含 `SKILL.md` + `templates/`
2. **追加 marketplace.json 条目**：在 `.claude-plugin/marketplace.json` 的 `plugins` 数组中添加新条目
3. **创建命令入口**：在 `commands/` 下添加 `xxx.md`

## 使用流程

```
# 选择语言与市场（默认 Python + crypto）
export STRATEGY_LANG=python      # 或 rust
export STRATEGY_MARKET=crypto    # 或 futures（需先提供 K 线路径）

/trading-dev new              → 创建项目脚手架 + 策略开发 + 回测验证
/trading-dev new --from <src> → 全自动模式
/trading-dev scaffold         → 只创建脚手架
/trading-dev backtest         → 对当前项目执行回测
```

详细流程见 SKILL.md。
