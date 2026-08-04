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

### 方式 2：npx skills CLI

```bash
npx skills add ZkwareDAO/trading --skill trading-dev
```

重启 Claude Code 会话以加载。

### 方式 3：手动安装

```bash
git clone https://github.com/ZkwareDAO/trading ~/.claude/plugins/trading
```

编辑 `~/.claude/plugins/installed_plugins.json`，添加：

```json
{
  "version": 2,
  "plugins": {
    "trading-dev@trading-skills": [
      {
        "scope": "user",
        "installPath": "/home/<you>/.claude/plugins/trading",
        "version": "0.1.0"
      }
    ]
  }
}
```

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

## Contributing

Contributions are welcome: bug fixes, documentation, and feature ideas; past contributions are credited per release in [`CHANGELOG.md`](CHANGELOG.md).

## License

Apache License 2.0
