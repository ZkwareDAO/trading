# 策略开发规范

> **文档定位**：编写/修改策略代码时的核心参考文档，涵盖基类功能、平仓方法、冷却机制、K 线周期、时间戳、仓位持久化等规范。

---

## 1. 新架构开发规范

> 使用 `BaseStrategy` / `BaseStrategyCore` / `BaseState` 基类开发新策略。

### 1.1 必需实现的抽象方法

| 类 | 抽象方法 | 说明 |
|----|----------|------|
| **Strategy** | `_create_core()` | 创建 Core 实例 |
| **Strategy** | `_get_indicator_timeframes()` | 返回指标周期集合 |
| **Core** | `_get_state(symbol)` | 获取 per-symbol 状态 |
| **Core** | `analyze()` | 入场逻辑（接收 `realtime_price` 参数） |
| **Core** | `check_realtime_exit()` | 出场逻辑 |
| **Core** | `get_status()` | 状态查询 |

> **v3.7.0 新增**：`analyze()` 方法新增 `realtime_price` 参数，用于入场判断时使用 1m K 线实时价格，避免未来函数问题。

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

> **v3.7.1 新增**：入场时必须生成 `position_id`，确保平仓时持久化文件能被正确清理。

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
get_closed_data(klines_data, timeframe, ...) -> DataFrame: ... # 获取已闭合 K 线

# 仓位回调（自动判断 backtest_mode）
_notify_position_enter(symbol, state): ...
_notify_position_exit(symbol, state, exit_price, exit_reason, is_stop_loss, exit_time): ...
_notify_position_update(symbol, state): ...

# 平仓通用方法（v3.6.0 新增）
_notify_exit_and_clear(symbol, state, exit_price, exit_reason, is_stop_loss, exit_time) -> str: ...

# 平仓前钩子（v3.7.0 新增）
_on_before_exit_clear(symbol, state, is_stop_loss) -> None: ...
```

### 1.5 BaseStrategy 已实现功能（无需手动编写）

| 功能 | 说明 |
|------|------|
| on_start() | 注册时间框架、设置回调、恢复状态 |
| on_stop() | 停止运行 |
| on_kline() | 完整 K 线处理流程 |
| K 线冷却 | 同一根入场周期 K 线不重复触发，回测和实盘行为一致 |
| 仓位持久化 | 实盘模式自动持久化，回测时自动禁用 |
| 信号创建 | 自动创建 Signal 对象 |

---

## 2. 平仓方法规范（v3.6.0 新增）

> **关键规范**：所有策略的 `_close` 方法应调用基类 `_notify_exit_and_clear()` 方法。
>
> **v3.7.1 变更**：`_notify_exit_and_clear()` 现在**无条件**调用 `_notify_position_exit`（移除了
> `if state.position_id` 守卫）。这意味着即使策略未设置 `position_id`，持久化文件和
> 历史仓位记录也会被正确清理。前提是入场时正确生成了 `position_id`（见 [Section 1.2](#12-basestate-已包含字段无需重复定义)）。

### 平仓前钩子（v3.7.0 新增）

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
class OBVCoreV2(BaseStrategyCore[OBVStateV2]):
    def _on_before_exit_clear(self, symbol, state, is_stop_loss):
        """平仓前钩子：更新连续盈利递减状态"""
        exit_direction = state.position
        self._update_win_streak(state, is_stop_loss, exit_direction)
        self._persist_win_streak_state(symbol, state)
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

| 冷却类型 | 实现位置 | 说明 |
|----------|----------|------|
| **K 线冷却** | BaseStrategy | 已实现，使用 `cooldown_timeframe`（默认入场时间框架） |
| **止损日冷却** | Core.analyze() | 使用 `state.stop_loss_date` 检查 |

**K 线冷却配置**（策略配置文件）：

```yaml
cta_ict_v3:
  timeframes: ["1d", "4h", "15m"]
  cooldown_timeframe: "15m"  # 可选，默认使用最后一个时间框架（入场时间框架）
```

多时间框架策略（如 ICT: 1d/4h/15m）：
- 入场判断在 15m 上执行
- 冷却也应使用 15m，而非 1d
- 通过 `cooldown_timeframe` 配置项指定

**止损日冷却实现**（Core 类）：

```python
def analyze(self, symbol, klines_data, current_time):
    state = self._get_state(symbol)
    today = current_time.date() if current_time else datetime.now(timezone.utc).date()
    if state.stop_loss_date == today:
        return {"action": "hold", "metadata": {"reason": "今日已触发止损，禁止开仓"}}
```

**止损时自动记录日期**（通过 clear_position）：

```python
def _close(self, symbol, state, price, reason, is_stop_loss=False):
    state.clear_position(record_stop_loss=is_stop_loss)
```

---

## 4. K 线周期处理规范

### 核心原则

| 场景 | 周期 | 数据要求 |
|------|------|----------|
| 入场判断 | 大周期（如 1h, 4h） | 使用 `realtime_price`（来自 1m K 线） |
| 出场判断 | 1m | 使用 `current_price` 参数 |
| 指标计算 | 各指标配置的周期 | 必须使用已闭合 K 线 |

### realtime_price 使用规范（v3.7.0 新增）

`analyze()` 方法签名：

```python
def analyze(
    self,
    symbol: str,
    klines_data: Dict[str, pd.DataFrame],
    current_time: Optional[datetime] = None,
    realtime_price: Optional[float] = None,  # 新增参数
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
    tf_set.add(p.get("obv_timeframes", "1h"))
    tf_set.add(p.get("atr_timeframes", "1h"))
    return tf_set
```

### 多周期分析参数配置（v3.7.0）

多周期策略应使用明确的参数指定各分析的周期，而非依赖 `timeframes` 列表顺序：

```yaml
# strategies/cta_ict_v3/overrides/BTCUSDT.yaml
cta_ict_v3:
  timeframes:
    - 1d
    - 4h
    - 15m
  params:
    # 明确指定各分析的周期
    direction_timeframes: 1d          # 方向确认周期
    market_structure_timeframes: 4h   # 市场结构分析周期
    fvg_timeframes: 15m               # FVG 检测 + 入场周期
```

**参数说明**：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `direction_timeframes` | 大周期方向确认 | `1d` |
| `market_structure_timeframes` | 市场结构分析（HH/HL/LH/LL） | `4h` |
| `fvg_timeframes` | FVG 检测和入场执行 | `15m` |

**代码实现要点**：

```python
class ICTCoreV3(BaseStrategyCore):
    def __init__(self, symbols, timeframes, params):
        p = params or {}
        self.fvg_timeframes = p.get("fvg_timeframes", "15m")
        self.market_structure_timeframes = p.get("market_structure_timeframes", "4h")
        self.direction_timeframes = p.get("direction_timeframes", "1d")

    def _refresh_analysis(self, symbol, klines_data, current_time):
        # 只在指定周期分析市场结构
        ms_timeframes = {self.direction_timeframes, self.market_structure_timeframes}

        # 在指定周期检测 FVG
        fvg_tf = self.fvg_timeframes
```

**修改 4h FVG 配置示例**：

```yaml
# 改用 4h 周期检测 FVG（减少交易频率）
params:
  direction_timeframes: 1d
  market_structure_timeframes: 4h
  fvg_timeframes: 4h  # 改为 4h
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
timestamp=self._current_kline_timestamp or datetime.now(timezone.utc)

# 错误
entry_ts = int(current_time.timestamp() * 1000)  # 毫秒级
timestamp=datetime.now()  # 缺少时区
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
