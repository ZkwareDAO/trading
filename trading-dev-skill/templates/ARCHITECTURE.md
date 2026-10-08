# CTA Strategy Core 系统架构文档

**版本**: 3.7.0
**更新日期**: 2026-09-03

---

## 1. 系统概述

Strategy Core 是一个模块化的量化交易策略执行框架，采用**单体模式**，支持多策略并行运行。每个策略独立进程，直连 Binance 行情与下单（CCXT）。

### 1.1 核心功能

- **策略执行**: 加载并运行多个交易策略（CTA、ICT、Dolphin 等），每个策略独立进程
- **数据管理**: 从本地 CSV 文件加载 K 线数据，支持 WS 实时推送、自动同步和多时间框架聚合
- **信号生成**: 策略根据市场分析生成交易信号
- **信号持久化**: 信号自动写入 CSV 文件，单体模式下由策略进程直连交易所下单
- **仓位持久化**: 策略重启后自动恢复仓位状态

### 1.2 系统边界

| 功能 | Strategy Core |
|------|---------------|
| 策略逻辑实现 | ✅ |
| 策略启停控制 | ✅（run_strategies_manager 进程监督） |
| K 线数据获取 | ✅ (CSV/WS 直连 Binance) |
| 信号生成 | ✅ |
| 信号持久化 | ✅ (CSV) |
| 订单执行 | ✅ (direct_trading 直连下单) |

---

## 2. 架构设计

### 2.1 架构图

```
┌──────────────────────────────────────────────────────────────────────┐
│                    run_strategies_manager.py                         │
│                    (策略进程监督者)                                    │
│  - 解析 enabled 策略清单                                              │
│  - 拉起每个策略的独立子进程                                            │
│  - 监控子进程退出（不自动重启）                                         │
│  - SIGTERM/SIGINT 优雅停止                                            │
└──────────────────────────┬───────────────────────────────────────────┘
                           │ 每个策略启动独立进程
                           ▼
┌──────────────────────────────────────────────────────────────────────┐
│                       run_strategy.py (独立进程)                      │
│                                                                       │
│  ┌──────────────────┐  ┌────────────────────┐                        │
│  │ SignalLogger     │  │  BaseStrategy      │                        │
│  │ (信号日志+下单)  │  │  (策略基类)         │                        │
│  └────────┬─────────┘  └────────┬───────────┘                        │
│         │                   │                      │                   │
│  ┌──────┴───────────────────┴──────────────────────┴───────────┐      │
│  │                     DataManager                             │      │
│  │  (数据管理器 - CSV缓存 + WS实时推送 + 多时间框架聚合)         │      │
│  └────────────────────────────┬───────────────────────────────┘      │
│                               │                                       │
│  ┌────────────────────────────┴───────────────────────────────┐      │
│  │  PositionPersistence (仓位持久化)                            │      │
│  └────────────────────────────────────────────────────────────┘      │
└──────────────────────────────────────────────────────────────────────┘
                           │                    │
              ┌────────────┘                    └────────────┐
              ▼                                              ▼
    ┌─────────────────┐                          ┌─────────────────┐
    │ data/klines/    │                          │ data/signals/   │
    │ (K线 CSV 文件)  │                          │ (信号 CSV 文件)  │
    └─────────────────┘                          └─────────────────┘
```

### 2.2 核心组件

| 组件 | 类型 | 职责 |
|------|------|------|
| **strategy_core** | 核心框架 | 策略基类、信号日志与参数构建、仓位持久化 |
| **data_manager** | 独立包 | 通用数据接入层（CSV + WS + 缓存 + 聚合 + 指标计算） |
| **strategies** | 策略插件 | 具体策略逻辑实现（继承 BaseStrategy） |
| **backtest** | 回测框架 | backtrader 集成、批量回测、绩效分析、报告生成 |

### 2.3 数据流

1. **策略加载**: `run_strategies_manager.py` 从 `config/strategies.yaml` 解析 enabled 策略清单
2. **策略启动**: 每个策略由 manager 拉起为 `run_strategy.py` 独立子进程
3. **数据获取**: 策略进程内 `DataManager` 初始化，直连 Binance 公共 WS 拉实时（realtime_enabled=false 则只用本地 CSV）
4. **信号生成**: 策略 Core 的 `analyze()` / `check_realtime_exit()` 生成交易信号
5. **信号持久化**: 信号通过 `SignalLogger` 写入 CSV 存储，`direct_trading.enabled` 时本进程直连交易所下单
6. **订单执行**: 单体模式下订单直达交易所；下游系统可读信号 CSV 做对账/复盘

---

## 3. 核心模块说明

### 3.1 策略基类架构（BaseStrategy / BaseStrategyCore / BaseState）

策略采用三层基类架构，新增策略只需实现入场逻辑和出场逻辑：

```
BaseStrategy (strategy_core/base/strategy.py)
├── 通用配置解析、K 线分发、信号生成、仓位管理、冷却控制
├── 回测兼容（backtest_mode 自动判断）
└── 子类只需设置 STRATEGY_TYPE, STRATEGY_PREFIX, DEFAULT_TIMEFRAME

BaseStrategyCore (strategy_core/base/core.py)
├── 仓位回调机制（_notify_position_enter / _notify_position_exit）
├── 工具方法（方向过滤、K 线获取、平仓逻辑）
└── 子类只需实现: _get_state(), analyze(), check_realtime_exit(), get_status()

BaseState (strategy_core/base/state.py)
├── 共有状态字段（position, entry_price, peak_price, stop_price, stop_loss_date...）
├── 持久化方法（to_persist_dict / restore_from_dict）
└── 子类可添加特有字段，需重写持久化方法
```

**子类必需实现**:

| 类 | 抽象方法 | 说明 |
|----|----------|------|
| Strategy | `_create_core()` | 创建 Core 实例 |
| Strategy | `_get_indicator_timeframes()` | 返回指标周期集合 |
| Core | `_get_state(symbol)` | 获取 per-symbol 状态 |
| Core | `analyze(symbol, klines_data, current_time)` | 入场逻辑 |
| Core | `check_realtime_exit(symbol, current_price, ...)` | 出场逻辑 |
| Core | `get_status()` | 状态查询 |

**共享指标模块**: `strategy_core/base/indicators.py` 提供策略共享的指标计算（ADX、EMA 等），优先使用 TA-Lib，不可用时回退手动计算。

### 3.2 策略进程运行器（StrategyProcessRunner）

**文件**: `run_strategy.py`

单体模式下不再有独立的策略引擎/注册表：每个策略进程直接 `importlib` 加载
`strategies/<name>/strategy.py` 的 `Strategy` 类并实例化，WS K 线回调直接调用
`strategy.on_kline()`，产生的信号统一经 `_handle_signal()` 写 CSV 后直连下单
（见 §3.4）。策略进程退出由 `run_strategies_manager.py` 监控（不自动重启）。

### 3.3 Data Manager（数据管理器）

**文件**: `data_manager/manager.py`

**核心方法**（5 个）:

| 方法 | 说明 |
|------|------|
| `download_daily_data(symbol, day)` | 下载单日数据，保存 CSV |
| `batch_download_history(symbol, days)` | 批量下载 N 天历史数据 |
| `init_today_realtime(symbol)` | 初始化今日实时数据（下载+补齐+WS） |
| `manage_memory_cache(symbol)` | 管理内存缓存（行数和年龄限制） |
| `get_klines(symbol, timeframe, limit)` | 统一查询接口（增量返回） |

**辅助方法**:

| 方法 | 说明 |
|------|------|
| `connect_and_sync(symbols)` | 启动时连接+预加载+WS |
| `register_timeframes(symbol, timeframes)` | 注册时间框架 |
| `is_data_complete(symbols)` | 检查数据完整性 |
| `aggregate_1m_to_interval(df, interval)` | 从 1m 聚合到大周期 |
| `auto_load_missing_data(symbol, start, end)` | 按日期区间加载缺失数据 |

**子模块**:

| 文件 | 职责 |
|------|------|
| `kline_repository.py` | 多时间框架注册与聚合（1m→4h/1h/15m），轻量级设计只维护元数据 |
| `klines_ws_client.py` | WebSocket 实时 K 线接收（无限重连、退避上限 120s、心跳 30s） |
| `klines_loader.py` | K 线数据加载、重采样、CSV 持久化 |
| `indicators.py` | 技术指标计算（ADX, EMA, RSI, MACD, BOLL, ATR, KD, Envelope） |
| `cache.py` | 分层缓存（1m 常驻 + 大周期 LRU） |

**缓存设计**:
- 1m 数据: 常驻缓存，不淘汰（除非 manage_memory_cache 触发限制）
- 大周期: LRU 缓存，淘汰最久未使用的条目
- 大周期数据优先从 1m 缓存实时聚合，而非单独缓存

### 3.4 Signal Logging（信号日志）

**文件**: `strategy_core/signal_logging/`

**子模块**:

| 文件 | 职责 |
|------|------|
| `storage.py` | Signal 数据模型、SignalType 枚举、确定性 signal_id 生成 |
| `csv_adapter.py` | CtaSignalCSV 格式转换器（CSV/JSON 格式） |
| `signal_params.py` | `build_signal_params`：从 overrides 配置构建 CtaSignalCSV 参数（原引擎 `_build_strategy_params` 内联迁移） |
| `logger.py` | SignalStorage（CSV 存储）+ SignalLogger（统一接口） |
| `binance_trader.py` | BinanceTrader 直连下单执行器（单体模式唯一信号出口） |
| `json_exporter.py` | JSON 导出器 |

注：历史上的 `http_sender.py`（signal_hub HTTP 推送）已随单体化删除。

**信号类型**:
- `BUY` / `SELL` - 开仓信号
- `BUY_CLOSE` / `SELL_CLOSE` - 平仓信号
- `FLAT` - 平仓
- `REVERSE_LONG` / `REVERSE_SHORT` - 反手信号

**signal_id 生成规则**: 基于 `strategy_type + symbol + 1m K线时间戳 + signal_type` 的 SHA256 哈希，确保实盘与回测使用相同 K 线数据时 ID 一致。

### 3.6 Position Persistence（仓位持久化）

**文件**: `strategy_core/position_persistence.py`

**存储位置**: `data/positions/{strategy_name}.json`

**持久化时机**:
- **开仓时**: `save_on_entry()` 立即持久化
- **平仓时**: `update_state()` 更新状态 / `clear_state()` 清除文件
- **SIGTERM**: 优雅退出时保存当前仓位

### 3.7 回测框架

**文件**: `backtest/`

**核心组件**:

| 文件 | 职责 |
|------|------|
| `run_backtest.py` | 回测入口 CLI |
| `bt_strategy.py` | backtrader ↔ CTA 策略桥接层 |
| `signal_mapper.py` | Signal → buy/sell/close 映射 |
| `batch_runner.py` | 批量回测执行器（subprocess 并发） |
| `backtest_reporter.py` | 报告生成 (CSV/TXT/JSON) |
| `analyzer.py` | 回测分析器（权益曲线、回撤、图表） |
| `config_loader.py` | 回测配置加载 |

**使用方式**:
```bash
# 单次回测（symbol 由 --strategies 的 name:symbol 指定）
python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260610 --end 20260708

# 批量回测（按 config/strategies.yaml 并发）
python3 -m backtest.batch_runner
```

---

## 4. 策略子模块

### 4.1 策略命名规范

策略运行时名称由配置自动生成（prefix 由策略目录名推导，不依赖 `STRATEGY_PREFIX` 常量）：

```
{PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}_{MODE}
```

**示例**（以 `strategies/sar_snt3_v3` 为例）:
- `sar_snt3_8H_3_BTCUSDT_LIVE`
- `sar_snt3_8H_3_BTCUSDT_PAPER_TRADING`

### 4.2 已实现策略

> 本仓库作为**模板**发布，只保留一个完整的参考实现（历史版本曾包含 cta_ict_v3、
> cta_rbreaker_v3 等多个策略，开源时已移除，见 CHANGELOG）。

| 策略 | 目录 | 说明 | 基类架构 | 时间周期 | 多标的 |
|------|------|------|----------|----------|--------|
| **sar_snt3_v3** | `strategies/sar_snt3_v3/` | SAR + 情绪指标趋势策略 | ✅ BaseStrategy | 1m→多周期 | ✅ |

**新架构策略结构**:
```
strategies/sar_snt3_v3/
├── strategy.py       # 继承 BaseStrategy，~190 行
├── sar_snt3_v3_core.py  # 继承 BaseStrategyCore，实现 analyze/check_realtime_exit
├── config.yaml       # 策略默认参数
├── overrides/        # per-symbol 参数（唯一事实来源）
│   └── BTCUSDT.yaml
└── __init__.py
```

### 4.3 仓位持久化字段

| 策略 | 持久化字段 |
|------|---------------|
| `sar_snt3_v3` | 继承 `BaseState` 全部字段（position, entry_price, peak_price, stop_price, stop_loss_date 等），特有字段见 `strategies/sar_snt3_v3/` 内 State 定义 |

---

## 5. 配置管理

配置采用**三层模型**，回测与实盘共用同一份策略参数——这是"回测可信"的物理保证。
详细规范见 [docs/CONFIG_UNIFICATION_SPEC.md](docs/CONFIG_UNIFICATION_SPEC.md)。

### 5.1 三层配置模型

```
第 0 层  环境变量    .env（不入库，仅 .env.example）
                    服务地址 / 密钥实际值，运行时 source .env 注入
─────────────────────────────────────────────────────────────
第 1 层  系统层      config/settings.yaml
                    数据源 / 信号日志 / 引擎全局参数（${VAR} 占位）
                    实盘回测共用。不含策略列表，不含策略参数
─────────────────────────────────────────────────────────────
第 2 层  编排层      config/strategies.yaml
                    跑哪些策略 × 哪些 symbol × 什么 trading_mode
                    实盘回测共用同一份
─────────────────────────────────────────────────────────────
第 3 层  策略层      strategies/<name>/overrides/<SYMBOL>.yaml
                    per-symbol 策略参数【唯一事实来源】
                    回测与实盘都读这一份
─────────────────────────────────────────────────────────────
第 4 层  run-profile config/backtest.yaml
                    回测的【运行方式】：时间范围 / 初始资金 / 手续费 /
                    输出位置 / 并发。绝不含策略参数。
                    回测读【两份】配置：本层 + 第 1 层 settings.yaml
                    （后者提供 use_bar_high_low_for_exit，影响成交判定，
                      必须回测实盘一致），二者键集合不相交、无覆盖关系。
                    唯一语义重复 data_dir ↔ settings.data_manager.csv_dir，
                    必须一致，启动时由 verify_data_dir_consistency 校验。
                    只写有代码消费的键（无消费者的说明性配置会造成
                    "两处不同值、都不生效"的假象）。
                    实盘无 --profile：manager 只读 settings.yaml + strategies.yaml。
```

### 5.2 系统层：config/settings.yaml

```yaml
use_bar_high_low_for_exit: false                 # 止损检测价格源（顶层键）

data_manager:
  csv_dir: "./data/klines"                       # 与 config/backtest.yaml 的 data_dir 一致（启动时校验）
  realtime_enabled: true                         # 单体模式：直连 Binance 公共 WS + fapi 历史

signal_logging:
  storage:
    type: "csv"
    path: "./data/signals"

direct_trading:          # 单体模式唯一信号出口：存储后直连交易所下单
  enabled: false
  testnet: false
```

外部依赖仅剩 Binance 公共源（无 API key）与可选的直连下单凭证（`.env`）；K 线与下单均直连 Binance。

### 5.3 编排层：config/strategies.yaml

```yaml
strategies:
  sar_snt3_v3:
    trading_mode: "paper_trading"      # live / paper_trading / smoking
    symbols:                            # 字符串数组，或对象数组（可 per-symbol 覆盖 trading_mode）
      - BTCUSDT
      - ETHUSDT
```

`interval` 与 `version` 不在此声明——由 `StrategiesLoader` 从 per-symbol overrides 的
`timeframes[0]` 和 `version` 自动读取，避免两处维护。

### 5.4 策略层：strategies/&lt;name&gt;/overrides/&lt;SYMBOL&gt;.yaml

per-symbol 参数的**唯一事实来源**，回测与实盘读同一份：

```yaml
sar_snt3_v3:
  enabled: true
  version: '3'
  trading_mode: "paper_trading"
  symbols: [BTCUSDT]
  timeframes: [8h]
  params:
    sar_step: 0.015
    adx_threshold: 25
  signal:
    min_strength: 0.5
    exchange: hyperliquid
  capital:
    max_cash: 200
    leverage: 1
  risk:
    fixed_stop_loss_pct: 2.0
    trailing_profit:
      enabled: true
      activation_pct: 2.0
```

### 5.5 run-profile：config/backtest.yaml

承载回测的运行方式。回测**不初始化**推送与下单客户端，因此不依赖任何外部服务
—— 这由链路保证，不由配置开关表达（但回测确实读 `settings.yaml` 的
`use_bar_high_low_for_exit`，见 §5.2）：

```yaml
# config/backtest.yaml
start: "20260601"
end: ""
cash: 5000
commission: 0.0004
data_dir: "./data/klines"          # 必须与 settings.yaml 的 csv_dir 一致（启动时校验）
output_dir: "./backtest_output"
use_today_as_output_date: true
log_level: "INFO"
max_workers: 4
```

键集合与 `config/settings.yaml` **完全不相交**，故两份配置不存在覆盖关系。
只写有代码消费的键：`mode` / `signal_hub` / `strategy_engine` 曾写在此处但无任何
消费者，已删除（见 CONFIG_UNIFICATION_SPEC §4.5）。

### 5.6 合并优先级

```
1. CLI 参数（--start / --end / --strategies / --log-level）
2. run-profile（config/backtest.yaml，仅回测）
3. per-symbol overrides（策略参数唯一来源）
4. 代码默认值
```

**关键不变量**：策略参数（timeframes / 资金 / 风控 / 交易所）**永远只从第 3 层读取**。
CLI 和 run-profile 不得覆盖策略参数本身，只能覆盖 run-profile 范畴的字段
（时间范围、并发、外部服务开关）。这是消除回测/实盘配置分叉的硬约束。

---

## 6. 运行流程

### 6.1 启动流程

```
1. run_strategies_manager.py 加载 config/strategies.yaml（或 CLI --run）
2. 解析策略清单，展开每个 symbol 为独立配置
3. 对每个 enabled 策略启动 run_strategy.py 独立子进程:
   a. 加载策略配置（strategies/<name>/overrides/<symbol>.yaml）
   b. 初始化 DataManager（预加载 1m 数据、gap 补齐、数据完整性检查）
   c. 初始化 SignalLogger（可选 direct_trader 直连下单）
   d. 直接实例化策略类（importlib，不经注册表/引擎）
   e. 启动实时数据服务（直连 Binance 公共 WS，realtime_enabled 开关）
   f. 调用 strategy.on_start()（含仓位恢复）
   g. WS K 线回调进入事件循环
```

### 6.2 信号生成流程

```
1. K 线数据更新（Binance 公共 WS 推送）
   ↓
2. DataManager 刷新缓存 + 多时间框架聚合
   ↓
3. get_klines() 增量返回新增 K 线
   ↓
4. BaseStrategy 分发到对应 symbol 的时间框架
   ↓
5. Core.analyze() 执行入场逻辑
   ↓
6. Core.check_realtime_exit() 执行出场逻辑
   ↓
7. 生成 Signal 对象（确定性 signal_id）
   ↓
8. 进程统一写 CSV + SignalLogger 触发（direct_trader 直连下单）
   ↓
9. 信号已落存储，订单已直达交易所
```

**信号异常路径覆盖表**（信号生成→触达执行的异常路径，验收依据）：

| 步骤 | 正常路径 | 异常路径 | 补偿/重试 | 现状 |
|------|----------|----------|-----------|------|
| CSV 写入 | 落盘成功 | 磁盘错误/目录缺失 | 进程日志报错 | ⚠️ 写入失败不阻断下单 |
| 直连下单 | 交易所成交 | 下单 API 异常 | `newClientOrderId=signal_id` 幂等，可安全重试 | 反手先平后开，平仓失败则放弃开仓 |
| 直连下单 | — | 网络超时 / 5xx | 仅网络异常与 5xx 重试；4xx 一律不重试 | 失败如实返回 False（无第二通道兜底） |
| 直连下单 | — | 凭证缺失 | — | 进程启动即失败（不静默降级） |
| WS 断连 | 自动重连 | 退避上限 120s 后仍失败 | 无限重连 + REST 轮询降级 | 数据不丢，策略持续运行 |
| 信号幂等 | — | 同一信号重复推送 | 确定性 signal_id（SHA256），下游可去重 | 实盘/回测 ID 一致 |

> ⚠️ 标记行对应 CHANGELOG 自曝缺陷：HTTP 通道失败后 `log_signal` 返回 True（信号被丢弃却报告成功）。修复方案评审时以本表为基线。

### 6.3 仓位持久化流程

```
开仓 → PositionPersistence.save_on_entry() → data/positions/{strategy_name}.json
平仓 → PositionPersistence.clear_state()  → 删除 JSON 文件
SIGTERM → strategy.on_stop() → 保存当前状态 → 进程退出
恢复 → strategy.on_start() → _restore_position_state() → 从 JSON 恢复
```

---

## 7. 外部集成

### 7.1 Binance 公共数据源（单体模式内置）

K 线数据的唯一实时来源（单体模式内置，无外部行情服务）：
- WebSocket 实时 K 线推送：`wss://fstream.binance.com`
- REST 轮询回退 + 历史数据：`https://fapi.binance.com`

`data_manager.realtime_enabled=false` 时只用本地 CSV，不启动实时服务。

### 7.2 Go 交易系统

单体模式下订单已直达交易所，Go 系统如需对账/复盘可读取信号 CSV：

**文件路径**: `data/signals/{strategy_id}/{date}.csv`

### 7.3 直连下单（单体模式）

信号出口仅一条：`direct_trading` 启用时策略进程经 `BinanceTrader` 直接调用
Binance U 本位合约 API 下单，凭证只从环境变量 `BINANCE_API_KEY` / `BINANCE_API_SECRET` 读取。
未启用 `direct_trading` 时信号只落 CSV/JSON 存储，不下单。
回测链路不初始化直连执行器。

---

## 8. 故障排查

| 问题 | 可能原因 | 解决方案 |
|------|----------|----------|
| 策略加载失败 | 缺少 strategy.py 文件 | 检查策略目录结构 |
| 信号未生成 | 策略冷却中/无新 K 线 | 检查日志确认 K 线更新 |
| 实时数据中断 | Binance WS 断连 | 自动重连（退避上限 120s）+ REST 轮询回退 |
| CSV 格式错误 | 列重复/缺失 | 运行数据修复脚本 |
| 仓位未恢复 | 持久化文件损坏/不存在 | 检查 data/positions/ 目录 |
| 下单失败 | 凭证/网络/交易所拒绝 | 检查进程日志（失败如实上报，不静默降级） |

---

## 9. 关键代码位置

| 功能 | 文件路径 | 主要类/方法 |
|------|----------|-------------|
| 策略运行时管理 | `run_strategies_manager.py` | `main()` |
| 策略进程入口 | `run_strategy.py` | `main()` |
| 策略基类 | `strategy_core/base/strategy.py` | `BaseStrategy` |
| 核心逻辑基类 | `strategy_core/base/core.py` | `BaseStrategyCore` |
| 状态基类 | `strategy_core/base/state.py` | `BaseState` |
| 数据管理 | `data_manager/manager.py` | `DataManager` |
| K 线仓库 | `data_manager/kline_repository.py` | `KlineRepository` |
| WS 客户端 | `data_manager/klines_ws_client.py` | `KlinesWebSocketClient` |
| 信号日志 | `strategy_core/signal_logging/logger.py` | `SignalLogger` |
| 信号格式 | `strategy_core/signal_logging/csv_adapter.py` | `CtaSignalCSV` |
| 仓位持久化 | `strategy_core/position_persistence.py` | `PositionPersistence` |
| 回测入口 | `backtest/run_backtest.py` | `main()` |
