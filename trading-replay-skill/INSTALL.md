# Trading Replay Skill — 安装指南

## 环境要求

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Claude Code | 最新版 | CLI / Desktop / IDE 扩展均可 |
| Python | 3.10+ | sync-exee.py / analyze_snapshot.py 运行环境 |
| PyYAML | 5.0+ | 配置文件解析 |
| SSH/SCP | 任意 | 策略代码备份（sync 模式需要） |
| rsync | 任意 | SCP 增量同步（推荐） |

## 安装方式

### 方式 1：Claude Code Plugin Marketplace（推荐）

```bash
# 添加 marketplace 源（首次）
claude plugin marketplace add ZkwareDAO/trading

# 安装 trading-replay skill
claude plugin install trading-replay@trading-skills
```

**作用域**：默认 `user`（全局）。仅当前项目用 `--scope local`。

**更新**：

```bash
claude plugin marketplace update
claude plugin update trading-replay@trading-skills
```

**卸载**：

```bash
claude plugin uninstall trading-replay@trading-skills
```

### 方式 2：本地路径安装（开发迭代）

```bash
claude plugin marketplace add /path/to/trading --scope local
claude plugin install trading-replay@trading-skills --scope local
```

改完代码后需 `claude plugin marketplace update trading-skills` 重新拉取。

### 方式 3：symlink（最快开发模式）

```bash
ln -s /path/to/trading/trading-replay-skill ~/.claude/skills/trading-replay
```

无需重启，下次对话自动加载。symlink 模式不注册斜杠命令，需 `/trading-replay` 时用方式 1/2。

## 验证安装

在 Claude Code 中输入 `/trading-replay`，应看到 skill 被激活。

或 CLI 查询：

```bash
claude plugin list | grep trading-replay
```

## 自定义配置

### 配置文件

```bash
cp templates/config.example.yaml config.yaml
cp templates/.env.example .env
```

编辑 `.env` 填入实际 SCP 连接信息：

| 变量 | 示例 | 说明 |
|------|------|------|
| `SCP_HOST` | `your-production-server` | 实盘机器 IP/域名 |
| `SCP_PORT` | `22` | SSH 端口 |
| `SCP_USER` | `trader` | SSH 用户名 |
| `SCP_PROJECT_DIR` | `/home/trader/cta_project` | 实盘项目根目录 |
| `SCP_KEY` | `~/.ssh/id_rsa` | SSH 私钥路径 |

### 定时任务

```bash
# 复制 crontab 模板
cp templates/crontab.example /tmp/trading-replay-crontab

# 修改路径为实际安装路径
sed -i 's|/path/to/replay|/actual/install/path|g' /tmp/trading-replay-crontab

# 安装 crontab
crontab /tmp/trading-replay-crontab
```

## 目录结构

```
trading-replay-skill/
├── SKILL.md                 # Skill 定义
├── INSTALL.md               # 本文件
└── templates/               # 模板文件
    ├── replay.sh            # 每日回放回测脚本
    ├── sync-exee.py         # 每日策略代码备份脚本
    ├── discover_remote.py   # 远程策略发现
    ├── analyze_snapshot.py  # 快照策略分析
    ├── strategy_analyzer.py
    ├── config.example.yaml  # 全局配置模板
    ├── .env.example         # 环境变量模板
    └── crontab.example      # 定时任务模板
```

## 使用流程

```
/trading-replay run                    → 执行当日完整流程（sync + replay）
/trading-replay run --date 20260801    → 指定日期
/trading-replay sync                   → 只备份策略代码
/trading-replay replay                 → 只执行回放回测
/trading-replay replay --date 20260801 → 重新回放指定日期
```

详细流程见 SKILL.md。
