---
name: trading-deploy
description: 策略部署上线 skill。git pull 拉取策略代码 → AI 分析配置 → WebSocket 数据验证 → K线数据准备 loop → 创建配置文件 → 启动策略运行。
origin: trading
---

# Trading Deploy — 策略部署上线全链路

从策略代码拉取到生产运行，一条链路闭环。

**核心行为**：git pull → AI 分析策略结构和配置 → 验证数据流 → 准备K线数据 → 生成运行时配置 → 启动策略。

**首要原则：无参数或参数不全时，必须一步一步引导用户，不要报错让用户自己补命令。**

## When to Activate

- `/trading-deploy`（无参数）→ **进入交互式引导**
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
| `/trading-deploy` | 无参数 → 进入交互式引导，一步一步收集参数 |
| `/trading-deploy run` | 完整部署流程（Phase 0→5） |
| `/trading-deploy run --strategy NAME` | 部署指定策略 |
| `/trading-deploy run --git-url URL` | 指定 git 地址部署 |
| `/trading-deploy analyze` | 只分析策略结构（Phase 2） |
| `/trading-deploy prepare-data` | 只准备K线数据（Phase 3） |
| `/trading-deploy start --strategy NAME` | 只启动策略（Phase 5） |
| `/trading-deploy status` | 查看运行中的策略状态 |

---

## Phase -1: 交互式引导（无参数/参数不全时） ← NEW

### 触发条件

进入引导的判定（满足任一即进入）：

| 条件 | 说明 |
|------|------|
| 无任何参数 | 用户只敲了 `/trading-deploy` |
| `run` 缺 `--strategy` 且无默认 | 必需参数缺失 |
| `start` 缺 `--strategy` | start 子命令必需策略名 |

**不进入引导**（直接走原流程）：

- `/trading-deploy run --strategy XXX`（参数齐全）
- `/trading-deploy status`（无需参数）
- `/trading-deploy analyze` / `prepare-data`（可用默认策略目录）

### 引导核心原则

1. **缺啥补啥**：用户已经给的参数跳过不问，只问缺失项
2. **一步一问**：每次只问一个问题，给默认值 + 示例
3. **每步可改**：用户随时能修改前面给过的值
4. **不报错**：宁可多问一轮，也不要扔"参数不全"给用户
5. **引导完汇总**：参数收齐后输出部署计划让用户确认，确认后才进 Phase 0

### 引导顺序

```
Step 1: 问子命令（run / analyze / prepare-data / start / status）
        → 给默认：run
       ↓
Step 2: 问策略（--strategy）
        → run / start 必需
        → 列出 STRATEGIES_DIR 下可用策略供选择
        → 若策略目录空，先走 git pull
       ↓
Step 3: 问 git 地址（--git-url，run 子命令）
        → 若已有策略，给默认：用本地已有
        → 若需拉取，从 .env / config.yaml 读默认，或询问
       ↓
Step 4: 汇总确认 → 用户确认后进 Phase 0
```

### Step 1 话术模板：问子命令

```
🧭 交互式引导 — 第 1 步（共 3 步）：要执行什么操作？

  1. run           ← 完整部署流程
  2. analyze       ← 只分析策略结构
  3. prepare-data  ← 只准备K线数据
  4. start         ← 只启动已配置策略
  5. status        ← 查看运行中策略

请选择（输入编号或命令名）。默认：1（run）
```

### Step 2 话术模板：问策略

```
🧭 交互式引导 — 第 2 步（共 3 步）：选择策略

可用策略（来自 ./strategies）：
  1. ema_rsi
  2. ict_v4

请选择（输入编号或策略名）：
  > 1 / ema_rsi
```

**若策略目录为空**：先引导 git 地址 → 走 git pull → 拉完再列策略。

### Step 3 话术模板：问 git 地址（run 子命令）

```
🧭 交互式引导 — 第 3 步（共 3 步）：策略代码来源

本地 ./strategies 已有策略，是否用本地代码？
  > y / 回车   ← 用本地已有代码
  > n          ← 重新 git pull，请输入 git 地址
```

**选 n 时**：

```
请输入 git 地址（默认从 .env 的 STRATEGIES_GIT_URL 读取）：
  > git@github.com:user/strategies.git
```

### Step 4 话术模板：汇总确认

```
📋 引导完成 — 部署计划确认

  操作:    run（完整部署）
  策略:    ema_rsi
  代码来源: 本地 ./strategies

确认执行？
  > y / 回车   ← 进 Phase 0
  > n          ← 取消
  > 改 XX      ← 修改某项
```

### 引导收尾

用户确认后：把引导参数组装成等效命令行 → **进入 Phase 0 正式预检**。

### 引导 vs 原流程对照

| 场景 | 旧行为 | 新行为 |
|------|--------|--------|
| `/trading-deploy` 无参数 | 不明确 | 进引导，问子命令→策略→git地址 |
| `/trading-deploy run` | 默认行为可能不明确 | 进引导，问策略 |
| `/trading-deploy run --strategy XXX` | 直接跑 | 跳过引导直接跑（参数齐全） |
| `/trading-deploy status` | 直接跑 | 跳过引导直接跑（无需参数） |

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
用户输入:
  /trading-deploy                  → 无参数，进引导
  /trading-deploy run              → 进引导（缺策略）
  /trading-deploy run --strategy X → 参数齐全，直接跑
       ↓
Phase -1: 交互式引导（无参数/参数不全时）  ← NEW
  ├── Step 1: 问子命令（默认 run）
  ├── Step 2: 问策略（列可用策略，目录空则先 git pull）
  ├── Step 3: 问 git 地址（默认用本地）
  └── Step 4: 汇总确认 → 进 Phase 0
       ↓
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
