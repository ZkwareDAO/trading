# 策略开发 API 参考

> **文档定位**：BaseStrategy / BaseStrategyCore / BaseState 的 API 参考。只列出"有什么"和"签名是什么"，"怎么做"见 PRACTICAL_GUIDE.md。

---

## 1. 必需实现的抽象方法

| 类 | 抽象方法 | 说明 |
|----|----------|------|
| **Strategy** | `_create_core()` | 创建 Core 实例 |
| **Strategy** | `_get_indicator_timeframes() -> set` | 返回指标周期集合 |
| **Core** | `_get_state(symbol) -> State` | 获取 per-symbol 状态 |
| **Core** | `analyze(symbol, klines_data, current_time, realtime_price)` | 入场逻辑。`realtime_price` = 1m K线 **close** |
| **Core** | `check_realtime_exit(symbol, current_price, current_time, bar_high, bar_low)` | 出场逻辑。`current_price` = 1m **close**，`bar_high/low` = 1m **high/low** |
| **Core** | `get_status() -> Dict` | 状态查询 |

---

## 2. BaseState 字段（继承即得，无需重复定义）

```python
position: Optional[str] = None        # 'long', 'short', None
position_id: Optional[str] = None      # 仓位唯一标识
entry_timestamp: Optional[int] = None  # 开仓时间戳（秒级）
entry_price: float = 0.0               # 开仓价格
entry_time: Optional[datetime] = None  # 开仓时间
peak_price: float = 0.0                # 峰值价格
stop_price: float = 0.0                # 止损价格
stop_loss_date: Optional[date] = None  # 止损日期（冷却机制）
max_pnl_pct: float = 0.0               # 最大盈利百分比（>0）
min_pnl_pct: float = 0.0               # 最大亏损百分比（<0）
```

---

## 3. BaseState 方法

```python
is_in_position() -> bool
clear_position(record_stop_loss=False, current_time=None)
to_persist_dict() -> Dict[str, Any]
restore_from_dict(data: Dict[str, Any])
update_pnl_extremes(current_price: float)
```

---

## 4. BaseStrategyCore 方法

```python
# K 线数据
get_closed_data(klines_data, timeframe, min_rows, current_time) -> DataFrame

# 仓位回调（自动判断 backtest_mode）
_notify_position_enter(symbol, state)
_notify_exit_and_clear(symbol, state, exit_price, exit_reason, is_stop_loss, exit_time) -> str

# 平仓前钩子（子类可选重写）
_on_before_exit_clear(symbol, state, is_stop_loss) -> None

# 止损检测价格
_get_exit_detection_prices(current_price, bar_high, bar_low) -> tuple
```

---

## 5. BaseStrategy 已实现功能

| 功能 | 说明 |
|------|------|
| on_start() | 注册时间框架、设置回调、恢复状态 |
| on_stop() | 停止运行 |
| on_kline() | 完整 K 线处理流程 |
| K 线冷却 | 同一根入场周期 K 线不重复触发，回测自动跳过 |
| 仓位持久化 | 实盘自动持久化，回测自动禁用 |
| 信号创建 | 自动创建 Signal 对象 |

---

## 6. 风控配置

### config.yaml 风控字段

```yaml
risk:
  enabled: true
  fixed_stop_loss_pct: 20.0        # 固定止损百分比
  trailing_profit:
    enabled: true
    activation_pct: 50.0            # 激活阈值（%）
    drawdown_pct: 5.0               # 从最大盈利回落的百分比
  fixed_take_profit_pct: 0.0        # 固定止盈（0 = 禁用）
```

### 检查优先级

固定止损 > 回落止盈 > 固定止盈

### RiskController API

```python
from strategy_core.base.risk_control import RiskController, ExitSignal

controller = RiskController(RiskControlConfig.from_dict(config))
signal: Optional[ExitSignal] = controller.check_exit(state, current_price)
# ExitSignal: action, reason, is_stop_loss
```

---

## 7. 仓位持久化

### 文件位置

| 类型 | 路径 |
|------|------|
| 当前仓位 | `data/positions/{strategy_name}.json` |
| 历史仓位 | `data/history_positions/{strategy_name}/{YYYYMMDD}.csv` |

### 历史仓位 CSV 字段

position_id, strategy_name, symbol, position_type, entry_price, exit_price, entry_time, exit_time, entry_timestamp, exit_timestamp, peak_price, stop_price, max_pnl_pct, min_pnl_pct, exit_reason, is_stop_loss, price_diff, pnl_pct, atr_at_entry, trail_activated, duration_seconds
