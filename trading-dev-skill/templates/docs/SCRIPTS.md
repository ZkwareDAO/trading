# 脚本参考文档

**版本**: 3.7.0
**更新日期**: 2026-10-08

本文档列出系统提供的所有命令行脚本和工具。所有命令均以仓库根目录为工作目录。

---

## 1. 主程序

### 1.1 策略管理器

```bash
python3 run_strategies_manager.py
```

**说明**: 策略进程监督者。按登记表或 `--run` 清单拉起策略子进程并监控。

**职责**:
- 按登记表或 `--run` 清单启动策略进程（每策略独立进程）
- 监控子进程退出（只告警，不自动重启）
- 收到 SIGTERM/SIGINT 时优雅停止全部子进程（SIGTERM→SIGKILL）

**参数**:

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--config` | 否 | `config/settings.yaml` | 系统配置文件路径 |
| `--strategies` | 否 | `config/strategies.yaml` | 策略登记表路径 |
| `--run` | 否 | 无 | 显式清单 `name:symbol,...`，优先于登记表；缺 overrides 报错 |
| `--log-level` | 否 | `INFO` | 日志级别 |

**示例**:

```bash
# 使用默认配置（读 config/strategies.yaml 登记表）
python3 run_strategies_manager.py

# 指定自定义系统配置（复制 config/settings.yaml 改名维护）
python3 run_strategies_manager.py --config config/settings.custom.yaml

# 只跑指定组合（不改登记表）
python3 run_strategies_manager.py --run sar_snt3_v3:BTCUSDT,sar_snt3_v3:ETHUSDT
```

一键启停见 [start.sh / stop.sh](#93-一键启停) 与 [9.2 批量实盘](#92-批量实盘多策略--多代币)。

**架构说明**:
- 每个策略运行在独立进程（`run_strategy.py`），直连 Binance 行情与下单
- 子进程崩溃后由监控循环告警，不自动重启（由外部 supervisor/systemd 决定拉起策略）

---

### 1.2 运行单个策略进程

```bash
python3 run_strategy.py --name sar_snt3_v3 --symbol BTCUSDT --interval 4h --version 3 --trading-mode live
```

**说明**: 启动独立策略进程。通常由 `run_strategies_manager.py` 拉起，
也可手动单独启动调试。

**参数**:

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--name` | 是 | - | 策略目录名（如 `sar_snt3_v3`） |
| `--symbol` | 是 | - | 交易对（如 `BTCUSDT`） |
| `--interval` | 否 | 从 overrides 读 | 主周期；缺省时取 `timeframes[0]` |
| `--version` | 否 | 从 overrides 读 | 版本号；缺省时取 `version` |
| `--trading-mode` | 否 | 从 overrides 读，默认 `live` | `live`/`paper_trading`/`smoking` |
| `--config-path` | 否 | `strategies/<name>/overrides/<SYMBOL>.yaml` | 策略配置完整路径（优先级最高） |
| `--global-config` | 否 | `config/settings.yaml` | 全局配置文件路径 |
| `--log-level` | 否 | `INFO` | 日志级别（`DEBUG`/`INFO`/`WARNING`/`ERROR`） |

`--interval`/`--version`/`--trading-mode` 省略时自动从
`strategies/<name>/overrides/<SYMBOL>.yaml` 补全——**策略层是唯一事实来源**，
CLI 只是可选覆盖。

**信号处理**:

| 信号 | 行为 |
|------|------|
| `SIGTERM` | 触发优雅退出，调用 `on_stop()` 进行仓位持久化 |
| `SIGINT` (Ctrl+C) | 触发优雅退出 |

**示例**:

```bash
# 最简形式：interval/version/trading_mode 全部从 overrides 读取
python3 run_strategy.py --name sar_snt3_v3 --symbol BTCUSDT

# 显式指定全部参数
python3 run_strategy.py --name sar_snt3_v3 --symbol BTCUSDT --interval 4h --version 3 --trading-mode live

# 模拟盘
python3 run_strategy.py --name sar_snt3_v3 --symbol ETHUSDT --trading-mode paper_trading

# 指定配置文件路径
python3 run_strategy.py --name sar_snt3_v3 --symbol BTCUSDT --config-path /path/to/config.yaml

# 指定日志级别
python3 run_strategy.py --name sar_snt3_v3 --symbol BTCUSDT --log-level DEBUG
```

**进程特性**:
- 独立的 DataManager（专属 CSV 路径）
- 独立的 SignalLogger（CSV 存储 + 交易所直连下单）
- 独立的 WS 连接（直连 Binance 公共源）

---

## 2. 数据工具

### 2.1 下载 K 线数据

```bash
python3 scripts/download_data.py --symbol BTCUSDT --interval 1m --days 30
```

**说明**: 从 Binance 公共 fapi 下载 K 线数据，**无需 API key**。

**参数**:

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--symbol` | 是 | - | 交易对，支持逗号分隔多个（如 `BTCUSDT,ETHUSDT`） |
| `--interval` | 否 | `1m` | K 线周期（回测按 1m 驱动，大周期由框架自动聚合） |
| `--days` | 否 | `30` | 下载最近 N 天 |
| `--data-dir` | 否 | `./data/klines` | 输出目录（与 `settings.yaml` 的 `csv_dir` 一致） |

**环境变量**:

| 变量 | 说明 |
|------|------|
| `HTTPS_PROXY` / `HTTP_PROXY` | 代理地址，国内网络必需 |

**示例**:

```bash
# 下载 BTCUSDT 最近 30 天的 1m 数据
python3 scripts/download_data.py --symbol BTCUSDT --interval 1m --days 30

# 下载多个交易对
python3 scripts/download_data.py --symbol BTCUSDT,ETHUSDT --interval 1m --days 30

# 国内网络走代理
HTTPS_PROXY=http://<host>:<port> python3 scripts/download_data.py --symbol ETHUSDT --days 30
```

**输出路径**: `{data_dir}/{interval}/{SYMBOL}_{interval}.csv`

**数据来源**: Binance 公共 fapi（`/fapi/v1/klines`），分页拉取，单次上限 1500 条；
长缺口自动改走归档包（`data.binance.vision`，完整月 monthly zip / 零头天 daily zip）。

**库入口 `download_range()`**: 区间由调用方给定（而非从 CSV 末根推导）。
`backtest.run_backtest` 发现数据缺口时调用它自动补数，与 CLI 共用同一条
归档/fapi/merge 链路与落盘格式。无对应 CLI 参数。

---

### 2.2 重采样 1m 到多时间框架

```bash
python3 scripts/resample_1m_to_multi_tf.py --symbol BTCUSDT --timeframes 15m,1h,4h
```

**说明**: 将按日分片的 1m CSV 聚合成大周期 CSV。

> ⚠️ **本脚本不能直接消费 `download_data.py` 的产出**，两者格式不通：
>
> | | 路径 | 格式 |
> |---|---|---|
> | `download_data.py` 写 | `data/klines/1m/BTCUSDT_1m.csv` | 6 列，单文件 |
> | 本脚本读 | `data/klines/BTCUSDT/1m/BTCUSDT-1m-{日期}.csv` | 12 列 Binance 归档格式，按日分片 |
>
> 本脚本的输入是 Binance 官方按日归档包。用 `download_data.py` 下载的数据
> **无需重采样** —— 回测运行时会自动聚合大周期并缓存。

**参数**:

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--symbol` | 否 | `BTCUSDT,ETHUSDT,SOLUSDT` | 交易对，逗号分隔 |
| `--timeframes` | 否 | `5m,15m,30m,1h,4h,1d` | 目标周期，逗号分隔 |
| `--force` | 否 | 否 | 覆盖已存在的文件 |
| `--log-level` | 否 | `INFO` | 日志级别 |

---

## 3. 回测工具

### 3.1 运行回测

```bash
python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260610 --end 20260708
```

**参数**（7 个，v3.7 配置收敛后）:

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--strategies` | 是 | - | 运行清单 `name:symbol`，symbol 唯一来源；**单次仅支持一个**（传多个报错，多标的用 `batch_runner`） |
| `--start` | 是 | - | 开始时间（支持 YYYYMMDD、秒时间戳、毫秒时间戳），覆盖 profile.start |
| `--end` | 否 | 当前时间 | 结束时间（同上格式），覆盖 profile.end |
| `--profile` | 否 | `backtest` | run-profile，读 `config/<name>.yaml` |
| `--config-path` | 否 | `strategies/<name>/overrides/<SYMBOL>.yaml` | 策略配置完整路径（文件必须存在，否则报错） |
| `--overrides` | 否 | - | 配置覆盖字段（JSON 字符串） |
| `--log-level` | 否 | 跟 profile | 日志级别（优先级：CLI > 策略配置 > profile） |

注意：`--strategies` 的值是 `name:symbol`（如 `sar_snt3_v3:BTCUSDT`），
不是纯策略名；且**只接受一对**。底层解析复用
`run_strategies_manager.parse_explicit_strategies()`（与实盘 `--run`、
`batch_runner --run` 三处同一实现），传多个 pair 会直接 `exit 1`。

**回测专有参数已下放到 profile**，不再是 CLI 参数：`timeframe`、`data_dir`、
`output_dir`、`cash`、`commission`、输出日期模式 → 全部读 `config/backtest.yaml`。

理由：策略参数若能被 CLI 覆盖，回测与实盘就会读到两份不同参数，属**回测失真**。
详见 [CONFIG_UNIFICATION_SPEC.md](CONFIG_UNIFICATION_SPEC.md)。

**时间格式支持**:

| 格式 | 示例 | 说明 |
|------|------|------|
| YYYYMMDD | `20260518` | 日期格式 |
| 秒时间戳 | `1779118020` | 10 位数字 |
| 毫秒时间戳 | `1779118020000` | 13 位数字 |

**示例**:

```bash
# 使用日期格式
python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260610

# 使用秒时间戳（精确到秒）
python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 1779118020

# 使用毫秒时间戳（精确到毫秒）
python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 1779118020000

# 指定结束时间与配置文件（overrides 文件必须真实存在，否则直接报错）
python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260610 --end 20260708 \
  --config-path strategies/sar_snt3_v3/overrides/BTCUSDT.yaml

# 用 --overrides 覆盖配置参数
python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260610 \
  --overrides '{"params":{"stop_loss_pct":3.0},"capital":{"max_cash":100}}'

# 降日志级别提速
python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260610 --log-level WARNING
```

多标的回测请用 `batch_runner`（见 3.2），其 `--run` 接受与实盘同格式的 `name:symbol,...` 清单。

**自动数据补齐**:

回测框架会自动检查并补齐缺失的 K 线数据：
- 如果 CSV 起始时间晚于预热需求，自动下载预热期间数据
- 如果 CSV 最新时间早于回测结束时间，自动下载缺失数据

注意：补齐会写回源 CSV，**行数会变化**，属预期行为。

**输出文件**:

回测完成后在 `backtest_output/{strategy}/{date}/{time}/{symbol}/` 目录生成：
- `backtest_signals.csv` - 信号记录
- `backtest_equity.csv` - 权益曲线
- `backtest_trades.csv` - 交易记录
- `backtest_result.json` - 回测结果
- `backtest_report.txt` - 回测报告
- `backtest_analysis_report.md` - 分析报告
- `config.yaml` - 本次实际生效的策略配置（供复现）
- `charts/backtest_equity_curve.png` - 权益曲线图（含价格叠加）
- `charts/backtest_drawdown.png` - 回撤图

**目录结构示例**:

```
backtest_output/
└── sar_snt3_v3/
    └── 20260817/
        └── 054812/
            └── BTCUSDT/
                ├── backtest_signals.csv
                ├── backtest_equity.csv
                ├── backtest_trades.csv
                ├── backtest_result.json
                ├── backtest_report.txt
                ├── backtest_analysis_report.md
                ├── config.yaml
                └── charts/
                    ├── backtest_equity_curve.png
                    └── backtest_drawdown.png
```

### 3.2 批量回测执行器

```bash
python3 -m backtest.batch_runner
```

**说明**: 按 `config/strategies.yaml` 登记的 `策略 × symbol` 并发执行回测任务
（也可用 `--run` 显式指定清单）。**建议日常直接用
`./scripts/run_backtest_batch.sh` 包装脚本**（见 [9.1](#91-批量回测多策略--多代币)），
它负责笛卡尔积/登记表展开与 overrides 预检，最终转调本模块。

**配置结构（三层模型）**:

| 配置文件 | 内容 |
|----------|------|
| `config/strategies.yaml` | 编排层：跑哪些策略、symbols、trading_mode（**实盘回测共用**） |
| `strategies/<name>/overrides/<SYM>.yaml` | 策略层：per-symbol 参数（**唯一事实来源**） |
| `config/backtest.yaml` | run-profile：start、end、data_dir、output_dir、max_workers |

**参数**:

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--config` | 否 | `config/strategies.yaml` | 策略登记表路径 |
| `--run` | 否 | 无 | 显式清单 `name:symbol,...`，优先于 `--config`；缺 overrides 报错 |
| `--profile` | 否 | `backtest` | run-profile 名 |
| `--start` | 否 | profile 中的值 | 回测开始时间（覆盖 profile） |
| `--end` | 否 | profile 中的值 | 回测结束时间（覆盖 profile） |
| `--daemon` | 否 | 否 | 后台运行模式 |
| `--log-level` | 否 | 跟 profile | 日志级别，透传给每个子进程 |
| `--batch-id` | 否 | 自动生成 | 批次 ID（内部使用） |

**配置文件示例**:

```yaml
# config/strategies.yaml - 编排层（实盘/回测共用）
strategies:
  sar_snt3_v3:
    trading_mode: "smoking"
    # config_dir 默认 strategies，per-symbol 在 strategies/<name>/overrides/
    symbols:
      - BTCUSDT
      - ETHUSDT
      - name: SOLUSDT        # symbol 级别覆盖 trading_mode
        trading_mode: "paper_trading"
```

`interval` 和 `version` 从 `strategies/<name>/overrides/<SYMBOL>.yaml` 自动读取，
不在编排层重复声明。

```yaml
# config/backtest.yaml - run-profile（回测专有参数，键与 settings.yaml 不相交）
start: "20260928"
end: ""                  # 留空则用当前时间
cash: 5000
commission: 0.0004       # 币安合约 taker 0.04%
data_dir: "./data/klines"  # 必须与 settings.yaml 的 csv_dir 一致，启动时校验
output_dir: "./backtest_output"
use_today_as_output_date: true
log_level: "DEBUG"
max_workers: 4
```

profile 只写有代码消费的键；"回测不下单"由回测链路本身保证
（回测不初始化直连执行器），无需也不应在此写开关。注意回测**确实**读
`config/settings.yaml` 的顶层 `use_bar_high_low_for_exit`（影响止损判定）。

**示例**:

```bash
# 默认：config/strategies.yaml + config/backtest.yaml
python3 -m backtest.batch_runner

# 覆盖时间范围
python3 -m backtest.batch_runner --start 20260610 --end 20260708

# 用自定义 profile（复制 config/backtest.yaml 改参数）
python3 -m backtest.batch_runner --profile myrun

# 只跑部分标的（不改登记表），格式同实盘 --run，逗号分隔多个 name:symbol
python3 -m backtest.batch_runner --run sar_snt3_v3:BTCUSDT,sar_snt3_v3:ETHUSDT

# 后台运行
python3 -m backtest.batch_runner --daemon
```

**输出示例**:

```json
{
  "total": 3,
  "results": [
    {"task": {...}, "status": "success", "return_code": 0},
    {"task": {...}, "status": "success", "return_code": 0},
    {"task": {...}, "status": "failed", "return_code": 1}
  ]
}
```

### 3.3 每日定时回测

```bash
python3 backtest/daily_backtest.py
```

**说明**: 每日定时回测脚本，thin wrapper around `batch_runner.py`。自动计算日期范围（UTC 时间），适合配置在 Crontab 中。

**参数**:

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--yesterday` | 否 | - | 回测昨天 |
| `--days N` | 否 | - | 回测最近 N 天（滚动窗口模式） |
| `--start YYYYMMDD` | 否 | 今天 | 开始日期 |
| `--end YYYYMMDD` | 否 | 今天 | 结束日期 |
| `--config` | 否 | - | 透传给 `batch_runner.py` |
| `--log-level` | 否 | - | 透传给 `batch_runner.py` |
| 其他参数 | 否 | - | 透传给 `batch_runner.py`（如 `--profile`、`--help`） |

**日期模式**（优先级：`--start` > `--yesterday` > `--days` > 默认当天）:

| 模式 | 示例 | 说明 |
|------|------|------|
| 默认 | `python3 backtest/daily_backtest.py` | 回测当天（UTC） |
| `--yesterday` | `python3 backtest/daily_backtest.py --yesterday` | 回测昨天 |
| `--days N` | `python3 backtest/daily_backtest.py --days 30` | 回测最近 N 天 |
| `--start/--end` | `python3 backtest/daily_backtest.py --start 20260612 --end 20260612` | 指定日期范围 |

**示例**:

```bash
# 回测当天
python3 backtest/daily_backtest.py

# 回测昨天
python3 backtest/daily_backtest.py --yesterday

# 回测最近 30 天（滚动窗口）
python3 backtest/daily_backtest.py --days 30

```bash
# 回测指定日期
python3 backtest/daily_backtest.py --start 20260612 --end 20260612

# 指定配置和日志级别
python3 backtest/daily_backtest.py --start 20260612 --config config/strategies.yaml --log-level DEBUG
# 查看帮助（透传给 batch_runner）
python3 backtest/daily_backtest.py --help
```

---

## 4. 测试工具

### 4.1 运行单元测试

```bash
# 运行所有测试
python3 -m pytest tests/

# 按模块运行
python3 -m pytest backtest/tests/ -v          # 回测框架
python3 -m pytest data_manager/tests/ -v      # 数据管理器
python3 -m pytest strategy_core/tests/ -v     # 策略核心

# 运行特定测试
python3 -m pytest tests/test_parallel_execution.py -v

# 运行并生成覆盖率报告
python3 -m pytest --cov=. --cov-report=html
```

**测试目录**:

| 目录 | 覆盖范围 |
|------|----------|
| `tests/` | 集成测试（管理器、子进程环境、并行执行） |
| `backtest/tests/` | 回测框架（配置加载、批量执行、桥接层） |
| `data_manager/tests/` | 数据层（加载、聚合、缓存、WS） |
| `strategy_core/tests/` | 策略核心（基类、信号格式、状态） |

---

## 5. 脚本执行流程

### 5.1 典型工作流程

```
1. 下载历史数据（大周期由回测自动聚合，无需重采样）
   python3 scripts/download_data.py --symbol BTCUSDT,ETHUSDT --interval 1m --days 40

2. 批量回测（overrides 缺失会预检拒绝）
   ./scripts/run_backtest_batch.sh --strategies sar_snt3_v3 --symbols BTCUSDT,ETHUSDT \
       --start 20260610 --end 20260708

3. 查看结果
   ls -t backtest_output/sar_snt3_v3/$(date +%Y%m%d)/ | head -1

4. 启动实盘/模拟盘
   ./scripts/run_live_batch.sh --strategies sar_snt3_v3 --symbols BTCUSDT --daemon

5. 停止
   ./stop.sh
```

### 5.2 数据流向

```
Binance 公共 fapi + 归档（data.binance.vision）
         ↓
scripts/download_data.py
  ├─ CLI（人工前置备料：--symbol/--days）
  └─ download_range()  ←──────────┐  回测发现缺口时自动调用
         ↓                        │
./data/klines/{INTERVAL}/{SYMBOL}_{INTERVAL}.csv
         ↓                        │
    ┌────┴────────────────────────┼───┐
    ↓                             │   ↓
backtest.run_backtest ────────────┘  run_strategies_manager.py
（backtrader 驱动）                        ↓
    ↓                              run_strategy.py（每策略独立进程）
./backtest_output/...                     ↓
                                   ./data/signals/{STRATEGY_ID}/{DATE}.csv
                                          ↓
                                   signal hub（可选）
                                          ↓
                                   下游交易系统（读取信号并执行）
```

回测启动时校验 1m 数据覆盖 `[warm-up 起点, 回测结束]`：
- 缺头部（warm-up 不足）或缺尾部 → 自动调 `download_range()` 只补缺失的子区间
- 补齐后仍不覆盖 → **exit 1**，打印「需要 / 实有 / 缺口天数」与手动补数命令。
  不覆盖时硬失败而非继续：跑出来的会是「处理 K 线数：0」的零成交报告，
  看起来像"策略没信号"，实则窗口内一根数据都没有。
- 中部空洞不阻断（交易所停机属常态），由 data_manager 的连续性扫描负责。

回测与实盘**读同一份 CSV**（`./data/klines/`），走同一个 `on_kline()`，
只在成交与信号推送环节分叉。

---

## 6. 环境变量

全部环境变量都是**可选**的——单体模式直连 Binance 公共源，本地开发/回测
无需配置任何环境变量。

来源：`.env.example`（复制为 `.env` 后填写）。

| 变量 | 必填 | 说明 | 示例 |
|------|------|------|------|
| `DATA_PATH` | 否 | 按日 ZIP 原始数据根目录 | `./data` |
| `LOG_LEVEL` | 否 | 日志级别，由管理器传给子进程 | `INFO` |
| `HTTPS_PROXY` / `HTTP_PROXY` | 否 | 代理地址，国内网络访问 Binance 公共源时需要；注意 websockets 对 `ws://` 回环地址会显式绕过代理 | `http://<host>:<port>` |
| `BINANCE_API_KEY` / `BINANCE_API_SECRET` | 直连下单时必填 | 只放 `.env`，配置文件不出现（详见 direct_trading 配置） | — |

（历史上的 `KLINES_WS_URL` / `KLINES_HTTP_URL` / `FACTORY_ENDPOINT` /
`POSITION_PROXY_URL` / `SIGNAL_HUB_ENDPOINT` 已随单体化移除：
K 线直连 Binance 公共源，下单走交易所直连，无外部服务。）

---

## 7. 日志目录结构

### 7.1 目录结构

```
logs/
├── {YYYY-MM-DD}/
│   └── strategies_runtime.log                 # 实盘主进程（manager）
│
├── strategies/                                # 实盘策略子进程
│   └── {YYYY-MM-DD}/
│       └── SARSNT3_8H_3_BTCUSDT_PAPER.log
│
└── backtest/                                  # 回测
    └── {YYYY-MM-DD}/
        ├── batch_runner.log                       # 批量回测主日志
        └── SARSNT3_8H_3_BTCUSDT_BACKTEST.log      # 单策略回测日志
```

注意主进程与策略子进程的日期层级位置不同：主进程是 `logs/{DATE}/`，
子进程是 `logs/strategies/{DATE}/`。

### 7.2 日志命名格式

| 模式 | 格式 | 示例 |
|------|------|------|
| 实盘 | `{PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}_LIVE` | `SARSNT3_8H_3_BTCUSDT_LIVE.log` |
| 模拟盘 | `{PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}_PAPER` | `SARSNT3_8H_3_ETHUSDT_PAPER.log` |
| 回测 | `{PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}_BACKTEST` | `SARSNT3_8H_3_BTCUSDT_BACKTEST.log` |

命名由 `strategy_core/utils/strategy_naming.py` 的
`build_strategy_id_from_overrides()` 生成，回测与实盘共用同一函数。

### 7.3 查看日志

```bash
# 实盘主进程
tail -f logs/$(date -u +%Y-%m-%d)/strategies_runtime.log

# 实盘策略子进程（注意 strategies 在日期之前）
tail -f logs/strategies/$(date -u +%Y-%m-%d)/*.log

# 回测主进程
tail -f logs/backtest/$(date -u +%Y-%m-%d)/batch_runner.log

# 回测单策略
tail -f logs/backtest/$(date -u +%Y-%m-%d)/SARSNT3_8H_3_BTCUSDT_BACKTEST.log
```

---

## 8. 退出码

| 退出码 | 说明 |
|--------|------|
| `0` | 成功执行 |
| `1` | 失败（参数错误、配置缺失、profile 不存在、数据不足等） |

各脚本目前只区分成功/失败两种状态，未细分错误类别。

---

## 9. 辅助脚本（scripts/ 目录）

重采样脚本见 [2.2](#22-重采样-1m-到多时间框架)，数据下载见 [2.1](#21-下载-k-线数据)。

### 9.1 批量回测（多策略 × 多代币）

**方式 A：登记表（多策略各配不同代币，推荐）**

笛卡尔积表达不了"策略 A 跑 2 个币、策略 B 跑 5 个币"，这种情况用登记表。
格式与 `config/strategies.yaml` 一致，实盘/回测共用同一份清单：

```yaml
# my_backtest.yaml
strategies:
  sar_snt3_v3:
    trading_mode: "paper_trading"
    symbols: [BTCUSDT, ETHUSDT]

  obv_atr_v2:                      # 示例占位：实际使用时替换为已实现的策略目录名
    trading_mode: "paper_trading"
    symbols: [SOLUSDT, XRPUSDT, DOGEUSDT]
```

```bash
./scripts/run_backtest_batch.sh --config my_backtest.yaml --start 20260610 --end 20260708
```

`symbols` 也支持对象格式，给单个币指定不同模式（symbol 级覆盖策略级）：

```yaml
    symbols:
      - name: BTCUSDT
        trading_mode: "paper_trading"
      - name: ETHUSDT
        trading_mode: "live"
```

**方式 B：笛卡尔积（同一批币试多个策略）**

```bash
# 1 策略 × 2 币 = 2 个任务
./scripts/run_backtest_batch.sh --strategies sar_snt3_v3 --symbols BTCUSDT,ETHUSDT \
    --start 20260610 --end 20260708

# 2 策略 × 3 币 = 6 个任务（第二项为示例占位，替换为实际策略名）
./scripts/run_backtest_batch.sh --strategies sar_snt3_v3,obv_atr_v2 \
    --symbols BTCUSDT,ETHUSDT,SOLUSDT --start 20260610
```

⚠️ **`--strategies` 只写策略名**（`sar_snt3_v3`），Python 侧才是 `name:symbol`。
两种模式互斥，同时指定会报错。任务数 > 6 时会交互式确认，CI 用 `--yes` 跳过。

**参数**: `--config`（登记表）或 `--strategies` + `--symbols`（笛卡尔积），
`--start` 必需；`--end` / `--profile` / `--log-level` / `--daemon` / `--yes` 可选。

### 9.2 批量实盘（多策略 × 多代币）

```bash
# 方式 A：登记表（注意实盘用 --registry，因 --config 已被系统配置占用）
./scripts/run_live_batch.sh --registry my_live.yaml --daemon

# 方式 B：笛卡尔积，前台运行（Ctrl-C 停止）
./scripts/run_live_batch.sh --strategies sar_snt3_v3 --symbols BTCUSDT,ETHUSDT

# 停止（两种模式、前台后台都通用）
./stop.sh
```

> ⚠️ **运行模式默认是 live**：**未声明 `trading_mode` 时默认为 `live`（真实资金下单）**。
> 两种模式的来源不同，与 Python 侧一致：
> - `--registry` → 取自登记表（symbol 级覆盖策略级）
> - `--strategies`/`--symbols` → 取自 `strategies/<name>/overrides/<SYMBOL>.yaml`
>
> 脚本启动前会逐个解析并展示模式，含 live 实例时需**手动输入 `live`** 确认。
> `--yes` 会跳过这道确认。

### 9.3 一键启停

根目录的 `start.sh` / `stop.sh` 按 `config/strategies.yaml` 登记表启停：

```bash
./start.sh                    # 按登记表启动（长期固定清单）
./start.sh --dev              # DEBUG 日志
./stop.sh                     # 停止（对任意方式启动的进程都通用）
```

与 9.2 的分工：

| 场景 | 用哪个 |
|---|---|
| 跑 `config/strategies.yaml` 登记表 | `./start.sh` |
| 命令行临时指定策略 × 代币 | `./scripts/run_live_batch.sh` |
| 自定义登记表文件 | `./scripts/run_live_batch.sh --registry 表.yaml` |
| 停止 | `./stop.sh` |

三者共用同一个 PID 文件（`cta_strategy_core.pid`），所以 `stop.sh` 通用；
也因此**不能同时运行** —— 后启动的会先停掉前一个。

### 9.4 设计边界

两个批量脚本只做**参数展开 + 前置校验 + 转调**：

| 职责 | 归属 |
|---|---|
| 笛卡尔积展开、代币转大写、组合去重 | shell |
| overrides 存在性预检、trading_mode 展示与警示 | shell |
| 登记表解析（两种 symbols 格式、模式优先级） | `StrategiesLoader` |
| 并发调度、结果汇总、退出码判定 | `backtest/batch_runner.py` |
| 策略进程编排 | `run_strategies_manager.py` |

执行逻辑与 YAML 解析都不在 shell 里重复实现 —— 否则会与 Python 侧形成两套语义，
即配置分叉。展开逻辑的测试见 `scripts/tests/test_batch_scripts.py`。

**overrides 缺失即拒绝启动**：显式运行清单在下游是缺配置直接报错而非跳过，
笛卡尔积又容易生成不存在的组合，故在启动前一次性列出全部缺失项。

### 9.5 测试

```bash
python3 -m pytest scripts/tests/ -v          # 脚本自身测试（展开逻辑、依赖声明对账、下载器）
python3 -m pytest strategy_core/tests/ -v    # 框架测试
bash -n scripts/*.sh scripts/lib/*.sh        # shell 语法检查
```

---

## 10. 历史仓位记录

### 10.1 自动记录

每次平仓时自动记录历史仓位信息到 CSV 文件。

**存储位置**: `data/history_positions/{strategy_name}/{YYYYMMDD}.csv`

**CSV 字段**:

| 字段 | 类型 | 说明 |
|------|------|------|
| position_id | str | 仓位唯一标识 |
| strategy_name | str | 策略名称 |
| symbol | str | 交易标的 |
| position_type | str | 'long' / 'short' |
| entry_price | float | 开仓价格 |
| exit_price | float | 平仓价格 |
| entry_time | datetime | 开仓时间 |
| exit_time | datetime | 平仓时间 |
| entry_timestamp | int | 开仓时间戳（秒） |
| exit_timestamp | int | 平仓时间戳（秒） |
| peak_price | float | 持仓期间最高/最低价 |
| stop_price | float | 止损价格 |
| exit_reason | str | 平仓原因 |
| is_stop_loss | bool | 是否止损 |
| pnl | float | 盈亏金额 |
| pnl_pct | float | 盈亏百分比 |
| atr_at_entry | float | 入场时 ATR |
| trail_activated | bool | 是否触发移动止盈 |
| duration_seconds | int | 持仓时长（秒） |

**触发条件**: 仅实盘模式，平仓时自动记录

**实现位置**: `strategy_core/history_position_logger.py`

---

## 11. 相关文件

- [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) - 系统概览
- [ARCHITECTURE.md](../ARCHITECTURE.md) - 架构文档
- [CONFIG_UNIFICATION_SPEC.md](CONFIG_UNIFICATION_SPEC.md) - 配置收敛规范（三层模型）
- [SIGNAL_CSV_FORMAT.md](SIGNAL_CSV_FORMAT.md) - 信号 CSV 字段定义
