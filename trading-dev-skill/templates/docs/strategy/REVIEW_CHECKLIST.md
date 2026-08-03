# 策略研发检查表

> **文档定位**：新策略提交前自查、代码审查时逐项检查。每项标记：✅ PASS / ❌ FAIL / ⬜ N/A

---

## 0. 基类继承检查

| # | 检查项 | 标准 | 状态 |
|---|--------|------|------|
| 0.1 | Strategy 继承 `BaseStrategy` | 必需 | ⬜ |
| 0.2 | Core 继承 `BaseStrategyCore` | 必需 | ⬜ |
| 0.3 | State 继承 `BaseState` | 必需 | ⬜ |
| 0.4 | 设置 `STRATEGY_TYPE` 类属性 | 必需 | ⬜ |
| 0.5 | 设置 `STRATEGY_PREFIX` 类属性 | 必需 | ⬜ |
| 0.6 | 实现 `_create_core()` 方法 | 必需 | ⬜ |
| 0.7 | 实现 `_get_indicator_timeframes()` 方法 | 必需 | ⬜ |
| 0.8 | State 子类重写 `to_persist_dict()` | 有特有字段时必需 | ⬜ |
| 0.9 | State 子类重写 `restore_from_dict()` | 有特有字段时必需 | ⬜ |
| 0.10 | 使用 `state.clear_position()` 清除持仓 | 必需 | ⬜ |
| 0.11 | `_close()` 调用 `_notify_exit_and_clear()` | 必需 | ⬜ |
| 0.12 | `check_realtime_exit()` 调用 `update_pnl_extremes()` | 必需 | ⬜ |
| 0.13 | 数组/字典字段使用 `field(default_factory=...)` | 必需 | ⬜ |
| 0.14 | 嵌套对象实现 `to_dict()` 和反序列化 | 有嵌套对象时必需 | ⬜ |

**0 类结论**：⬜ PASS / ⬜ FAIL

---

## A. 目录结构

| # | 检查项 | 标准 | 状态 |
|---|--------|------|------|
| A1 | `strategy.py` 存在 | 必需 | ⬜ |
| A2 | `{prefix}_core.py` 存在 | 必需 | ⬜ |
| A3 | `__init__.py` 存在 | 推荐 | ⬜ |
| A4 | `config.yaml` 存在 | 必需 | ⬜ |
| A5 | `config.test.yaml` 存在 | 必需（回测） | ⬜ |
| A6 | `tests/` 目录存在 | 推荐 | ⬜ |

**A 类结论**：⬜ PASS / ⬜ FAIL

---

## B. Strategy 接口

| # | 检查项 | 标准 | 状态 |
|---|--------|------|------|
| B1 | `strategy_name` 属性存在 | 必需 | ⬜ |
| B2 | `strategy_name` 格式正确 | `{Type}v{version}_{tf}_{symbol}` | ⬜ |
| B3 | `name` 属性返回目录名 | 必需 | ⬜ |
| B4 | `subscribed_symbols` 返回 set | 必需 | ⬜ |
| B5 | `poll_timeframes` 返回 `["1m"]` | 必需 | ⬜ |
| B6 | `on_start()` 注册时间框架 | 必需 | ⬜ |
| B7 | `on_kline()` 返回 Signal 或 None | 必需 | ⬜ |
| B8 | `get_status()` 返回 dict | 必需 | ⬜ |
| B9 | `_is_same_bar()` K 线冷却实现 | 推荐 | ⬜ |
| B10 | K 线冷却在回测模式跳过 | 必需 | ⬜ |

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
| C10 | `_get_closed_data()` 方法存在 | 必需 | ⬜ |
| C11 | `_get_expected_last_closed_timestamp()` 方法存在 | 推荐 | ⬜ |
| C12 | `_get_closed_data()` 包含边界验证 | 推荐 | ⬜ |
| C13 | 止损日冷却检查实现 | analyze() 中检查 stop_loss_date | ⬜ |
| C14 | 止损时记录 stop_loss_date | check_realtime_exit() 中 ATR 止损时设置 | ⬜ |
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
| E4 | 每个指标有 `*_timeframes` 配置 | 必需 | ⬜ |
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
| G1 | `set_position_callbacks()` 实现 | 实盘必需 | ⬜ |
| G2 | `_on_position_enter()` 实现 | 实盘必需 | ⬜ |
| G3 | `_on_position_exit()` 实现 | 实盘必需 | ⬜ |
| G4 | `_restore_position_state()` 实现 | 实盘必需 | ⬜ |

**G 类结论**：⬜ PASS / ⬜ FAIL

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

## 审查结论

| 类别 | 通过/总数 | 结论 |
|------|-----------|------|
| 0. 新架构检查 | /14 | ⬜ PASS / ⬜ FAIL / ⬜ N/A |
| A. 目录结构 | /6 | ⬜ PASS / ⬜ FAIL |
| B. Strategy 接口 | /10 | ⬜ PASS / ⬜ FAIL |
| C. 核心逻辑类 | /17 | ⬜ PASS / ⬜ FAIL |
| D. K 线周期处理 | /5 | ⬜ PASS / ⬜ FAIL |
| E. 配置文件 | /5 | ⬜ PASS / ⬜ FAIL |
| F. 时间戳处理 | /3 | ⬜ PASS / ⬜ FAIL |
| G. 仓位持久化 | /4 | ⬜ PASS / ⬜ FAIL / ⬜ N/A |
| H. 测试覆盖 | /4 | ⬜ PASS / ⬜ N/A |

**总体结论**：⬜ PASS / ⬜ FAIL
