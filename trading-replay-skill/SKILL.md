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
```

---

## Phase 1: 任务触发与初始化检查

### 1.1 用户自然语言输入

用户通过自然语言向 AI Skill 发起 replay（复盘）指令。

### 1.2 初始化状态检查

系统解析指令后，检查当前运行环境/任务状态是否已初始化。

**判断逻辑**：确认 `trading-replay-skill/templates/` 下是否已存在脚本与配置文件内容（`sync-exee.py`、`replay.py`、`config.yaml`）。

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

- **动作**：执行 `templates/sync-exee.py`，从实盘机器拉取策略代码与运行数据。
- **主要运行** `sync-exee.py`。

```bash
python3 sync-exee.py --date 20260807 --config config.yaml
```

**具体操作项**：

1. 执行策略代码同步脚本 → 代码存入 `snapshot/{day}/{策略文件夹}/`
2. 同步所需数据 → 数据存入 `replay_data/{day}/{策略文件夹}/data/`
3. 同步仓位信息 → `data/signals/{策略名}/{day}.csv`、`data/positions/`、`data/history_positions/{策略名}/{day}.csv`
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

- **动作**：执行 `templates/replay.py`，读取 `config.yaml` 中所有策略并执行每日回放。
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
6. 回测结果输出到 `replay_outputs/{day}/{策略文件夹}/`。

---

## Phase 6: 结果输出与验证

### 6.1 输出结果

- **动作**：将回测产生的结果文件输出并保存至指定目录，直接检查结果。
- **目录**：`replay_outputs/{day}/{策略文件夹}/`（由 `backtest.yaml.output_dir` 直指，回测原生写入）。

确认结果文件存在（如 `backtest_result.json`）即为复盘完成。

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
│   ├── signals/strategyA/20260807.csv
│   ├── positions/
│   └── history_positions/strategyA/20260807.csv
│
├── data/klines/1m/                       ← K线数据（download_data.py 写入，回测读）
│   ├── BTCUSDT_1m.csv
│   └── ETHUSDT_1m.csv
│
└── replay_outputs/20260807/strategyA/    ← 回测结果（replay.py 写入）
    └── ...
```

**目录对仗**：`replay_data`（实盘输入基准）↔ `replay_outputs`（回测输出结果）。
**数据流转**：`symbols.yaml`（sync 产出）→ `download_data.py` 读 → `data/klines/`（回测输入）。

---

## config.yaml 结构

```yaml
product:                # 实盘
  strategy_name1:
    host: user@1.2.3.4
    path: /home/trader/strategyA
paper:                  # 纸上交易
  strategy_name2:
    host: user@1.2.3.4
    path: /home/trader/strategyB
smoking:                # 模拟盘
  strategy_name3:
    host: user@1.2.3.4
    path: /home/trader/strategyC
```

| 字段 | 说明 |
|------|------|
| 顶层 key | model 类型：`product`/`paper`/`smoking` |
| 策略名 key | 策略标识，同时作为 `data/` 子目录的 strategy_id |
| `host` | `user@ip` 或 ssh 别名，端口/密钥走 `~/.ssh/config` |
| `path` | 实盘项目根目录，basename 即快照文件夹名 |

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
| `--snapshot-dir` | `./snapshot` | 代码快照根目录 |
| `--data-dir` | `./replay_data` | data 子集根目录 |

### replay.py — 每日回放回测

```bash
python3 replay.py [--date YYYYMMDD] [--config config.yaml] [--snapshot-dir ./snapshot] [--output-dir ./replay_outputs] [--start YYYYMMDD] [--end YYYYMMDD]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--date` | 昨天 | 回放日期 `YYYYMMDD` |
| `--config` | `config.yaml` | 配置文件路径 |
| `--snapshot-dir` | `./snapshot` | 快照根目录 |
| `--output-dir` | `./replay_outputs` | 回测结果根目录 |
| `--start` | = date | 回测开始日期 |
| `--end` | = date | 回测结束日期 |

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

- `trading-dev`: CTA 策略开发全生命周期
- `trading-discovery`: 指定代币/策略/时间范围的回测探索
