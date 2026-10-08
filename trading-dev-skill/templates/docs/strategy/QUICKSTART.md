# 策略快速入门

> **文档定位**：新策略开发第一步，涵盖目录结构、代码骨架和配置模板。

---

## Step 0：先完整读一遍参考实现（必做）

本项目自带**两个**参考实现，都是纯 pandas 无 talib 依赖，交易逻辑故意做得很笨——
用途是把**框架契约**演示清楚，不是赚钱：

| 参考实现 | 读哪个场景 |
|----------|-----------|
| [`strategies/example_ma_cross/`](../../strategies/example_ma_cross/) | **先读这个**。单周期双均线交叉，文件最短，框架契约最全（完整入场分支、止损、持久化） |
| [`strategies/example_mtf_trend/`](../../strategies/example_mtf_trend/) | **做多周期策略读这个**。1d 定方向 + 4h 触发 + 1h 确认 + ATR 止损，演示每个周期分别 `get_closed_data()` 的标准写法 |

本文档给的都是占位符骨架，**有相当一部分约定只存在于代码里**——`action` 的合法取值、
入场分支要做哪些事、下单量放在哪个字段。只看文档不看参考实现，写出来的策略大概率
"能启动、不报错、就是不出信号"。**动手前先读完对应参考实现的四个文件，然后照着改**：

```
strategies/example_ma_cross/strategy.py               # Strategy 接口层（最简形态）
strategies/example_ma_cross/example_ma_cross_core.py  # Core 逻辑层
strategies/example_ma_cross/overrides/BTCUSDT.yaml    # per-symbol 配置
strategies/example_ma_cross/tests/                    # 测试写法
```

代码里标 ★ 的注释就是重点：**那些是写错了不会报错、只会静默不发信号的地方**。

> **多周期策略额外必读**：[DEVELOPMENT_GUIDE §4](DEVELOPMENT_GUIDE.md) 的多周期小节
> 和 `example_mtf_trend_core.py` 开头连续三段 `get_closed_data()`——每个周期都要单独
> 取已闭合 K 线、单独做数据不足检查，这是红线 #12。

### 代码地图（按"我现在要写什么"查）

> 行号对应 v3.7.0，改动后可能漂移，以函数名为准。
> 下表 `core.py` = `example_ma_cross_core.py`。

| 我要写… | 看参考实现哪里 | 骨架里看不出来的点 |
|---------|----------------|-------------------|
| **完整入场分支** | `core.py` `_open()` `:127-186` | **入场必须调用 `self._notify_position_enter(symbol, state)`**（`:165`）——漏了仓位根本不落盘，进程一重启就丢 |
| **`action` 合法取值** | 入场 `:172` `"buy"`（开多）/ `"sell"`（开空）；平仓的 action 是 `_notify_exit_and_clear()` 的**返回值**（`_close()` `:188-214`），不要自己拼字符串 | 全集 `buy` / `sell` / `buy_close` / `sell_close`，见 [SIGNAL_CSV_FORMAT.md](../SIGNAL_CSV_FORMAT.md)。拼错的 action 会让基类 `_create_signal()` 返回 None，信号被静默丢弃 |
| **入场要给 state 赋哪些字段** | `:152-163` | `position` / `position_id` / `entry_price` / `entry_time` / `entry_timestamp` / `stop_price` / `peak_price` + 策略特有字段，一个都不能少 |
| **下单量（名义值）** | `:184` `metadata["target_notional"] = (current_cash or 0) * self.leverage` | `current_cash` 由基类从 `capital.max_cash` 传入；**杠杆的坑**：Strategy 层的 `capital.leverage` 不会传给 Core，Core 只能从 `params.leverage` 读（`:95`） |
| **方向过滤** | `:264`、`:274` `self.direction` | 基类从 `params["direction"]` 解析，取值 `neutral` / `long` / `short` |
| **平仓** | `_close()` `:188-214` | 一律走 `_notify_exit_and_clear()`，它一次做完：触发钩子、写历史仓位 CSV、清持久化、清状态、记 `stop_loss_date` |
| **平仓时重置策略特有字段** | State 重写 `clear_position()` `:56-70` | 比在 `_close()` 里逐个重置更可靠：统一风控兜底平仓**不经过**你的 `_close()`，但一定会走到 `clear_position()` |
| **State 定义与持久化** | `:25-70` | `@dataclass` 必须加（`:25`）；缓存字段（`:39-41`）**不写进** `to_persist_dict()` |
| **已闭合 K 线** | `analyze()` `:235-239` | `get_closed_data(min_rows=N)` **不保证**返回 N 行——它只拦"原始数据不足"，过滤掉未闭合 bar 之后可能还是不够，所以 `:239` 要再判一次 `len()` |
| **入场价** | `:256-259` | 优先 `realtime_price`（1m 实时价），退回已闭合收盘价；绝不能用大周期最后一根未闭合 bar |
| **`klines_data` 的 DataFrame 结构** | `tests/test_example_ma_cross_core.py` `make_klines()` | 列名：`timestamp`（是**列**不是 index）/ `open` / `high` / `low` / `close` / `volume` |
| **出场检测价** | `check_realtime_exit()` `:309-310` | 用基类 `_get_exit_detection_prices()` 拿 `(check_high, check_low)`，别直接拿 `current_price` 比 |
| **统一风控怎么接** | `overrides/BTCUSDT.yaml` 的 `risk` 段 | 策略 `check_realtime_exit()` 返回 hold 之后，基类会接着查 `check_risk_control()` 兜底。回落止盈、固定止盈不用自己写 |
| **指标计算** | `core.py` `_compute_ma()` `:121-125` | 基类另有 `calculate_adx` / `calculate_bollinger`（`from strategy_core.base import calculate_adx`），能复用就别重写 |
| **多周期怎么写** | **[`example_mtf_trend/`](../../strategies/example_mtf_trend/) 全套** | 1d/4h/1h 三周期：每个周期单独 `get_closed_data()` + 单独数据检查；`strategy.py` 把三个 `*_timeframes` 都收集进订阅集合 |
| **测试怎么写** | `tests/test_example_ma_cross_core.py`（322 行）、`tests/test_strategy_logging.py`（112 行） | 运行：`python3 -m pytest strategies/example_ma_cross/tests/ -v` |
| **配置有哪些字段** | `overrides/BTCUSDT.yaml`（逐条带注释） | 配置三层模型见 [CONFIG_UNIFICATION_SPEC.md](../CONFIG_UNIFICATION_SPEC.md) |
| **策略规格文件** | `.strategy-spec.yaml`（两个参考实现各有一份） | 字段 schema 见 [STRATEGY_SPEC.md](STRATEGY_SPEC.md) |

### ⚠️ 一个必须先搞清楚的框架行为

基类 `on_kline()` 的默认节奏是 **每根 1m K 线都走一遍**：

- 有持仓 → 调 `check_realtime_exit()`（每分钟检查出场）
- 无持仓 → 调 `analyze()`（**每分钟**尝试入场，不是每根 4h 才调一次）

这不是 bug：指标用 `get_closed_data()` 取已闭合大周期 K 线（没有未来函数），
入场价用 `realtime_price`，所以条件一成立就能进场，不必等大周期收线。

如果你的策略要求"只在大周期闭合的那一分钟才判断入场"，**必须自己重写 `on_kline()`**
加闭合边界判断——参考写法见 `strategy.py` 文件末尾的附录注释。

> 下文"最简 strategy.py 约 35 行"指的就是不重写 `on_kline()` 的情形。
> 参考实现的 `strategy.py` 是 100 行，多出来的基本都是注释。

---

## 开发流程

```
Step 0: 读完参考实现 strategies/example_ma_cross/
   ↓
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
├── .strategy-spec.yaml      # 策略规格（可选，逻辑确认阶段产物，schema 见 [STRATEGY_SPEC.md](STRATEGY_SPEC.md)）
├── overrides/               # per-symbol 参数配置（必需）
│   └── {SYMBOL}.yaml        # 如 BTCUSDT.yaml，一个交易对一个文件
└── tests/
    ├── __init__.py                # 必需！见下方说明
    ├── test_{prefix}_core.py      # 核心逻辑测试
    └── test_strategy_logging.py   # 信号日志测试
```

> **`tests/__init__.py` 不能省。** 每个策略的测试目录里都有一个同名的
> `test_strategy_logging.py`，缺了这个空文件，pytest 在同时收集两个策略的测试时会因
> basename 冲突直接报错退出（`import file mismatch`）。加上它，模块名带上策略目录名
> 前缀就不会撞。参考实现里已经放好了，照抄目录结构即可。

**策略目录内不放 config.yaml**。配置分两层入口：

| 文件 | 作用 |
|------|------|
| `config/strategies.yaml` | 策略登记表：策略名 + `symbols` + `trading_mode` |
| `strategies/{name}/overrides/{SYMBOL}.yaml` | per-symbol 策略参数（周期、指标参数、资金、风控） |
| `config/settings.yaml` | 系统级配置（数据管理、信号、直连下单），一般无需改 |

**命名规范**：
- `{strategy_name}`: 策略目录名，如 `my_cta_v1`
- `{prefix}`: 核心文件前缀，与目录名一致，如 `my_cta_v1_core.py`
- 类名前缀（如目录名 `my_cta_v1` → `MyCtaV1Core`）由框架自动推导，**无需定义 `STRATEGY_PREFIX`**（见 `strategy_core/utils/strategy_naming.py`）

---

## 基类继承模式

> 使用 `BaseStrategy` / `BaseStrategyCore` / `BaseState` 基类，策略类只需实现特有逻辑，
> 生命周期、仓位持久化、统一风控接线等均由基类统一处理。
> （**入场 K 线冷却不在其中**，见 [DEVELOPMENT_GUIDE §1.5 的警告](DEVELOPMENT_GUIDE.md#15-basestrategy-已实现功能无需手动编写)）

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
    DEFAULT_TIMEFRAME = "4h"               # 默认主周期（overrides 的 timeframes 优先）

    # ========== 必需抽象方法 ==========

    def _create_core(self):
        """创建核心逻辑实例"""
        return {Prefix}Core(
            symbols=self.symbols,
            timeframes=self.timeframes,
            params=self.params,
            global_config=self._get_global_config(),
        )

    def _get_indicator_timeframes(self) -> set:
        """收集所有指标使用的 K 线周期"""
        tf_set = set(self.timeframes)
        p = self.params or {}
        tf_set.add(p.get("{indicator}_timeframes", "4h"))
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

    def __init__(
        self,
        symbols: List[str],
        timeframes: List[str],
        params: Optional[Dict[str, Any]] = None,
        global_config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(symbols, timeframes, params, global_config)

    def _get_state(self, symbol: str) -> {Prefix}State:
        if symbol not in self._state:
            self._state[symbol] = {Prefix}State()
        return self._state[symbol]

    def analyze(self, symbol, klines_data, current_time=None,
                realtime_price=None, current_cash=None):
        """入场分析

        - 指标只用 get_closed_data() 取已闭合 K 线计算
        - 入场价格优先用 realtime_price（1m K 线实时价），避免未来函数
        """
        state = self._get_state(symbol)
        if state.is_in_position():
            return {"action": "hold", "price": 0, "strength": 0, "metadata": {"reason": f"已有持仓: {state.position}"}}
        closed = self.get_closed_data(klines_data, self.timeframes[0], min_rows=50, current_time=current_time)
        if closed.empty:
            return {"action": "hold", "price": 0, "strength": 0, "metadata": {"reason": "K线数据不足"}}
        # TODO: 用 closed 计算指标，用 realtime_price 判断入场价格
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

**第一步：在 `config/strategies.yaml` 登记策略**（决定跑哪些标的、什么模式）：

```yaml
strategies:
  {strategy_name}:
    trading_mode: "paper_trading"   # live / paper_trading / smoking
    symbols:
      - BTCUSDT
```

**第二步：为每个标的创建 `strategies/{strategy_name}/overrides/BTCUSDT.yaml`**（策略参数唯一事实来源）：

```yaml
{strategy_name}:
  enabled: true
  version: '1'
  trading_mode: "paper_trading"
  direction: neutral

  # 标的与周期
  symbols:
    - BTCUSDT
  timeframes:
    - 4h

  # 策略参数：每个指标必须配置 *_timeframes
  params:
    {indicator}_timeframes: 4h
    # 其他策略参数...

  # 信号配置
  signal:
    min_strength: 0.5
    cooldown_ms: 0

  # 资金字段
  capital:
    max_cash: 200
    max_parts: 1
    leverage: 1

  # 统一风控（基类兜底，策略 check_realtime_exit() 返回 hold 后生效）
  # 百分比用数值形式：20 表示 20%
  risk:
    enabled: true
    fixed_stop_loss_pct: 5.0
    trailing_profit:
      enabled: true
      activation_pct: 3.0
      drawdown_pct: 20.0
    fixed_take_profit_pct: 0.0

  user_id: 1
```

> **不要写 `cooldown_timeframe` / `cooldown_bars` / `cooldown_ms`** —— 三者都是死配置，
> 代码里没有任何地方读取（`cooldown_ms` 只被赋值从未使用），写了不会生效。
> `interval`（timeframes[0]）、`version`、`trading_mode` 都从本文件读取，
> `run_strategy.py` 的 `--interval/--version/--trading-mode` 仅作可选覆盖。

---

## 下一步

- 详细开发规范 → [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)
- 常见问题与踩坑排查 → [EXAMPLES.md](EXAMPLES.md)（可复制代码看两个参考实现）
- 提交前检查 → [REVIEW_CHECKLIST.md](REVIEW_CHECKLIST.md)
