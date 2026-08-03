# CTA 策略回测框架

基于 `backtrader` + 真实 CTA 策略。

## 架构

```
backtest/
├── run_backtest.py        # 回测入口 CLI
├── bt_strategy.py          # backtrader ↔ CTA 策略桥接层
├── signal_mapper.py        # Signal → buy/sell/close 映射
├── batch_runner.py         # 批量回测执行器（subprocess 并发）
├── backtest_reporter.py    # 报告生成 (CSV/TXT/JSON)
├── analyzer.py             # 回测分析器（权益曲线、回撤、图表）
├── config_loader.py        # 回测配置加载
├── backtest_resample.py    # 数据重采样
├── chart_generator.py      # 图表生成
└── tests/                  # 单元测试
```

## 快速开始

### 前置条件

```bash
pip install backtrader
```

### 单次回测

```bash
# 通用格式
python -m backtest.run_backtest \
  --strategy <策略简称> \
  --start <开始日期 YYYYMMDD> \
  --end <结束日期 YYYYMMDD> \
  --symbol <交易对> \
  [--timeframe <K线周期>] \
  [--data-dir <数据目录>] \
  [--output-dir <输出目录>] \
  [--cash <初始资金>] \
  [--commission <手续费率>] \
  [--log-level <日志级别>] \
  [--config <配置文件路径>]

# 各策略示例
python -m backtest.run_backtest --strategy rbreaker --start 20260101 --end 20260331 --symbol btcusdt
python -m backtest.run_backtest --strategy trend --start 20260101 --end 20260331 --symbol btcusdt
python -m backtest.run_backtest --strategy ict --start 20260101 --end 20260331 --symbol btcusdt
python -m backtest.run_backtest --strategy trend_strength --start 20260101 --end 20260331 --symbol btcusdt

# 性能优化：使用 WARNING 日志级别减少 IO 开销
python -m backtest.run_backtest --strategy obv --start 20260501 --end 20260514 --symbol ETHUSDT --log-level WARNING
```

### 参数说明

| 参数 | 必填 | 默认值 | 说明 |
|------|------|--------|------|
| `--strategy` | 是 | - | 策略简称或完整目录名 |
| `--start` | 是 | - | 开始日期（YYYYMMDD） |
| `--end` | 否 | 当前时间 | 结束日期（YYYYMMDD） |
| `--symbol` | 否 | BTCUSDT | 交易对，支持逗号分隔多个 |
| `--timeframe` | 否 | 1m | K 线周期（回测强制使用 1m） |
| `--data-dir` | 否 | ./data/strategies | K 线数据目录 |
| `--output-dir` | 否 | ./backtest_output | 回测输出目录 |
| `--cash` | 否 | 100000 | 初始资金 |
| `--commission` | 否 | 0.0 | 手续费率 |
| `--log-level` | 否 | INFO | 日志级别（DEBUG/INFO/WARNING/ERROR） |
| `--config` | 否 | strategies/{strategy}/config.test.yaml | 策略配置文件路径 |

### 策略简称映射

| 简称 | 策略目录 | 时间框架 |
|------|----------|----------|
| `rbreaker` | `cta_rbreaker_v3` | 15m |
| `trend` | `cta_trend` | 15m |
| `ict` | `cta_ict_v3` | 1d, 4h, 15m |
| `trend_strength` | `cta_trend_strength` | 1d, 4h, 15m |
| `dolphin` | `dolphin_trading_v2` | 4h, 1h, 15m |
| `obv` | `obv_atr_v2` | 4h, 1h |

## 数据准备

### 1. 准备 K 线数据

回测需要 1m 精度的 CSV 数据。数据来源：

**方式 A：使用 klines_service（本地服务）**

确保 `http://127.0.0.1:17081` 正在运行。

**方式 B：手动放置 CSV 文件**

CSV 文件放在 `data/strategies/<策略名>/1m/` 目录下，格式：

```
timestamp,open,high,low,close,volume,quote_volume,count,taker_buy_volume,taker_buy_quote_volume
2026-04-01 00:00:00+00:00,77000.0,77100.0,76900.0,77050.0,100.0,...
```

### 2. ICT 策略特殊要求

ICT 策略需要多时间框架数据，会自动从 1m 聚合：

```
data/strategies/cta_ict/
├── 1m/
│   └── BTCUSDT_1m.csv    # 必须有（聚合源）
├── 15m/                   # 自动从 1m 聚合并保存
├── 1h/                    # 自动从 1m 聚合并保存
└── 4h/                    # 自动从 1m 聚合并保存
```

**自动保存大周期 CSV**：回测完成后，聚合的 15m/4h/1d 数据会自动保存到对应目录的 CSV 文件，下次回测可直接使用，无需重新聚合。

数据量参考：
- 30 天 1m ≈ 43,200 条
- 30 天 15m ≈ 2,880 条
- 30 天 4h ≈ 180 条

## 输出结果

回测完成后在 `backtest_output/` 生成 4 个文件：

| 文件 | 格式 | 内容 |
|------|------|------|
| `*_report.txt` | 文本 | 可读摘要（盈亏、回撤、交易次数） |
| `*_result.json` | JSON | 完整指标（可编程读取） |
| `*_equity.csv` | CSV | 权益曲线（每 bar 一个数据点） |
| `*_trades.csv` | CSV | 信号明细（时间、类型、价格、强度） |

### 示例报告

```
============================================================
回测报告
============================================================

初始资金: 100000.00
最终净值: 103031.73
盈亏:     +3031.73 (+3.03%)
信号数量: 1

最大回撤: 9.52
回撤比例: 9.52%

总交易次数: 1
净盈亏: +0.00
```

## 回测流程

```
1. 加载策略配置 (config.yaml)
   ↓
2. 创建 DataManager (回测模式：禁用 WS，启用 backtest_timestamp 过滤)
   ↓
3. 预加载全部 1m CSV 数据到缓存
   ↓
4. 预聚合大周期数据到缓存 (ict 策略需要 4h/1h/15m)
   ↓
5. 实例化策略 (StrategyClass)
   ↓
6. 创建 backtrader Cerebro 引擎
   ↓
7. 加载 CSV 数据 (1m 逐 bar 推送)
   ↓
8. 每个 bar:
   - set_backtest_timestamp(ts) → 设置当前时间
   - _on_kline_received → 跳过缓存更新（优化：数据已预加载）
   - on_kline() → 获取 Signal → 映射为订单
   ↓
9. 运行回测
   ↓
10. 提取分析器指标 (DrawDown / TradeAnalyzer / SharpeRatio)
   ↓
11. 生成报告 (TXT + JSON + CSV)
```

## 性能优化

回测框架已内置多项性能优化，保持与实盘逻辑一致：

### 1. 预加载优化

回测启动时预加载全部数据到内存缓存，避免每个 bar 重复读取 CSV。

### 2. 跳过冗余缓存更新

回测模式下 `_on_kline_received` 跳过缓存更新和大周期聚合：
- 数据已预加载到缓存
- 通过 `backtest_timestamp` 过滤实现与实盘相同效果
- 显著减少每个 bar 的 DataFrame 操作

### 3. 合并相同周期调用

策略 `analyze()` 中多个指标使用相同周期时，自动合并 `_get_closed_data` 调用。

### 4. 日志级别优化

回测模式下高频模块自动降为 WARNING 级别：
- `data_manager.manager`
- `backtest.bt_strategy`

### 推荐命令

```bash
# 使用 WARNING 日志级别获得最佳性能
python -m backtest.run_backtest --strategy obv --start 20260501 --end 20260514 --symbol ETHUSDT --log-level WARNING
```

## 自定义回测

### 修改参数

```python
from backtest.run_backtest import run_backtest

run_backtest(
    strategy_dir_name="cta_rbreaker",  # 或 cta_trend, cta_ict
    symbol="ETHUSDT",
    start_date="20260201",
    end_date="20260401",
    timeframe="1m",
    data_dir="./data/strategies/cta_rbreaker",
    output_dir="./custom_output",
    cash=50000,
    commission=0.0005,  # 更低手续费
    days=60,            # 预加载天数
)
```

### 多标的回测

回测框架当前每次只支持单个交易对。如需多标的回测，需要分别运行多次：

```bash
python -m backtest.run_backtest --strategy ict --start 20260101 --end 20260331 --symbol btcusdt
python -m backtest.run_backtest --strategy ict --start 20260101 --end 20260331 --symbol ethusdt
```

## 批量回测

`batch_runner.py` 支持并发执行多个回测任务，通过 subprocess 调用 `run_backtest.py`。

### 使用方式

```bash
# 使用配置文件中的时间范围
python3 -m backtest.batch_runner

# CLI 覆盖时间
python3 -m backtest.batch_runner --start 20260101 --end 20260331

# 后台运行
python3 -m backtest.batch_runner --daemon
```

### CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--config` | `backtest/config/strategies.yaml` | 策略配置文件路径 |
| `--backtest-config` | `backtest/config/main.yaml` | 回测参数配置文件路径 |
| `--start` | 配置文件中的值 | 覆盖开始时间（优先级高于配置文件） |
| `--end` | 配置文件中的值 | 覆盖结束时间（优先级高于配置文件） |
| `--daemon` | `False` | 后台运行模式 |
| `--status` | - | 查看运行状态（待实现） |

### 时间格式支持

| 格式 | 示例 | 说明 |
|------|------|------|
| YYYYMMDD | `20260101` | 日期格式 |
| 秒时间戳 | `1735689600` | 10 位数字 |
| 毫秒时间戳 | `1735689600000` | 13 位数字 |

### 配置文件格式

`batch_runner.py` 支持两种配置格式，**推荐使用新格式**：

#### 新格式（推荐）

配置分离为两个文件：

**`backtest/config/strategies.yaml`** - 定义策略列表：

```yaml
strategies:
  dolphin_trading_v2:
    trading_mode: "live"
    config_dir: "backtest/config"
    symbols:
      - BTCUSDT
      - ETHUSDT
      - SOLUSDT

  cta_ict_v3:
    trading_mode: "live"
    config_dir: "backtest/config"
    symbols:
      - BTCUSDT
```

**`backtest/config/main.yaml`** - 定义回测参数：

```yaml
start: "20260601"
end: "20260710"
data_dir: "./data/strategies"
output_dir: "./backtest_output"
max_workers: 15
log_level: "INFO"
use_today_as_output_date: true
```

**运行命令**：

```bash
python3 -m backtest.batch_runner
# 等同于
python3 -m backtest.batch_runner --config backtest/config/strategies.yaml --backtest-config backtest/config/main.yaml
```

#### 旧格式（完全支持）

所有配置在一个文件中，`strategies` 为列表格式。运行时需通过 `--config` 指定配置文件。

**`backtest/config/main.yaml`**：

```yaml
# 完整示例见 backtest/config/main.legacy.example.yaml
start: "20250101"
end: "20260301"
data_dir: "./data/strategies"
output_dir: "./backtest_output"
max_workers: 4
log_level: "INFO"
use_today_as_output_date: true

strategies:
  - name: cta_ict_v3
    symbols: ["BTCUSDT", "ETHUSDT"]
    enabled: true
  - name: dolphin_trading_v2
    symbols: ["BTCUSDT"]
    enabled: true
    overrides:
      signal:
        min_strength: 0.5
```

**运行命令**：

```bash
python3 -m backtest.batch_runner --config backtest/config/main.yaml
```

#### 格式自动检测

代码根据 `strategies` 字段类型自动检测格式：

| `strategies` 类型 | 格式 | 配置来源 |
|-------------------|------|----------|
| `dict`（对象） | 新格式 | 策略从 `--config`，回测参数从 `--backtest-config` |
| `list`（数组）或不存在 | 旧格式 | 所有配置从 `--config` |

#### 两种格式对比

| 特性 | 新格式 | 旧格式 |
|------|--------|--------|
| 配置分离 | 策略与回测参数分离 | 合并在一起 |
| 实盘/回测共用 | ✅ 可与 `run_strategies_manager.py` 共用 | ❌ 仅回测使用 |
| 维护性 | 高（职责分离） | 低（配置耦合） |
| 推荐度 | ⭐⭐⭐ 推荐 | 兼容保留 |

### 配置路径组合

策略配置文件路径按以下规则组合：

```
{config_dir}/{strategy_name}/{symbol}.yaml
```

示例：
- `backtest/config/dolphin_trading_v2/BTCUSDT.yaml`
- `backtest/config/cta_ict_v3/ETHUSDT.yaml`

### 示例

```bash
# 使用配置文件中的时间范围
python3 -m backtest.batch_runner

# CLI 覆盖 start（YYYYMMDD）
python3 -m backtest.batch_runner --start 20260101

# CLI 覆盖 start（时间戳）
python3 -m backtest.batch_runner --start 1735689600

# 同时覆盖 start 和 end
python3 -m backtest.batch_runner --start 20260101 --end 20260331

# 定时任务：每天回测最近 30 天
python3 -m backtest.batch_runner --start $(date -d "-30 days" +%Y%m%d) --end $(date +%Y%m%d)

# 后台运行
python3 -m backtest.batch_runner --daemon
```

## 常见问题

### 回测速度慢

回测已内置多项优化（预加载、跳过冗余更新、日志级别）。如仍需加速：

1. **使用 WARNING 日志级别**：减少高频模块的日志输出
   ```bash
   python -m backtest.run_backtest --strategy obv --start 20260501 --end 20260514 --symbol ETHUSDT --log-level WARNING
   ```

2. **缩短回测周期**：先用短周期验证策略逻辑，再用长周期验证稳定性

### 未找到 CSV 数据文件

```
ERROR: 未找到 CSV 数据文件: data/strategies/cta_ict/1m/BTCUSDT_1m.csv
```

需要先下载数据到 `data/strategies/<策略名>/1m/` 目录。确保 `klines_service` 运行中，或使用 `DataManager.batch_download_history()` 下载。

### ICT 策略信号太少

ICT 策略依赖 4h 级别的市场结构分析，短周期内信号稀少：
- 建议至少 60-90 天数据
- 可调整 `config.yaml` 中 `signal.min_strength` 降低阈值（默认 0.4）
- 检查 `direction` 配置：`neutral` 允许多空，`bullish` 只做多，`bearish` 只做空

### backtrader 未安装

```bash
pip install backtrader
# 或使用系统包管理器
pip install --break-system-packages backtrader
```
