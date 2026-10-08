# Data Manager 架构文档

**版本**: 3.7.0
**更新日期**: 2026-09-06

## 概述

Data Manager 是量化交易策略系统的数据接入层，为策略层提供统一的 K 线数据访问服务。单体模式下采用本地 CSV 文件存储 + 内存缓存 + 直连 Binance 公共 WS 实时推送的轻量化设计（无外部行情服务）。

---

## 架构位置

```
┌─────────────────────────────────────────────────┐
│              Strategy Core Layer                │
│  (sar_snt3_v3 等策略插件)   │
└────────────────────┬────────────────────────────┘
                     │ get_klines(symbol, timeframe, limit)
                     ↓
┌─────────────────────────────────────────────────┐
│              Data Manager Layer                 │
│  ┌──────────────┐  ┌──────────────┐             │
│  │ DataCache    │  │ Indicators   │             │
│  │ (1m常驻+LRU) │  │ (ADX/RSI/...)│             │
│  └──────────────┘  └──────────────┘             │
│  ┌──────────────┐  ┌──────────────┐             │
│  │KlineRepo     │  │ WS Client    │             │
│  │(多TF聚合)    │  │ (实时推送)    │             │
│  └──────────────┘  └──────────────┘             │
└────────────────────┬────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────┐
│  data/klines/{symbol}_{timeframe}.csv           │
│  Binance 公共 WS/REST（单体模式内置实时源）        │
└─────────────────────────────────────────────────┘
```

---

## 模块组成

| 文件 | 职责 |
|------|------|
| `manager.py` | 核心数据管理器（5 个核心方法 + 辅助方法） |
| `cache.py` | 分层缓存（1m 常驻 + 大周期 LRU） |
| `kline_repository.py` | 多时间框架注册与聚合（轻量级，只维护元数据） |
| `klines_ws_client.py` | WebSocket 实时 K 线接收（无限重连、退避上限 120s） |
| `klines_loader.py` | K 线数据加载、重采样、CSV 持久化 |
| `klines_data.py` | 共享 Kline 数据类 |
| `indicators.py` | 技术指标计算（ADX, EMA, RSI, MACD, BOLL, ATR, KD, Envelope） |

---

## 数据流设计

### 实时数据流

```
Binance 公共 fstream WS 推送 1m K 线
    ↓
KlinesWSClient._on_kline_received()
    ↓
完整性验证（差值 > 90s → fapi REST 补齐 gap）
    ↓
save_klines_to_csv() 统一持久化
    ↓
KlineRepository 触发大周期聚合（1m→4h/1h/15m）
    ↓
DataManager 缓存更新
    ↓
get_klines() 增量返回给策略
```

### 查询流程

```
策略请求 get_klines(symbol, timeframe, limit)
    ↓
检查 1m 缓存 → 有则聚合返回
    ↓
检查 LRU 缓存 → 有则返回
    ↓
从 CSV 文件加载 → 更新缓存 → 返回
```

---

## 缓存机制

| 缓存层 | 数据类型 | 淘汰策略 | 说明 |
|--------|----------|----------|------|
| 1m 常驻缓存 | 1m K 线 | 不淘汰 | 除非 manage_memory_cache 触发限制 |
| LRU 缓存 | 大周期数据 | 最近最少使用 | 默认容量 10000 条目 |
| 实时聚合 | 1m → 大周期 | 不缓存 | 优先从 1m 缓存实时聚合 |

---

## 技术指标

| 指标 | 函数 | 说明 |
|------|------|------|
| ADX/DI | `compute_adx()` | 趋势强度 |
| EMA | `compute_ema()` | 指数移动平均 |
| SMA | `compute_sma()` | 简单移动平均 |
| RSI | `compute_rsi()` | 相对强弱 |
| MACD | `compute_macd()` | 异同移动平均 |
| BOLL | `compute_boll()` | 布林带 |
| ATR | `compute_atr()` | 平均真实波幅 |
| KD/KDJ | `compute_kd()` | 随机指标 |
| Envelope | `compute_envelope()` | 均线包络通道 |

---

## 配置

```yaml
data_manager:
  csv_dir: "./data/klines"
  csv_filename_pattern: "{symbol}_{timeframe}.csv"
  cache_max_size: 10000
  auto_load: true
  realtime_enabled: true    # 单体模式：直连 Binance 公共 WS + fapi 历史
```

DataManagerConfig 字段:

| 字段 | 默认值 | 说明 |
|------|--------|------|
| `csv_dir` | `./data/klines` | CSV 文件目录 |
| `cache_max_size` | 5000 | 大周期 LRU 缓存大小 |
| `preload_1m_enabled` | True | 是否启用 1m 预加载 |
| `preload_days` | 7 | 预加载最近 N 天 |
| `cache_1m_max_rows` | 500000 | 1m 缓存最大行数 |
| `cache_1m_max_age_days` | 90 | 1m 缓存最大年龄 |
| `realtime_enabled` | True | 单体模式：直连 Binance 公共 WS + fapi 历史（false 只用本地 CSV） |
| `sync_history_days` | 30 | 启动时补齐历史天数 |
| `persistence_interval_minutes` | 5 | 缓存刷到 CSV 的间隔 |
| `backtest_mode` | False | 回测模式（禁用增量返回） |
