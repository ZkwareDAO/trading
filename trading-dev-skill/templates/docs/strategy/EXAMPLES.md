# 策略参考示例

> **文档定位**：代码模板和常见问题 FAQ，开发时直接参考。

---

## 新架构完整示例：obv_atr_v2

### strategy.py（35 行）

```python
#!/usr/bin/env python3
"""OBV ATR V2 — Strategy 接口类"""

from strategy_core.base import BaseStrategy
from .obv_core import OBVCoreV2


class Strategy(BaseStrategy):
    """OBV ATR V2 策略"""

    STRATEGY_TYPE = "obv_atr_v2"
    STRATEGY_PREFIX = "OBVATR"
    DEFAULT_TIMEFRAME = "4h"

    def _create_core(self):
        return OBVCoreV2(
            symbols=self.symbols,
            timeframes=self.timeframes,
            params=self.params,
        )

    def _get_indicator_timeframes(self) -> set:
        tf_set = set(self.timeframes)
        p = self.params or {}
        tf_set.add(p.get("obv_timeframes", "4h"))
        tf_set.add(p.get("atr_timeframes", "1h"))
        tf_set.add(p.get("adx_timeframes", "4h"))
        tf_set.add(p.get("volume_timeframes", "4h"))
        return tf_set
```

### State 示例

```python
from strategy_core.base import BaseState
from dataclasses import dataclass

@dataclass
class OBVStateV2(BaseState):
    """OBV ATR V2 状态 - 继承 BaseState"""

    atr_at_entry: float = 0.0
    trail_mult_at_entry: float = 2.0
    trail_anchor_price: float = 0.0
    trail_activated: bool = False

    def to_persist_dict(self):
        data = super().to_persist_dict()
        data.update({
            "atr_at_entry": self.atr_at_entry,
            "trail_mult_at_entry": self.trail_mult_at_entry,
            "trail_anchor_price": self.trail_anchor_price,
            "trail_activated": self.trail_activated,
        })
        return data

    def restore_from_dict(self, data):
        super().restore_from_dict(data)
        self.atr_at_entry = data.get("atr_at_entry", 0.0)
        self.trail_mult_at_entry = data.get("trail_mult_at_entry", 2.0)
        self.trail_anchor_price = data.get("trail_anchor_price", 0.0)
        self.trail_activated = data.get("trail_activated", False)
```

---

## 常见问题 FAQ

### Q0: 新旧架构如何选择？

推荐使用新架构（BaseStrategy 基类继承）：

| 对比项 | 新架构 | 旧架构 |
|--------|--------|--------|
| 代码量 | ~35 行 strategy.py | ~250 行 strategy.py |
| 生命周期 | 基类自动处理 | 手动实现 |
| K线冷却 | 基类自动处理（回测时跳过） | 手动实现 |
| 仓位持久化 | 基类自动处理（回测时禁用） | 手动实现 |
| 维护成本 | 只维护特有逻辑 | 独立维护全部 |

**迁移建议**：现有策略可保持不变，新策略使用新架构。

---

### Q1: 为什么入场必须用已闭合 K 线？

实盘 WS 推送 1m K 线，大周期（如 4h）的最后一根可能未闭合。使用未闭合数据会导致：
- 回测时"偷看未来"
- 实盘信号与回测不一致

---

### Q2: 冷却机制为什么用 K 线时间戳而非时间间隔？

同一根大周期 K 线内，入场条件不会变化，重复检查无意义。使用 K 线时间戳可以：
- 精确控制每根 K 线最多触发一次
- 回测模式可跳过，不影响历史回测

---

### Q3: entry_timestamp 为什么用秒级？

与 K 线数据格式一致，便于：
- 计算持仓时间
- 与 position 文件对齐
- 生成 position_id

---

### Q4: K 线冷却和止损日冷却的区别？

| 冷却类型 | 触发条件 | 持续时间 | 实现位置 |
|----------|----------|----------|----------|
| K 线冷却 | 发出信号后 | 同一根 K 线内 | Strategy |
| 止损日冷却 | 触发止损 | 当天剩余时间 | Core |

---

### Q5: 为什么移动止盈不记录止损日期？

移动止盈是盈利出场，不是止损。次日应该可以正常开仓，不应被止损日冷却阻止。

---

### Q6: 回测模式如何处理冷却？

- **K 线冷却**：回测模式跳过（`backtest_mode` 检查）
- **止损日冷却**：正常生效，使用 K 线时间判断

---

### Q7: 多标的策略如何处理状态？

使用 `_state: Dict[str, State]` 字典，每个标的独立状态：

```python
def _get_state(self, symbol: str) -> State:
    if symbol not in self._state:
        self._state[symbol] = State()
    return self._state[symbol]
```

---

### Q8: 如何调试策略信号？

1. 检查 `metadata["reason"]` 字段，了解 hold 原因
2. 添加 `logger.debug()` 输出中间计算结果
3. 运行回测查看信号记录 CSV
4. 使用测试用例验证边界条件

---

### Q9: 为什么技术指标必须在 analyze() 内计算？

1. **避免绕远路**：在 Strategy 类预计算指标增加复杂度
2. **回测兼容**：回测框架调用 `analyze()` 时，指标应自动计算
3. **数据一致性**：每次调用时使用最新的已闭合 K 线计算指标
4. **代码简洁**：所有入场逻辑集中在 Core.analyze() 内

**错误示例**：

```python
# ❌ 错误：在 Strategy.on_start() 中预计算指标
def on_start(self):
    df = self.data_manager.get_dataframe_cached(symbol, "1d")
    self.core._update_price_lines(symbol, df.iloc[-1])
```

**正确示例**：

```python
# ✅ 正确：在 analyze() 内实时计算
def analyze(self, symbol, klines_data, current_time):
    closed_1d = self._get_closed_data(klines_data, "1d", min_rows=1, current_time=current_time)
    if not closed_1d.empty:
        prev = closed_1d.iloc[-1]
        self._update_price_lines(symbol, prev["high"], prev["low"], prev["close"])
```
