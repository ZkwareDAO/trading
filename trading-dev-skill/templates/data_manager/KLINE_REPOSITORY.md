# K 线仓库模块 (KlineRepository) - 轻量级设计

**版本**: 3.7.0
**更新日期**: 2026-05-29

## 概述

K 线仓库模块提供了轻量级的多时间框架 K 线数据管理，当 1m K 线更新时自动聚合并更新所有注册的大周期数据。

**核心设计原则：**
- **不存储数据在内存中** - 所有数据存储在 CSV 文件
- **只维护状态标识** - 记录 symbol 注册时间框架和更新状态
- **懒加载读取** - 需要数据时从 CSV 文件读取
- **实时聚合** - 1m 更新时立即聚合并写入 CSV

## 使用方法

### 1. 启用 K 线仓库

```python
from data_manager.manager import DataManager, DataManagerConfig

dm = DataManager(DataManagerConfig())
dm.enable_kline_repository()
```

### 2. 注册时间框架

```python
dm.register_timeframes('BTCUSDT', ['1m', '15m', '1h', '4h'])
dm.register_timeframes('ETHUSDT', ['1m', '15m', '1h', '4h'])
```

### 3. 更新 1m K 线并自动聚合

```python
results = dm.update_klines_from_1m('BTCUSDT', new_klines)
# {'1m': True, '15m': True, '4h': True}
```

### 4. 读取数据

```python
klines_4h = dm.get_klines('BTCUSDT', '4h', limit=100)
df_15m = dm.get_dataframe('BTCUSDT', '15m', limit=100)
```

## 工作流程

```
策略启动 → register_timeframes() → 注册到 KlineRepository (仅记录)
                                     ↓
1m K 线更新 → update_klines_from_1m() → 更新 1m CSV 文件
                                     ↓
                             从 1m CSV 读取数据
                                     ↓
                             聚合并写入大周期 CSV
                                     ↓
策略读取 → get_klines() → 从 CSV 文件加载
```

## API 参考

### KlineRepository

| 方法 | 说明 |
|------|------|
| `register_symbol(symbol, timeframes)` | 注册 symbol 和时间框架（仅记录） |
| `update_from_1m(symbol, new_1m_klines)` | 从 1m K 线更新并聚合到 CSV |
| `get_timeframes(symbol)` | 获取 symbol 已注册的时间框架 |
| `get_status()` | 获取仓库状态（不包含数据） |
| `clear(symbol)` | 清除状态（不清除 CSV 文件） |
| `unregister_symbol(symbol)` | 注销 symbol |

### DataManager (扩展)

| 方法 | 说明 |
|------|------|
| `enable_kline_repository()` | 启用 K 线仓库功能 |
| `register_timeframes(symbol, timeframes)` | 注册时间框架 |
| `update_klines_from_1m(symbol, klines)` | 更新 1m 并聚合 |
| `get_repository_status()` | 获取仓库状态 |

## 注意事项

1. **数据读取**: 使用标准方法 `get_klines()` 或 `get_dataframe()`，从 CSV 文件读取
2. **启用时机**: 在 DataManager 初始化后立即调用 `enable_kline_repository()`
3. **注册时机**: 策略启动时调用 `register_timeframes()`
4. **并发安全**: 仓库内部使用线程锁，支持并发访问
5. **迭代更新**: 支持多次增量更新，`save_klines_to_csv` 使用时间戳去重
