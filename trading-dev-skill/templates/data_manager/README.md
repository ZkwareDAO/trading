# Data Manager 使用指南

**版本**: 3.7.0
**更新日期**: 2026-05-29

## 架构设计

### 数据流程概览

```
klines_service              data_manager                     策略
┌──────────────┐           ┌──────────────────┐            ┌─────────────┐
│ WS 实时推送   │ ────────▶ │ KlinesWSClient   │            │             │
│ HTTP API     │ ────────▶ │ DataManager      │ ────────▶ │ get_klines()│
└──────────────┘           │ KlineRepository  │            │ Kline 对象  │
                           │ Cache (1m+LRU)   │            └─────────────┘
本地 CSV 文件 ────────────▶ │ BacktestLoader   │
  {symbol}_{tf}.csv        └──────────────────┘
```

## 模块职责

### manager.py - 数据管理器核心（5 个核心方法）

| 方法 | 说明 |
|------|------|
| `download_daily_data(symbol, day)` | 通过 HTTP API 下载单日数据并保存 CSV |
| `batch_download_history(symbol, days)` | 批量下载最近 N 天历史数据 |
| `init_today_realtime(symbol)` | 初始化今日数据：下载 + 补齐 + 开启 WS 推送 |
| `manage_memory_cache(symbol)` | 管理内存缓存：保留近 2 天，清理过期数据 |
| `get_klines(symbol, timeframe, limit)` | 统一查询接口：支持增量返回、缓存、CSV 回退 |

**辅助方法**:

| 方法 | 说明 |
|------|------|
| `connect_and_sync(symbols)` | 启动时连接+预加载+WS |
| `register_timeframes(symbol, timeframes)` | 注册时间框架到 KlineRepository |
| `is_data_complete(symbols)` | 检查数据完整性 |
| `aggregate_1m_to_interval(df, interval)` | 从 1m 聚合到大周期 |
| `auto_load_missing_data(symbol, start, end)` | 按日期区间加载缺失数据 |
| `get_dataframe_cached(symbol, timeframe, limit)` | 获取缓存 DataFrame |

### kline_repository.py - K 线仓库

轻量级多时间框架更新管理：

- 维护 symbol 与时间框架的注册关系
- 1m K 线更新时自动触发大周期聚合（直接保存到 CSV）
- **不存储数据在内存中**，需要时从 CSV 懒加载

### klines_ws_client.py - WebSocket 客户端

与 klines_service 的实时连接：

- 无限重连（指数退避，上限 120s）
- 心跳检测（30s）
- 回调机制支持同步和异步函数

```python
from data_manager.klines_ws_client import KlinesWebSocketClient

client = KlinesWebSocketClient(ws_url="ws://127.0.0.1:17081/ws/klines")
await client.connect()
client.set_on_kline_callback(on_kline)
await client.subscribe(["BTCUSDT", "ETHUSDT"])
```

### klines_loader.py - 数据加载与重采样

从原始按日期分文件的 CSV 数据中加载、合并、重采样。

### backtest_data_loader.py - 回测数据智能加载

按回测日期区间查找覆盖文件，未覆盖时从细粒度源数据合成。

### indicators.py - 技术指标计算

支持：ADX/DI、EMA/SMA、RSI、MACD、BOLL、ATR、KD/KDJ、Envelope

### cache.py - 分层缓存

- 1m 数据: 常驻缓存，不淘汰（除非 manage_memory_cache 触发限制）
- 大周期: LRU 缓存，淘汰最久未使用的条目
- 大周期数据优先从 1m 缓存实时聚合

### klines_data.py - 共享数据类

统一的 `Kline` 数据类，供 WS 客户端和 DataManager 共享使用。

## 配置

通过 DataManagerConfig 配置类设置：

```python
from data_manager import DataManager, DataManagerConfig

config = DataManagerConfig(
    csv_dir="./data/klines",
    cache_max_size=10000,
    preload_1m_enabled=True,
    preload_days=7,
    cache_1m_max_rows=500000,
    cache_1m_max_age_days=90,
    klines_service_enabled=True,
    klines_service_ws_url="ws://127.0.0.1:17081/ws/klines",
    klines_service_http_url="http://127.0.0.1:17081",
    sync_history_days=30,
    auto_sync_on_connect=True,
    persistence_interval_minutes=5,
)
```

## 使用方式

```python
from data_manager import DataManager, DataManagerConfig

# 1. 创建并连接
config = DataManagerConfig(csv_dir="./data/klines")
dm = DataManager(config)
dm.connect()

# 2. 下载数据
await dm.download_daily_data("BTCUSDT", "2026-05-29")
await dm.batch_download_history("BTCUSDT", days=30)

# 3. 初始化今日实时数据
await dm.init_today_realtime("BTCUSDT")

# 4. 获取 K 线数据（增量返回）
klines = dm.get_klines("BTCUSDT", "1m", limit=100)

# 5. 管理内存缓存
dm.manage_memory_cache("BTCUSDT")
```

## 数据完整性保障

### 启动流程

```
connect()
  → connect_and_sync()
      1. 预加载 1m 数据
      2. 扫描中间 gap（相邻行时间差 > 120 秒）
      3. 调用 API 补齐 gap
      4. 补齐"最后一行 → 现在"的数据
      5. 裁剪为最新 500 行 → 存入内存缓存
  → is_data_complete()
      1. 缓存中有数据
      2. 最新数据距今 < 5 分钟
      3. CSV 无中间 gap
  → _data_ready = all(complete)
      → True: 开启 WS 实时推送
      → False: 降级为 CSV 轮询
```

### WS 推送时完整性验证

```
_on_kline_received(kline):
  差值 == 60 秒 → 正常，追加
  差值 > 90 秒  → 调用 API 补齐中间缺失 → 合并到缓存
```

### 统一 CSV 持久化

所有写入路径（WS 推送、gap 补齐、API 回退、缓存保存）统一使用 `save_klines_to_csv`：
1. 读取现有 CSV
2. 合并新旧数据
3. 按时间戳去重（新覆盖旧）
4. 按时间戳排序
5. 写回 CSV
