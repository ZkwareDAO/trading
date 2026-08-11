# Trading Dev Skill

CTA 量化策略开发全生命周期 Claude Code Skill — 脚手架 → 策略编码 → 回测验证 → benchmark 输出，loop-engineering 跨 Phase 大闭环。

## 安装

### 方式 1：Claude Code Plugin Marketplace（推荐）

```bash
claude plugin marketplace add ZkwareDAO/trading
claude plugin install trading-dev@trading-skills
```

更新：

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
ln -s /path/to/trading/trading-dev-skill ~/.claude/skills/trading-dev
```

无需重启，下次对话自动加载。symlink 模式不注册斜杠命令，需 `/trading-dev` 时用方式 1/2。

### 方式 4：OpenAI Codex CLI

```bash
# 1. 克隆仓库
git clone https://github.com/ZkwareDAO/trading ~/.codex/trading

# 2. 创建 skill symlink（Codex 自动发现）
ln -s ~/.codex/trading/codex/trading-dev ~/.codex/skills/trading-dev

# 3. 创建 prompt 触发器
ln -s ~/.codex/trading/commands/trading-dev.md ~/.codex/prompts/trading-dev.md

# 4. 重启 Codex
```

项目级安装（仅当前项目生效）：

```bash
mkdir -p .agents/skills/trading-dev
cp -r codex/trading-dev/* .agents/skills/trading-dev/

mkdir -p .agents/prompts
cp commands/trading-dev.md .agents/prompts/trading-dev.md
```

Codex 触发方式：`$trading-dev` 直接调用，或 `/prompts:trading-dev` 手动触发。

详细说明见 [.codex/INSTALL.md](.codex/INSTALL.md)。

## 使用

| 命令 | 模式 | 说明 |
|------|------|------|
| `/trading-dev new` | 交互 | 逐步确认策略信息 |
| `/trading-dev new --from <source>` | 全自动 | 从文件/URL/描述零交互 |
| `/trading-dev new <描述>` | 全自动 | 从自然语言提取 |
| `/trading-dev scaffold` | 单步 | 只创建脚手架 |
| `/trading-dev develop` | 单步 | 只生成策略代码 |
| `/trading-dev backtest` | 单步 | 只跑回测 |
| `/trading-dev benchmark` | 单步 | 只输出 benchmark |

## 核心特性

- **三种模式**：全自动 / 交互 / 单步
- **loop-engineering**：回测不达标自动回到策略开发修改，循环直到达标
- **完整模板**：strategy_core / backtest / data_manager / scripts 一键脚手架

## 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Claude Code | 最新版 | CLI / Desktop / IDE 扩展 |
| Python | 3.10+ | 策略运行环境 |
| ta-lib C 库 | 0.4.0 | 回测指标计算（可选） |

## 贡献

欢迎贡献：bug 修复、文档完善、功能建议；历史贡献按版本记录在 [`CHANGELOG.md`](CHANGELOG.md) 中。

## License

Apache License 2.0
