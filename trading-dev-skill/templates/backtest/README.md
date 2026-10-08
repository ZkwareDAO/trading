# CTA 策略回测框架

基于 `backtrader` 驱动**真实策略代码**——回测与实盘跑同一个 `BaseStrategy.on_kline()`，
读同一份策略参数（`strategies/<name>/overrides/<SYM>.yaml`）。这是"回测结果可信"的前提。

## 架构

```
backtest/
├── run_backtest.py         # 回测入口 CLI（8 个参数）
├── bt_strategy.py          # backtrader ↔ CTA 策略桥接层（模拟 WS 推送）
├── signal_mapper.py        # Signal → buy/sell/close 映射
├── batch_runner.py         # 批量回测执行器（subprocess 并发）
├── backtest_reporter.py    # 报告生成 (CSV/TXT/JSON)
├── analyzer.py             # 回测分析器（权益曲线、回撤、图表）
├── config_loader.py        # 配置加载（load_main_config / parse_date / merge）
├── backtest_resample.py    # 数据重采样
├── chart_generator.py      # 图表生成
└── tests/                  # 单元测试
```

**桥接原理**：`BacktestBTStrategy` 每根 1m bar 调用
`data_manager._on_kline_received(kline)` 模拟实盘 WS 推送，再调 `strategy.on_kline()`。
策略代码完全不知道自己在回测中——不存在"回测专用分支"。

## 快速开始

### 前置条件

```bash
pip install -r requirements.txt   # 含 backtrader、TA-Lib
```

仓库自带 30 天 BTCUSDT 示例数据（`data/klines/1m/BTCUSDT_1m.csv`），可直接跑。

### 单次回测

```bash
python -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260610 --end 20260708
```

回测**不依赖任何外部服务**——回测链路不初始化任何交易所客户端（由代码保证，非配置开关）。

### CLI 参数（7 个）

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--strategies` | 是 | - | 运行清单 `name:symbol`，格式与实盘 `--run` 一致；symbol 唯一来源 |
| `--start` | 是 | - | 开始日期（YYYYMMDD / 秒 / 毫秒时间戳） |
| `--end` | 否 | 当前时间 | 结束日期，覆盖 `profile.end` |
| `--profile` | 否 | `backtest` | run-profile，读 `config/<name>.yaml` |
| `--config-path` | 否 | 按 overrides 推导 | 策略配置完整路径，与实盘同名参数一致 |
| `--overrides` | 否 | - | 字段覆盖（JSON 字符串） |
| `--log-level` | 否 | 跟 profile | DEBUG/INFO/WARNING/ERROR |

单次回测**只跑一个 `name:symbol`**，多个请用 `batch_runner`。

**已删除的参数**（v3.7 配置收敛）：`--strategy`、`--config`、`--symbol`、`--timeframe`、
`--data-dir`、`--output-dir`、`--cash`、`--commission`、
`--use-today-as-output-date`、`--use-end-date-as-output-date`。

这些不是"简化掉了"，而是**移到了它们该在的层**：

| 原 CLI 参数 | 现在从哪读 |
|-------------|-----------|
| `--timeframe` `--data-dir` `--output-dir` `--cash` `--commission` 输出日期模式 | `config/backtest.yaml` |
| `--strategy` `--config` | `--strategies name:symbol` → `strategies/<name>/overrides/<SYM>.yaml` |

理由：策略参数（周期 / 资金 / 风控 / 交易所）由 CLI 覆盖，就等于回测与实盘读两份
不同的参数——那是**回测失真**，性质等同未来函数。详见
[docs/CONFIG_UNIFICATION_SPEC.md](../docs/CONFIG_UNIFICATION_SPEC.md)。

### run-profile

`config/backtest.yaml` 只承载**回测的运行方式**。

回测读**两份**配置：`config/settings.yaml`（与实盘共用，提供
`use_bar_high_low_for_exit` —— 决定止损止盈用 K 线 high/low 还是收盘价判定，
影响成交次数与 PnL）+ 本文件。两者键集合不相交，无覆盖关系：

```yaml
start: "20260601"
end: ""
cash: 5000
commission: 0.0004      # 币安合约 taker 0.04%
data_dir: "./data/klines"   # 必须与 settings.yaml 的 csv_dir 一致，启动时校验
output_dir: "./backtest_output"
use_today_as_output_date: true
log_level: "INFO"
max_workers: 4
```

以上 9 个键**全部有代码消费**。profile 里不写没人读的"说明性配置" ——
早期版本曾写 `mode: backtest` 与 `signal_hub.enabled: false` /
但回测不初始化推送与下单客户端，
"回测不推信号"由链路本身保证，那三个键从未生效，
反而与 `settings.yaml`（其中 `signal_hub.enabled: true`）形成"两处不同值"的假象，
已删除。

### `--profile`：参数集存档（可选）

`--profile` 默认 `backtest`，即读 `config/backtest.yaml`。**日常回测不需要传这个参数**：

```bash
# 这两条命令完全等价
python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260610
python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260610 --profile backtest
```

它的用途是**换一套参数而不改动入库文件**。调参是量化开发的日常（试不同初始资金、
手续费口径、并发数），但直接改 `config/backtest.yaml` 有两个问题：容易误提交，
以及"上次那轮跑的什么参数"不可追溯。一个 profile 文件 = 一套有名字、可存档、
可复现的参数集：

```bash
cp config/quick.example.yaml config/myrun.yaml   # 改 cash / commission / max_workers
python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT \
  --start 20260610 --end 20260708 --profile myrun
```

`config/quick.example.yaml` 是可直接使用的示例（`cash=100000`、`commission=0.001`）。

约束：profile 名不能是 `settings` / `strategies`（那是系统层与编排层配置，
结构完全不同，会被 `load_profile` 拦截并报错），也不能含路径分隔符。

## 数据准备

### 目录结构

```
data/klines/
├── 1m/
│   └── BTCUSDT_1m.csv    # 必须有（大周期的聚合源）
├── 15m/                   # 自动从 1m 聚合并保存
├── 1h/                    # 自动从 1m 聚合并保存
└── 4h/                    # 自动从 1m 聚合并保存
```

`data_dir` 由 `config/backtest.yaml` 指定，与实盘 `config/settings.yaml` 的
`csv_dir` 指向同一路径——回测与实盘读同一份数据。

CSV 格式：

```
timestamp,open,high,low,close,volume,quote_volume,count,taker_buy_volume,taker_buy_quote_volume
2026-06-10 00:00:00+00:00,77000.0,77100.0,76900.0,77050.0,100.0,...
```

### 下载数据

```bash
# Binance 公共 API，无需 API key
python scripts/download_data.py --symbol ETHUSDT --interval 1m --days 30

# 国内网络配代理
HTTPS_PROXY=http://<host>:<port> python scripts/download_data.py --symbol ETHUSDT --interval 1m --days 30
```

**自动保存大周期 CSV**：回测中聚合出的 15m/1h/4h 会自动写回对应目录，下次直接复用。
注意这会让 1m CSV 被补齐缺口后**行数变化**，属预期行为。

数据量参考：30 天 1m ≈ 43,200 条 / 15m ≈ 2,880 条 / 4h ≈ 180 条。

## 输出结果

输出到 `backtest_output/<策略名>/<日期>/<时刻>/<SYMBOL>/`：

| 文件 | 格式 | 内容 |
|------|------|------|
| `backtest_report.txt` | 文本 | 可读摘要（盈亏、回撤、交易次数） |
| `backtest_result.json` | JSON | 完整指标（可编程读取） |
| `backtest_analysis_report.md` | Markdown | 分析报告 |
| `backtest_equity.csv` | CSV | 权益曲线（每 bar 一个数据点） |
| `backtest_trades.csv` | CSV | 交易明细 |
| `backtest_signals.csv` | CSV | 信号明细（时间、类型、价格、强度） |
| `charts/*.png` | 图表 | 权益曲线与回撤图 |
| `config.yaml` | YAML | 本次回测实际生效的策略配置（供复现） |

`config.yaml` 是复现的关键——它是本次实际读取的 `overrides/<SYM>.yaml` 副本。

## 回测流程

```
1. 加载 run-profile (config/backtest.yaml)
   ↓
2. 加载策略配置 (strategies/<name>/overrides/<SYM>.yaml)
   ↓
3. 创建 DataManager (回测模式：禁用 WS，启用 backtest_timestamp 过滤)
   ↓
4. 预加载全部 1m CSV 到缓存 + 预聚合大周期
   ↓
5. 实例化真实策略 (与实盘同一个类)
   ↓
6. 创建 backtrader Cerebro 引擎，加载 1m PandasData
   ↓
7. 每个 bar:
   - set_backtest_timestamp(ts)        → 设置"当前时间"，屏蔽未来数据
   - _on_kline_received(kline)         → 模拟实盘 WS 推送
   - strategy.on_kline()               → 返回 Signal → 映射为订单
   ↓
8. 提取分析器指标 (DrawDown / TradeAnalyzer / SharpeRatio)
   ↓
9. 生成报告 (TXT + JSON + CSV + PNG)
```

`backtest_timestamp` 是防未来函数的物理机制：任何 `get_closed_data()` 调用都
只能看到 ≤ 当前 bar 时间的已闭合 K 线。

## 成交模型的简化（必读）

回测结果**乐观于实盘**，已知简化项：

| 简化 | 影响 |
|------|------|
| 无滑点 | 实盘成交价差于回测 |
| 按信号价成交 | 实盘按下一 bar 开盘或盘口成交 |
| 假设流动性充足 | 大单实盘会打穿盘口 |
| 固定 taker 费率 0.04% | 未区分 maker/taker、未计资金费率 |
| 期末权益含浮动盈亏 | 未平仓头寸按最后价计入 |

评估策略时请把这些当作**已知偏差**，不要把回测收益当预期收益。

## 批量回测

`batch_runner.py` 按 `config/strategies.yaml`（**与实盘共用的编排层**）
并发执行多个 `策略 × symbol` 任务。

```bash
# 用 profile 中的时间范围
python3 -m backtest.batch_runner

# CLI 覆盖时间
python3 -m backtest.batch_runner --start 20260610 --end 20260708

# 后台运行
python3 -m backtest.batch_runner --daemon
```

### 只跑部分标的：`--run`

不想改 `config/strategies.yaml`（那是实盘共用的登记表）时，用 `--run` 直接给清单，
格式与实盘 `run_strategies_manager.py --run` 完全一致：

```bash
# 多标的
python3 -m backtest.batch_runner --run sar_snt3_v3:BTCUSDT,sar_snt3_v3:ETHUSDT

# 多策略多标的
python3 -m backtest.batch_runner --run sar_snt3_v3:BTCUSDT,sar_snt3_v3:ETHUSDT
```

`--run` 优先于 `--config` 登记表。symbol 小写自动转大写。

**与登记表路径的一处刻意差异** —— overrides 文件缺失时：

| 来源 | 缺文件 | 为什么 |
|------|--------|--------|
| `--config` 登记表 | warn + 跳过 | 长期清单，个别标的没配好不该阻断整批 |
| `--run` 清单 | **报错退出** | 既然点名指定，静默跳过等于给出一份不完整的结果却不告知 |

三个入口的清单协议是同一个（共用 `parse_explicit_strategies`）：

| 入口 | 参数 | 数量 |
|------|------|------|
| `run_strategies_manager.py` | `--run` | 不限 |
| `backtest.batch_runner` | `--run` | 不限 |
| `backtest.run_backtest` | `--strategies` | **仅 1 个**（多个请用 batch_runner） |

### CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--config` | `config/strategies.yaml` | 策略登记表（与实盘共用） |
| `--run` | 无 | 显式清单 `name:symbol,...`，优先于 `--config` |
| `--profile` | `backtest` | run-profile，读 `config/<name>.yaml` |
| `--start` | profile 中的值 | 覆盖开始时间 |
| `--end` | profile 中的值 | 覆盖结束时间 |
| `--daemon` | `False` | 后台运行模式 |
| `--batch-id` | 自动生成 | 批次 ID（内部使用） |

时间格式：`20260610`（YYYYMMDD）/ `1735689600`（秒）/ `1735689600000`（毫秒）。

### 编排层格式

`config/strategies.yaml` —— 回测与实盘读的是同一个文件：

```yaml
strategies:
  sar_snt3_v3:
    trading_mode: "live"
    symbols:
      - BTCUSDT
      - ETHUSDT
```

策略参数不写在这里，只声明"跑什么"。参数从
`strategies/sar_snt3_v3/overrides/BTCUSDT.yaml` 读取——回测与实盘同一份。

并发数从 `config/backtest.yaml` 的 `max_workers` 读取。

### 定时批量

```bash
# 每天回测最近 30 天
python3 -m backtest.batch_runner --start $(date -d "-30 days" +%Y%m%d) --end $(date +%Y%m%d)
```

## 常见问题

### 未找到 CSV 数据文件

```
ERROR: 未找到 CSV 数据文件: data/klines/1m/BTCUSDT_1m.csv
```

用 `python scripts/download_data.py --symbol BTCUSDT --interval 1m --days 30` 下载，
或确认 `config/backtest.yaml` 的 `data_dir` 指向了实际数据目录。

### profile 文件不存在

```
ERROR: 无法加载 profile: xxx（config/xxx.yaml 不存在）
```

`--profile` 传的名字要对应 `config/<name>.yaml`。默认 `backtest`。

### 回测速度慢

1. **降日志级别**：`--log-level WARNING` 显著减少高频 IO
2. **缩短回测周期**：先短周期验逻辑，再长周期验稳定性
3. 回测已内置预加载与跳过冗余缓存更新，1m 数据量大时（>100 万条）仍会较慢

### 信号太少

- 多周期策略依赖大周期结构，短窗口内信号稀疏，建议至少 60-90 天数据
- 调低 `overrides/<SYM>.yaml` 中 `signal.min_strength` 阈值
- 检查 `direction`：`neutral` 允许多空 / `bullish` 只做多 / `bearish` 只做空

### backtrader 未安装

```bash
pip install backtrader
```

## 相关文档

- [配置统一规范](../docs/CONFIG_UNIFICATION_SPEC.md) —— 三层模型与收敛理由
- [策略开发指南](../docs/strategy/DEVELOPMENT_GUIDE.md)
- [AI 编码约束](../docs/strategy/AI_CONSTRAINTS.md) —— 含防未来函数红线
