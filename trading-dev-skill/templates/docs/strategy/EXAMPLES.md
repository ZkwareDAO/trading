# 策略开发 FAQ

> **文档定位**：只回答"为什么"和"踩坑了怎么办"。**可复制的完整代码不在本文**——
> 以参考实现为准：
>
> - 单周期：[`strategies/example_ma_cross/`](../../strategies/example_ma_cross/)
> - 多周期：[`strategies/example_mtf_trend/`](../../strategies/example_mtf_trend/)
> - 目录结构 / 配置模板：[QUICKSTART.md](QUICKSTART.md)
> - 完整开发规范：[DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md)

---

## Q0: 我该抄哪份代码？

| 你的策略 | 抄哪个 |
|----------|--------|
| 只看一个周期 | `example_ma_cross`（最短，契约最全） |
| 用了两个及以上周期（常态） | `example_mtf_trend`（1d+4h+1h 三周期共振） |
| 要"大周期收线才入场" | `example_ma_cross/strategy.py` 末尾附录的 `on_kline()` 重写范例 |

不要抄本文档里曾经的占位符骨架——参考实现是能跑回测的真代码，且会随框架一起更新。

---

## Q1: 为什么入场必须用已闭合 K 线？

实盘 WS 推送 1m K 线，大周期（如 4h）的最后一根可能未闭合。使用未闭合数据会导致：
- 回测时"偷看未来"
- 实盘信号与回测不一致

判定方式交给基类：`get_closed_data(klines_data, tf, min_rows=N, current_time=...)`
会用 `bar_end <= current_time` 过滤掉未闭合 bar。**注意过滤后仍可能不足 N 行，要再判一次 `len()`。**

---

## Q2: 入场判断多久跑一次？

**每根 1m K 线一次。** 基类默认 `on_kline()` 在无持仓时每分钟都调 `analyze()`
（`strategy_core/base/strategy.py:373-452`），没有入场侧冷却。

这样不会有未来函数：指标取自 `get_closed_data()` 的已闭合大周期 K 线，
入场价用 `realtime_price`。好处是条件一成立就能进场，不必等大周期收线。

想改成"只在大周期闭合那一分钟判断"，重写 `on_kline()` —— 可复制的实现见
`example_ma_cross/strategy.py` 文件末尾附录。

---

## Q3: entry_timestamp 为什么用秒级？

与 K 线数据格式一致，便于：
- 计算持仓时间
- 与 position 文件对齐
- 生成 position_id

---

## Q4: 有哪几种冷却？

| 冷却类型 | 触发条件 | 持续时间 | 谁实现 |
|----------|----------|----------|--------|
| 止损日冷却 | 触发止损 | 当天剩余时间 | **你自己写**（`analyze()` 里查 `state.stop_loss_date`），日期由基类自动记录 |
| 平仓信号去重 | 发出平仓信号后 | 同一根 1m K 线内 | 基类已实现 |
| 入场 K 线冷却 | — | — | **基类没有**，需要就自己重写 `on_kline()` |

> `cooldown_timeframe` / `cooldown_bars` / `cooldown_ms` 是死配置，代码里没有任何地方
> 读取它们，写在 overrides 里也不生效。

---

## Q5: 为什么移动止盈不记录止损日期？

移动止盈是盈利出场，不是止损。次日应该可以正常开仓，不应被止损日冷却阻止。
走 `_notify_exit_and_clear(..., is_stop_loss=False)` 即可，基类不会写 `stop_loss_date`。

---

## Q6: 回测模式如何处理冷却？

- **止损日冷却**：正常生效，用 K 线时间判断（不是 `datetime.now()`）
- **平仓信号去重**：正常生效，用 K 线时间戳比对，回测与实盘一致
- **自己实现的入场冷却**：必须用 `self._backtest_mode` 判据跳过，否则回测信号缺失

---

## Q7: 多标的策略如何处理状态？

使用 `_state: Dict[str, State]` 字典，每个标的独立状态：

```python
def _get_state(self, symbol: str) -> State:
    if symbol not in self._state:
        self._state[symbol] = State()
    return self._state[symbol]
```

---

## Q8: 多周期策略最容易错在哪？

三个高频错误，对照参考实现 `example_mtf_trend_core.py` 自查：

1. **`_get_indicator_timeframes()` 漏收集周期** → `klines_data` 里没有那个 key，
   `get_closed_data()` 返回空 df，信号永远不出。
2. **直接用 `klines_data[tf]` 原始 df 算指标** → 最后一根未闭合 bar 进指标 = 未来函数。
   **每个周期都必须单独调用 `get_closed_data()`**。
3. **只检查了一个周期的数据量** → 其余周期预热不足时指标 NaN。每个周期都要单独判空和行数。

多周期的周期配置也要显式参数化（`trend_timeframe` / `confirm_timeframe`），
不要靠 `timeframes` 列表顺序的隐含约定；主周期永远是 `timeframes[0]`。

---

## Q9: 如何调试策略信号？

1. 检查 `metadata["reason"]` 字段，了解 hold 原因
2. 添加 `logger.debug()` 输出中间计算结果
3. 运行回测查看信号记录 CSV 与 `backtest_output/<策略>/` 产物
4. 用测试复现边界条件——参考实现的 `tests/` 就是测试清单：
   前置检查、入场、未闭合 bar、方向过滤、出场、持久化往返

"策略能启动、日志正常、就是不出信号"时，按顺序排查：
`min_strength` 门槛 → 数据不足 hold → 周期没订阅 → 止损日冷却 → 已有持仓。

---

## Q10: 为什么技术指标必须在 analyze() 内计算？

1. **避免绕远路**：在 Strategy 类或 `on_start()` 里预计算指标，回测时不会重放
2. **回测兼容**：回测框架调用 `analyze()` 时，指标必须能随 K 线自算
3. **数据一致性**：每次调用时使用最新的已闭合 K 线计算指标
4. **代码简洁**：所有入场逻辑集中在 Core.analyze() 内

**错误示例**：

```python
# ❌ 错误：在 Strategy.on_start() 中预计算指标
def on_start(self):
    super().on_start()
    df = self._data_manager.get_dataframe_cached(symbol, "1d")
    self._core._update_price_lines(symbol, df.iloc[-1])
```

**正确示例**：

```python
# ✅ 正确：在 analyze() 内用已闭合 K 线实时计算
def analyze(self, symbol, klines_data, current_time, realtime_price=None, current_cash=None):
    closed_1d = self.get_closed_data(klines_data, "1d", min_rows=1, current_time=current_time)
    if not closed_1d.empty:
        prev = closed_1d.iloc[-1]
        ...  # 用 prev 的 high/low/close 计算
```

---

## Q11: 基类已有指标可以复用吗？

可以。`strategy_core.base` 导出了通用指标，先查再自己写：

```python
from strategy_core.base import calculate_adx, calculate_bollinger
```

- `calculate_adx(df, period=14)`：TA-Lib 可用时用 TA-Lib，否则内部纯 Python 回退
- `calculate_bollinger(...)`：布林带

其他指标（MA / EMA / RSI / ATR）直接用 pandas 一行即可，参考实现里都有纯 pandas 写法。

---

## Q12: 策略特有字段在哪里重置？

在 State 里**重写 `clear_position()`**，不要只在自己的 `_close()` 里重置：

```python
def clear_position(self, record_stop_loss=False, current_time=None):
    super().clear_position(record_stop_loss=record_stop_loss, current_time=current_time)
    self.my_field = 0.0
```

平仓有两条路径——策略自己的 `check_realtime_exit()`，和基类统一风控兜底
（`strategy.py` 里 `check_risk_control()` 命中后直接 `_notify_exit_and_clear()`）。
后者不经过你的 `_close()`，但一定经过 `clear_position()`。
