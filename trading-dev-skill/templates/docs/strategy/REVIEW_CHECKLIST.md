# 策略研发检查表

> **文档定位**：新策略提交前自查、代码审查时逐项检查。每项标记：✅ PASS / ❌ FAIL / ⬜ N/A

---

## 0. 基类架构检查

> 使用 `BaseStrategy` / `BaseStrategyCore` / `BaseState` 基类的策略检查项

| # | 检查项 | 标准 | 状态 |
|---|--------|------|------|
| 0.1 | Strategy 继承 `BaseStrategy` | 推荐 | ⬜ |
| 0.2 | Core 继承 `BaseStrategyCore` | 推荐 | ⬜ |
| 0.3 | State 继承 `BaseState` | 推荐 | ⬜ |
| 0.4 | 设置 `STRATEGY_TYPE` 类属性 | 必需 | ⬜ |
| 0.5 | `STRATEGY_PREFIX` 无需设置（由策略目录名自动推导） | 自动 | N/A |
| 0.6 | 实现 `_create_core()`（传 `global_config=self._get_global_config()`） | 必需 | ⬜ |
| 0.7 | 实现 `_get_indicator_timeframes()` 方法 | 必需 | ⬜ |
| 0.8 | State 子类重写 `to_persist_dict()` | 有特有字段时必需 | ⬜ |
| 0.9 | State 子类重写 `restore_from_dict()` | 有特有字段时必需 | ⬜ |
| 0.10 | 平仓统一走 `_notify_exit_and_clear()`（内部清除持仓状态） | 必需 | ⬜ |
| 0.11 | `_close()` 调用 `_notify_exit_and_clear()` | 必需 | ⬜ |
| 0.12 | `check_realtime_exit()` 调用 `update_pnl_extremes()` | 必需 | ⬜ |
| 0.13 | 数组/字典字段使用 `field(default_factory=...)` | 必需 | ⬜ |
| 0.14 | 嵌套对象实现 `to_dict()` 和反序列化 | 有嵌套对象时必需 | ⬜ |
| 0.15 | 入场时生成 `position_id`（`PositionPersistence.generate_position_id()`） | 必需 | ⬜ |

**0 类结论**：⬜ PASS / ⬜ FAIL

---

## A. 目录结构

| # | 检查项 | 标准 | 状态 |
|---|--------|------|------|
| A1 | `strategy.py` 存在 | 必需 | ⬜ |
| A2 | `{prefix}_core.py` 存在 | 必需 | ⬜ |
| A3 | `__init__.py` 存在 | 推荐 | ⬜ |
| A4 | `overrides/<SYMBOL>.yaml` 存在且参数完整 | 必需 | ⬜ |
| A5 | 已在 `config/strategies.yaml` 登记（symbols + trading_mode） | 必需 | ⬜ |
| A6 | `tests/` 目录存在 | 推荐 | ⬜ |

**A 类结论**：⬜ PASS / ⬜ FAIL

---

## B. Strategy 接口

> 这一段绝大多数项由 `BaseStrategy` 提供，**子类不要重写**。
> 真正要人工检查的只有 B1、B2 和「重写了 `on_kline()` 才适用」的几条。

| # | 检查项 | 标准 | 状态 |
|---|--------|------|------|
| B1 | `STRATEGY_TYPE` 等于策略目录名 | 必需 | ⬜ |
| B2 | `DEFAULT_TIMEFRAME` 已设置 | 必需 | ⬜ |
| B3 | `strategy_name` / `name` / `subscribed_symbols` / `poll_timeframes` / `signal_fields` / `get_status()` | 基类已实现，**勿重写** | N/A |
| B4 | `strategy_name` 由入口生成并注入，格式 `{PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}_{MODE}`（如 `SARSNT3_4H_3_BTCUSDT_PAPER`） | 基类只读属性，**勿手写** | N/A |
| B5 | `on_start()` 注册时间框架、恢复仓位、接线风控 | 基类已实现 | N/A |
| B6 | `on_kline()` 返回 Signal 或 None | 基类已实现；若重写必须保持该契约 | ⬜ |
| B7 | 若重写 `on_kline()`：入场闸只挡**无持仓**分支，持仓时仍每根 1m 检查出场 | 重写时必需 | ⬜ |
| B8 | 若自己实现入场冷却：回测模式跳过（`self._backtest_mode`） | 自实现时必需 | ⬜ |
| B9 | 不依赖 `cooldown_timeframe` / `cooldown_bars` / `cooldown_ms` 做冷却 | 必需（三者均为死配置，代码零引用） | ⬜ |

**B 类结论**：⬜ PASS / ⬜ FAIL

---

## C. 核心逻辑类

| # | 检查项 | 标准 | 状态 |
|---|--------|------|------|
| C1 | State 类使用 `@dataclass` | 推荐 | ⬜ |
| C2 | State 包含必需字段 | position, entry_timestamp, entry_price, stop_price | ⬜ |
| C3 | `_get_state(symbol)` 方法存在 | 必需 | ⬜ |
| C4 | `analyze()` 方法存在 | 必需 | ⬜ |
| C5 | `analyze()` 接收 `realtime_price` 参数 | 必需 | ⬜ |
| C6 | `analyze()` 使用 `realtime_price` 判断入场 | 必需 | ⬜ |
| C7 | `analyze()` 返回格式正确 | action, price, strength, metadata | ⬜ |
| C8 | `check_realtime_exit()` 方法存在 | 必需 | ⬜ |
| C9 | `check_realtime_exit()` 返回格式正确 | action, price, strength, metadata | ⬜ |
| C10 | 使用基类 `get_closed_data()` 取已闭合 K 线 | 必需 | ⬜ |
| C11 | `get_expected_last_closed_timestamp()` 方法存在 | 推荐 | ⬜ |
| C12 | `get_closed_data()` 传 `min_rows` 并检查 empty | 推荐 | ⬜ |
| C13 | 止损日冷却检查实现 | analyze() 中检查 stop_loss_date | ⬜ |
| C14 | 止损时记录 stop_loss_date | 止损路径 `is_stop_loss=True`（基类自动记录） | ⬜ |
| **C15** | **技术指标在 analyze() 内计算** | 必需 | ⬜ |
| **C16** | **禁止 Strategy 类计算技术指标** | 必需 | ⬜ |
| **C17** | **技术指标使用已闭合 K 线** | 必需 | ⬜ |

**C 类结论**：⬜ PASS / ⬜ FAIL

---

## D. K 线周期处理

| # | 检查项 | 标准 | 状态 |
|---|--------|------|------|
| D1 | 入场判断使用 `realtime_price` | 必需 | ⬜ |
| D2 | 出场判断使用 `current_price` 参数 | 必需 | ⬜ |
| D3 | 各指标配置 `*_timeframes` | 必需 | ⬜ |
| D4 | `_get_indicator_timeframes()` 实现 | 必需 | ⬜ |
| D5 | 数据不足时返回 hold | 必需 | ⬜ |

**D 类结论**：⬜ PASS / ⬜ FAIL

---

## E. 配置文件

| # | 检查项 | 标准 | 状态 |
|---|--------|------|------|
| E1 | `version` 字段存在 | 必需 | ⬜ |
| E2 | `symbols` 为数组格式 | 必需 | ⬜ |
| E3 | `timeframes` 为数组格式 | 必需 | ⬜ |
| E4 | overrides 的 `params` 中每个指标有 `*_timeframes` 配置 | 必需 | ⬜ |
| E5 | `signal.min_strength` 存在 | 必需 | ⬜ |

**E 类结论**：⬜ PASS / ⬜ FAIL

---

## F. 时间戳处理

| # | 检查项 | 标准 | 状态 |
|---|--------|------|------|
| F1 | 使用 UTC 时区 | 必需 | ⬜ |
| F2 | 信号时间戳使用 K 线时间 | 必需 | ⬜ |
| F3 | `entry_timestamp` 为秒级 | 必需（10 位数字） | ⬜ |

**F 类结论**：⬜ PASS / ⬜ FAIL

---

## G. 仓位持久化（实盘模式）

| # | 检查项 | 标准 | 状态 |
|---|--------|------|------|
| G1 | `set_position_callbacks()` 由 BaseStrategy 自动接线 | 基类已实现 | N/A |
| G2 | `_on_position_enter()` 由 BaseStrategy 自动处理 | 基类已实现 | N/A |
| G3 | `_on_position_exit()` 由 BaseStrategy 自动处理（含 HistoryPositionLogger） | 基类已实现 | N/A |
| G4 | `_restore_position_state()` 由 BaseStrategy 启动时自动恢复 | 基类已实现 | N/A |

> 策略侧只需保证：入场生成 `position_id`、平仓走 `_notify_exit_and_clear()`、
> 特有字段正确实现 `to_persist_dict()` / `restore_from_dict()`。

**G 类结论**：⬜ PASS / ⬜ FAIL / ⬜ N/A

---

## H. 测试覆盖

| # | 检查项 | 标准 | 状态 |
|---|--------|------|------|
| H1 | 入场逻辑测试 | 推荐 | ⬜ |
| H2 | 出场逻辑测试 | 推荐 | ⬜ |
| H3 | K 线闭合判断测试 | 推荐 | ⬜ |
| H4 | 回测验证通过 | 推荐 | ⬜ |

**H 类结论**：⬜ PASS / ⬜ N/A

---

## I. 多周期策略（仅使用 ≥2 个周期时检查）

> 参考实现：`strategies/example_mtf_trend/`（1d 定方向 + 4h 触发 + 1h 确认）。
> 单周期策略整段标 N/A。

| # | 检查项 | 标准 | 状态 |
|---|--------|------|------|
| I1 | 每个指标周期在 overrides `params` 中有对应的 `*_timeframes` | 必需 | ⬜ |
| I2 | `_get_indicator_timeframes()` 收集了**全部**周期（含更短的跟踪止损周期） | 必需；漏一个周期该周期数据就是空 df | ⬜ |
| I3 | `analyze()` 对每个周期**单独**调用 `get_closed_data()` | 必需（红线 #12，禁止直接用 `klines_data[tf]` 原始 df） | ⬜ |
| I4 | 每个周期单独做 `empty` / `len()` 数据不足检查并返回 hold | 必需 | ⬜ |
| I5 | `timeframes[0]` 是触发主周期；其余周期用显式参数名（如 `trend_timeframe`），不靠列表顺序 | 必需 | ⬜ |
| I6 | 各周期的未闭合 bar 均不进指标（`get_closed_data` 传了 `current_time`） | 必需 | ⬜ |
| I7 | 有跨周期未来函数测试：向任一周期追加一根未闭合极端 bar，结果不变 | 推荐，照抄 `example_mtf_trend/tests/` | ⬜ |

**I 类结论**：⬜ PASS / ⬜ FAIL / ⬜ N/A

---

## 审查结论

| 类别 | 通过/总数 | 结论 |
|------|-----------|------|
| 0. 基类架构检查 | /15 | ⬜ PASS / ⬜ FAIL |
| A. 目录结构 | /6 | ⬜ PASS / ⬜ FAIL |
| B. Strategy 接口 | /9 | ⬜ PASS / ⬜ FAIL |
| C. 核心逻辑类 | /17 | ⬜ PASS / ⬜ FAIL |
| D. K 线周期处理 | /5 | ⬜ PASS / ⬜ FAIL |
| E. 配置文件 | /5 | ⬜ PASS / ⬜ FAIL |
| F. 时间戳处理 | /3 | ⬜ PASS / ⬜ FAIL |
| G. 仓位持久化 | /4 | ⬜ PASS / ⬜ FAIL / ⬜ N/A |
| H. 测试覆盖 | /4 | ⬜ PASS / ⬜ N/A |
| I. 多周期策略 | /7 | ⬜ PASS / ⬜ FAIL / ⬜ N/A |

**总体结论**：⬜ PASS / ⬜ FAIL

**审查人**：___________ **日期**：___________
