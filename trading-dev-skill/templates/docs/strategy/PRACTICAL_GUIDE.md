# 策略实战开发注意事项

> **文档定位**：策略开发规范补充。涵盖 K 线使用、开仓检查、止盈止损、配置说明、State 设计等关键注意事项。与 AI_CONSTRAINTS.md 配合使用——本文说"怎么做"，CONSTRAINTS 说"不能做"。

---

## 1. K 线数据使用

### 1.1 已闭合 K 线

实盘推送 1m K 线，大周期（4h、1d）最后一根可能未闭合。用未闭合数据入场 = 未来函数 = 回测失真。

```python
# ✅ 正确
closed_4h = self.get_closed_data(klines_data, "4h", min_rows=50, current_time=current_time)
if closed_4h.empty:
    return self._hold_result("4h 已闭合 K 线数据不足")

# ❌ 错误
df = klines_data["4h"]  # 最后一根可能未闭合
```

### 1.2 多周期策略

每个时间框架必须独立调用 `get_closed_data()`，不能混用：

```python
closed_1d = self.get_closed_data(klines_data, "1d", min_rows=30, current_time=current_time)
closed_4h = self.get_closed_data(klines_data, "4h", min_rows=50, current_time=current_time)
closed_15m = self.get_closed_data(klines_data, "15m", min_rows=100, current_time=current_time)
```

### 1.3 开仓/平仓的 K 线周期与价格字段

**核心规则：所有策略的 K 线推送周期都是 1m。** 无论策略使用什么时间框架（4h/1d/15m），BaseStrategy 的 `on_kline()` 每根 1m K 线都会触发。

#### 开仓（`analyze` 调用链）

| 阶段 | K 线周期 | 价格字段 | 说明 |
|------|---------|---------|------|
| 触发 | 1m | `kline.close` | `_parse_kline_price()` 取 close，传入 `realtime_price` |
| 技术指标 | 各 `*_timeframes` | OHLCV | `get_closed_data()` 获取已闭合 K 线 |
| 入场判断 | 1m | `realtime_price`（即 1m close） | 用实时价格判断是否满足入场条件 |
| 入场执行价 | — | 策略自定义 | 如 FVG midline、ATR 偏移价等，**不是 close/open** |

**关键点**：`realtime_price` 来自 1m K 线的 **close**，不是 open。因为 1m K 线推送时该 K 线已闭合（或接近闭合），close 代表当前最新成交价。

#### 平仓（`check_realtime_exit` 调用链）

| 阶段 | K 线周期 | 价格字段 | 说明 |
|------|---------|---------|------|
| 触发 | 1m | `kline.close` | 同开仓，每根 1m 都触发出场检查 |
| 止损/止盈检测 | 1m | `bar_high` / `bar_low` | K 线内极值，比 close 更准确 |
| 止损执行价 | 1m | `current_price`（即 1m close） | 平仓信号中 price = current_price |

**为什么用 bar_high/bar_low 检测止损**：K 线内价格可能瞬间穿过止损位后回弹，close 可能未触发但实际已穿过。用 high/low 检测更准确，避免漏触。

```python
# BaseStrategy._parse_kline_price() 取的是 close
current_price = self._parse_kline_price(kline)  # → kline.close
bar_high = self._parse_kline_high(kline)         # → kline.high
bar_low = self._parse_kline_low(kline)           # → kline.low

# 出场检测时用 high/low
check_high, check_low = self._get_exit_detection_prices(current_price, bar_high, bar_low)
```

#### 总结

| 操作 | 触发周期 | 判断价格 | 执行价格 |
|------|---------|---------|---------|
| 开仓 | 1m | 1m close（`realtime_price`） | 策略自定义（如 FVG midline） |
| 平仓-止损检测 | 1m | 1m high/low（`bar_high`/`bar_low`） | 1m close（`current_price`） |
| 平仓-止盈检测 | 1m | 1m high/low（`bar_high`/`bar_low`） | 1m close（`current_price`） |

### 1.4 realtime_price 入场判断

`analyze()` 接收 `realtime_price` 参数，用于 1m 实时价格判断入场，避免未来函数。

```python
def analyze(self, symbol, klines_data, current_time=None, realtime_price=None):
    price = float(realtime_price or 0.0)
    # 用 price 做入场判断，用 closed 数据算指标
```

### 1.5 min_rows 计算

`min_rows` 取决于指标参数，不能硬编码：

```
min_rows = max(最长指标周期 + 回看窗口, 次长指标周期 × 安全系数)
```

安全系数一般取 3-4，确保指标充分预热。

### 1.5 信号边界过滤

当信号时间框架 > 1m 时，1m K 线推送中大部分不需要处理。实现边界过滤可减少无意义计算：

```python
@staticmethod
def _is_signal_boundary(timestamp) -> bool:
    """判断是否为信号时间框架的K线边界"""
    if timestamp is None or not hasattr(timestamp, "minute"):
        return True
    # 根据策略周期实现：如2h/4h/15m的边界判断
    ...
```

**何时需要**：策略信号时间框架 > 1m 时建议实现。

---

## 2. 开仓逻辑

### 2.1 开仓前必须检查的状态（按优先级）

```python
def analyze(self, symbol, klines_data, current_time=None, realtime_price=None):
    state = self._get_state(symbol)

    # 1. 已有持仓 → hold
    if state.is_in_position():
        return self._hold_result("已有持仓")

    # 2. current_time 为空 → hold
    if current_time is None:
        return self._hold_result("current_time is required")

    # 3. 止损日冷却 → hold
    if state.stop_loss_date == current_time.date():
        return self._hold_result("今日已触发止损")

    # 4. 数据不足 → hold
    # 5. 指标无效 → hold
    # 6. 方向过滤 → hold
    ...
```

### 2.2 开仓时必须设置的字段

```python
state.position = side                       # "long" 或 "short"
state.entry_timestamp = int(current_time.timestamp())  # 秒级时间戳
state.entry_time = current_time
state.entry_price = execution_price
state.peak_price = execution_price
state.stop_price = ...                      # 止损价
```

### 2.3 开仓价格选择

`realtime_price` 来自 1m K 线的 **close**（`_parse_kline_price()` 取 `kline.close`）。

入场判断用 `realtime_price`（1m close），入场执行价由策略自定义：

```python
# 入场判断：用 realtime_price（1m close）判断是否满足条件
if condition_met(realtime_price):
    # 入场执行价：策略自定义，不一定是 close
    execution_price = fvg.midline  # 如 ICT 策略用 FVG 中线
    # 或
    execution_price = realtime_price  # 简单策略直接用 1m close
```

**常见入场执行价选择**：

| 策略类型 | 入场执行价 | 说明 |
|---------|-----------|------|
| 简单趋势 | `realtime_price`（1m close） | 当前价直接入场 |
| ICT/FVG | `fvg.midline` | FVG 中线入场 |
| ATR 偏移 | `realtime_price ± ATR * n` | ATR 偏移挂单 |

### 2.4 方向过滤

| 配置值 | 效果 |
|--------|------|
| `neutral` | 多空双向 |
| `long` | 只做多 |
| `short` | 只做空 |

```python
def _direction_allowed(self, side: str) -> bool:
    direction = str(self.direction or "neutral").lower()
    return direction in ("neutral", "both", "all", side)
```

---

## 3. 止盈止损逻辑

### 3.1 两套止盈止损系统

项目有 **两套** 止盈止损系统，可叠加使用：

**系统 A：策略自定义（Core 中实现）**

在 `check_realtime_exit()` 中实现策略特有的止损逻辑（如 ATR 止损、追踪止损）。

**系统 B：统一风控（RiskController，config.yaml 配置）**

```yaml
risk:
  enabled: true
  fixed_stop_loss_pct: 20.0        # 固定止损：亏损 20% 平仓
  trailing_profit:
    enabled: true
    activation_pct: 50.0            # 盈利 50% 激活回落止盈
    drawdown_pct: 5.0               # 从最大盈利回落 5% 平仓
  fixed_take_profit_pct: 0.0        # 固定止盈（0 = 禁用）
```

**优先级**：固定止损 > 回落止盈 > 固定止盈

两套系统可以同时生效。策略自定义止损在 `check_realtime_exit` 中检测，RiskController 的止损由基类在 `_check_exit` 中调用。

### 3.2 ATR 止损实现模板

开仓时设置止损价：

```python
is_long = side == "long"
state.stop_price = entry_price + (-1 if is_long else 1) * (atr_multiplier * atr_value)
state.initial_stop_price = state.stop_price  # 保存初始止损价
```

追踪止损（可选）——只往有利方向移动：

```python
if is_long:
    new_stop = current_price - trailing_multiplier * current_atr
    state.stop_price = max(state.stop_price, new_stop)  # 多头止损只上移
else:
    new_stop = current_price + trailing_multiplier * current_atr
    state.stop_price = min(state.stop_price, new_stop)  # 空头止损只下移
```

### 3.3 止损日冷却

止损触发后，当天（UTC）禁止再开仓。防连亏机制。

```python
# 止损时自动记录日期
state.clear_position(record_stop_loss=True)  # BaseState 自动设置 stop_loss_date

# 开仓前检查
if state.stop_loss_date == current_time.date():
    return self._hold_result("今日已触发止损")
```

**重要**：移动止盈 **不记录** 止损日期。移动止盈是盈利出场，次日应可正常开仓。

### 3.4 bar_high / bar_low 检测

`check_realtime_exit()` 接收 `bar_high` 和 `bar_low` 参数，来自 1m K 线的 **high** 和 **low**（`_parse_kline_high()` / `_parse_kline_low()`）。

用它们检测止损比用 `current_price`（1m close）更准确——K 线内价格可能瞬间穿过止损位后回弹，close 未触发但 high/low 已穿过。

```python
check_high, check_low = self._get_exit_detection_prices(current_price, bar_high, bar_low)
# check_high = bar_high if available, else current_price  （1m high 或 fallback 到 1m close）
# check_low = bar_low if available, else current_price    （1m low 或 fallback 到 1m close）

stop_hit = check_low <= state.stop_price if is_long else check_high >= state.stop_price
```

**平仓执行价**：`current_price`（1m close），不是 high/low。因为实际成交价是 close，high/low 只用于判断是否触发。

### 3.5 指标出场

可选择性实现 `check_indicator_exit()`，在 K 线闭合时检查指标是否触发出场信号。用 `state.last_indicator_bar` 防止同一根 K 线重复触发。

### 3.6 强制平仓

日内策略可配置强制平仓时间：

```yaml
params:
  force_close_hour_utc: 23
  force_close_minute_utc: 55
```

### 3.7 check_realtime_exit 开头必须调用 update_pnl_extremes

```python
def check_realtime_exit(self, symbol, current_price, current_time=None, bar_high=None, bar_low=None):
    state = self._get_state(symbol)
    if not state.is_in_position():
        return self._hold_result("无持仓")
    state.update_pnl_extremes(current_price)  # 必需！
    ...
```

### 3.8 _close 必须调用 _notify_exit_and_clear

```python
def _close(self, symbol, state, price, reason, is_stop_loss=False, current_time=None):
    action = self._notify_exit_and_clear(
        symbol=symbol, state=state, exit_price=price,
        exit_reason=reason, is_stop_loss=is_stop_loss, exit_time=current_time,
    )
    return {"action": action, "price": price, "strength": 0.8,
            "metadata": {"reason": reason, "is_stop_loss": is_stop_loss}}
```

---

## 4. 配置说明

### 4.1 周期配置（timeframes）

**关键规则：每个指标必须配置 `*_timeframes`**

```yaml
params:
  ema_timeframes: 4h        # EMA 指标用 4h K 线
  atr_timeframes: 1h        # ATR 指标用 1h K 线
  adx_timeframes: 4h        # ADX 指标用 4h K 线
```

`_get_indicator_timeframes()` 必须返回所有指标使用的周期集合，否则数据管理器不会订阅对应周期的数据：

```python
def _get_indicator_timeframes(self) -> set:
    tf_set = set(self.timeframes)
    p = self.params or {}
    tf_set.add(p.get("ema_timeframes", "4h"))
    tf_set.add(p.get("atr_timeframes", "1h"))
    return tf_set
```

### 4.2 多周期策略的 timeframes 配置

多周期策略在顶层 `timeframes` 中列出所有需要的周期，每个指标通过 `*_timeframes` 参数指定自己的周期。

如果策略内部使用了不在 `timeframes` 中的周期（如额外需要 1d），必须在 `_get_indicator_timeframes()` 中显式添加。

### 4.3 cooldown_timeframe

信号冷却的时间框架。同一根 `cooldown_timeframe` K 线内不重复发信号。

```yaml
cooldown_timeframe: 4h  # 4h K 线内最多一次信号
```

**必须与策略信号周期匹配**。

### 4.4 kline_limits

长周期指标（如 EMA120）需要大量历史数据。通过 `kline_limits` 配置每个周期的 K 线数量上限：

```yaml
params:
  warmup_period: 500
  kline_limits:
    4h: 500
```

配合 Strategy 中的 `_get_min_bars_for_timeframe()`：

```python
def _get_min_bars_for_timeframe(self, timeframe: str) -> int:
    if timeframe == "4h":
        return 500
    return super()._get_min_bars_for_timeframe(timeframe)
```

### 4.5 _calc_required_history_days()

多周期策略需要指定历史数据天数，确保数据管理器加载足够的历史数据：

```python
def _calc_required_history_days(self) -> int:
    # 根据最长指标周期 + 缓冲计算
    return 30
```

### 4.6 配置文件格式

| 规则 | 错误示例 | 正确示例 |
|------|----------|----------|
| 必须有顶层策略名键 | `name: xxx` 在顶层 | `{strategy_name}: ...` |
| 参数放在 params 下 | `obs_n: 20` 在顶层 | `params:\n  obs_n: 20` |
| symbols 用数组格式 | `symbol: BTCUSDT` | `symbols:\n  - BTCUSDT` |

---

## 5. State 字段设计

### 5.1 持久化 vs 缓存字段

**持久化字段**：开仓后需要保存的（重启后恢复）。必须写在 `to_persist_dict()` 和 `restore_from_dict()` 中。

**缓存字段**：运行时临时计算，重启后不需要。**禁止**写入 `to_persist_dict()`。

```python
@dataclass
class MyState(BaseState):
    # 持久化字段
    atr_at_entry: float = 0.0
    initial_stop_price: float = 0.0

    # 缓存字段（不持久化）
    last_evaluated_bar: Optional[datetime] = None

    def to_persist_dict(self):
        data = super().to_persist_dict()
        data.update({
            "atr_at_entry": self.atr_at_entry,
            "initial_stop_price": self.initial_stop_price,
        })
        # last_evaluated_bar 不写入！
        return data
```

### 5.2 可变默认值陷阱

```python
# ❌ 错误：所有实例共享同一个 list/dict
class MyState(BaseState):
    swing_highs: list = []        # 共享状态！
    indicators: dict = {}         # 共享状态！

# ✅ 正确：用 field(default_factory=...)
from dataclasses import dataclass, field

@dataclass
class MyState(BaseState):
    swing_highs: list = field(default_factory=list)
    indicators: dict = field(default_factory=dict)
```

### 5.3 clear_position() 必须重置特有字段

```python
def clear_position(self, record_stop_loss=False, current_time=None):
    super().clear_position(record_stop_loss=record_stop_loss, current_time=current_time)
    self.atr_at_entry = 0.0
    self.initial_stop_price = 0.0
    self.last_evaluated_bar = None  # 缓存字段也要重置
```

### 5.4 嵌套对象字段

State 包含嵌套对象（如 FVG、PriceLines）时，嵌套类必须实现 `to_dict()` 方法，State 的 `to_persist_dict()` 和 `restore_from_dict()` 中处理序列化/反序列化。

---

## 6. 常见错误清单

| # | 错误 | 正确做法 | 影响 |
|---|------|---------|------|
| 1 | 用未闭合 K 线入场 | `get_closed_data()` + `realtime_price` | 回测失真 |
| 2 | `datetime.now()` 做时间戳 | 用 K 线的 `current_time` | 实盘/回测不一致 |
| 3 | State 用 `[]` 或 `{}` 做默认值 | `field(default_factory=list)` | 多标的共享状态 |
| 4 | 缓存字段写进 `to_persist_dict()` | 只持久化经济风险字段 | 持久化膨胀/数据错乱 |
| 5 | 跳过数据不足检查 | `if df.empty or len(df) < min_rows` | 指标计算 NaN |
| 6 | 回测模式启用冷却 | 基类自动跳过，不要手动覆盖 | 回测信号缺失 |
| 7 | 在 Strategy 类中计算指标 | 指标在 Core.analyze() 内 | 代码冗余/回测不兼容 |
| 8 | 自定义止损计数字段 | 用 `BaseState.stop_loss_date` | 止损日冷却失效 |
| 9 | 配置缺少 `*_timeframes` | 每个指标配 `xxx_timeframes` | 数据不订阅/指标为空 |
| 10 | 配置缺少顶层策略名键 | `{strategy_name}: ...` | 配置加载失败 |
| 11 | 追踪止损往不利方向移动 | 多头止损只上移，空头止损只下移 | 止损位越来越远 |
| 12 | 移动止盈记录止损日期 | 只在真正止损时 `record_stop_loss=True` | 次日无法开仓 |
| 13 | `check_realtime_exit` 不调 `update_pnl_extremes` | 方法开头必须调用 | RiskController 盈亏计算错 |
| 14 | `_close()` 不调 `_notify_exit_and_clear()` | 必须调用 | 仓位不清理/信号不发送 |
