# 策略开发规范

> **文档定位**：编写/修改策略代码时的核心参考文档，涵盖基类功能、平仓方法、冷却机制、K 线周期、时间戳、仓位持久化等规范。

---

## 1. 开发规范

> 所有策略基于 `BaseStrategy` / `BaseStrategyCore` / `BaseState` 基类开发。

### 1.1 必需实现的抽象方法

| 类 | 抽象方法 | 说明 |
|----|----------|------|
| **Strategy** | `_create_core()` | 创建 Core 实例 |
| **Strategy** | `_get_indicator_timeframes()` | 返回指标周期集合 |
| **Core** | `_get_state(symbol)` | 获取 per-symbol 状态 |
| **Core** | `analyze()` | 入场逻辑（接收 `realtime_price`、`current_cash` 参数） |
| **Core** | `check_realtime_exit()` | 出场逻辑 |
| **Core** | `get_status()` | 状态查询 |

> `analyze()` 的 `realtime_price` 参数为入场判断价格（来自 1m K 线实时价），避免使用未闭合 K 线造成未来函数。

### 1.2 BaseState 已包含字段（无需重复定义）

继承 `BaseState` 后自动获得以下字段：

```python
position: Optional[str] = None        # 'long', 'short', None
position_id: Optional[str] = None      # 仓位唯一标识
entry_timestamp: Optional[int] = None  # 开仓时间戳（秒）
entry_price: float = 0.0               # 开仓价格
entry_time: Optional[datetime] = None  # 开仓时间
peak_price: float = 0.0                # 峰值价格
stop_price: float = 0.0                # 止损价格
stop_loss_date: Optional[date] = None  # 止损日期（冷却机制）
max_pnl_pct: float = 0.0               # 最大盈利百分比（>0）
min_pnl_pct: float = 0.0               # 最大亏损百分比（<0）
```

> 入场时必须生成 `position_id`，确保平仓时持久化文件能被正确清理。

```python
from strategy_core.position_persistence import PositionPersistence

# 在 analyze() 入场分支中：
entry_ts = int(current_time.timestamp())
state.position_id = PositionPersistence.generate_position_id(
    self._strategy_name, symbol, entry_ts
)
```

### 1.3 BaseState 已包含方法

```python
def is_in_position(self) -> bool: ...                    # 判断是否持仓
def clear_position(self, record_stop_loss=False, ...): ... # 清除持仓
def to_persist_dict(self) -> Dict[str, Any]: ...         # 持久化
def restore_from_dict(self, data: Dict[str, Any]): ...   # 恢复
def update_pnl_extremes(self, current_price: float): ... # 更新盈亏极值
```

### 1.4 BaseStrategyCore 已包含方法

```python
# 工具方法
parse_interval_to_minutes(interval: str) -> int: ...     # 解析周期为分钟数
get_expected_last_closed_timestamp(...) -> datetime: ... # 计算期望闭合时间
get_closed_data(klines_data, timeframe, min_rows, current_time) -> DataFrame: ...
# ↑ min_rows 只拦"原始数据不足"，过滤未闭合 bar 后可能仍不够，
#   拿到结果后必须再判一次 if df.empty or len(df) < N

_get_exit_detection_prices(current_price, bar_high, bar_low) -> tuple: ...
# ↑ 返回 (check_high, check_low)。出场判断用它，别直接拿 current_price 比

check_risk_control(symbol, current_price) -> Optional[ExitSignal]: ...
# ↑ 统一风控，基类在策略出场返回 hold 后自动调用，策略侧一般不用管

# 仓位回调（自动判断 backtest_mode）
_notify_position_enter(symbol, state): ...   # ★ 入场时必须调用，否则仓位不落盘
_notify_position_exit(symbol, state, exit_price, exit_reason, is_stop_loss, exit_time): ...
_notify_position_update(symbol, state): ...

# 平仓通用方法（一次做完：触发钩子 → 写历史仓位 → 清持久化 → 清状态 → 记止损日）
_notify_exit_and_clear(...) -> str: ...      # 返回 "sell_close"（平多）/ "buy_close"（平空）

# 平仓前钩子
_on_before_exit_clear(symbol, state, is_stop_loss) -> None: ...
```

> **主周期是 `timeframes[0]`**，不是最后一个。基类的 `self.main_timeframe`
> 就取 `timeframes[0]`（`strategy.py:93`）。多周期策略请用显式的
> `*_timeframes` 参数指定各指标周期，不要依赖列表顺序。

### 1.5 BaseStrategy 已实现功能（无需手动编写）

| 功能 | 说明 |
|------|------|
| on_start() | 注册时间框架、设置回调、恢复状态、自动补历史数据 |
| on_stop() | 停止运行 |
| on_kline() | 完整 K 线处理流程 |
| 平仓信号去重 | 同一根 1m K 线内不重复发平仓信号（`_last_exit_signal_time`） |
| 统一风控兜底 | 策略 `check_realtime_exit()` 返回 hold 后，自动检查 `risk` 段配置的止损/回落止盈 |
| 仓位持久化 | 实盘模式自动持久化，回测时自动禁用 |
| 信号创建 | 自动创建 Signal 对象（`action` 不在白名单内会返回 None，信号被静默丢弃） |

> ### ⚠️ 基类**没有**入场侧 K 线冷却
>
> 基类默认 `on_kline()`（`strategy_core/base/strategy.py:373-452`）的节奏是**每根 1m K 线走一遍**：
> 有持仓 → `check_realtime_exit()`；无持仓 → `analyze()`。
> **`analyze()` 是每分钟被调用的，不是每根大周期才调一次。**
>
> 这不是缺陷：指标用 `get_closed_data()` 取已闭合大周期 K 线（无未来函数），
> 入场价用 `realtime_price`，所以条件一成立就能进场，不必等收线。
>
> 如果你的策略要求"只在大周期闭合的那一分钟才判断入场"，**必须自己重写 `on_kline()`**
> 加闭合边界判断，参考写法见 `strategies/example_ma_cross/strategy.py` 文件末尾附录。
> 自己实现的冷却记得在回测模式跳过（`self._backtest_mode`）。

---

## 2. 平仓方法规范

> **关键规范**：所有策略的 `_close` 方法应调用基类 `_notify_exit_and_clear()` 方法。
>
> `_notify_exit_and_clear()` **无条件**调用 `_notify_position_exit`：即使策略未设置
> `position_id`，持久化文件和历史仓位记录也会被清理。前提是入场时正确生成了
> `position_id`（见 [Section 1.2](#12-basestate-已包含字段无需重复定义)）。

### 平仓前钩子

`BaseStrategyCore` 提供 `_on_before_exit_clear` 钩子方法，子类可重写以在平仓时执行特有逻辑：

```python
def _on_before_exit_clear(self, symbol: str, state: StateType, is_stop_loss: bool) -> None:
    """
    平仓前钩子（在状态清除之前调用）

    无论平仓路径如何（策略特有/统一风控），都会触发此钩子。

    Args:
        symbol: 交易标的
        state: 仓位状态对象
        is_stop_loss: 是否止损平仓
    """
    # 默认空实现，子类可选重写
    pass
```

**使用场景**：
- 更新连续盈利递减状态
- 记录平仓时的特有指标
- 执行策略特有的平仓后处理

**示例**：

```python
class {Prefix}Core(BaseStrategyCore[{Prefix}State]):
    def _on_before_exit_clear(self, symbol, state, is_stop_loss):
        """平仓前钩子：执行策略特有的平仓前处理"""
        exit_direction = state.position
        self._update_custom_state(state, is_stop_loss, exit_direction)
        self._persist_custom_state(symbol, state)
```

### 标准平仓方法模板

```python
def _close(
    self, symbol: str, state: {Prefix}State, price: float,
    reason: str, is_stop_loss: bool = False, current_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """平仓"""
    action = self._notify_exit_and_clear(
        symbol=symbol, state=state, exit_price=price,
        exit_reason=reason, is_stop_loss=is_stop_loss, exit_time=current_time,
    )
    # 重置策略特有字段（在清除状态之后）
    state.my_special_field = 0.0
    return {
        "action": action, "price": price, "strength": 0.8,
        "metadata": {"reason": reason, "is_stop_loss": is_stop_loss},
    }
```

### 特有字段保存（在清除状态前）

如果策略需要在清除状态后使用特有字段，必须在调用基类方法前保存：

```python
def _close(self, symbol, state, price, reason, is_stop_loss, current_time):
    my_special_field = state.my_special_field  # 先保存
    action = self._notify_exit_and_clear(...)
    if my_special_field and is_stop_loss:
        # 处理特有逻辑
        pass
    return {...}
```

### 嵌套对象字段处理

如果 State 包含嵌套对象（如 FVG、PriceLines），需要：

1. **定义嵌套类**：实现 `to_dict()` 方法
2. **State.to_persist_dict()**：序列化嵌套对象
3. **State.restore_from_dict()**：反序列化嵌套对象

```python
@dataclass
class FVG:
    type: str; high: float; low: float; midline: float; index: int; filled: bool = False
    def to_dict(self) -> dict:
        return {"type": self.type, "high": self.high, "low": self.low,
                "midline": self.midline, "index": self.index, "filled": self.filled}

@dataclass
class MyState(BaseState):
    entry_fvg: Optional[FVG] = None

    def to_persist_dict(self) -> dict:
        data = super().to_persist_dict()
        if self.entry_fvg:
            data["entry_fvg"] = self.entry_fvg.to_dict()
        return data

    def restore_from_dict(self, data: dict) -> None:
        super().restore_from_dict(data)
        fvg_data = data.get("entry_fvg")
        if fvg_data:
            self.entry_fvg = FVG(**fvg_data)
```

### `_hold_result` 方法说明

`_hold_result` 是策略私有方法，签名由策略自行决定：

```python
# 简单签名
def _hold_result(self, reason: str) -> Dict[str, Any]: ...
# 带 price 参数
def _hold_result(self, price: float, reason: str) -> Dict[str, Any]: ...
# 带 state 参数（用于输出缓存指标）
def _hold_result(self, state, price: float, reason: str) -> Dict[str, Any]: ...
```

### 出场检查方法规范

`check_realtime_exit()` 方法开头**必须**调用 `update_pnl_extremes()`：

```python
def check_realtime_exit(self, symbol, current_price, current_time=None, bar_high=None, bar_low=None):
    state = self._get_state(symbol)
    if not state.is_in_position():
        return {"action": "hold", "price": current_price, "strength": 0, "metadata": {"reason": "无持仓"}}
    state.update_pnl_extremes(current_price)  # 必需
    # ...
```

---

## 3. 冷却机制规范

| 冷却类型 | 实现位置 | 状态 |
|----------|----------|------|
| **止损日冷却** | Core.analyze() | 需自己写：检查 `state.stop_loss_date`；止损日期由基类在 `is_stop_loss=True` 时自动记录 |
| **平仓信号去重** | BaseStrategy | 基类已实现：同一根 1m K 线内不重复发平仓信号 |
| **入场 K 线冷却** | — | **基类没有**，见 [§1.5 的警告](#15-basestrategy-已实现功能无需手动编写) |

> **`cooldown_timeframe` / `cooldown_bars` / `cooldown_ms` 是死配置。**
> 前两个在代码里零引用；`cooldown_ms` 只在 `strategy.py:106` 被赋值给 `self.cooldown_ms`，
> 之后从未被读取。overrides 里写了也不生效，不要依赖它们做冷却。

**需要"一根大周期只入场一次"怎么办**：重写 `on_kline()`，在入场分支前加闭合边界判断
（`strategies/example_ma_cross/strategy.py` 末尾有可直接复制的实现）。这样天然满足
"一根 K 线最多触发一次"，且不需要额外的冷却状态。

**止损日冷却实现**（Core 类）：

```python
def analyze(self, symbol, klines_data, current_time, realtime_price=None, current_cash=None):
    state = self._get_state(symbol)
    if current_time is None:
        return {"action": "hold", "price": 0, "strength": 0,
                "metadata": {"reason": "K线时间缺失"}}
    if state.stop_loss_date == current_time.date():
        return {"action": "hold", "price": 0, "strength": 0,
                "metadata": {"reason": "今日已触发止损，禁止开仓"}}
```

> 禁止用 `datetime.now()` 推算止损日——回测时必须以 K 线时间为准（见 [AI_CONSTRAINTS.md](AI_CONSTRAINTS.md) 红线 #6）。

**止损时自动记录日期**（统一走 `_notify_exit_and_clear()`，内部在 `is_stop_loss=True` 时记录 `stop_loss_date`）：

```python
def _close(self, symbol, state, price, reason, is_stop_loss=False, current_time=None):
    return self._notify_exit_and_clear(
        symbol=symbol, state=state, exit_price=price,
        exit_reason=reason, is_stop_loss=is_stop_loss, exit_time=current_time,
    )
```

---

## 4. K 线周期处理规范

### 核心原则

| 场景 | 周期 | 数据要求 |
|------|------|----------|
| 入场判断 | 大周期（如 1h, 4h） | 使用 `realtime_price`（来自 1m K 线） |
| 出场判断 | 1m | 使用 `current_price` 参数 |
| 指标计算 | 各指标配置的周期 | 必须使用已闭合 K 线 |

### realtime_price 使用规范

`analyze()` 方法签名：

```python
def analyze(
    self,
    symbol: str,
    klines_data: Dict[str, pd.DataFrame],
    current_time: Optional[datetime] = None,
    realtime_price: Optional[float] = None,  # 新增参数
    current_cash: Optional[float] = None,    # 当前可用资金（动态资金计算用）
) -> Dict[str, Any]:
```

**参数说明**：

| 参数 | 来源 | 说明 |
|------|------|------|
| `realtime_price` | Strategy 传入 | 1m K 线收盘价，用于入场价格判断 |
| `klines_data` | DataManager | 多时间框架 K 线数据，用于指标计算 |

**使用场景**：

```python
def analyze(self, symbol, klines_data, current_time, realtime_price):
    # 1. 使用已闭合 K 线计算指标
    closed_4h = self.get_closed_data(klines_data, "4h", min_rows=30, current_time=current_time)
    adx = self._calculate_adx(closed_4h)  # 使用已闭合数据

    # 2. 使用 realtime_price 判断入场价格
    if realtime_price is not None and realtime_price > 0:
        current_price = realtime_price  # 优先使用实时价格
    elif not closed_4h.empty:
        current_price = float(closed_4h["close"].iloc[-1])  # 回退到已闭合 K 线
    else:
        return self._hold_result("数据不足")

    # 3. 入场条件判断
    if current_price > upper_rail:
        return self._create_entry("buy", current_price, ...)
```

**重要规则**：

1. **优先使用 `realtime_price`**：避免使用未闭合 K 线收盘价（未来函数）
2. **回退到已闭合 K 线**：当 `realtime_price` 为空时使用 `get_closed_data()`
3. **指标计算仍用已闭合 K 线**：技术指标不能使用实时价格

### 多周期策略处理（重要）

> **关键**：多周期策略必须对**每个时间框架**单独调用 `get_closed_data()` 获取已闭合 K 线。

```python
def _check_entry(self, symbol, state, klines_data, current_price, current_time):
    closed_4h = self.get_closed_data(klines_data, "4h", min_rows=30, current_time=current_time)
    closed_1h = self.get_closed_data(klines_data, "1h", min_rows=50, current_time=current_time)
    closed_15m = self.get_closed_data(klines_data, "15m", min_rows=20, current_time=current_time)

    if closed_4h.empty or closed_1h.empty or closed_15m.empty:
        return self._hold_result("数据不足")
```

### 指标周期配置

每个使用的指标必须在配置中声明周期，并在 Strategy 中收集：

```python
def _get_indicator_timeframes(self) -> set:
    tf_set = set(self.timeframes)
    p = self.params or {}
    tf_set.add(p.get("indicator_a_timeframes", "4h"))
    tf_set.add(p.get("indicator_b_timeframes", "4h"))
    return tf_set
```

### 多周期分析参数配置

多周期策略应使用明确的参数指定各分析的周期，而非依赖 `timeframes` 列表顺序：

```yaml
# strategies/<name>/overrides/<SYMBOL>.yaml
{strategy_name}:
  timeframes:
    - 4h
  params:
    # 明确指定各分析的周期（参数名由策略自定义）
    indicator_a_timeframes: 4h       # 指标 A 周期
    indicator_b_timeframes: 4h       # 指标 B 周期
    tracking_timeframe: 1h           # 跟踪止损周期（可比入场周期更短）
```

**参数说明**：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `{indicator}_timeframes` | 各指标的分析周期（由策略定义） | `timeframes[0]` |
| `tracking_timeframe` | 跟踪止损周期（可比入场周期更短，参数名由策略自定义） | `timeframes[0]` |

**代码实现要点**（`_get_indicator_timeframes()` 属于 **Strategy 类**，不是 Core）：

```python
class Strategy(BaseStrategy):
    STRATEGY_TYPE = "{strategy_name}"

    def _create_core(self):
        return {Prefix}Core(
            symbols=self.symbols,
            timeframes=self.timeframes,
            params=self.params,
            global_config=self._get_global_config(),
        )

    def _get_indicator_timeframes(self) -> set:
        # 指标周期集合 = timeframes ∪ 各 *_timeframes 参数
        tf_set = set(self.timeframes)
        p = self.params or {}
        tf_set.add(p.get("indicator_a_timeframes", "4h"))
        tf_set.add(p.get("indicator_b_timeframes", "4h"))
        tf_set.add(p.get("tracking_timeframe", "4h"))
        return tf_set
```

> Core 类只在 `__init__` 中从 `params` 读取各参数值（如
> `self.tracking_timeframe = p.get("tracking_timeframe", timeframes[0])`），
> 不负责声明订阅周期。

**修改指标周期配置示例**：

```yaml
# strategies/<name>/overrides/<SYMBOL>.yaml
# 跟踪止损改用 1h（比入场周期更频繁地更新止损）
timeframes:
  - 4h
params:
  tracking_timeframe: 1h
```

---

## 5. 时间戳处理规范

| 规则 | 说明 |
|------|------|
| 时区 | 统一使用 UTC |
| entry_timestamp | 秒级时间戳（10 位数字） |
| 信号时间戳 | 使用 K 线时间，而非 `datetime.now()` |

```python
# 正确
entry_ts = int(current_time.timestamp())  # 秒级
timestamp=self._current_kline_timestamp   # 用 K 线时间；为 None 时应跳过信号，而非回退 now()

# 错误
entry_ts = int(current_time.timestamp() * 1000)  # 毫秒级
timestamp=datetime.now(timezone.utc)             # 禁止：信号时间戳必须可重现
```

---

## 6. 仓位持久化规范（实盘模式）

实盘策略必须实现仓位持久化，基类 `BaseStrategy._on_position_exit()` 自动调用 `HistoryPositionLogger`。

### 持久化文件位置

| 类型 | 文件位置 | 说明 |
|------|----------|------|
| 当前仓位 | `data/positions/{strategy_name}.json` | 实盘运行时仓位状态 |
| 历史仓位 | `data/history_positions/{strategy_name}/{YYYYMMDD}.csv` | 每次平仓记录 |

### 历史仓位 CSV 字段

| 字段 | 说明 |
|------|------|
| position_id | 仓位唯一标识 |
| strategy_name / symbol | 策略名称 / 交易标的 |
| position_type | 'long' / 'short' |
| entry_price / exit_price | 开仓价格 / 平仓价格 |
| entry_time / exit_time | 开仓时间 / 平仓时间 |
| entry_timestamp / exit_timestamp | 开仓时间戳（秒）/ 平仓时间戳（秒） |
| peak_price / stop_price | 持仓期间最高/最低价 / 止损价格 |
| max_pnl_pct / min_pnl_pct | 持仓期间最大盈利百分比 / 最大亏损百分比 |
| exit_reason / is_stop_loss | 平仓原因 / 是否止损 |
| price_diff / pnl_pct | 价格差 / 盈亏百分比 |
| atr_at_entry / trail_activated | 入场时 ATR / 是否触发移动止盈 |
| duration_seconds | 持仓时长（秒） |
