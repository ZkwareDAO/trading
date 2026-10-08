# 策略规格文件（.strategy-spec.yaml）

> **文档定位**：`.strategy-spec.yaml` 的字段 schema。该文件是**策略逻辑确认阶段**的产物
> （skill `/zk_cta-strategy-logic-refine`），由 `/zk_cta-strategy-implement` 消费，
> 位于 `strategies/<name>/.strategy-spec.yaml`。
>
> 它只描述"策略要做什么"，不描述"框架怎么跑"。运行时**不读取**这个文件——它服务于
> 人机确认和 AI 生成代码，改错了不会直接影响线上，但会让生成的代码偏离确认过的逻辑。

---

## 完整示例

```yaml
strategy_name: example_mtf_trend        # 必需，等于策略目录名
prefix: EXAMPLEMTFTREND                 # 必需，目录名去下划线大写、去版本后缀
direction: neutral                      # neutral / long / short
timeframes: [4h]                        # 主周期列表，[0] 必须是触发主周期
extra_timeframes: [1d, 1h]              # 可选：除主周期外订阅的其他周期

symbols: [BTCUSDT]                      # 设计覆盖的标的（实际运行以登记表为准）

entry:
  description: "一句话说清入场逻辑"
  conditions:                           # 条件逐条列，生成代码时一条对应一个判断
    - "1d：收盘价 > EMA50 允许做多"
    - "4h：MA10 上穿 MA30"
    - "1h：RSI14 > 55"

exit:
  stop_loss: "2 × ATR14(4h)"            # 硬止损规则；不做空字符串
  trailing_stop: ""                     # 没有就留空字符串
  signal_reversal: ""
  note: "可选：其他出场说明"

state_fields:                           # 策略特有状态字段（BaseState 已有字段不要列）
  - name: atr_at_entry
    type: float                         # float / int / bool / str / date
    default: 0.0
    persist: true                       # true=进 to_persist_dict；false=每根 K 线重算的缓存
  - name: latest_rsi
    type: float
    default: 50.0
    persist: false

default_params:                         # Core.__init__ 从 params 读取的参数及默认值
  trend_timeframe: 1d
  ma_fast_period: 10
  atr_stop_mult: 2.0
```

真实范例：
[`strategies/example_ma_cross/.strategy-spec.yaml`](../../strategies/example_ma_cross/.strategy-spec.yaml)
（单周期）、
[`strategies/example_mtf_trend/.strategy-spec.yaml`](../../strategies/example_mtf_trend/.strategy-spec.yaml)
（多周期）。

---

## 字段说明

### 顶层

| 字段 | 必需 | 说明 |
|------|------|------|
| `strategy_name` | 是 | 必须等于策略目录名 |
| `prefix` | 是 | 类名前缀。由目录名推导：去 `cta_` 前缀、去末尾 `_vN`/`_trading_vN`、去下划线大写（`example_ma_cross` → `EXAMPLEMACROSS`，规则见 `strategy_core/utils/strategy_naming.py`） |
| `direction` | 是 | `neutral`（多空都做）/ `long` / `short` |
| `timeframes` | 是 | 主周期列表。**第一个是触发主周期**，对应基类 `main_timeframe` 和 `timeframes[0]` |
| `extra_timeframes` | 否 | 多周期策略的其他周期。代码生成后它们必须同时出现在 `Strategy._get_indicator_timeframes()` 和每个指标的 `*_timeframes` 参数里 |
| `symbols` | 是 | 设计覆盖的标的列表 |

### `entry`

| 字段 | 必需 | 说明 |
|------|------|------|
| `description` | 是 | 一句话概述，会写进 Core 模块 docstring |
| `conditions` | 是 | 字符串数组，**一条一个可判定条件**。避免"适当止损""趋势向好"这类无法直接翻译成代码的描述 |

写法要求：

- 每条条件要能直接对应 `analyze()` 里的一个布尔变量
- 注明所用指标、周期、参数（"RSI14(1h) > 55"，不要只写"RSI 超买"）
- 多周期条件必须注明周期
- 入场价来源默认是 `realtime_price`，退回已闭合收盘价；有特殊要求写明

### `exit`

| 字段 | 必需 | 说明 |
|------|------|------|
| `stop_loss` | 是* | 硬止损规则；无止损时显式写 `"无（依赖 risk 段兜底）"`，不要留空 |
| `trailing_stop` | 否 | 移动止损规则，没有留 `""` |
| `signal_reversal` | 否 | 信号反转出场规则，没有留 `""` |
| `note` | 否 | 其他说明（如"回落止盈走 risk 段统一风控"） |

\* 至少要能看出亏损到什么程度会出场——要么策略自己有止损，要么明确声明依赖
overrides `risk` 段的统一风控。

### `state_fields`

只列**策略特有字段**。以下 BaseState 已有字段禁止重复列出：
`position` / `position_id` / `entry_timestamp` / `entry_price` / `entry_time` /
`peak_price` / `stop_price` / `stop_loss_date` / `max_pnl_pct` / `min_pnl_pct` /
`trail_activated` / `trail_trigger_pct`。

| 子字段 | 说明 |
|--------|------|
| `name` | 字段名，snake_case |
| `type` | `float` / `int` / `bool` / `str` / `date`；嵌套对象用类型名并在 description 里说明 |
| `default` | 默认值。**禁止**用 `[]` / `{}` 这类可变默认值，代码里要生成 `field(default_factory=...)` |
| `persist` | `true` → 进 `to_persist_dict()` / `restore_from_dict()`；`false` → 缓存字段，重启可丢 |

判断 `persist` 的标准：**进程在持仓途中重启，这个字段丢了会不会影响后续出场逻辑？**
会 → `true`；只是每根 K 线重算的中间值 → `false`。

### `default_params`

参数名 → 默认值的映射。规则：

- 每个指标周期必须有 `*_timeframes` 键（多周期策略尤其不能漏）
- 键名要和 overrides 模板、Core `__init__` 里 `params.get(...)` 的键名完全一致
- 百分比参数统一用数值形式（`2.0` 表示 2%），不要写 `"2%"`

---

## 自检清单

写完 spec、进入代码生成前，逐条确认：

- [ ] `strategy_name` 与目录名一致，`prefix` 符合推导规则
- [ ] `timeframes[0]` 是触发主周期；多周期的其他周期都在 `extra_timeframes`
- [ ] 每条 `conditions` 都注明了指标 + 周期 + 参数 + 比较关系
- [ ] `exit.stop_loss` 明确（自有止损或声明依赖 risk 兜底）
- [ ] `state_fields` 没有重复 BaseState 字段；每个字段的 `persist` 判断过
- [ ] 没有可变默认值
- [ ] `default_params` 覆盖了每条 condition 用到的参数和每个指标的 `*_timeframes`
