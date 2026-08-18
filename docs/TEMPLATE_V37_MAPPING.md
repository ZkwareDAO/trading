# strategy-template v3.7 命令映射表

**用途**：本仓 4 个 skill 转调 strategy-template 时的**唯一权威映射**。
**事实来源**：`strategy-template` 源码 `add_argument` + `--help` 实跑输出，非文档抄录。
**锚定版本**：v3.7.0（`docs/SCRIPTS.md` 头部声明，2026-08-17）

> ⚠️ 改任何 skill 里的转调命令前，先查本表。本表与 template `--help` 不一致时，
> 以 `--help` 为准并更新本表——不要在 skill 里另立一套理解，那正是 upstream
> `CONFIG_UNIFICATION_SPEC.md` 定级为 P0 的「配置分叉」。

---

## 0. 前置条件（skill 必须先检查，否则命令必然 127）

| 项 | 要求 | 检查方式 |
|---|---|---|
| Python 解释器 | **项目 venv**，`python3` 通常不在 PATH | `[ -x .venv/bin/python ]` |
| 工作目录 | 必须是 template 仓库根 | `[ -f config/settings.yaml ]` |
| 策略 overrides | `strategies/<name>/overrides/<SYMBOL>.yaml` 必须存在 | 显式清单缺文件直接抛 `FileNotFoundError` |

```bash
# skill 内统一用这个变量，不要写死 python3
PY="${TEMPLATE_PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY="$(command -v python3)"
```

---

## 1. 回测：单组合

**已删除的旧写法（v3.7 前）**：

```bash
# ❌ 这些参数 v3.7 全部不存在，跑必报 unrecognized arguments
python -m backtest.run_backtest \
    --strategy NAME --symbol SYMBOL \
    --config PATH --output DIR \
    --timeframe 1m --data-dir D --output-dir D --cash N --commission N
```

**v3.7 正确写法（7 参数）**：

```bash
$PY -m backtest.run_backtest \
    --strategies NAME:SYMBOL \
    --start 20260601 [--end 20260701] \
    [--profile backtest] [--config-path PATH] [--overrides JSON] [--log-level INFO]
```

| 参数 | 必填 | 说明 |
|---|---|---|
| `--strategies` | ✅ | `name:symbol`，**symbol 唯一来源**。多于 1 个组合直接 `exit(1)` |
| `--start` | ✅ | `YYYYMMDD` / 秒时间戳 / 毫秒时间戳 |
| `--end` | | 默认当前时间 |
| `--profile` | | 默认 `backtest`，读 `config/<name>.yaml` |
| `--config-path` | | 覆盖默认 overrides 路径 |
| `--overrides` | | JSON 字符串，**深合并**进配置 |
| `--log-level` | | `DEBUG/INFO/WARNING/ERROR` |

**参数迁移对照**：

| 旧参数 | v3.7 去哪了 |
|---|---|
| `--strategy X` + `--symbol S` | 合并为 `--strategies X:S` |
| `--config P` | → `--config-path P`（默认自动读 overrides，通常不必给） |
| `--output D` / `--output-dir D` | → profile 的 `output_dir` 键 |
| `--timeframe` / `--data-dir` | → profile 的 `timeframe` / `data_dir` 键 |
| `--cash` / `--commission` | → profile 的 `cash` / `commission` 键 |
| `--use-today-as-output-date` | → profile 的 `use_today_as_output_date` 键 |

> 下放理由（`run_backtest.py:810-814`）：策略参数若能被 CLI 覆盖，回测与实盘就会读
> 两份不同参数，属**回测失真**。

---

## 2. 回测：批量多组合

单次 `run_backtest` 只能跑一个组合。多组合用 `batch_runner`：

```bash
# 显式清单（与实盘 --run 同格式）
$PY -m backtest.batch_runner \
    --run NAME:SYM1,NAME:SYM2,OTHER:SYM3 \
    --start 20260601 [--end 20260701] [--profile backtest] [--log-level INFO]

# 或按登记表
$PY -m backtest.batch_runner --config config/strategies.yaml --start 20260601
```

并发由 profile 的 `max_workers` 控制（`ProcessPoolExecutor`，默认 4）。
**不需要在 skill 里手写 `for` 循环或 `xargs -P`。**

`batch_runner` 内部转调 `run_backtest` 只拼 5 个参数（`batch_runner.py:118-127`）：
`--strategies` / `--start` / `--profile` / `--config-path` /（可选 `--end`、`--overrides`、`--log-level`）。

**退出码**：任一任务失败 → `exit(1)`（`batch_runner.py:299-310`）。
`--daemon` 模式不参与判定。

### ⚠️ `--daemon` 已知缺陷 — 不要用

`batch_runner.py:187-191` 重启后台子进程时**只透传 `--profile` 和 `--batch-id`**，
丢失 `--run` / `--start` / `--end` / `--config`：

```python
cmd = [sys.executable, "-m", "backtest.batch_runner",
       "--profile", self.profile, "--batch-id", batch_id]   # ← --run 等全丢
```

后果：`--run A,B --daemon` 后台实际跑的是 `config/strategies.yaml` 登记表，
不是你给的清单，且时间范围回退到 profile 默认值。

**skill 侧后台执行请自己 `nohup`，不要用 `--daemon`**：

```bash
nohup $PY -m backtest.batch_runner --run "$RUN_LIST" \
    --start "$START" --end "$END" --profile "$PROFILE" \
    > "$LOG" 2>&1 &
```

---

## 3. 回测：每日定时

```bash
$PY backtest/daily_backtest.py [--yesterday | --days N | --start YYYYMMDD [--end YYYYMMDD]] \
    [--config PATH] [--log-level LEVEL] [其余参数透传 batch_runner]
```

`daily_backtest.py` 是 `batch_runner` 的 thin wrapper（83 行）：只算 UTC 日期范围，
然后 `subprocess` 调 `-m backtest.batch_runner --start X --end Y <透传>`。

日期优先级：`--start` > `--yesterday` > `--days N` > 默认当天（UTC）。

> **skill 不要自己实现"回测最近 N 天"的日期计算 + 循环**——直接转调本脚本。
> `--profile` 等未声明参数会通过 `parse_known_args` 自动透传。

---

## 4. 实盘：单策略进程

```bash
# ❌ 不存在：python -m backtest.run_strategy --strategy X --config P
# ✅ v3.7：
$PY run_strategy.py --name NAME --symbol SYMBOL \
    [--interval 4h] [--version 3] [--trading-mode live|paper_trading|smoking] \
    [--config-path PATH] [--global-config config/settings.yaml] [--log-level INFO]
```

`backtest/run_strategy.py` **从不存在**。真实入口在仓库根目录。

`--interval` / `--version` / `--trading-mode` 省略时自动从
`strategies/<name>/overrides/<SYMBOL>.yaml` 补全（`run_strategy.py:529-531`）：

```python
interval = args.interval or _read_interval_from_overrides(...) or "4h"
version  = args.version  or str(overrides_section.get("version", "2"))
trading_mode = args.trading_mode or overrides_section.get("trading_mode", "live")
```

> ⚠️ **`trading_mode` 缺省是 `live`（真实下单）**。skill 生成命令时必须显式声明，
> 或在启动前把解析出的模式展示给用户确认。

---

## 5. 实盘：批量 / 一键启停

```bash
# 按登记表 config/strategies.yaml
./start.sh [--dev]
./stop.sh

# 命令行临时指定（注意 --strategies 只写策略名，不是 name:symbol）
./scripts/run_live_batch.sh --strategies NAME1,NAME2 --symbols BTCUSDT,ETHUSDT [--daemon] [--yes]

# 自定义登记表（实盘用 --registry，因 --config 已被系统配置占用）
./scripts/run_live_batch.sh --registry my_live.yaml --daemon
```

三者共用 PID 文件 `cta_strategy_core.pid`，因此 `stop.sh` 通用，
也因此**不能同时运行**（后启动的会先停掉前一个）。

含 `live` 实例时脚本要求手动输入 `live` 确认，`--yes` 跳过。

---

## 6. 数据下载

```bash
$PY scripts/download_data.py --symbol BTCUSDT,ETHUSDT --interval 1m --days 30 \
    [--data-dir ./data/klines]
```

输出：`{data_dir}/{interval}/{SYMBOL}_{interval}.csv`（6 列单文件）。

回测按 1m 驱动，大周期由框架**自动聚合并缓存**，
**不需要**跑 `resample_1m_to_multi_tf.py`（那个脚本读的是 Binance 按日归档 12 列格式，
与 `download_data.py` 产出格式不通）。

---

## 7. run-profile：自定义输出目录

skill 需要把输出落到自己的目录（如 `discovery_outputs/`）时，**建 profile，不要传 `--output`**。

```yaml
# config/discovery.yaml  ← 用 --profile discovery 选取
start: "20260601"
end: ""
cash: 5000
commission: 0.0004
data_dir: "./data/klines"      # ⚠️ 必须与 settings.yaml 的 data_manager.csv_dir 完全一致
output_dir: "./discovery_outputs"   # ← 只有这个键可以自由改
use_today_as_output_date: true
log_level: "INFO"
max_workers: 4
```

### 🔴 `data_dir` 是硬约束，不能随便改

`run_backtest.py:886` 启动即校验 `profile.data_dir == settings.yaml 的 data_manager.csv_dir`，
不一致直接 `sys.exit(1)`，报错原文（`config_loader.py:126-132`）：

```
数据目录配置分叉：
  profile data_dir            = ...
  settings.yaml csv_dir       = ...
二者必须指向同一目录，否则实盘写入与回测读取会落在不同位置，回测将基于过时数据得出结论。
```

路径比较已归一化，`./data/klines` / `data/klines` / `data/klines/` 视为相同。

### profile 名的限制（`config_loader.py:68-77`）

- 不能含 `/` `\`，不能以 `.` 开头（防路径穿越）
- 保留名不可用：`settings` / `settings.example` / `strategies` / `strategies.example`
- 文件不存在或内容为空 → 抛异常，**不会静默回退默认值**

### profile 被代码真实消费的键（`run_backtest.py:868-873` + `batch_runner.py:149`）

`timeframe` · `data_dir` · `output_dir` · `cash` · `commission` ·
`use_today_as_output_date` · `log_level` · `max_workers` · `start` · `end`

其余键写了也不生效——不要往 profile 里塞 `mode` / `signal_hub` / `strategy_engine`，
upstream 已因"无消费者且与 settings.yaml 同名键取值相反"删除过这三段。

---

## 8. 输出产物结构

```
{output_dir}/{strategy}/{date}/{time}/{symbol}/
├── backtest_signals.csv
├── backtest_equity.csv
├── backtest_trades.csv
├── backtest_result.json
├── backtest_report.txt
├── backtest_analysis_report.md
├── config.yaml                  # 本次实际生效的策略配置（供复现）
└── charts/
    ├── backtest_equity_curve.png
    └── backtest_drawdown.png
```

路径由 `BacktestReporter` 拼接（`backtest_reporter.py:46-51`）：
`{base_output_dir}/{strategy_name}/{date_dir}/{time_dir}/{symbol}/`。

`date_dir` 取值受 `use_today_as_output_date` 控制（`run_backtest.py:690`）：
`true` → 当天日期；`false` → 回测 `end_date`。

> **skill 聚合结果时按此结构 glob**，不要假设自定义的扁平目录。
> 实测样例：`discovery_outputs/sar_snt3_v3/20260817/150342/BTCUSDT/backtest_result.json`

---

## 9. 配置三层模型（skill 生成配置时必须遵守）

```
config/settings.yaml                        系统层：数据源/日志/推送（${VAR} 占位）
config/strategies.yaml                      编排层：跑哪些策略 × symbol × trading_mode（实盘回测共用）
strategies/<name>/overrides/<SYM>.yaml      策略层：per-symbol 参数，唯一事实来源
config/<profile>.yaml                       run-profile：回测运行方式
```

### 已删除、不要再生成的路径

| 路径/参数 | 状态 |
|---|---|
| `strategies/<name>/config.test.yaml` | ❌ 从不存在于 v3.7 |
| `strategies/<name>/config.yaml` | ❌ 代码中无任何读取点（`CONFIG_UNIFICATION_SPEC.md` 提及的是收敛前历史状态） |
| `strategies/<name>/config/<SYMBOL>.yaml` | ❌ 已改为 `overrides/<SYMBOL>.yaml` |
| `backtest/config/main.yaml` | ❌ 已删除 |
| `backtest/config/strategies.yaml` | ❌ 已删除 |
| `--backtest-config` | ❌ 已删除，改用 `--profile` |

依据：`CONFIG_UNIFICATION_SPEC.md:6-10` 明文声明上述"均已删除"。

### `${VAR}` 环境变量占位符

未设置时：整串是 `${VAR}` → 解析为 `None`；嵌入式 → 替换为空串
（`run_strategy.py:36-58`）。全部环境变量均**可选**，缺失时对应功能优雅降级
（跳过 factory 注册 / 回退 Binance 公共源 / 不推信号），所以纯回测无需任何环境变量。

### `.strategy-spec.yaml`

策略目录下的规格文件，**无任何代码消费**（全仓 grep 确认），是给人和 AI 读的策略契约。
其 `default_params` 与 `overrides/<SYM>.yaml` 的 `params` 是"默认值 vs per-symbol 覆盖"关系。

---

## 10. 新增策略的最小文件集

```
strategies/<name>/
├── strategy.py                 # 必需，实现 Strategy 类（继承 BaseStrategy）
├── __init__.py                 # 建议
├── <name>_core.py              # 建议，指标与信号逻辑
├── .strategy-spec.yaml         # 建议，规格契约
└── overrides/
    └── <SYMBOL>.yaml           # 必需，至少一个
```

策略加载走模块路径 `strategies.<name>.strategy`（`run_strategy.py:261-268`），
所以目录名即策略名，必须能作为 Python 包名。

---

## 11. 漂移门禁

改完 skill 后跑，命中数必须为 0：

```bash
grep -rn 'backtest\.run_strategy\|--backtest-config\|config\.test\.yaml' \
    trading-*/SKILL.md trading-*/templates/ | wc -l

grep -rn 'run_backtest.*--strategy \|run_backtest.*--symbol \|run_backtest.*--output ' \
    trading-*/SKILL.md trading-*/templates/ | wc -l
```

注意区分两类 `--strategy`：

| 类别 | 例子 | 处理 |
|---|---|---|
| skill 自己的用户接口 | `/trading-deploy run --strategy ema_rsi` | ✅ 保留，这是 skill 的 UX |
| 转调 template | `python -m backtest.run_backtest --strategy X` | ❌ 必须改 |
