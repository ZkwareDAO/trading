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

### 方式 4：symlink（开发迭代）

```bash
ln -s /path/to/trading/trading-dev-skill ~/.claude/skills/trading-dev
```

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

## 新增 Skill

本项目支持多 skill 架构，新增只需 3 步：

1. 创建 skill 目录（含 `SKILL.md` + `templates/`）
2. 在 `.claude-plugin/marketplace.json` 的 `plugins` 数组追加条目
3. 在 `commands/` 下添加命令入口 `.md`

## 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Claude Code | 最新版 | CLI / Desktop / IDE 扩展 |
| Python | 3.10+ | 策略运行环境 |
| ta-lib C 库 | 0.4.0 | 回测指标计算（可选） |

## License

MIT
