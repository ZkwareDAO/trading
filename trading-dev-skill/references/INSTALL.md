# Trading Dev Skill — 安装指南

## 环境要求

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Claude Code | 最新版 | CLI / Desktop / IDE 扩展均可 |
| Python | 3.10+ | Python 模式策略运行环境 |
| Rust | 最新稳定版 | Rust 模式策略运行环境（rustc + cargo） |
| ta-lib C 库 | 0.4.0 | 回测指标计算（可选，缺则回测不可用；仅 Python 模式需要） |

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
| Rust | `https://github.com/ZkwareDAO/strategy-template-rs.git` | `v1.0.0` |

**选择语言**：
```bash
# 默认 Python；切换 Rust 模式
export STRATEGY_LANG=rust
```

**指定版本（tag）**：
```bash
# 默认拉取 v1.0.0；可覆盖为其他 tag
export STRATEGY_TEMPLATE_TAG=v1.0.0
```

**离线回退（本地缓存）**：
```bash
# GitHub 克隆失败时使用本地缓存
export TRADING_DEV_TEMPLATE_DIR=/path/to/local/strategy-template
```

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
│   └── INSTALL.md               # 本文件
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
# 选择语言（默认 Python）
export STRATEGY_LANG=python   # 或 rust

/trading-dev new              → 创建项目脚手架 + 策略开发 + 回测验证
/trading-dev new --from <src> → 全自动模式
/trading-dev scaffold         → 只创建脚手架
/trading-dev backtest         → 对当前项目执行回测
```

详细流程见 SKILL.md。
