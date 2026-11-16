# frontend-data v2 数据说明（新版）

本文档以 `generate-kanban-data.py` 的实际产物为准，描述新版 frontend-data 的目录组织、文件内容与字段口径。

## 1. 生成链路

```text
snapshot/{day}/{project}/                    代码快照（引擎/策略/杠杆/meta 来源）
replay_data/{day}/{project}/data/state/...   实盘运行数据（live 侧）
replay_outputs/{day}/{project}/...           回放回测结果（backtest 侧）
data/klines/1m/{SYMBOL}_1m.csv               K线（OPEN 仓位 mark 价）
                    ↓
        generate-kanban-data.py
                    ↓
frontend-data/
```

生成命令：

```bash
$TRADING_PY generate-kanban-data.py --date 20261026 \
  --replay-data   /path/replay_data \
  --replay-outputs /path/replay_outputs \
  --snapshot      /path/snapshot \
  --klines        /path/data/klines \
  --out           /path/frontend-data
```

可选：`--all` / `--start --end` 批量、`--display-names` 显示名映射、`--run latest` 只保留最新批次、`--prune` 清理旧策略目录、`--dry-run`。

## 2. 目录结构

```text
frontend-data/
├── catalog.csv                            # 总目录（所有日期）
└── {day}/                                 # YYYYMMDD，如 20261026
    ├── manifest.csv                       # 当日策略×代币汇总
    ├── backtest_runs.csv                  # 当日全部回放 run
    └── {strategy}/                        # runtime 族名，如 sar_supertrend_4H_3
        ├── meta.json                      # 策略元数据
        ├── manifest.csv                   # 本策略 策略×代币 清单
        ├── backtest_runs.csv              # 本策略全部 run
        ├── live_positions.csv             # 实盘仓位（新版仓位入口）
        ├── live_signals.csv               # 实盘信号
        ├── backtest_positions.csv         # 回测仓位
        ├── backtest_signals.csv           # 回测信号
        ├── signal_comparison.csv          # 实盘 vs 回测信号对比
        └── backtest_results/
            └── {run_stamp}/               # YYYYMMDDTHHMMSS
                └── {SYMBOL}.json          # 引擎原始回测结果
```

> **新版约定**：不再产出日期级 `positions.csv`（账户仓位快照已废弃）。仓位数据以各策略目录下的 `live_positions.csv` / `backtest_positions.csv` 为准。
>
> **按需建文件**：没有数据的文件不会创建，不用空表头占位。

## 3. 读取顺序

1. `catalog.csv` → 选日期
2. `{day}/manifest.csv` → 当日策略/代币概览
3. `{day}/{strategy}/meta.json` → 策略展示信息
4. `{day}/{strategy}/live_positions.csv` / `backtest_positions.csv` → 仓位
5. `{day}/{strategy}/signal_comparison.csv` → 实盘/回放差异

页面取回放数据时必须过滤 `is_latest = 1`，否则同日多轮次仓位会叠加。

## 4. 文件说明

### 4.1 catalog.csv

全量日期索引。

```csv
schema_version,day,strategies,has_live,has_backtest,updated_at
1,20261026,new_dolphin_4H_3|sar_supertrend_4H_3,1,1,2026-11-11T08:40:14Z
```

| 字段 | 说明 |
|---|---|
| `schema_version` | 固定 `1` |
| `day` | 日期 `YYYYMMDD` |
| `strategies` | 当日策略名，竖线分隔 |
| `has_live` / `has_backtest` | 当日是否存在实盘/回测数据（0/1） |
| `updated_at` | 生成时间，ISO8601 UTC |

### 4.2 {day}/manifest.csv（26 列）

当日「策略 × 代币」汇总，一行一个 runtime 标的。

```text
schema_version,data_day,strategy,source_strategy,strategy_display_name,strategy_version,
symbol,runtime_name,engine,trading_mode,status,has_live,has_backtest,total_trades,
winning_trades,losing_trades,win_rate,total_pnl,open_positions,floating_pnl,
latest_run_id,latest_annualized_return,latest_roe,latest_max_drawdown,strategy_path
```

| 字段 | 说明 |
|---|---|
| `strategy` | runtime 族名，如 `sar_supertrend_4H_3` |
| `source_strategy` | 配置策略名，如 `sar_supertrend` |
| `strategy_display_name` | 展示名（未传映射时同 strategy） |
| `strategy_version` | 当前取日期 `YYYYMMDD` |
| `symbol` | 交易对 |
| `runtime_name` | 实盘 runtime，如 `sar_supertrend_4H_3_BTCUSDT_LIVE`；纯回测为空 |
| `engine` | `rust` / `python` |
| `trading_mode` | `live` / `paper_trading` / `smoking` / `backtest` |
| `status` | `success` / 其它失败态 |
| `has_live` / `has_backtest` | 0/1 |
| `total_trades` / `winning_trades` / `losing_trades` | 成交统计 |
| `win_rate` | 小数，`0.3` = 30% |
| `total_pnl` | 金额 ÷ 初始资金 |
| `open_positions` | 当前未平仓数 |
| `floating_pnl` | OPEN 仓位浮盈 ÷ 初始资金 |
| `latest_run_id` | 最新回放 run id |
| `latest_annualized_return` / `latest_roe` / `latest_max_drawdown` | 小数 |
| `strategy_path` | 相对路径 `{day}/{strategy}` |

### 4.3 {day}/backtest_runs.csv（28 列）

当日全部回放 run，一行一个「run × 代币」。

```text
schema_version,source,data_day,batch_id,run_id,run_day,run_stamp,sweep,strategy,
source_strategy,strategy_display_name,strategy_version,config_version,symbol,
start_date,end_date,status,completed_at,signals_processed,trades_count,
annualized_return,roe,total_return,max_drawdown,win_rate,total_trades,
sharpe_ratio,is_latest
```

| 字段 | 说明 |
|---|---|
| `source` | `replay`（回放）或 `discovery` |
| `batch_id` | `{day}-{HHMM}`，同时序批次聚合 |
| `run_id` | `{strategy}-{run_stamp}` |
| `run_day` | `YYYYMMDD` |
| `run_stamp` | `YYYYMMDDTHHMMSS`（标识符，不是数据时间） |
| `sweep` | 同策略同日的轮次，从 0 起 |
| `start_date` / `end_date` | 回测区间 `YYYY-MM-DD`；**start 会前推 warmup 天数**，因此可能早于 `data_day` |
| `completed_at` | ISO8601 UTC |
| `signals_processed` / `trades_count` | 引擎统计 |
| `annualized_return` / `roe` / `total_return` / `max_drawdown` / `win_rate` / `sharpe_ratio` | 小数 |
| `is_latest` | 0/1，前端必须只取 1 |

策略级 `backtest_runs.csv` 列完全相同，只是只含该策略的行。

### 4.4 {strategy}/meta.json

```json
{
  "schema_version": 1,
  "day": "20261026",
  "strategy": "sar_supertrend_4H_3",
  "source_strategy": "sar_supertrend",
  "display_name": "sar_supertrend",
  "description": "sar_supertrend 回测",
  "version": "20261026",
  "engine": "rust",
  "timeframe": "4h",
  "leverage": 1,
  "warmup_days": 30,
  "indicators": [],
  "indicator_params": {},
  "logic": {"entry": [], "risk": []},
  "params": {},
  "captured_at": "2026-11-11T08:38:10Z"
}
```

| 字段 | 说明 |
|---|---|
| `strategy` / `source_strategy` | runtime 族名 / 配置策略名 |
| `display_name` | 可用 `--display-names` 注入中文名 |
| `description` | 未配置时为 `{strategy} 回测` |
| `version` | 当前取日期 |
| `timeframe` / `leverage` / `warmup_days` | 来自快照配置 |
| `indicators` / `indicator_params` | 从配置 params 推导 |
| `logic` | `entry` 开仓条件；`risk` 风控条件（含原平仓/止损/仓位管理原文）。不再单独输出 `exit` |
| `params` | 策略参数 |
| `captured_at` | 生成时间，ISO8601 UTC |

### 4.5 {strategy}/manifest.csv（10 列）

```text
schema_version,data_day,strategy,symbol,runtime_name,engine,trading_mode,status,has_live,has_backtest
```

一行一个「策略 × 代币」。实盘侧 `runtime_name` 形如 `..._LIVE`，纯回测为空。

### 4.6 {strategy}/live_positions.csv（25 列，新版仓位入口）

实盘仓位，含当日已平仓与未平仓。

```text
schema_version,data_day,strategy,source_strategy,strategy_display_name,strategy_version,
symbol,runtime_name,engine,trading_mode,position_id,side,status,qty,entry_time,
entry_price,exit_time,exit_price,realized_pnl,pnl_pct,max_pnl_pct,min_pnl_pct,
leverage,exit_reason,updated_at
```

| 字段 | 说明 |
|---|---|
| `position_id` | 仓位标识 |
| `side` | `long` / `short` |
| `status` | `OPEN` / `CLOSED` |
| `qty` | 数量 |
| `entry_time` / `exit_time` | ISO8601 UTC；OPEN 的 `exit_time` 为空 |
| `entry_price` / `exit_price` | 成交价 |
| `realized_pnl` | 已实现盈亏（金额） |
| `pnl_pct` | 盈亏百分比（百分数，`1.9073` = 1.9073%） |
| `max_pnl_pct` / `min_pnl_pct` | 持仓期间最大/最小浮盈百分比 |
| `leverage` | 杠杆 |
| `exit_reason` | 如 `live_close`、`stop_loss`；OPEN 为空 |
| `updated_at` | 数据快照时间 |

### 4.7 {strategy}/live_signals.csv（21 列）

```text
schema_version,data_day,strategy,source_strategy,strategy_display_name,strategy_version,
symbol,runtime_name,engine,trading_mode,signal_id,signal_time,side,action,direction,
price,qty,status,filled_price,filled_qty,reason
```

| 字段 | 说明 |
|---|---|
| `side` | `BUY` / `SELL` |
| `action` | `open` / `close` |
| `direction` | `long` / `short` |
| `signal_time` | ISO8601 UTC |
| `price` / `qty` | 意图价与数量 |
| `status` | `filled` 等 |
| `filled_price` / `filled_qty` | 实际成交 |
| `reason` | 备注 |

### 4.8 {strategy}/backtest_positions.csv（31 列）

```text
schema_version,source,data_day,strategy,source_strategy,strategy_display_name,
strategy_version,symbol,run_id,batch_id,run_day,run_stamp,sweep,is_latest,
engine,trading_mode,position_id,side,status,qty,entry_time,entry_price,exit_time,
exit_price,realized_pnl,pnl_pct,max_pnl_pct,min_pnl_pct,leverage,exit_reason,updated_at
```

字段含义同 `live_positions.csv`，另含 run 定位字段：

| 字段 | 说明 |
|---|---|
| `source` | `replay` |
| `run_id` / `batch_id` / `run_day` / `run_stamp` / `sweep` | 对应 `backtest_runs.csv` |
| `is_latest` | 0/1 |
| `trading_mode` | 固定 `backtest` |

> 当前口径：包含回测全区间（start 前推 warmup），因此 `entry_time` 可能早于 `data_day`。

### 4.9 {strategy}/backtest_signals.csv（30 列）

```text
schema_version,source,data_day,strategy,source_strategy,strategy_display_name,
strategy_version,symbol,run_id,batch_id,run_day,run_stamp,sweep,is_latest,
engine,trading_mode,signal_id,signal_time,side,action,direction,price,qty,status,
filled_price,filled_qty,reason
```

字段含义同 `live_signals.csv`，多出 run 定位字段。开仓与平仓各产生一行。

### 4.10 {strategy}/signal_comparison.csv（20 列）

实盘信号与回测信号的匹配结果。

```text
schema_version,data_day,strategy,source_strategy,strategy_display_name,symbol,run_id,
batch_id,record_type,match_type,signal_action,live_signal_id,backtest_signal_id,
live_time,backtest_time,time_diff_seconds,live_price,backtest_price,price_diff_pct,status
```

| 字段 | 说明 |
|---|---|
| `record_type` | `matched` / `unmatched_live` / `unmatched_backtest` |
| `match_type` | `exact` / `window` / `none` |
| `signal_action` | `open` / `close` |
| `live_signal_id` / `backtest_signal_id` | 两侧信号 id（未匹配的一侧为空） |
| `live_time` / `backtest_time` | ISO8601 UTC |
| `time_diff_seconds` | 匹配时间差（秒） |
| `live_price` / `backtest_price` | 两侧价格 |
| `price_diff_pct` | 价格差百分比 |
| `status` | `matched` / `missed` |

### 4.11 {strategy}/backtest_results/{run_stamp}/{SYMBOL}.json

引擎原始回测结果，页面用于单标的详情、权益曲线等。

顶层键：

```text
accounts, config, daily_equity, duration_seconds, end_time, klines_processed,
metrics, performance_summary, signals_processed, start_time, status, trades_count
```

| 键 | 说明 |
|---|---|
| `config` | 本次回测配置（`initial_cash`、`start_date`、`end_date`、`symbols` 等） |
| `daily_equity` | 每日权益序列 |
| `metrics` / `performance_summary` | 收益/回撤/胜率等指标 |
| `accounts` | 账户维度结果 |
| `start_time` / `end_time` | ISO8601 UTC |
| `duration_seconds` | 运行耗时 |
| `klines_processed` / `signals_processed` / `trades_count` | 引擎统计 |
| `status` | `success` |

## 5. 口径约定

| 项 | 约定 |
|---|---|
| 日期目录 | `YYYYMMDD` |
| 时间戳 | ISO8601 UTC，如 `2026-10-26T01:45:00Z` |
| `run_stamp` | `YYYYMMDDTHHMMSS`，标识符不是数据时间 |
| `batch_id` | `{day}-{HHMM}` |
| 比率 | 小数：`roe=0.0164` 表示 1.64% |
| `pnl_pct` / `price_diff_pct` | 百分数：`2.2049` 表示 2.2049% |
| `total_pnl` / `floating_pnl` | 金额 ÷ 初始资金（兜底 10000） |
| 空回测 | `signals_processed=0` 的 run 保留行，但不生成 positions/signals CSV |
| 无数据 | 不建文件，不用表头占位 |
| 多轮次 | 前端用 `is_latest=1` 过滤；`sweep` 为轮次 |

## 6. 与旧版 frontend-data 的差异

| 项 | 旧版 | 新版 |
|---|---|---|
| 日期级 `positions.csv` | 有（账户仓位快照） | **不再产出** |
| 仓位入口 | 日期级 + 策略级 | 策略级 `live_positions.csv` / `backtest_positions.csv` |
| `strategy` 命名 | runtime 名 | runtime 族名（如 `sar_supertrend_4H_3`） |
| `source_strategy` | 配置名 | 配置名（如 `sar_supertrend`） |
| 实盘/回测合并 | 依赖同名 runtime | 由 engine runtime 目录解析族名后合并 |
| 无数据文件 | 部分空表 | 不建文件 |

## 7. 已知限制

1. `backtest_positions/signals` 与 `signal_comparison` 当前包含 warmup 区间（`start_date` 早于 `data_day`），如只需当日数据需按 `data_day` 过滤。
2. `meta.json` 的 `indicators` / `logic` / `params` 依赖策略 spec；`logic` 仅含 `entry`（开仓）与 `risk`（风控，平仓内容已并入），未配置时为空。
3. `display_name` 未传 `--display-names` 时等于 `strategy`。
4. `backtest_results` 直接透传引擎结果，不同引擎（Rust/Python）键可能略有差异。
