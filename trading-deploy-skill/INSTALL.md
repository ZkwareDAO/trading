# Trading Deploy Skill — 安装指南

## 环境要求

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Claude Code | 最新版 | CLI / Desktop / IDE 扩展均可 |
| Python | 3.10+ | git_pull.py / create_config.py / subscribe_websocket.py 运行环境 |
| git | 任意 | 策略代码拉取 |
| websockets | 任意 | WebSocket 数据验证（Phase 5） |
| PyYAML | 5.0+ | 配置文件解析 |

## 安装方式

### 方式 1：Claude Code Plugin Marketplace（推荐）

```bash
# 添加 marketplace 源（首次）
claude plugin marketplace add ZkwareDAO/trading

# 安装 trading-deploy skill
claude plugin install trading-deploy@trading-skills
```

**作用域**：默认 `user`（全局）。仅当前项目用 `--scope local`。

**更新**：

```bash
claude plugin marketplace update
claude plugin update trading-deploy@trading-skills
```

**卸载**：

```bash
claude plugin uninstall trading-deploy@trading-skills
```

### 方式 2：本地路径安装（开发迭代）

```bash
claude plugin marketplace add /path/to/trading --scope local
claude plugin install trading-deploy@trading-skills --scope local
```

改完代码后需 `claude plugin marketplace update trading-skills` 重新拉取。

### 方式 3：symlink（最快开发模式）

```bash
ln -s /path/to/trading/trading-deploy-skill ~/.claude/skills/trading-deploy
```

无需重启，下次对话自动加载。symlink 模式不注册斜杠命令，需 `/trading-deploy` 时用方式 1/2。

## 验证安装

在 Claude Code 中输入 `/trading-deploy`，应看到 skill 被激活。

或 CLI 查询：

```bash
claude plugin list | grep trading-deploy
```

## 自定义配置

```bash
cp templates/config.example.yaml config.yaml
cp templates/.env.example .env
```

关键字段：

| 变量 | 说明 |
|------|------|
| `STRATEGIES_GIT_URL` | 策略 git 仓库地址 |
| `STRATEGIES_DIR` | 策略本地目录 |
| `KLINE_DATA_DIR` | 1m K 线数据目录 |
| `WS_URL` | WebSocket 订阅地址（默认币安） |
| `DEFAULT_CAPITAL` | 默认资金（USDT） |
| `DEFAULT_LEVERAGE` | 默认杠杆 |

## 目录结构

```
trading-deploy-skill/
├── SKILL.md                 # Skill 定义
├── INSTALL.md               # 本文件
└── templates/               # 模板文件
    ├── deploy.sh            # 部署入口脚本
    ├── run_strategy.sh      # 策略启动脚本
    ├── git_pull.py          # git pull + 策略分析
    ├── create_config.py     # 运行时配置生成
    ├── data_readiness_check.py  # K线数据就绪检查
    ├── subscribe_websocket.py   # WebSocket 订阅验证
    ├── config.example.yaml  # 全局配置模板
    └── .env.example         # 环境变量模板
```

## 使用流程

```
/trading-deploy run                          → 完整部署流程（Phase 0→5）
/trading-deploy run --strategy ema_rsi       → 部署指定策略
/trading-deploy run --git-url git@...        → 指定 git 地址
/trading-deploy analyze                      → 只分析策略
/trading-deploy prepare-data                 → 只准备 K 线数据
/trading-deploy start --strategy ema_rsi     → 只启动策略
/trading-deploy status                       → 查看运行状态
```

详细流程见 SKILL.md。
