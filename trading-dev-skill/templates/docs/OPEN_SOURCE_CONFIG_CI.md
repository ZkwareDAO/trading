# 配置收敛与 CI 方案

> P1 文档：开源后的配置治理与持续集成方案。本文是规划文档，部分尚未落地。

## 一、配置收敛现状（P0 已完成）

### 配置层次（自顶向下）

| 层 | 文件 | 作用 | 入库 |
|----|------|------|------|
| 1 环境变量 | `.env` | 服务地址 / 密钥实际值 | ❌（仅 `.env.example`） |
| 2 系统配置 | `config/settings.yaml` | 数据/信号/引擎全局参数 | ✅（`${VAR}` 占位） |
| 3 回测配置 | `config/backtest.yaml` | 回测专用参数 | ✅（`${VAR}` 占位） |
| 4 策略列表 | `config/strategies.yaml` | 策略名 + symbols + trading_mode | ✅ |
| 5 per-symbol | `strategies/<name>/overrides/<symbol>.yaml` | 单标的参数覆盖 | ✅ |

### 已完成的收敛

- 删除 `config/zktrading/`（117 文件）+ `config/zktrading.yaml` → 统一到 `strategies/<name>/overrides/`
- 删除 `config/openviking_sync.yaml` + 模块
- 删除 K 线订阅 Kafka（`KlineKafkaConsumer`），保留信号推送 Kafka（`KafkaSignalProducer`）
- 所有内网 IP / `zkware.cn` → `${ENV_VAR}` 占位
- `strategies_loader.py` 默认 `config_dir: "strategies"`，per-symbol 路径 `strategies/<name>/overrides/<symbol>.yaml`

### 占位符约定

`settings.yaml` / `backtest.yaml` 内用 `${VAR_NAME}` 引用环境变量。加载时由 `strategy_core/utils/config_loader.py` 解析替换。

`.env.example` 提供全部变量清单：
- `DATA_PATH` / `KLINES_WS_URL` / `KLINES_HTTP_URL`
- `FACTORY_ENDPOINT` / `POSITION_PROXY_URL`
- `SIGNAL_HUB_ENDPOINT` / `KAFKA_BOOTSTRAP_SERVERS`

## 二、待落地的配置优化（P2 候选）

### 2.1 配置校验脚本

新增 `scripts/validate_config.py`：
- 校验 `settings.yaml` / `strategies.yaml` YAML 语法
- 校验所有 `${VAR}` 在 `.env` 或环境变量中已定义
- 校验 `strategies.yaml` 里每个 symbol 在 `strategies/<name>/overrides/<symbol>.yaml` 存在
- CI 中必跑，防止配置漂移

### 2.2 单一配置入口（远期）

当前 `settings.yaml` + `strategies.yaml` + per-symbol 三层对新手偏复杂。远期可考虑：
- 提供 `scripts/init_config.py` 交互式生成 `.env` + `settings.yaml`
- 或合并 `settings.yaml` 的 `strategies` 段到 `strategies.yaml`（目前 `run_strategies_manager.py` 已支持两种格式，推荐用 `strategies.yaml`）

## 三、CI 方案

### 3.1 GitHub Actions 工作流（建议）

`.github/workflows/ci.yml`：

```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: 安装依赖（无 TA-Lib C 库，跳过依赖它的测试）
        run: |
          pip install -r requirements.txt -r requirements-dev.txt
      - name: 语法检查
        run: python3 -c "import ast,glob;[ast.parse(open(f).read()) for f in glob.glob('**/*.py',recursive=True)]"
      - name: 配置校验
        run: python3 scripts/validate_config.py
      - name: 数据管理器测试
        run: python3 -m pytest data_manager/tests/ -v --ignore=data_manager/tests/test_ws_reconnect.py
      - name: 回测测试
        run: python3 -m pytest backtest/tests/ -v
```

### 3.2 CI 前需修复的预存问题

| 问题 | 位置 | 处理 |
|------|------|------|
| `test_register_factory.py` 硬编码 `/home/qpw/workspace/cta-strategy-code` | 已归档到 `docs/archive/` | ✅ |
| WS 重连测试依赖真实服务 | `data_manager/tests/test_ws_reconnect.py` | CI 中 `--ignore` |
| `pandas_ta` / `pytest-asyncio` 未在 requirements | requirements.txt | 需补 |
| 部分 backtest 测试引用已删策略 `cta_rbreaker_v3` | `backtest/tests/` | 需清理 fixture |

### 3.3 脱敏检查（CI gate）

新增 `scripts/check_desensitization.py`，扫描：
- 禁止出现的 IP 正则：`192\.168\.\d+\.\d+`、`10\.\d+\.\d+\.\d+`、`172\.(1[6-9]|2\d|3[01])\.\d+\.\d+`
- 禁止域名：`zkware.cn`、内网域名
- 禁止密钥模式：`api_key = "..."`、`password = "..."`（非占位）

CI 中作为强制 gate，命中即失败。

## 四、文档统一（P1）

### 4.1 现状

文档分散在：
- 根 `README.md` + `ARCHITECTURE.md`（若存在）
- `docs/INDEX.md`（索引）
- `docs/claude/`（架构 + 运维）
- `docs/strategy/`（开发指南族）
- 各模块 `README.md`（`data_manager/`、`backtest/`、`strategies/`）

### 4.2 统一原则

- `docs/INDEX.md` 为唯一入口，所有文档从索引可达
- 配置相关全部指向本文 + `docs/claude/operations.md`
- 策略开发指向 `docs/strategy/QUICKSTART.md` 起步
- 历史文档移入 `docs/archive/`，索引不指向归档

### 4.3 待办

- [ ] 更新 `docs/INDEX.md`：加入 `CONTRIBUTING.md`、`LICENSE`、本文链接
- [ ] 更新 `docs/claude/operations.md`：将 `zktrading` 引用改为 `strategies/<name>/overrides/`
- [ ] 更新 `docs/SCRIPTS.md`：移除已删脚本（daily_backtest_sync.sh 等）
- [ ] 根 `ARCHITECTURE.md` 若存在，校对路径

## 五、验收标准

P1 完成的标志：
1. 本文档存在且索引可达
2. `docs/INDEX.md` 更新到当前结构（无失效链接）
3. CI 方案文档可执行（脚本占位即可，不要求落地）
4. 生产代码 + 配置零内网地址 / 真实密钥
