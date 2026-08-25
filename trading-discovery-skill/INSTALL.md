# Trading Discovery Skill — 安装指南

## 环境要求

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Claude Code | 最新版 | CLI / Desktop / IDE 扩展均可 |
| Python | 3.10+ | 回测引擎运行环境 |
| 回测引擎 | — | trading-dev scaffold 生成的项目内 `backtest` 模块 |

## 安装方式

### 方式 1：Claude Code Plugin Marketplace（推荐）

```bash
# 添加 marketplace 源（首次）
claude plugin marketplace add ZkwareDAO/trading

# 安装 trading-discovery skill
claude plugin install trading-discovery@trading-skills
```

**作用域**：默认 `user`（全局）。仅当前项目用 `--scope local`。

**更新**：

```bash
claude plugin marketplace update
claude plugin update trading-discovery@trading-skills
```

**卸载**：

```bash
claude plugin uninstall trading-discovery@trading-skills
```

### 方式 2：本地路径安装（开发迭代）

```bash
claude plugin marketplace add /path/to/trading --scope local
claude plugin install trading-discovery@trading-skills --scope local
```

改完代码后需 `claude plugin marketplace update trading-skills` 重新拉取。

### 方式 3：symlink（最快开发模式）

```bash
ln -s /path/to/trading/trading-discovery-skill ~/.claude/skills/trading-discovery
```

无需重启，下次对话自动加载。symlink 模式不注册斜杠命令，需 `/trading-discovery` 时用方式 1/2。

## 验证安装

在 Claude Code 中输入 `/trading-discovery`，应看到 skill 被激活。

或 CLI 查询：

```bash
claude plugin list | grep trading-discovery
```

## 自定义配置

```bash
cp templates/config.example.yaml config.yaml
cp templates/.env.example .env
```

关键字段：

| 变量 | 说明 |
|------|------|
| `PROJECT_DIR` | CTA 项目根目录（含 `backtest` 模块） |
| `KLINE_DATA_DIR` | 1m K 线数据目录 |
| `STRATEGIES_DIR` | 策略代码目录 |
| `DISCOVERY_OUTPUTS_DIR` | 回测结果输出目录 |

## 目录结构

```
trading-discovery-skill/
├── SKILL.md                 # Skill 定义
├── INSTALL.md               # 本文件
└── templates/               # 模板文件
    ├── fetch_strategies.py  # 策略代码获取（git clone / pull）
    ├── discovery.py         # 回测执行（遍历策略目录调 wrapper）
    ├── download_data.py     # Binance 1m K线下载
    ├── init_overrides.py    # per-symbol 配置兜底
    ├── config.example.yaml  # 策略登记表模板（git_url）
    ├── backtest.example.yaml # 回测 run-profile 模板
    └── .env.example         # 环境变量模板
```

## 使用流程

```
# 1. 首次：填 config.yaml（策略目录名 + git_url）
cp templates/config.example.yaml config.yaml

# 2. 拉取策略代码
python3 templates/fetch_strategies.py --config config.yaml --strategies-dir .

# 3. 回测探索
python3 templates/discovery.py --start 20260601 --end 20260801
python3 templates/discovery.py --start 20260601 --strategies sar_snt
```

详细流程见 SKILL.md。
