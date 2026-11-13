---
name: trading-replay
description: 每日策略复盘（Replay）skill。从实盘机器备份策略代码与运行数据到本地，按日期回放回测，输出对比结果。支持指定日期重新复盘。
origin: trading
---

# Trading Replay — 每日策略复盘

AI Skill 自动化复盘工作流：自然语言触发 → 初始化检查 → 备份实盘代码/数据 → 回放回测 → 输出结果。

**首要原则**：参数不全或环境未就绪时，逐步引导用户补齐，不报错甩给用户。

## When to Activate

- 用户说「复盘」「回放回测」「今日 replay」「每日回测」
- 用户执行 `/trading-replay`（无参数）

## 触发输入

用户用自然语言发起复盘指令即可，例如：

- 「复盘一下昨天」
- 「今天 replay」
- 「重新复盘 20260807」

解析出日期（默认昨天，格式 `YYYYMMDD`）后进入 Phase 1。

---

## 工作流总览

```
Phase 1   → 任务触发与初始化检查
Phase 1.5 → 环境准备与配置（仅首次/重置）
Phase 2   → 运行前安全检查与信息确认
Phase 3   → 数据同步（实盘快照同步）
Phase 4   → 数据下载（从快照 overrides 收取代币，拉最新K线）
Phase 5   → 回测执行
Phase 6   → 结果输出与验证
Phase 7   → 看板数据生成（frontend-data v2，供 strategy-kanban 前端消费）
```

---

## Phase 1: 任务触发与初始化检查

### 1.1 用户自然语言输入

用户通过自然语言向 AI Skill 发起 replay（复盘）指令。

### 1.2 初始化状态检查

系统解析指令后，检查当前运行环境/任务状态是否已初始化。

**判断逻辑**：确认 `trading-replay-skill/scripts/` 下是否已存在脚本（`sync-exee.py`、`replay.py`），且工作目录已有配置文件（`config.yaml`）。

| 判断 | 流向 |
|------|------|
| 是（已初始化） | 跳过环境准备，直接进入 Phase 2 |
| 否（未初始化） | 进入 Phase 1.5 进行环境准备 |

---

## Phase 1.5: 环境准备与配置（仅限首次或重置）

> 此阶段涉及 AI 协助与人工确认。仅当 Phase 1.2 判定未初始化时执行。

### 1.5.1 备份

- **动作**：AI 协助备份 skill 的 `templates/` 下所有文件。
- **涉及文件**：`config.yaml`、`sync-exee.py`、`replay.py`。
- **目的**：保留可回滚副本，配置出错时可还原。

### 1.5.2 配置环境

- **动作**：主要修改 `templates/config.yaml`。

1. **设置策略代码路径及机器路径**：在 `product`/`paper`/`smoking` 三个分组下，为每个策略填写 `host`（`user@ip` 或 ssh 别名）和 `path`（实盘项目根目录）。
2. **执行相关命令，准备 Python 3 运行环境**：确认本机有 `python3`、`pyyaml`、`rsync`（备份用）、`ssh`。
3. **准备配置文件 `config.yaml`**：从 `config.example.yaml` 复制并填写实际策略。

完成后回到 Phase 1.2 复检，通过则进入 Phase 2。

---

## Phase 2: 运行前安全检查与信息确认

### 2.1 确认环境

- **动作**：确认当前运行环境是否就绪。
- **主要输出 `config.yaml` 内容**，不做其他事情，供用户核对。

### 2.2 确认备份信息

**前置条件/操作**：

1. 确认需要拷贝机器的策略（`host`/`path` 是否正确）。
2. 确认当前需要输出的策略信息（product/paper/smoking 各组下的策略名）。

- **判断条件**：确认相关数据的备份状态及环境配置是否正确。

| 判断 | 流向 |
|------|------|
| 否 | 用户介入，确认并修改 `config.yaml`，随后重新回到 2.2 确认 |
| 是 | 环境准备完毕，进入 Phase 3 |

---

## Phase 3: 数据同步（实盘快照同步）

### 3.1 执行备份脚本

- **动作**：执行 `scripts/sync-exee.py`，从实盘机器拉取策略代码与运行数据。
- **主要运行** `sync-exee.py`。

```bash
python3 sync-exee.py --date 20260807 --config config.yaml
```

**具体操作项**：

1. 执行策略代码同步脚本 → 代码存入 `snapshot/{day}/{策略文件夹}/`
2. 同步所需数据 → 数据存入 `replay_data/{day}/{策略文件夹}/data/`
3. 同步仓位信息（拉整目录，目录名为 runtime 名而非 config key）：
   - Python：`data/signals/`、`data/positions/`、`data/history_positions/`
   - Rust：`data/state/{day}/signal.csv`、`position.csv`、`history_position.csv`、
     `stop.csv`、`cooldown.csv`、`data/state/history_positions/`
4. 扫描所有快照 `strategies/*/overrides/*.yaml` 文件名，收集代币去重 → 生成 `snapshot/{day}/symbols.yaml`

**排除项**：`logs`、`.venv`、`backtest_output`（.gitignore 产物）不拉取。

**为何同步在前**：本步生成的 `symbols.yaml` 是 Phase 4 下载K线的代币清单来源，故必须先同步、后下载。

---

## Phase 4: 数据下载（拉取最新K线）

### 4.1 读取代币清单并下载

- **动作**：每次执行 replay 回测前，先更新到最新K线数据，保证回测无缺口。
- **主要运行** `download_data.py`。
- **代币来源**：读 Phase 3 生成的 `snapshot/{day}/symbols.yaml`（已去重）。

```bash
python3 download_data.py --symbols-file ./snapshot/20260807/symbols.yaml --data-dir ./data/klines
```

**具体操作项**：

1. 读取 `symbols.yaml` 代币清单（`--symbols-file`）。
2. 每个代币读取本地 `data/klines/1m/{SYMBOL}_1m.csv` 最新K线时间（UTC）。
3. 无数据 → 用 `data.binance.vision` `monthly/klines` 批量下载历史月度数据。
4. 有缺口 → 用 `daily/klines` 补到 UTC 昨天（daily 优先于 REST）。
5. daily 拿不到的最新一段 → REST API(fapi) 补到当前（失败则放弃该代币并报错）。
6. 合并去重排序，存为本地 UTC 格式 CSV。

**目录**：`data/klines/1m/{SYMBOL}_1m.csv`（与 `config/settings.yaml` 的 `csv_dir` 一致，回测可直接读）。

> 也支持手动指定代币：`python3 download_data.py --symbols BTCUSDT,ETHUSDT`。

---

## Phase 5: 回测执行

### 5.1 执行策略回测代码

- **动作**：执行 `scripts/replay.py`，读取 `config.yaml` 中所有策略并执行每日回放。
- **主要运行** `replay.py`。

```bash
python3 replay.py --date 20260807 --config config.yaml
```

**具体操作项**：

1. 每个快照目录内创建并激活 venv（`python3 -m venv .venv`，有 `requirements.txt` 自动装依赖）。
2. 扫快照 `strategies/*/overrides/*.yaml`，收集策略名（子目录名）+ 代币（文件名 stem，去重大写）。
3. 在快照 `config/` 下生成 `backtest.yaml`（动态 `start`/`end`/`data_dir`/`output_dir`，其余取 `backtest.example.yaml` 默认值），供脚本 `--profile backtest` 读取。
4. 运行快照自带的 `scripts/run_backtest_batch.sh`（笛卡尔积模式）：

   ```bash
   bash scripts/run_backtest_batch.sh \
     --strategies <策略名,逗号分隔> \
     --symbols <代币,逗号分隔> \
     --profile backtest \
     --start <日期> --end <日期> \
     --yes
   ```

   - `--strategies`/`--symbols` 由快照 overrides 扫描得到，二选一必需（脚本不认 `--output-dir`）。
   - `--profile backtest` 指向第 3 步生成的 `config/backtest.yaml`。
   - `--yes` 跳过任务数确认（replay 跑在自动流/crontab）。
   - 输出目录由 `backtest.yaml.output_dir` 直指 `replay_outputs/{day}/{策略文件夹}/`，回测原生写入，无需 cp。
5. **设定回测日期**：默认为昨天（复盘昨日实盘），可用 `--date` 指定当天或其他日期，亦可用 `--start`/`--end` 自定义区间。
   **交易窗口只含回放日**（Rust `--start day --end day+1`），`warmup_days` 通过 `--warmup-start` 只加载预热数据、不产生交易。
6. 回测结果输出到 `replay_outputs/{day}/{策略文件夹}/`。

---

## Phase 6: 结果输出与验证

### 6.1 输出结果

- **动作**：将回测产生的结果文件输出并保存至指定目录，直接检查结果。
- **目录**：`replay_outputs/{day}/{策略文件夹}/`（由 `backtest.yaml.output_dir` 直指，回测原生写入）。

确认结果文件存在（如 `backtest_result.json`）即为复盘完成。

---

## Phase 7: 看板数据生成（frontend-data v2）

> **触发条件**：`config.yaml` 的 `frontend_data_dir` 非空（或 CLI `--frontend-out`）时，
> Phase 5 回测成功后自动执行；为空则跳过 Phase 7，不算失败。

### 7.1 生成前端可消费数据

- **动作**：执行 `scripts/generate-kanban-data.py`，把实盘基准数据（`replay_data/{day}`）与回放回测结果（`replay_outputs/{day}`）转换为 strategy-kanban 前端消费的 **frontend-data v2（CSV 参数化）布局**，格式逐列对齐 `strategy-kanban/docs/frontend-data-sample/`。
- **数据说明**：目录组织与各文件字段见 [`references/FRONTEND-DATA.md`](references/FRONTEND-DATA.md)。
- **前置**：Phase 3（实盘快照）、Phase 5（回测）已完成；`data/klines` 有对应代币（用于 OPEN 仓位浮动盈亏 mark 价）。

```bash
python3 generate-kanban-data.py --date 20261026
# 输出根：config.yaml 的 frontend_data_dir（未配置则回退 REPLAY_WORKSPACE/frontend-data）
python3 generate-kanban-data.py --all --out /path/to/strategy-kanban/public/frontend-data
```

**具体操作项**：

1. 读 `replay_data/{day}/{项目}/data/state/{day}/{signal,position,history_position,cooldown}.csv` 与 `data/state/history_positions/{runtime}/{day}.csv` → 实盘侧运行实例（按 `(strategy, symbol)` 聚合，`mode` 从 runtime 后缀解析）。
2. 读 `replay_outputs/{day}/{项目}/{strategy}/{run_date}/{HHMMSS}/{SYMBOL}/` 的 `backtest_result.json` + `engine/…` → 回测侧，逐 run 生成 `backtest_results/{run_stamp}/{SYMBOL}.json`。
3. 分配 `batch_id`（`{day}-{HHMM}`，按 `--batch-gap` 秒时序聚簇）与 `sweep`（轮次，从 0）；每 `(strategy, symbol)` 标 `is_latest=1`。
4. 由引擎信号（`engine/signals/*/signal.csv`，缺则按仓位一开一平反推）与实盘信号产出 `backtest_signals/positions.csv`、`live_signals/positions.csv`；实盘 vs 回放信号按 `(时间戳精确 → 时间窗口)` 匹配生成 `signal_comparison.csv`（无实盘信号的纯回测标的不出对比表，对齐样例存在规则）。
5. 写 `{day}/manifest.csv`、`{day}/backtest_runs.csv`、`{day}/{strategy}/{meta.json,manifest.csv,…}`，并 upsert `catalog.csv`。

**口径要点**（详见样例 README 第 6/8 节，脚本内置）：

| 项 | 规则 |
|----|------|
| 时间 | ISO8601 UTC `2026-10-26T01:45:00Z`；日期目录 `YYYYMMDD` |
| `run_stamp/batch_id/run_id` | 标识符，非时间 |
| 比率（`roe`/`max_drawdown`/`win_rate`/`*_return`） | 小数，`0.0164`=1.64% |
| `pnl_pct`/`price_diff_pct` | 百分数，`2.2049`=2.2049% |
| `total_pnl`/`floating_pnl` | 金额 ÷ 初始资金（`result.config.initial_cash`，兜底 10000） |
| 空回测（`signals_processed=0`） | 保留 run 行，**不生成** positions/signals CSV |
| `has_live=0/has_backtest=0` | 不建对应文件，不用表头占位 |

> `sweep` 与 `is_latest` 由脚本落盘，前端页面须用 `is_latest=1` 过滤，否则同日多轮次仓位会叠加。

---

## 目录结构

```
workspace/
├── snapshot/20260807/                    ← 快照根（按日期）
│   ├── symbols.yaml                      ← 代币清单（sync-exee.py 从 overrides 去重生成的）
│   ├── strategyA/                        ← 代码快照（纯代码，不含 data）
│   │   ├── strategies/
│   │   ├── scripts/run_backtest_batch.sh
│   │   └── ...
│   └── strategyB/
│
├── replay_data/20260807/strategyA/data/ ← 实盘基准数据（sync-exee.py 写入）
│   ├── signals/{runtime名}/20260807.csv       ← Python
│   ├── positions/{runtime名}.json
│   ├── history_positions/{runtime名}/20260807.csv
│   └── state/20260807/{signal,position,history_position,stop,cooldown}.csv
│       └── state/history_positions/{runtime名}/20260807.csv  ← Rust
│
├── data/klines/1m/                       ← K线数据（download_data.py 写入，回测读）
│   ├── BTCUSDT_1m.csv
│   └── ETHUSDT_1m.csv
│
└── replay_outputs/20260807/strategyA/    ← 回测结果（replay.py 写入）
    └── ...

frontend-data/                            ← 看板数据（generate-kanban-data.py 写入）
├── catalog.csv
└── 20260807/
    ├── manifest.csv                      ← 每日收益页
    ├── backtest_runs.csv                 ← 每日回放页
    └── {strategy}/
        ├── meta.json / manifest.csv
        ├── live_positions/signals.csv     ← 有实盘时
        ├── backtest_runs/positions/signals.csv
        ├── signal_comparison.csv          ← 有实盘信号时
        └── backtest_results/{run_stamp}/{SYMBOL}.json
```

**目录对仗**：`replay_data`（实盘输入基准）↔ `replay_outputs`（回测输出结果）。
**数据流转**：`symbols.yaml`（sync 产出）→ `download_data.py` 读 → `data/klines/`（回测输入）；`replay_data` + `replay_outputs` → `generate-kanban-data.py` → `frontend-data/`（前端消费，布局对齐 `strategy-kanban/docs/frontend-data-sample`）。

---

## config.yaml 结构

```yaml
# 工作区根目录（可选）。设置后 snapshot/replay_data/replay_outputs
# 以及相对的 data_dir/frontend_data_dir 都以它为基准
workspace: /path/to/replay-workspace

# K线根目录（可选）：绝对路径，或相对 workspace
data_dir: data/klines

# 看板输出根目录（可选）：绝对路径，或相对 workspace；留空则跳过 Phase 7
frontend_data_dir: frontend-data

product:                # 实盘
  strategy_name1:
    host: user@1.2.3.4
    path: /home/trader/strategyA
    lang: python          # python（默认）| rust
paper:                  # 纸上交易
  strategy_name2:
    host: user@1.2.3.4
    path: /home/trader/strategyB
    lang: rust
smoking:                # 模拟盘
  strategy_name3:
    host: 127.0.0.1      # 本地源：无需 SSH，走本地 rsync
    path: /home/trader/strategyC
    lang: python
```

| 字段 | 说明 |
|------|------|
| `data_dir` | 可选，顶层 K 线根目录；默认 `./data/klines`。Python 回测通过软链接入快照，Rust 直接作为 `--data-dir` |
| 顶层 key | model 类型：`product`/`paper`/`smoking` |
| 策略名 key | 策略标识，同时作为 `data/` 子目录的 strategy_id |
| `host` | `user@ip` 或 ssh 别名，端口/密钥走 `~/.ssh/config` |
| `path` | 实盘项目根目录，basename 即快照文件夹名 |

> **lang 自动检测**：无需手动配置。sync-exee.py 和 replay.py 会根据 `path` 指向的项目根目录自动判断语言类型：
> - 存在 `Cargo.toml` → Rust 策略（拉取 `data/state/{day}/*.csv` + `data/state/history_positions/`，排除 `target/`，用 `cargo run -- backtest` 回测）
> - 存在 `requirements.txt` 或 `strategy_core/` → Python 策略（拉取 `data/signals/`、`data/positions/`、`data/history_positions/` 整目录，用 `scripts/run_backtest_batch.sh` 回测）
>
> config.yaml 中也可显式指定 `lang: rust` 覆盖自动检测（默认不填即可）。
>
> **Rust 仓位读取注意**：`data/state/{day}/position.csv` 每行带 `deleted`（0/1）软删标志，
> `deleted=1` 为已平仓仓位（软删行），读取当前持仓须按 `deleted==0` 过滤，否则会把已平仓
> 仓位全部误读为持仓。当日/历史平仓明细以 `history_position.csv` 和
> `data/state/history_positions/{runtime名}/{day}.csv` 为准。

---

## 脚本说明

### sync-exee.py — 每日策略项目备份

```bash
python3 sync-exee.py [--date YYYYMMDD] [--config config.yaml] [--snapshot-dir ./snapshot] [--data-dir ./replay_data]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--date` | 昨天 | 备份日期 `YYYYMMDD` |
| `--config` | `config.yaml` | 配置文件路径 |
| `--snapshot-dir` | `<workspace>/snapshot` | 代码快照根目录 |
| `--data-dir` | `<workspace>/replay_data` | data 子集根目录 |

### replay.py — 每日回放回测

```bash
python3 replay.py [--date YYYYMMDD] [--config config.yaml] [--snapshot-dir ./snapshot] [--output-dir ./replay_outputs] [--start YYYYMMDD] [--end YYYYMMDD] [--data-dir DIR] [--frontend-out DIR]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--date` | 昨天 | 回放日期 `YYYYMMDD` |
| `--config` | `config.yaml` | 配置文件路径 |
| `--snapshot-dir` | `<workspace>/snapshot` | 快照根目录 |
| `--output-dir` | `<workspace>/replay_outputs` | 回测结果根目录 |
| `--start` | = date | 回测开始日期 |
| `--end` | = date | 回测结束日期 |
| `--data-dir` | `config.yaml` 的 `data_dir`（相对 `workspace`）→ `<workspace>/data/klines` | K 线根目录 |
| `--frontend-out` | `config.yaml` 的 `frontend_data_dir`（相对 `workspace`） | 看板输出根目录；非空则自动生成 |

### generate-kanban-data.py — 看板数据生成（Phase 7）

```bash
python3 generate-kanban-data.py [--date YYYYMMDD | --start YYYYMMDD --end YYYYMMDD | --all] [--out DIR]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--date` / `--start`+`--end` / `--all` | replay_data 最新一天 | 日期选择，三选一 |
| `--replay-data` | `$REPLAY_WORKSPACE/replay_data` | 实盘快照根目录 |
| `--replay-outputs` | `$REPLAY_WORKSPACE/replay_outputs` | 回测输出根目录 |
| `--snapshot` | `$REPLAY_WORKSPACE/snapshot` | 代码快照（引擎/杠杆/meta 来源） |
| `--klines` | `$REPLAY_WORKSPACE/data/klines` | K线（OPEN 仓位 mark 价） |
| `--out` | `$REPLAY_WORKSPACE/frontend-data` | frontend-data 输出根目录 |
| `--batch-gap` | 1800 | 同策略回放批次聚簇间隔（秒），决定 sweep/batch_id |
| `--time-window` | 600 | 信号对比时间窗口（秒） |
| `--run` | all | all=同日全部批次（样例语义）；latest=每标的仅最新 |
| `--display-names` | 无 | JSON 映射 `{strategy: 中文名}` 写入 display_name |
| `--prune` | 关 | 删除目标日下不在本次清单里的旧策略目录 |
| `--dry-run` | 关 | 只打印统计不写文件 |

> 环境变量 `REPLAY_WORKSPACE` 指向 replay 工作区根（含 replay_data/replay_outputs/snapshot/data）。默认值按 `trading-replay-run` 兜底。

---

## Claude Code 权限需求

```json
{
  "permissions": {
    "allow": [
      "Bash(python3:*)",
      "Bash(rsync:*)",
      "Bash(ssh:*)",
      "Bash(bash:*)",
      "Bash(mkdir:*)",
      "Bash(date:*)",
      "Read(*)",
      "Write(*)",
      "Edit(*)"
    ]
  }
}
```

---

## Related Skills

- `trading-dev`: CTA 策略开发全生命周期。**dev 产出的项目（v3.7 单体模板）可直接被 replay 复盘**：
  代码/数据路径（`data/signals/`、`data/positions/`、`data/history_positions/`）、
  `strategies/<name>/overrides/<SYM>.yaml`、`scripts/run_backtest_batch.sh` 均与
  replay 的假设一致；deploy 到实盘机器后把项目根目录填进 `config.yaml` 的 `path` 即可。
- `trading-discovery`: 指定代币/策略/时间范围的回测探索
