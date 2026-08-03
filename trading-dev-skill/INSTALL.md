# Trading Dev Skill — 安装指南

## 环境要求

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Claude Code | 最新版 | CLI / Desktop / IDE 扩展均可 |
| Python | 3.10+ | 策略运行环境 |
| ta-lib C 库 | 0.4.0 | 回测指标计算（可选，缺则回测不可用） |

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

### 方式 2：npx skills CLI

```bash
npx skills add ZkwareDAO/trading --skill trading-dev
```

重启 Claude Code 会话以加载新 skill。

### 方式 3：手动安装（开发者/源码）

```bash
# 克隆仓库
git clone https://github.com/ZkwareDAO/trading ~/.claude/plugins/trading

# 注册到 installed_plugins.json
# 编辑 ~/.claude/plugins/installed_plugins.json，在 plugins 对象中添加：
```

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

更新方式：在插件目录内 `git pull`。

### 方式 4：symlink 安装（适合开发迭代）

```bash
# 假设源码在 /home/qpw/workspace/trading/trading-dev-skill/
ln -s /home/qpw/workspace/trading/trading-dev-skill ~/.claude/skills/trading-dev
```

源目录改动即时生效，无需重启。

## 验证安装

在 Claude Code 中输入 `/trading-dev`，应看到 skill 被激活。

## 自定义配置

### 模板目录

默认从 `~/.claude/skills/trading-dev/templates/` 读取模板。如需覆盖：

```bash
# 在 .env 或 shell profile 中设置
export TRADING_DEV_TEMPLATE_DIR=/custom/path/to/templates
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
│   ├── INSTALL.md               # 本文件
│   └── templates/               # 项目模板
│       ├── strategy_core/       # 基类框架
│       ├── backtest/            # 回测引擎
│       │   └── config/
│       │       ├── main.example.yaml
│       │       ├── main.legacy.example.yaml
│       │       ├── strategies.example.yaml
│       │       └── example/
│       ├── data_manager/        # K线数据管理
│       ├── scripts/             # 辅助脚本
│       ├── config/              # 配置模板
│       ├── docs/strategy/       # 开发规范文档
│       ├── strategies/          # 策略空壳（__init__.py）
│       ├── requirements.txt
│       ├── .env.example
│       ├── .gitignore
│       ├── run_strategies_manager.py
│       ├── run_strategy.py
│       ├── start.sh
│       └── stop.sh
└── cta_volume_resonance/        # 未来 skill 示例
```

## 新增 Skill 流程

在 trading 项目下新增 skill 只需 3 步：

1. **创建 skill 目录**：如 `cta_volume_resonance/`，内含 `SKILL.md` + `templates/`
2. **追加 marketplace.json 条目**：在 `.claude-plugin/marketplace.json` 的 `plugins` 数组中添加新条目
3. **创建命令入口**：在 `commands/` 下添加 `xxx.md`

## 使用流程

```
/trading-dev new              → 创建项目脚手架 + 策略开发 + 回测验证
/trading-dev new --from <src> → 全自动模式
/trading-dev scaffold         → 只创建脚手架
/trading-dev backtest         → 对当前项目执行回测
```

详细流程见 SKILL.md。
