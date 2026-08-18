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

## 新架构：基类继承模式（推荐）

> **v3.6.0 新增**：使用 `BaseStrategy` / `BaseStrategyCore` / `BaseState` 基类，大幅简化策略开发。

### 架构概述

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

### strategy.py 模板（约 35 行）

```python
#!/usr/bin/env python3
"""{策略名称} — Strategy 接口类"""

from strategy_core.base import BaseStrategy
from .{prefix}_core import {Prefix}Core


class Strategy(BaseStrategy):
    """{策略名称}"""

    # ========== 必需类属性 ==========
    STRATEGY_TYPE = "{strategy_name}"      # 策略目录名
    STRATEGY_PREFIX = "{PREFIX}"            # 策略名称前缀
    DEFAULT_TIMEFRAME = "1h"                # 默认主周期

    # ========== 必需抽象方法 ==========

    def _create_core(self):
        """创建核心逻辑实例"""
        return {Prefix}Core(
            symbols=self.symbols,
            timeframes=self.timeframes,
            params=self.params,
        )

    def _get_indicator_timeframes(self) -> set:
        """收集所有指标使用的 K 线周期"""
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
from datetime import datetime, timezone
import pandas as pd


class {Prefix}State(BaseState):
    """策略状态 - 继承 BaseState"""

    # 策略特有字段
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

    def __init__(self, symbols: List[str], timeframes: List[str], params: Optional[Dict[str, Any]] = None):
        super().__init__(symbols, timeframes, params)

    def _get_state(self, symbol: str) -> {Prefix}State:
        if symbol not in self._state:
            self._state[symbol] = {Prefix}State()
        return self._state[symbol]

    def analyze(self, symbol, klines_data, current_time=None):
        """入场分析"""
        state = self._get_state(symbol)
        if state.is_in_position():
            return {"action": "hold", "price": 0, "strength": 0, "metadata": {"reason": f"已有持仓: {state.position}"}}
        # TODO: 实现入场条件检查
        return {"action": "hold", "price": 0, "strength": 0, "metadata": {"reason": "未满足入场条件"}}

    def check_realtime_exit(self, symbol, current_price, current_time=None, bar_high=None, bar_low=None):
        """出场检查"""
        state = self._get_state(symbol)
        if not state.is_in_position():
            return {"action": "hold", "price": current_price, "strength": 0, "metadata": {"reason": "无持仓"}}
        state.update_pnl_extremes(current_price)
        # TODO: 实现出场条件检查
        return {"action": "hold", "price": current_price, "strength": 0, "metadata": {"reason": "持仓中"}}

    def get_status(self) -> Dict[str, Any]:
        return {
            "symbols": self.symbols,
            "timeframes": self.timeframes,
            "states": {s: self._get_state(s).to_persist_dict() for s in self.symbols},
        }
```

### __init__.py 模板

```python
#!/usr/bin/env python3
"""{策略名称} 策略模块"""

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
    # 其他参数...

  # 信号配置
  signal:
    min_strength: 0.5
    cooldown_ms: 60000

  # 系统字段
  capital:
    max_cash: 100
    max_parts: 1
```

---

## 新旧架构对比

| 对比项 | 旧版（手动实现） | 新版（基类继承） |
|--------|----------------|----------------|
| strategy.py 行数 | ~250 行 | ~35 行 |
| 重复代码 | 大量生命周期、冷却、持久化逻辑 | 基类统一处理 |
| 维护成本 | 每个策略独立维护 | 只维护特有逻辑 |
| 回测兼容 | 手动处理 backtest_mode | 基类自动处理 |

---

## 下一步

- 详细开发规范 → [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)
- 代码模板与 FAQ → [EXAMPLES.md](EXAMPLES.md)
- 提交前检查 → [REVIEW_CHECKLIST.md](REVIEW_CHECKLIST.md)
