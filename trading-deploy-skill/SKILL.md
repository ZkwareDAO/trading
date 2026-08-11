---
name: trading-deploy
description: 策略部署上线 skill。git pull 拉取策略代码 → AI 分析配置 → WebSocket 数据验证 → K线数据准备 loop → 创建配置文件 → 启动策略运行。
origin: trading
---

# Trading Deploy — 策略部署上线全链路

从策略代码拉取到生产运行，一条链路闭环。

**核心行为**：git pull → AI 分析策略结构和配置 → 验证数据流 → 准备K线数据 → 生成运行时配置 → 启动策略。

## When to Activate

- `/trading-deploy run` — 完整部署流程
- `/trading-deploy run --strategy ema_rsi` — 部署指定策略
- `/trading-deploy run --git-url git@github.com:user/strategies.git` — 指定 git 地址
- `/trading-deploy analyze` — 只分析策略（不部署）
- `/trading-deploy prepare-data` — 只准备K线数据
- `/trading-deploy start --strategy ema_rsi` — 只启动已配置好的策略
- `/trading-deploy status` — 查看运行中的策略

## Commands

| 命令 | 说明 |
|------|------|
| `/trading-deploy run` | 完整部署流程（Phase 0→5） |
| `/trading-deploy run --strategy NAME` | 部署指定策略 |
| `/trading-deploy run --git-url URL` | 指定 git 地址部署 |
| `/trading-deploy analyze` | 只分析策略结构（Phase 2） |
| `/trading-deploy prepare-data` | 只准备K线数据（Phase 3） |
| `/trading-deploy start --strategy NAME` | 只启动策略（Phase 5） |
| `/trading-deploy status` | 查看运行中的策略状态 |

---

## Phase 0: 环境预检

```bash
PYTHON_CMD="${PYTHON_CMD:-python3}"
$PYTHON_CMD --version &>/dev/null && echo "✅ Python" || echo "❌ Python 不可用（阻塞）"
git --version &>/dev/null && echo "✅ git" || echo "❌ git 不可用（阻塞）"
KLINE_DIR="${KLINE_DATA_DIR:-./data/strategies/1m}"
[ -d "$KLINE_DIR" ] && echo "✅ K线目录: $KLINE_DIR" || echo "⚠ K线目录不存在"
```

| 检测项 | 不达标 |
|--------|--------|
| Python | **阻塞** |
| git | **阻塞** |
| K线目录 | 非阻塞（Phase 3 可创建） |

---

## Phase 1: 配置初始化

优先级：`.env` > `config.yaml` > 默认值

| 配置项 | 必需 | 默认值 |
|--------|------|--------|
| `STRATEGIES_GIT_URL` | Phase 2 | 无 |
| `STRATEGIES_DIR` | 全流程 | ./strategies |
| `KLINE_DATA_DIR` | Phase 3+ | ./data/strategies/1m |
| `LOGS_DIR` | 全流程 | ./logs |
| `DEPLOY_OUTPUTS_DIR` | Phase 4+ | ./deploy_outputs |

---

## Phase 2: 策略代码获取 + AI 分析

### Step 1: git pull

```bash
python3 git_pull.py \
    --git-url "${STRATEGIES_GIT_URL}" \
    --strategies-dir "${STRATEGIES_DIR}" \
    --branch "${GIT_BRANCH:-main}"
```

**git_pull.py 行为**：

1. 确认 git URL（参数 > .env > 交互询问）
2. `STRATEGIES_DIR` 有 `.git/` → `git pull`，否则 → `git clone`
3. 列出所有策略目录和配置文件

### Step 2: AI 分析策略配置

```bash
python3 git_pull.py --analyze --strategy "${STRATEGY_NAME}"
```

**分析输出**：

```
============================================================
  AI 策略分析 — ema_rsi
============================================================
  配置:       config.test.yaml
  代币:       BTCUSDT, ETHUSDT, SOLUSDT
  时间框架:   4h, 1h
  方向:       neutral
  
  技术指标:
    OBV period=20 (4h: 需3.4天)
    EMA period=200 (4h: 需33.4天)  ← 最大依赖
  
  ✅ 代码完整 (strategy.py + ema_rsi_core.py)
============================================================
```

### Step 3: 用户确认

```
📋 以上是策略分析结果，是否继续部署？(y/n/edit)
```

---

## Phase 3: K线数据准备（loop）

### Step 1: 计算数据需求

```bash
python3 calc_data_requirements.py \
    --strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" \
    --kline-data-dir "${KLINE_DATA_DIR}"
```

> 共享模板，优先使用 `trading-discovery-skill/templates/calc_data_requirements.py`。

### Step 2: 数据就绪检查 → loop

```bash
python3 data_readiness_check.py \
    --strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" \
    --symbols "${SYMBOLS}" \
    --kline-data-dir "${KLINE_DATA_DIR}" \
    --required-days "${REQUIRED_DAYS}"
```

**loop 流程**：

```
检查数据 → 充足? ──YES──→ Phase 4
              │
              NO
              ↓
         尝试下载 → 成功? ──YES──→ 回到检查
                        │
                        NO
                        ↓
                   询问用户跳过?
                    ├── 跳过 → Phase 4 (partial)
                    └── 不跳过 → 退出
```

**退出条件**：数据充足 | 用户跳过 | 用户取消 | 最多 5 轮重试

---

## Phase 4: 创建配置文件

### Step 1: 生成运行时配置

```bash
python3 create_config.py \
    --strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" \
    --symbols "${SYMBOLS}" \
    --output "${DEPLOY_OUTPUTS_DIR}/${DEPLOY_DATE}/${STRATEGY_NAME}-runtime.yaml"
```

**生成配置包含**：策略参数 + 资金/杠杆/风控 + WebSocket URL + 日志设置

### Step 2: 用户确认

```
📋 运行时配置已生成，确认启动？(y/n/edit)
```

---

## Phase 5: 启动策略

### Step 1: WebSocket 验证（可选）

```bash
python3 subscribe_websocket.py \
    --symbol "${FIRST_SYMBOL}" \
    --test --timeout 30
```

### Step 2: 启动策略

```bash
bash run_strategy.sh \
    --strategy "${STRATEGY_NAME}" \
    --config "${DEPLOY_OUTPUTS_DIR}/${DEPLOY_DATE}/${STRATEGY_NAME}-runtime.yaml" \
    --log-dir "${LOGS_DIR}" \
    --background
```

**输出**：

```
✅ 策略已启动
  策略: ema_rsi | PID: 12345
  日志: logs/ema_rsi-20260810.log
  监控: tail -f logs/ema_rsi-20260810.log
```

---

## 环境变量

### 必需

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `STRATEGIES_GIT_URL` | — | 策略 git 仓库 |
| `STRATEGIES_DIR` | ./strategies | 策略本地目录 |
| `KLINE_DATA_DIR` | ./data/strategies/1m | K线数据目录 |
| `LOGS_DIR` | ./logs | 日志目录 |
| `DEPLOY_OUTPUTS_DIR` | ./deploy_outputs | 部署产物目录 |

### WebSocket

| 变量 | 默认值 |
|------|--------|
| `WS_URL` | wss://stream.binance.com:9443/ws |
| `REST_URL` | https://api.binance.com |

### 策略运行

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEFAULT_CAPITAL` | 10000 | 默认资金 (USDT) |
| `DEFAULT_LEVERAGE` | 1 | 默认杠杆 |
| `MAX_POSITIONS` | 3 | 最大持仓数 |
| `POSITION_SIZE_PCT` | 0.1 | 仓位比例 |

---

## 执行顺序

```
Phase 0: 环境预检 → Phase 1: 配置初始化
  → Phase 2: git pull + AI 分析 + 用户确认
  → Phase 3: K线数据准备 loop
  → Phase 4: 创建配置文件 + 用户确认
  → Phase 5: WebSocket 验证 + 启动策略
```

---

## Related Skills

- `trading-dev`: 写策略
- `trading-discovery`: 测策略（回测探索）
- `trading-replay`: 管策略（每日备份+回放）

> **边界**: dev 写 → discovery 测 → deploy 跑 → replay 管
