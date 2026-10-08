# example_mtf_trend — 多周期参考实现（multi-timeframe reference）

**正常的 CTA 策略基本都是多周期的。单周期入门读 [`example_ma_cross`](../example_ma_cross/)，
做多周期读这个。**

策略：三周期共振趋势跟随

```
1d 定方向   收盘价在 EMA50 上方 → 只做多；下方 → 只做空
4h 找触发   MA10 上穿/下穿 MA30（主周期 = timeframes[0]）
1h 做确认   RSI14 > 55 / < 45，过滤逆小势的假交叉
止损        2 × ATR14(4h)；统一风控在 risk 段兜底
```

交易逻辑依旧故意做得很笨，用途是演示**多周期的两条硬性规则**：

1. `Strategy._get_indicator_timeframes()` 必须把每个 `*_timeframe` 都收集进集合
   （`strategy.py`）——漏一个周期，`klines_data` 里就没有那个 key。
2. `Core.analyze()` 必须**对每个周期分别调用 `get_closed_data()` 并单独做数据不足检查**
   （`example_mtf_trend_core.py` 里连续三段），绝不能直接用 `klines_data[tf]` 原始 df。

## 文件

```
strategy.py                ~45 行  周期订阅声明
example_mtf_trend_core.py  ~280 行 三周期取数 / 指标 / 共振入场 / ATR 出场
overrides/BTCUSDT.yaml            三个 *_timeframe 参数的配置示范
tests/                            多周期特有坑的测试（缺周期、跨周期未来函数）
```

## 多周期测试清单（照抄结构）

见 `tests/test_example_mtf_trend_core.py`：

| 测试 | 防什么坑 |
|------|----------|
| 缺任一周期 → hold | `_get_indicator_timeframes()` 漏收集 |
| 任一周期根数不足 → hold | 预热期指标 NaN 仍发信号 |
| 未闭合 bar 追加到 4h / 1d → 结果不变 | 多周期未来函数 |
| 只有 4h 金叉、1d/1h 不配合 → hold | 没做共振判断 |
| 三周期全部对齐 → 入场，state 七字段齐 | 入场分支契约 |

## 跑一下

```bash
python3 -m pytest strategies/example_mtf_trend/tests/ -v
python -m backtest.run_backtest --strategies example_mtf_trend:BTCUSDT \
    --start 20260610 --end 20260708
```

> 回测/实盘里没有 1d CSV 也没关系，DataManager 会从 1m 自动聚合，
> 只要 1m 历史数据天数足够（1d EMA50 需要约 55 根日线）。
