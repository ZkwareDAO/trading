# example_ma_cross — 参考实现（reference implementation）

**这个策略不是拿来赚钱的，是拿来抄的。**

它的交易逻辑（双均线交叉 + 固定止损）故意做得很笨，目的是把
**框架契约**演示清楚 —— 那些骨架模板里看不出来、写错了又不会报错、
只会静默不发信号的约定。

新增策略时：完整读一遍这两个文件，然后照着改。

```
strategy.py               100 行 — Strategy 接口层（最简形态，不重写 on_kline）
example_ma_cross_core.py  326 行 — Core 逻辑层（完整入场分支 + 出场 + State）
overrides/BTCUSDT.yaml     73 行 — per-symbol 配置，字段逐条带注释
tests/                    434 行 — 新策略该测什么的清单
```

代码里标 ★ 的注释就是重点。按"我要写什么"查的地图见
[docs/strategy/QUICKSTART.md → Step 0](../../docs/strategy/QUICKSTART.md)。

## 跑一下

```bash
python3 -m pytest strategies/example_ma_cross/tests/ -v
```

> `tests/__init__.py` 是空文件但**不能删**：每个策略的测试目录都有一个同名的
> `test_strategy_logging.py`，没有这个包标记，pytest 同时收集多个策略的测试时会
> basename 冲突并直接中断收集。

## 它演示了什么

| 契约 | 位置 |
|------|------|
| 完整入场分支（7 个 state 字段 + `_notify_position_enter`） | `example_ma_cross_core.py` `_open()` |
| `action` 只能是 `buy` / `sell` / `buy_close` / `sell_close` | `_open()` 与 `_close()` |
| 平仓一律走 `_notify_exit_and_clear()`，action 用它的返回值 | `_close()` |
| 下单量放 `metadata["target_notional"]` | `_open()` |
| 指标只用 `get_closed_data()` 的已闭合 K 线 | `analyze()` |
| 入场价优先 `realtime_price`，退回已闭合收盘价 | `analyze()` |
| 缓存字段不进 `to_persist_dict()` | `ExampleMaCrossState` |
| 策略特有字段在 `clear_position()` 里重置（统一风控走这条路） | `ExampleMaCrossState` |
| 基类默认每根 1m K 线都调 `analyze()`；要改成收线才判断得自己重写 `on_kline()` | `strategy.py` 顶部注释 + 文件末尾附录 |

## 要不要让它跑起来

默认**没有**在 `config/strategies.yaml` 里登记，所以启动策略管理器不会拉起它。
想跑就去那个文件里加一段（建议先用 `trading_mode: smoking` 空跑）。
