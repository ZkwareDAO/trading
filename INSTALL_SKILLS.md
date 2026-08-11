# Trading Skills — 安装指南

一次性安装 trading-dev / trading-discovery / trading-deploy / trading-replay 四个 skill。

> 本文档所有命令均已在 Claude Code 2.1.x 上实测通过。不包含 `npx skills` / `openclaw` / `clawhub` 等虚构 CLI。

## 前置要求

| 依赖 | 版本 | 验证 |
|------|------|------|
| Claude Code | 最新版 | `claude --version` |
| Python | 3.10+ | `python3 --version` |
| git | 任意 | `git --version` |

---

## 方式 1：Claude Code Plugin Marketplace（推荐）

从 GitHub 仓库安装，自动读取根目录 `.claude-plugin/marketplace.json` 注册全部 4 个 plugin。

```bash
# 1. 添加 marketplace 源
claude plugin marketplace add ZkwareDAO/trading

# 2. 安装 4 个 skill（plugin@marketplace 格式）
claude plugin install trading-dev@trading-skills
claude plugin install trading-discovery@trading-skills
claude plugin install trading-deploy@trading-skills
claude plugin install trading-replay@trading-skills

# 3. 重启 Claude Code 会话以加载
```

**作用域**：默认 `user`（全局生效）。仅当前项目用 `--scope local`，仅当前 repo 用 `--scope project`。

**更新**：

```bash
claude plugin marketplace update                  # 拉取 marketplace 最新版本元数据
claude plugin update trading-dev@trading-skills   # 更新单个 plugin
```

**卸载**：

```bash
claude plugin uninstall trading-dev@trading-skills
claude plugin marketplace remove trading-skills
```

---

## 方式 2：本地路径安装（适合开发迭代 / 未 push 到 GitHub）

直接用本地 repo 路径作 marketplace，改代码后需重新 update。

```bash
# 1. 添加本地 marketplace
claude plugin marketplace add /home/qpw/workspace/trading --scope local

# 2. 安装（同方式 1，加 --scope local）
claude plugin install trading-dev@trading-skills --scope local
claude plugin install trading-discovery@trading-skills --scope local
claude plugin install trading-deploy@trading-skills --scope local
claude plugin install trading-replay@trading-skills --scope local
```

> 本地 marketplace 不会自动同步代码改动。改完 SKILL.md / templates 后需 `claude plugin marketplace update trading-skills` 重新拉取。

---

## 方式 3：symlink（最快开发模式，跳过 plugin 系统）

直接把 skill 目录 symlink 到 `~/.claude/skills/`，Claude Code 自动发现 SKILL.md。

```bash
mkdir -p ~/.claude/skills
ln -s /home/qpw/workspace/trading/trading-dev-skill       ~/.claude/skills/trading-dev
ln -s /home/qpw/workspace/trading/trading-discovery-skill ~/.claude/skills/trading-discovery
ln -s /home/qpw/workspace/trading/trading-deploy-skill    ~/.claude/skills/trading-deploy
ln -s /home/qpw/workspace/trading/trading-replay-skill    ~/.claude/skills/trading-replay

# 验证
ls -la ~/.claude/skills/trading-*
```

无需重启，下次对话自动加载。改代码即时生效（symlink 直指源目录）。

> **注意**：symlink 模式不走 plugin 系统，`commands/*.md` 不会被注册为 `/trading-xxx` 斜杠命令。如需斜杠命令，用方式 1 或 2。

---

## 验证安装

在 Claude Code 中输入以下命令，应看到对应 skill 被激活：

| 命令 | 说明 |
|------|------|
| `/trading-dev new` | 新建策略项目 |
| `/trading-discover run --symbols BTCUSDT --strategies ema_rsi --start 20260601` | 多策略回测探索 |
| `/trading-deploy run` | 策略部署上线 |
| `/trading-replay run` | 每日备份 + 回放 |

或用 CLI 查询：

```bash
claude plugin list | grep trading
```

---

## 前置依赖（运行时）

| 依赖 | 安装 | 用于 |
|------|------|------|
| PyYAML | `pip install pyyaml` | 配置解析（全部 skill） |
| websockets | `pip install websockets` | deploy 的 WebSocket 订阅 |
| rsync | `sudo apt install rsync` | replay 的 SCP 备份 |
| ta-lib C 库 | 见 trading-dev SKILL.md Phase 0 | dev 的回测指标计算 |

---

## 配置

每个 skill 有独立的 `.env.example`，复制到运行目录编辑：

```bash
# discovery + deploy 共享 K线/策略目录配置
cp trading-discovery-skill/templates/.env.example .env

# replay 需要 SCP 连接配置
cp trading-replay-skill/templates/.env.example .env  # 编辑 SCP_HOST / SCP_USER / SCP_STRATEGY_DIR

# deploy 需要 git URL + WebSocket 配置
cp trading-deploy-skill/templates/.env.example .env
```

> 三个 skill 共享 `KLINE_DATA_DIR` / `STRATEGIES_DIR` 等字段，建议合并到同一份 `.env`。

---

## 四个 Skill 关系

```
trading-dev        → 写策略 (scaffold → 编码 → 回测 → benchmark, loop-engineering 闭环)
trading-discovery  → 测策略 (多代币 × 多策略 × 自定义时间范围回测)
trading-deploy     → 跑策略 (git pull → K线准备 → 配置 → 启动)
trading-replay     → 管策略 (实盘每日 SCP 备份 + 回放回测)
```

边界：dev 写 → discovery 测 → deploy 跑 → replay 管。

---

## 故障排查

| 症状 | 原因 | 修复 |
|------|------|------|
| `Marketplace not found` | GitHub 仓库未公开或未 push | 确认 `git push origin main` 已完成 |
| `Plugin not found in marketplace` | marketplace.json 未含该 plugin | 检查 `.claude-plugin/marketplace.json` 的 `plugins[].name` |
| 斜杠命令不生效 | 用了 symlink 模式（方式 3） | 改用方式 1/2，或手动 `cp commands/*.md` 到 plugin 目录 |
| 改了代码不生效 | 本地 marketplace 缓存未更新 | `claude plugin marketplace update trading-skills` |
