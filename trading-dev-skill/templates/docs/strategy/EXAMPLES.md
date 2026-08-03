# 策略代码模板与 FAQ

> **文档定位**：通用代码模板和常见问题。

---

## strategy.py 模板

```python
#!/usr/bin/env python3
"""{策略名称} — Strategy 接口类"""

from strategy_core.base import BaseStrategy
from .{prefix}_core import {Prefix}Core


class Strategy(BaseStrategy):
    """{策略名称}"""

    STRATEGY_TYPE = "{strategy_name}"
    STRATEGY_PREFIX = "{PREFIX}"
    DEFAULT_TIMEFRAME = "{主时间框架}"

    def _create_core(self):
        return {Prefix}Core(
            symbols=self.symbols,
            timeframes=self.timeframes,
            params=self.params,
            global_config=self._get_global_config(),
        )

    def _get_indicator_timeframes(self) -> set:
        tf_set = set(self.timeframes)
        p = self.params or {}
        tf_set.add(p.get("xxx_timeframes", "4h"))
        return tf_set
```

---

## State 模板

```python
from strategy_core.base import BaseState
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

@dataclass
class {Prefix}State(BaseState):
    """策略状态"""

    # 持久化字段
    atr_at_entry: float = 0.0

    # 缓存字段（不持久化）
    last_evaluated_bar: Optional[datetime] = None

    def to_persist_dict(self):
        data = super().to_persist_dict()
        data.update({"atr_at_entry": self.atr_at_entry})
        return data

    def restore_from_dict(self, data):
        super().restore_from_dict(data)
        self.atr_at_entry = data.get("atr_at_entry", 0.0)

    def clear_position(self, record_stop_loss=False, current_time=None):
        super().clear_position(record_stop_loss=record_stop_loss, current_time=current_time)
        self.atr_at_entry = 0.0
        self.last_evaluated_bar = None
```

---

## Core 模板

```python
from strategy_core.base import BaseStrategyCore

class {Prefix}Core(BaseStrategyCore[{Prefix}State]):

    def _get_state(self, symbol):
        if symbol not in self._state:
            self._state[symbol] = {Prefix}State()
        return self._state[symbol]

    def analyze(self, symbol, klines_data, current_time=None, realtime_price=None):
        state = self._get_state(symbol)
        if state.is_in_position():
            return self._hold_result("已有持仓")
        if current_time is None:
            return self._hold_result("current_time is required")
        if state.stop_loss_date == current_time.date():
            return self._hold_result("今日已触发止损")

        closed = self.get_closed_data(klines_data, self.timeframes[0],
                                       min_rows=self.min_rows, current_time=current_time)
        if closed.empty or len(closed) < self.min_rows:
            return self._hold_result("K线数据不足")

        # TODO: 入场逻辑
        return self._hold_result("未满足入场条件")

    def check_realtime_exit(self, symbol, current_price, current_time=None,
                            bar_high=None, bar_low=None):
        state = self._get_state(symbol)
        if not state.is_in_position():
            return self._hold_result("无持仓")
        state.update_pnl_extremes(current_price)

        check_high, check_low = self._get_exit_detection_prices(
            current_price, bar_high, bar_low)
        is_long = state.position == "long"
        stop_hit = (check_low <= state.stop_price if is_long
                    else check_high >= state.stop_price)
        if stop_hit:
            return self._close(symbol, state, state.stop_price, "止损",
                               is_stop_loss=True, current_time=current_time)
        return self._hold_result("持仓中")

    def get_status(self):
        return {"symbols": self.symbols, "timeframes": self.timeframes,
                "states": {s: self._get_state(s).to_persist_dict() for s in self.symbols}}
```

---

## 配置文件模板

```yaml
{strategy_name}:
  enabled: true
  version: '1'
  direction: neutral
  symbols:
    - BTCUSDT
  timeframes:
    - 4h
  params:
    xxx_timeframes: 4h     # 每个指标必须配置 *_timeframes
    # 策略参数...
  signal:
    min_strength: 0.5
    cooldown_ms: 60000
  capital:
    max_cash: 100
    max_parts: 1
    leverage: 1
  risk:
    enabled: true
    fixed_stop_loss_pct: 20.0
    trailing_profit:
      enabled: true
      activation_pct: 50.0
      drawdown_pct: 5.0
    fixed_take_profit_pct: 0.0
  cooldown_timeframe: 4h
```

---

## FAQ

### Q1: 为什么入场必须用已闭合 K 线？

实盘 WS 推送 1m K 线，大周期的最后一根可能未闭合。使用未闭合数据会导致回测"偷看未来"且实盘信号与回测不一致。

### Q2: K 线冷却和止损日冷却的区别？

| 冷却类型 | 触发条件 | 持续时间 | 实现 |
|----------|----------|----------|------|
| K 线冷却 | 发出信号后 | 同一根 K 线内 | BaseStrategy 自动处理 |
| 止损日冷却 | 触发止损 | 当天剩余时间 | Core.analyze() 检查 stop_loss_date |

### Q3: 为什么移动止盈不记录止损日期？

移动止盈是盈利出场，不是止损。次日应可正常开仓。

### Q4: 回测模式如何处理冷却？

K 线冷却：基类自动跳过。止损日冷却：正常生效，使用 K 线时间判断。

### Q5: 多标的策略如何处理状态？

使用 `_state: Dict[str, State]` 字典，每个标的独立状态。

### Q6: 为什么技术指标必须在 analyze() 内计算？

1. 避免在 Strategy 类预计算指标增加复杂度
2. 回测框架调用 analyze() 时指标应自动计算
3. 每次调用使用最新已闭合 K 线，数据一致
