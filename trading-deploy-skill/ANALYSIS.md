# Trading Deploy Skill — 功能说明与时序分析

## 一、定位

`trading-deploy` 是 **策略部署上线 skill**，覆盖从策略代码拉取到生产运行的完整链路：

```
git pull 拉代码 → AI 分析配置 → WebSocket 数据验证 → K线数据准备 loop → 配置校验 → 启动策略运行
```

首要原则：无参数或参数不全时，必须一步一步引导用户，不要报错让用户自己补命令。

## 二、命令体系

| 命令 | 说明 |
|------|------|
| `/trading-deploy` | 无参数 → 进入交互式引导 |
| `/trading-deploy run` | 完整部署流程（Phase 0→5） |
| `/trading-deploy run --strategy NAME [--symbols S1,S2]` | 部署指定策略（symbols 默认取 overrides 全集） |
| `/trading-deploy run --strategy NAME --symbols S1 --init-configs` | 为缺 overrides 的代币自动创建配置（Phase 2.5） |
| `/trading-deploy run --git-url URL` | 指定 git 地址部署 |
| `/trading-deploy analyze` | 只分析策略结构（Phase 2） |
| `/trading-deploy prepare-data` | 只准备K线数据（Phase 3） |
| `/trading-deploy start --strategy NAME` | 只启动策略（Phase 5） |
| `/trading-deploy status` | 查看运行中策略状态 |

## 三、Phase 构成（功能分解）

### Phase -1：交互式引导（无参数/参数不全时）
触发条件（满足任一）：无任何参数 / `run` 缺 `--strategy` 且无默认 / `start` 缺 `--strategy`。

4 步引导：问子命令（默认 run）→ 问策略（列 `STRATEGIES_DIR` 下可用策略，目录空先走 git pull）→ 问 git 地址（默认用本地）→ 汇总确认 → 转 Phase 0。

### Phase 0：环境预检
检测项：
- `run_strategy.py` 存在（v3.7 实盘入口）— **阻塞**
- `scripts/run_live_batch.sh` 存在（实盘启动 wrapper）— **阻塞**
- Python（优先 `.venv/bin/python`，回退 `python3`/`python`）— **阻塞**
- git — **阻塞**
- K线目录 — 非阻塞（Phase 3 可创建）

### Phase 1：配置初始化
优先级：`.env` > `config.yaml` > 默认值。配置项：`STRATEGIES_GIT_URL`、`STRATEGIES_DIR`、`KLINE_DATA_DIR`、`LOGS_DIR`、`DEPLOY_OUTPUTS_DIR`。

### Phase 2：策略代码获取 + AI 分析
- **Step 1 git pull**：`git_pull.py` 自适应——目录有 `.git` 则 `git pull`，否则 `git clone`；列所有策略目录和配置文件。
- **Step 2 AI 分析**：`git_pull.py --analyze` 输出策略配置、代币、时间框架、方向、技术指标（含最大数据依赖天数）、代码完整性。
- **Step 3 用户确认**。

### Phase 2.5：per-symbol 配置初始化（init_overrides.py）
为缺 overrides 的代币补配置，**必须排在 Phase 3/4/5 之前**（否则需求天数算不出、配置校验拒绝、启动 precheck 拒绝）。

模板来源优先级：同策略已有 override（口径一致）→ `.strategy-spec.yaml` 的 `default_params`（只够拼骨架）→ 报错。

**⚠ 新建配置一律 `trading_mode: paper_trading`**，即使模板是 live（未回测验证就 live 会下真单）。开关 `--init-configs`，默认关闭（写盘动作需复核）。

### Phase 3：K线数据准备（loop）
- **Step 1 计算数据需求**：`calc_data_requirements.py`（共享模板，优先 `trading-discovery-skill/templates/`）。
- **Step 2 数据就绪检查 → loop**：`data_readiness_check.py`。

loop 流程：检查数据 → 充足 YES 进 Phase 4 / 不足 NO → 尝试下载 → 成功回检查 / 失败询问跳过 → 跳过进 Phase 4 (partial) / 不跳过退出。退出条件：数据充足 | 用户跳过 | 用户取消 | 最多 5 轮重试。

### Phase 4：配置校验（不生成 runtime config）
v3.7 起策略参数唯一事实来源是 `strategies/<name>/overrides/<SYMBOL>.yaml`，实盘与回测共用。**不再生成** `{strategy}-runtime.yaml`（无人消费，只误导）。

- **Step 1 校验 per-symbol 配置齐备性**：`create_config.py --check`。ISSUE（退出码 1 拒绝启动）：overrides 不存在 / trading_mode 非法。WARN：trading_mode 未设置（框架按 live 处理）/ enabled:false / timeframes 缺失。
- **Step 2（可选）登记编排表**：`create_config.py --check --register` 写入 `config/strategies.yaml`，可用 `./start.sh` 一次拉起全部。
- **Step 3 用户确认**。

**⚠ trading_mode 缺省即 live**。首次部署必须去改 overrides 写 `trading_mode: paper_trading`，不能靠命令行（v3.7 已删命令行覆盖能力，那是回测实盘不一致的来源）。

### Phase 5：启动策略
- **Step 1 WebSocket 验证（可选）**：`subscribe_websocket.py --test`。
- **Step 2 启动**：转调模板自带 `scripts/run_live_batch.sh`，**不要自己 nohup `run_strategy.py`**（孤儿进程风险：wrapper 用 `cta_strategy_core.pid`，与 `start.sh`/`stop.sh` 同一 PID 文件）。

**⚠ 整体重启语义**：wrapper 启动前会 kill 已有 manager 并 `pkill -9 -f "run_strategies_manager.py"`，一个进程托管全部 (策略,代币)，本次部署会**连带重启当前在跑的其它策略实例**，执行前必须向用户说明。

**⚠ wrapper 没有 `--trading-mode`**：trading_mode 唯一来源是 overrides（登记表模式下是 `config/strategies.yaml`）。`--trading-mode` 只能当断言用，与实际不符报错退出。

---

## 四、时序分析

### 时序图（完整执行流）

```
用户
 │
 ├─ /trading-deploy [无参数/参数不全] ─────────┐
 │                                            ▼
 │                                    ┌──────────────────┐
 │                                    │ Phase -1 引导    │
 │                                    │ 问子命令→策略    │
 │                                    │ →git地址→确认    │
 │                                    └─────────┬────────┘
 │                                              │
 ├─ /trading-deploy run --strategy X (参数齐全)►│
 ├─ /trading-deploy analyze|prepare-data|status►│(直达对应Phase)
 │                                              ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 0: 环境预检                                 │
 │   │  run_strategy.py / run_live_batch.sh / Python / git│
 │   │    └─阻塞项失败 → 报错退出                         │
 │   └──────────────────────┬───────────────────────────┘
 │                          ▼
 │   Phase 1: 配置初始化 (.env > config.yaml > 默认)
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 2: git pull + AI 分析 + 用户确认             │
 │   │  git_pull.py (pull/clone) → --analyze → 确认       │
 │   └──────────────────────┬───────────────────────────┘
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 2.5: per-symbol 配置初始化 (init_overrides)  │
 │   │  缺 overrides 的代币补配置 (默认 paper_trading)     │
 │   │  开关 --init-configs，默认关闭                      │
 │   └──────────────────────┬───────────────────────────┘
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 3: K线数据准备 (loop)                        │
 │   │  calc_data_requirements → data_readiness_check     │
 │   │  ┌─ 检查充足? ─YES─→ Phase 4                       │
 │   │  │   NO → 下载 → 成功?YES→回检查                   │
 │   │  │              NO→询问跳过                        │
 │   │  │   跳过→Phase4(partial) / 取消→退出 / 5轮→退出    │
 │   └──────────────────────┬───────────────────────────┘
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 4: 配置校验 (+ 可选登记编排表) + 用户确认     │
 │   │  create_config.py --check (ISSUE→退出1 / WARN)     │
 │   │  [--register → config/strategies.yaml]             │
 │   └──────────────────────┬───────────────────────────┘
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 5: WebSocket 验证(可选) + 启动策略           │
 │   │  subscribe_websocket --test (可选)                 │
 │   │  run_live_batch.sh --daemon --yes                  │
 │   │   ⚠ 连带重启其它在跑策略实例                        │
 │   └──────────────────────┬───────────────────────────┘
 │                          ▼
 └─ 完成: 策略运行 (PID: cta_strategy_core.pid)
```

### 时序关键点

1. **单步模式直达**：`analyze`→Phase 2；`prepare-data`→Phase 3；`start`→Phase 5；`status`→查状态。均跳过引导。

2. **Phase 2.5 必须先于 3/4/5**：缺 overrides 时后续环节全部失败（需求天数算不出、校验拒绝、启动 precheck 拒绝）。

3. **阻塞点**：Phase 0 的四项（run_strategy.py / run_live_batch.sh / Python / git）。K线目录非阻塞。

4. **数据准备 loop 终止条件**（四选一）：数据充足 / 用户跳过（partial 继续）/ 用户取消 / 5 轮重试上限。

5. **配置时序（v3.7 收敛）**：参数唯一来源 `overrides/<SYMBOL>.yaml`，不再生成 runtime config。`--trading-mode` 在 Phase 4 `--register` 时是**写入**（真实生效），在 Phase 5 启动时是**断言**（只读校验）—— 同名但语义不同。

6. **启动时序安全约束**：必须转调 `run_live_batch.sh`（共用 PID 文件），不可自己 nohup（孤儿进程 = 钱的问题）；wrapper 启动前会整体重启，会连带影响其它策略实例。

7. **trading_mode 缺省陷阱**：overrides 未声明时框架按 `live` 处理（下真单）。首次部署必须显式写 `paper_trading`。

---

## 五、环境变量清单

### 必需

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `STRATEGIES_GIT_URL` | — | 策略 git 仓库 |
| `STRATEGIES_DIR` | ./strategies | 策略本地目录 |
| `KLINE_DATA_DIR` | ./data/klines | K线数据目录（须与 settings.yaml csv_dir 一致） |
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
| `PROJECT_DIR` | `.` | CTA 项目根目录（含 run_strategy.py） |
| `TRADING_MODE` | 空 | live/paper_trading/smoking；留空由 overrides 决定，**overrides 缺省时框架按 live** |
| `REGISTER` | false | 是否登记进 config/strategies.yaml |

**资金/杠杆/仓位不由环境变量配置**，唯一来源是 `overrides/<SYMBOL>.yaml` 的 `capital`/`risk` 段。早期 `DEFAULT_CAPITAL`/`DEFAULT_LEVERAGE`/`MAX_POSITIONS`/`POSITION_SIZE_PCT` 已移除（只写进无人消费的 runtime config，设了不生效）。

---

## 六、关键约束

### 启动安全
1. **必须转调 `run_live_batch.sh`**，不可自己 nohup `run_strategy.py`（PID 文件 `cta_strategy_core.pid` 与 `start.sh`/`stop.sh` 共用，自己起的进程不在管辖内 = 孤儿进程）
2. **整体重启语义**：wrapper 启动前 kill 已有 manager + `pkill -9`，一个进程托管全部，连带重启其它策略实例
3. **`--yes` 必带**：跳过 wrapper 任务数确认（>3 实例）与 live 模式手输确认，非 TTY 下会卡死

### 配置单一来源（v3.7）
1. 策略参数唯一来源 `strategies/<name>/overrides/<SYMBOL>.yaml`，实盘回测共用
2. **不再生成** `{strategy}-runtime.yaml`（无人消费）
3. `trading_mode` 缺省即 live，首次部署必须显式写 `paper_trading`
4. v3.7 已删命令行覆盖 trading_mode 能力（回测实盘不一致的来源），`--trading-mode` 只能当断言
5. 新建 overrides 一律 `paper_trading`，即使模板是 live

---

## 七、边界（四个 skill 协作）

> **dev 写 → discovery 测 → deploy 跑 → replay 管**

| skill | 职责 |
|-------|------|
| `trading-dev` | 写策略（开发全生命周期） |
| `trading-discovery` | 测策略（回测探索） |
| `trading-deploy` | 跑策略（部署上线） |
| `trading-replay` | 管策略（每日备份+回放） |
