# AI 编码约束

> **文档定位**：AI 辅助开发时的硬性规则，定义不可违反的约束。加载此文档作为 system prompt 的一部分。

---

## 禁止事项（必须遵守）

| # | 约束 | 原因 |
|---|------|------|
| 1 | 禁止在入场判断中使用未闭合 K 线 | 会导致未来函数，回测失真 |
| 2 | 禁止使用 `datetime.now()` 作为信号时间戳 | 应使用 K 线时间，保证可重现 |
| 3 | 禁止在 State 中使用可变默认值 | `[]`, `{}` 会共享状态 |
| 4 | 禁止跳过数据不足检查 | 会导致指标计算错误 |
| 5 | 禁止在回测模式启用 K 线冷却 | 会导致回测信号缺失 |
| 6 | 禁止使用 `datetime.now()` 判断止损日冷却 | 回测时应使用 K 线时间 |
| 7 | 禁止移动止盈记录止损日期 | 非止损，次日应可开仓 |
| 8 | 禁止在 Strategy 类中计算技术指标 | 所有指标应在 Core.analyze() 内使用已闭合 K 线计算 |
| 9 | 禁止外部数据注入方法 | 避免在 on_start() 等方法中预计算指标 |
| 10 | 禁止依赖外部传入的指标值 | 指标应从 klines_data 参数计算 |
| 11 | 禁止自定义止损计数字段 | 使用 BaseState 提供的 `stop_loss_date` |
| 12 | 禁止直接使用原始 K 线入场判断 | 多周期策略必须对每个时间框架调用 `get_closed_data()` |
| 13 | 禁止数组/字典字段使用可变默认值 | 必须使用 `field(default_factory=list)` 或 `field(default_factory=dict)` |
| 14 | 禁止缓存字段持久化 | 缓存字段不应在 to_persist_dict() 中保存 |

---

## 必须实现

| # | 约束 | 位置 |
|---|------|------|
| 1 | 必须使用基类 `get_closed_data()` | 继承 BaseStrategyCore 即可使用 |
| 2 | 必须在 `analyze()` 中使用已闭合数据 | 核心逻辑类 |
| 3 | 必须实现 `_get_indicator_timeframes()` | Strategy 类 |
| 4 | 必须在 `on_start()` 中注册时间框架 | Strategy 类（BaseStrategy 已实现） |
| 5 | 必须检查数据是否足够 | `analyze()` 开头 |
| 6 | 必须实现 K 线冷却 | Strategy 类（BaseStrategy 已实现） |
| 7 | 止损时必须调用 `clear_position(record_stop_loss=True)` | Core 类 `_close()` 方法 |
| 8 | 必须在 `analyze()` 内计算所有技术指标 | Core 类 `analyze()` |
| 9 | 必须对每个时间框架调用 `get_closed_data()` | Core 类 `analyze()` |
| 10 | 必须在 config.yaml 配置 `*_timeframes` | 配置文件 |
| 11 | 数组/字典字段必须使用 `field(default_factory=...)` | State 类 |

---

## 代码模板

### 止损日冷却检查

```python
def analyze(self, symbol, klines_data, current_time):
    state = self._get_state(symbol)
    today = current_time.date() if current_time else datetime.now(timezone.utc).date()
    if state.stop_loss_date == today:
        return {"action": "hold", "price": 0, "strength": 0,
                "metadata": {"reason": "今日已触发止损，禁止开仓"}}
```

### 止损时记录日期

```python
def _close(self, symbol, state, price, reason, is_stop_loss=False):
    state.clear_position(record_stop_loss=is_stop_loss)
```

### 多周期已闭合 K 线获取

```python
def analyze(self, symbol, klines_data, current_time):
    closed_4h = self.get_closed_data(klines_data, "4h", min_rows=30, current_time=current_time)
    closed_1h = self.get_closed_data(klines_data, "1h", min_rows=50, current_time=current_time)
    closed_15m = self.get_closed_data(klines_data, "15m", min_rows=20, current_time=current_time)

    if closed_4h.empty:
        return self._hold_result("4h 已闭合 K 线数据不足")
    if closed_1h.empty:
        return self._hold_result("1h 已闭合 K 线数据不足")
```

### 数据不足检查

```python
def analyze(self, symbol, klines_data, current_time):
    df = self.get_closed_data(klines_data, self.timeframes[0], min_rows=50, current_time=current_time)
    if df.empty or len(df) < self.min_rows:
        return {"action": "hold", "price": 0, "strength": 0,
                "metadata": {"reason": "K线数据不足"}}
```

### 指标有效性检查

```python
indicator = compute_xxx(df, period=self.period)
if indicator.isna().iloc[-1]:
    return {"action": "hold", "price": 0, "strength": 0,
            "metadata": {"reason": "指标数据不足"}}
```

### K 线冷却

K 线冷却由基类自动处理：
- 同一根大周期 K 线不重复触发
- 回测模式自动跳过冷却
