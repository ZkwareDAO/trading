# Trading Replay Skill — 功能说明与时序分析

## 一、定位

`trading-replay` 是 **每日策略复盘（Replay）skill**，从实盘机器备份策略代码与运行数据到本地，按日期回放回测，输出对比结果，支持指定日期重新复盘。

```
自然语言触发 → 初始化检查 → 备份实盘代码/数据 → 回放回测 → 输出结果
```

首要原则：参数不全或环境未就绪时，逐步引导用户补齐，不报错甩给用户。

## 二、触发方式

用户用自然语言发起复盘指令即可，例如：
- 「复盘一下昨天」
- 「今天 replay」
- 「重新复盘 20260807」

解析出日期（默认昨天，格式 `YYYYMMDD`）后进入 Phase 1。

## 三、Phase 构成（功能分解）

### Phase 1：任务触发与初始化检查
- **1.1 用户自然语言输入**：发起 replay（复盘）指令。
- **1.2 初始化状态检查**：确认 `templates/` 下是否已存在脚本与配置（`sync-exee.py`、`replay.py`、`config.yaml`）。
  - 已初始化 → 跳过环境准备，直接进 Phase 2
  - 未初始化 → 进 Phase 1.5

### Phase 1.5：环境准备与配置（仅首次/重置）
> 涉及 AI 协助与人工确认。仅当 Phase 1.2 判定未初始化时执行。

- **1.5.1 备份**：AI 协助备份 `templates/` 下所有文件（`config.yaml`、`sync-exee.py`、`replay.py`），保留可回滚副本。
- **1.5.2 配置环境**：
  1. 在 `product`/`paper`/`smoking` 三个分组下，为每个策略填写 `host`（`user@ip` 或 ssh 别名）和 `path`（实盘项目根目录）。
  2. 确认本机有 `python3`、`pyyaml`、`rsync`（备份用）、`ssh`。
  3. 从 `config.example.yaml` 复制并填写 `config.yaml`。
- 完成后回 Phase 1.2 复检，通过进 Phase 2。

### Phase 2：运行前安全检查与信息确认
- **2.1 确认环境**：主要输出 `config.yaml` 内容供用户核对。
- **2.2 确认备份信息**：
  1. 确认需拷贝机器的策略（`host`/`path` 是否正确）。
  2. 确认当前需输出的策略信息（product/paper/smoking 各组策略名）。
  - 不通过 → 用户改 `config.yaml` → 回 2.2 重确认
  - 通过 → 进 Phase 3

### Phase 3：数据同步（实盘快照同步）
- 执行 `sync-exee.py`，从实盘机器拉取策略代码与运行数据。

```bash
python3 sync-exee.py --date 20260807 --config config.yaml
```

具体操作：
1. 策略代码同步 → `snapshot/{day}/{策略文件夹}/`（纯代码，不含 data）
2. 同步所需数据 → `replay_data/{day}/{策略文件夹}/data/`
3. 同步仓位信息 → `data/signals/{策略名}/{day}.csv`、`data/positions/`、`data/history_positions/{策略名}/{day}.csv`
4. 扫描所有快照 `strategies/*/overrides/*.yaml` 文件名，收集代币去重 → 生成 `snapshot/{day}/symbols.yaml`

**排除项**：`logs`、`.venv`、`backtest_output`（.gitignore 产物）不拉取。

**为何同步在前**：本步生成的 `symbols.yaml` 是 Phase 4 下载K线的代币清单来源，必须先同步、后下载。

### Phase 4：数据下载（拉取最新K线）
- 每次执行 replay 回测前，先更新到最新K线数据，保证回测无缺口。主要运行 `download_data.py`，代币来源是 Phase 3 生成的 `snapshot/{day}/symbols.yaml`（已去重）。

```bash
python3 download_data.py --symbols-file ./snapshot/20260807/symbols.yaml --data-dir ./data/klines
```

具体操作：
1. 读取 `symbols.yaml` 代币清单（`--symbols-file`）。
2. 每个代币读取本地 `data/klines/1m/{SYMBOL}_1m.csv` 最新K线时间（UTC）。
3. 无数据 → 用 `data.binance.vision` `monthly/klines` 批量下载历史月度数据。
4. 有缺口 → 用 `daily/klines` 补到 UTC 昨天（daily 优先于 REST）。
5. daily 拿不到的最新一段 → REST API(fapi) 补到当前（失败则放弃该代币并报错）。
6. 合并去重排序，存为本地 UTC 格式 CSV。

**目录**：`data/klines/1m/{SYMBOL}_1m.csv`（与 `config/settings.yaml` 的 `csv_dir` 一致，回测可直接读）。

> 也支持手动指定代币：`python3 download_data.py --symbols BTCUSDT,ETHUSDT`。

### Phase 5：回测执行
- 执行 `replay.py`，读取 `config.yaml` 中所有策略并执行每日回放。

```bash
python3 replay.py --date 20260807 --config config.yaml
```

具体操作：
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
   - `--strategies`/`--symbols` 由快照 overrides 扫描得到，二选一必需。
   - `--profile backtest` 指向第 3 步生成的 `config/backtest.yaml`。
   - `--yes` 跳过任务数确认（replay 跑在自动流/crontab）。
   - 输出目录由 `backtest.yaml.output_dir` 直指 `replay_outputs/{day}/{策略文件夹}/`，回测原生写入，无需 cp。
5. **设定回测日期**：默认为昨天（复盘昨日实盘），可用 `--date` 指定当天或其他日期，亦可用 `--start`/`--end` 自定义区间。
6. 回测结果输出到 `replay_outputs/{day}/{策略文件夹}/`。

### Phase 6：结果输出与验证
- 将回测结果文件输出并保存至指定目录，直接检查结果。
- **目录**：`replay_outputs/{day}/{策略文件夹}/`（由 `backtest.yaml.output_dir` 直指，回测原生写入）。
- 确认结果文件存在（如 `backtest_result.json`）即为复盘完成。

---

## 四、时序分析

### 时序图（完整执行流）

```
用户
 │
 ├─ 自然语言触发（复盘/回放回测/今日replay/每日回测）
 │   解析日期（默认昨天，YYYYMMDD）
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 1: 任务触发与初始化检查                      │
 │   │  1.1 自然语言输入 → 1.2 初始化状态检查              │
 │   │                          │                        │
 │   │            ┌─────────────┴──────────────┐         │
 │   │            ▼                            ▼         │
 │   │      已初始化?                       未初始化        │
 │   │      → 跳 Phase 2                  → Phase 1.5     │
 │   └──────────────────────────────────────────────────┘
 │                          │
 │   (未初始化)              ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 1.5: 环境准备与配置（仅首次/重置）            │
 │   │  1.5.1 备份 templates/ 全部文件（可回滚）           │
 │   │  1.5.2 配置 config.yaml（product/paper/smoking     │
 │   │        三组 host+path）+ 确认 python3/pyyaml/      │
 │   │        rsync/ssh → 回 1.2 复检 → 通过进 Phase 2    │
 │   └──────────────────────────────────────────────────┘
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 2: 运行前安全检查与信息确认                  │
 │   │  2.1 确认环境（输出 config.yaml 供核对）           │
 │   │  2.2 确认备份信息（host/path + 各组策略名）        │
 │   │      不通过→用户改config.yaml→回2.2 / 通过→↓       │
 │   └──────────────────────┬───────────────────────────┘
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 3: 数据同步（实盘快照同步）                  │
 │   │  sync-exee.py --date YYYYMMDD                     │
 │   │   ├─ 代码 → snapshot/{day}/{策略文件夹}/            │
 │   │   ├─ 数据 → replay_data/{day}/{策略文件夹}/data/    │
 │   │   ├─ 仓位 → signals/positions/history_positions    │
 │   │   └─ 扫 overrides 去重 → snapshot/{day}/symbols.yaml│
 │   │   排除: logs/.venv/backtest_output                 │
 │   └──────────────────────┬───────────────────────────┘
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 4: 数据下载（拉取最新K线）                   │
 │   │  download_data.py --symbols-file snapshot/{day}/symbols.yaml │
 │   │   读最新K线时间 → 无数据:monthly → 有缺口:daily →   │
 │   │   最新段:REST(fapi) → 合并去重排序存 UTC CSV         │
 │   │   → data/klines/1m/{SYMBOL}_1m.csv                 │
 │   └──────────────────────┬───────────────────────────┘
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 5: 回测执行                                  │
 │   │  replay.py --date YYYYMMDD                         │
 │   │   ├─ 每快照建 venv + 装依赖                          │
 │   │   ├─ 扫 overrides 收集 策略名+代币                   │
 │   │   ├─ 快照 config/ 下生成 backtest.yaml              │
 │   │   └─ run_backtest_batch.sh --profile backtest --yes │
 │   │      输出 → replay_outputs/{day}/{策略文件夹}/       │
 │   └──────────────────────┬───────────────────────────┘
 │                          ▼
 │   Phase 6: 结果输出与验证
 │    确认 backtest_result.json 存在 = 复盘完成
 │                          ▼
 └─ 完成: replay_outputs/{day}/{策略文件夹}/ 回测结果
```

### 时序关键点

1. **首次/重置才走 Phase 1.5**：已初始化环境直接跳到 Phase 2。初始化判定 = `templates/` 下 `sync-exee.py`/`replay.py`/`config.yaml` 齐全。

2. **确认回环**：Phase 2.2（备份信息）是"不通过 → 用户改 `config.yaml` → 回 2.2 重确认"的循环，直到通过才前进。

3. **同步必须在下载之前**：Phase 3 生成的 `symbols.yaml` 是 Phase 4 下载K线的代币清单来源（从实盘快照 overrides 去重），故必须先同步、后下载。这是跨 Phase 的硬依赖。

4. **数据流转时序**：`sync-exee.py`（实盘 → snapshot + replay_data + symbols.yaml）→ `download_data.py`（symbols.yaml → data/klines）→ `replay.py`（snapshot 代码 + data/klines → replay_outputs）。

5. **K线下载三级回退时序**：无数据 → `monthly/klines` 批量历史 → 有缺口 → `daily/klines` 补到昨天 → 最新段 → REST API(fapi) 补到当前。失败则放弃该代币报错。

6. **回测配置动态生成时序**：Phase 5 在每个快照 `config/` 下动态生成 `backtest.yaml`（`start`/`end`/`data_dir`/`output_dir` 动态，其余取 `backtest.example.yaml` 默认），`--profile backtest` 读取它，`output_dir` 直指 `replay_outputs/{day}/{策略文件夹}/`，回测原生写入无需 cp。

7. **目录对仗**：`replay_data`（实盘输入基准）↔ `replay_outputs`（回测输出结果），按 `{day}/{策略文件夹}/` 对仗组织，便于实盘 vs 回测对比。

---

## 五、目录结构

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

## 六、配置文件结构

### config.yaml

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

## 七、脚本说明

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

## 八、边界（四个 skill 协作）

> **dev 写 → discovery 测 → deploy 跑 → replay 管**

| skill | 职责 |
|-------|------|
| `trading-dev` | 写策略（开发全生命周期） |
| `trading-discovery` | 测策略（回测探索） |
| `trading-deploy` | 跑策略（部署上线） |
| `trading-replay` | 管策略（每日备份+回放） |
