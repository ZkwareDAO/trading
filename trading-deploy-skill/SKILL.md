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
| `/trading-deploy run --strategy NAME [--symbols S1,S2]` | 部署指定策略（symbols 默认取 overrides 全集） |
| `/trading-deploy run --strategy NAME --symbols S1 --init-configs` | 为缺 overrides 的代币自动创建配置（Phase 2.5） |
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
PROJECT_DIR="${PROJECT_DIR:-.}"

# 项目根目录必须含 run_strategy.py（v3.7 实盘入口）
[ -f "${PROJECT_DIR}/run_strategy.py" ] \
    && echo "✅ 项目根目录: $PROJECT_DIR" \
    || echo "❌ run_strategy.py 不存在（阻塞）"

# 实盘启动 wrapper（本 skill 经它启动，共用 cta_strategy_core.pid）
[ -f "${PROJECT_DIR}/scripts/run_live_batch.sh" ] \
    && echo "✅ scripts/run_live_batch.sh" \
    || echo "❌ scripts/run_live_batch.sh 不存在（阻塞，需模板 v3.7+）"

# 探测 Python：模板依赖装在 .venv，很多环境没有 python3 这个名字
if [ -z "${PYTHON_CMD:-}" ]; then
    if [ -x "${PROJECT_DIR}/.venv/bin/python" ]; then
        PYTHON_CMD="${PROJECT_DIR}/.venv/bin/python"
    elif command -v python3 &>/dev/null; then
        PYTHON_CMD="python3"
    else
        PYTHON_CMD="python"
    fi
fi
$PYTHON_CMD -c 'import sys' &>/dev/null && echo "✅ Python: $PYTHON_CMD" || echo "❌ Python 不可用（阻塞）"
git --version &>/dev/null && echo "✅ git" || echo "❌ git 不可用（阻塞）"

KLINE_DIR="${KLINE_DATA_DIR:-./data/klines}"
[ -d "$KLINE_DIR" ] && echo "✅ K线目录: $KLINE_DIR" || echo "⚠ K线目录不存在"
```

| 检测项 | 不达标 |
|--------|--------|
| `run_strategy.py` 存在 | **阻塞** |
| `scripts/run_live_batch.sh` 存在 | **阻塞** |
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
| `KLINE_DATA_DIR` | Phase 3+ | ./data/klines |
| `LOGS_DIR` | 全流程 | ./logs |
| `DEPLOY_OUTPUTS_DIR` | Phase 4+ | ./deploy_outputs |

---

## Phase 2: 策略代码获取 + AI 分析

### Step 1: git pull

```bash
$PYTHON_CMD git_pull.py \
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
$PYTHON_CMD git_pull.py --analyze --strategy "${STRATEGY_NAME}"
```

**分析输出**：

```
============================================================
  AI 策略分析 — ema_rsi
============================================================
  配置:       overrides/BTCUSDT.yaml（共 3 个代币）
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

## Phase 2.5: per-symbol 配置初始化（init_overrides.py） ← NEW

git pull 拉来的策略未必有目标代币的 `overrides/<SYMBOL>.yaml`。这一步补上它，
**必须排在 Phase 3 和 Phase 4 之前**：

| 后续环节 | 缺配置时的表现 |
|----------|---------------|
| Phase 3 K线数据准备 | 需求天数是从 overrides 的 `timeframes` + 指标周期算出的，缺配置算不出要下多少 |
| Phase 4 配置校验 | `--check` 直接判 ISSUE，退出码 1，拒绝启动 |
| Phase 5 启动 | wrapper 的 `precheck_overrides` 拒绝整批 |

```bash
$PYTHON_CMD init_overrides.py \
    --strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" \
    --symbols "${SYMBOLS}" \
    --dry-run          # 先看会建什么，确认后去掉

$PYTHON_CMD init_overrides.py \
    --strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" \
    --symbols "${SYMBOLS}"
```

模板来源优先级：**同策略已有 override**（结构完整、参数调过，复制它保证新老
代币口径一致）→ `.strategy-spec.yaml` 的 `default_params`（只够拼骨架，
缺 `capital`/`risk`/`signal` 及若干 timeframe 参数，需人工复核）→ 报错。

**⚠ 新建配置一律 `trading_mode: paper_trading`**，即使模板那份是 live。
新代币未经回测验证就继承 live 会直接下真单。要上实盘必须人工改这一行。

创建后把参数展示给用户，问是否需要调整，用户要改则直接编辑对应 YAML。

**开关**：`--init-configs`。默认关闭 —— 写盘动作且参数需复核，
不该在用户没要求时静默发生。

---

## Phase 3: K线数据准备（loop）

### Step 1: 计算数据需求

```bash
$PYTHON_CMD calc_data_requirements.py \
    --strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" \
    --kline-data-dir "${KLINE_DATA_DIR}"
```

> 共享模板，优先使用 `trading-discovery-skill/templates/calc_data_requirements.py`。

### Step 2: 数据就绪检查 → loop

```bash
$PYTHON_CMD data_readiness_check.py \
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

## Phase 4: 配置校验（不生成 runtime config）

v3.7 起策略参数的唯一事实来源是 `strategies/<name>/overrides/<SYMBOL>.yaml` ——
实盘 `run_strategy.py` 与回测 `run_backtest.py` 读的都是这一份，
"回测不失真"正是靠这个单一来源保证的。

因此本阶段**不再生成** `{strategy}-runtime.yaml`。早期版本会合成这样一份文件，
但模板没有任何代码消费它：真正生效的仍是 `overrides/<SYMBOL>.yaml`，
那份合成文件只会让人误以为改它就能改参数。

### Step 1: 校验 per-symbol 配置齐备性

```bash
$PYTHON_CMD create_config.py \
    --strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" \
    --symbols "${SYMBOLS}" \
    --check
```

**校验内容**：

| 检查项 | 不通过时 |
|--------|----------|
| `overrides/<SYMBOL>.yaml` 存在 | **ISSUE** — 退出码 1，拒绝启动 |
| `trading_mode` 合法（live/paper_trading/smoking） | **ISSUE** |
| `trading_mode` 未设置 | **WARN** — 框架按 `live` 处理，会下真单 |
| `enabled: false` | **WARN** — manager 会跳过它 |
| `timeframes` 缺失 | **WARN** |

**⚠ trading_mode 缺省即 live**：`run_strategy.py` 与
`run_strategies_manager.py` 在 overrides 未声明时都按 `live` 处理，直接下真单。

**首次部署必须去改 `overrides/<SYMBOL>.yaml`，写上
`trading_mode: paper_trading`** —— 不能靠命令行。v3.7 已删除"命令行覆盖
trading_mode"的能力（那是回测实盘不一致的来源），`scripts/run_live_batch.sh`
也没有 `--trading-mode` 参数。

本 skill 的 `--trading-mode` 只是**断言**：与 overrides 实际值不符时
Phase 5 直接报错退出，提示你去改唯一来源。它不会改变任何实际行为。

### Step 2（可选）: 登记进编排表

把策略写入项目的 `config/strategies.yaml`（编排层，实盘回测共用）：

```bash
$PYTHON_CMD create_config.py \
    --strategy-dir "${STRATEGIES_DIR}/${STRATEGY_NAME}" \
    --symbols "${SYMBOLS}" \
    --check --register \
    --project-dir "${PROJECT_DIR}" \
    --trading-mode paper_trading \
    --dry-run          # 先看会改什么，确认后去掉此参数
```

登记后可用项目自带的 `./start.sh` 一次拉起全部编排（单进程托管）。

**注意 `--trading-mode` 在这里含义不同**：`--register` 是**写入**动作 ——
把该值写进 `config/strategies.yaml` 的登记项，是真实生效的配置。
而 Phase 5 启动时的 `--trading-mode` 只是**断言**（校验 overrides，不覆盖）。
两者同名但一个写、一个只读。

### Step 3: 用户确认

```
📋 配置校验通过，确认启动？(y/n/edit)
```

---

## Phase 5: 启动策略

### Step 1: WebSocket 验证（可选）

```bash
$PYTHON_CMD subscribe_websocket.py \
    --symbol "${FIRST_SYMBOL}" \
    --test --timeout 30
```

### Step 2: 启动策略

**转调模板自带的 `scripts/run_live_batch.sh`，不要自己 nohup
`run_strategy.py`。**

理由是安全而非洁癖：wrapper 用的 PID 文件是 `cta_strategy_core.pid` ——
与模板 `start.sh` / `stop.sh` 同一个。自己 nohup 起的进程不在 `stop.sh`
管辖范围内，一旦忘记手动 kill，就是"以为停了、实际还在下单"的孤儿进程。
实盘场景下这是钱的问题。

```bash
(cd "${PROJECT_DIR}" && bash scripts/run_live_batch.sh \
    --strategies "${STRATEGY_NAME}" \
    --symbols "${SYMBOLS}" \
    --daemon \
    --yes)
```

**⚠ 整体重启语义**：wrapper 启动前会 kill 已有 manager 并
`pkill -9 -f "python.*run_strategies_manager.py"`，然后用**一个**
`run_strategies_manager.py` 进程托管全部 (策略, 代币)。所以本次部署会
**连带重启当前在跑的其它策略实例**。执行前必须向用户说明这一点。

**⚠ wrapper 没有 `--trading-mode`**：v3.7 中 `trading_mode` 的唯一来源是
`overrides/<SYMBOL>.yaml`（登记表模式下是 `config/strategies.yaml`）。
若用户传了 `--trading-mode`，**只能当断言用** —— 与 overrides 实际值不符
时报错并退出，让用户去改唯一来源，而不是在命令行悄悄覆盖。命令行覆盖正是
"回测实盘参数不一致"的来源，模板刻意删掉了这个能力。

**`--yes` 的作用**：跳过 wrapper 的任务数确认（> 3 个实例）与 live 模式
手输 `live` 确认。deploy 自己在 Phase 4 已做过 live 确认，此处重复交互在
非 TTY 下会直接卡死。

参数文件由 `--strategies` + `--symbols` 推导为
`strategies/<name>/overrides/<SYMBOL>.yaml`；
`interval` / `version` / `trading_mode` 都从该文件自动读取，无需显式传。

**停止**：`cd "${PROJECT_DIR}" && ./stop.sh`

**替代方案 — 全量托管启动**：项目自带的 `./start.sh` 会读
`config/strategies.yaml` 编排表拉起全部登记实例。想跑登记表而非临时清单
时用它；`run_live_batch.sh --registry config/strategies.yaml` 等价且多一层
模式提示。

---

## 环境变量

### 必需

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `STRATEGIES_GIT_URL` | — | 策略 git 仓库 |
| `STRATEGIES_DIR` | ./strategies | 策略本地目录 |
| `KLINE_DATA_DIR` | ./data/klines | K线数据目录（须与 settings.yaml 的 csv_dir 一致） |
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
| `PROJECT_DIR` | `.` | CTA 项目根目录（含 `run_strategy.py`） |
| `TRADING_MODE` | 空 | `live` / `paper_trading` / `smoking`；留空则由 overrides 决定，**而 overrides 缺省时框架按 live 处理** |
| `REGISTER` | false | 是否登记进 `config/strategies.yaml` |

**资金 / 杠杆 / 仓位不由环境变量配置。** 唯一来源是
`strategies/<name>/overrides/<SYMBOL>.yaml` 的 `capital` / `risk` 段
（实盘与回测读的都是那一份）。早期版本的 `DEFAULT_CAPITAL` /
`DEFAULT_LEVERAGE` / `MAX_POSITIONS` / `POSITION_SIZE_PCT` 已移除 ——
它们只写进那份没人消费的 runtime config，设了也不生效。

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
  → Phase 4: 配置校验（+ 可选登记编排表）+ 用户确认
  → Phase 5: WebSocket 验证 + 逐 symbol 启动策略
```

---

## Related Skills

- `trading-dev`: 写策略
- `trading-discovery`: 测策略（回测探索）
- `trading-replay`: 管策略（每日备份+回放）

> **边界**: dev 写 → discovery 测 → deploy 跑 → replay 管
