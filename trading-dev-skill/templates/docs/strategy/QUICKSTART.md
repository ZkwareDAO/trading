# 策略快速入门

> **文档定位**：新策略开发第一步，涵盖目录结构、代码骨架和配置模板。

---

## 开发流程

```
Step 1: 创建目录结构
   ↓
Step 2: 复制代码骨架
   ↓
Step 3: 实现核心逻辑
   ↓
Step 4: 编写配置文件
   ↓
Step 5: 编写测试用例
   ↓
Step 6: 运行审查检查表 → 参见 [REVIEW_CHECKLIST.md](REVIEW_CHECKLIST.md)
```

---

## 目录结构（必需）

```
strategies/{strategy_name}/
├── __init__.py              # 模块初始化
├── strategy.py              # Strategy 接口类（必需）
├── {prefix}_core.py         # 核心逻辑类（必需）
├── config.yaml              # 默认配置
├── config.dev.yaml          # 开发环境配置
├── config.test.yaml         # 测试/回测配置
└── tests/
    ├── test_{prefix}_core.py      # 核心逻辑测试
    └── test_strategy_logging.py   # 信号日志测试
```

**命名规范**：
- `{strategy_name}`: 策略目录名，如 `obv_atr`, `cta_trend`
- `{prefix}`: 核心文件前缀，如 `obv`, `trend`

---

## 基类继承模式

使用 `BaseStrategy` / `BaseStrategyCore` / `BaseState` 基类开发。

```
BaseState (strategy_core/base/state.py)
    ↓ 继承
{Prefix}State - 添加策略特有字段

BaseStrategyCore (strategy_core/base/core.py)
    ↓ 继承
{Prefix}Core - 实现 analyze() 和 check_realtime_exit()

BaseStrategy (strategy_core/base/strategy.py)
    ↓ 继承
Strategy - 只需设置类属性和实现两个抽象方法
```

### strategy.py 模板

```python
#!/usr/bin/env python3
"""{策略名称} — Strategy 接口类"""

from strategy_core.base import BaseStrategy
from .{prefix}_core import {Prefix}Core


class Strategy(BaseStrategy):
    """{策略名称}"""

    STRATEGY_TYPE = "{strategy_name}"
    STRATEGY_PREFIX = "{PREFIX}"
    DEFAULT_TIMEFRAME = "1h"

    def _create_core(self):
        return {Prefix}Core(
            symbols=self.symbols,
            timeframes=self.timeframes,
            params=self.params,
        )

    def _get_indicator_timeframes(self) -> set:
        tf_set = set(self.timeframes)
        p = self.params or {}
        tf_set.add(p.get("{indicator}_timeframes", "1h"))
        return tf_set
```

### {prefix}_core.py 骨架

```python
#!/usr/bin/env python3
"""{策略名称} — 核心逻辑"""

from strategy_core.base import BaseStrategyCore, BaseState
from typing import Dict, Any, Optional, List
from datetime import datetime
import pandas as pd


class {Prefix}State(BaseState):
    """策略状态"""

    atr_at_entry: float = 0.0
    trail_activated: bool = False

    def to_persist_dict(self) -> Dict[str, Any]:
        data = super().to_persist_dict()
        data.update({"atr_at_entry": self.atr_at_entry, "trail_activated": self.trail_activated})
        return data

    def restore_from_dict(self, data: Dict[str, Any]) -> None:
        super().restore_from_dict(data)
        self.atr_at_entry = data.get("atr_at_entry", 0.0)
        self.trail_activated = data.get("trail_activated", False)


class {Prefix}Core(BaseStrategyCore):

    def __init__(self, symbols, timeframes, params=None):
        super().__init__(symbols, timeframes, params)

    def _get_state(self, symbol):
        if symbol not in self._state:
            self._state[symbol] = {Prefix}State()
        return self._state[symbol]

    def analyze(self, symbol, klines_data, current_time=None, realtime_price=None):
        state = self._get_state(symbol)
        if state.is_in_position():
            return {"action": "hold", "price": 0, "strength": 0, "metadata": {"reason": "已有持仓"}}
        # TODO: 实现入场条件检查
        return {"action": "hold", "price": 0, "strength": 0, "metadata": {"reason": "未满足入场条件"}}

    def check_realtime_exit(self, symbol, current_price, current_time=None, bar_high=None, bar_low=None):
        state = self._get_state(symbol)
        if not state.is_in_position():
            return {"action": "hold", "price": current_price, "strength": 0, "metadata": {"reason": "无持仓"}}
        state.update_pnl_extremes(current_price)
        # TODO: 实现出场条件检查
        return {"action": "hold", "price": current_price, "strength": 0, "metadata": {"reason": "持仓中"}}

    def get_status(self):
        return {"symbols": self.symbols, "timeframes": self.timeframes,
                "states": {s: self._get_state(s).to_persist_dict() for s in self.symbols}}
```

### __init__.py 模板

```python
from .strategy import Strategy
from .{prefix}_core import {Prefix}Core, {Prefix}State

__all__ = ["Strategy", "{Prefix}Core", "{Prefix}State"]
```

---

## 配置文件模板

```yaml
{strategy_name}:
  enabled: true
  version: '1'

  # 标的与周期
  symbols:
    - BTCUSDT
  timeframes:
    - 1h
  direction: neutral

  # 策略参数
  params:
    {indicator}_timeframes: 1h  # 每个指标必须配置 *_timeframes

  # 信号配置
  signal:
    min_strength: 0.5
    cooldown_ms: 60000

  # 资金配置
  capital:
    max_cash: 100
    max_parts: 1

  # 风控配置（可选）
  risk:
    enabled: true
    fixed_stop_loss_pct: 20.0
    trailing_profit:
      enabled: true
      activation_pct: 50.0
      drawdown_pct: 5.0
    fixed_take_profit_pct: 0.0

  # 冷却周期
  cooldown_timeframe: 1h
```

---

## 下一步

- API 参考 → [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)
- 实战注意事项 → [PRACTICAL_GUIDE.md](PRACTICAL_GUIDE.md)
- 代码模板与 FAQ → [EXAMPLES.md](EXAMPLES.md)
- 编码约束 → [AI_CONSTRAINTS.md](AI_CONSTRAINTS.md)
- 提交前检查 → [REVIEW_CHECKLIST.md](REVIEW_CHECKLIST.md)
