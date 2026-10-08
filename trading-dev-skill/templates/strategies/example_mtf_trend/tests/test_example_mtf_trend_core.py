#!/usr/bin/env python3
"""example_mtf_trend 多周期核心逻辑测试（参考实现）

除了常规的入场/出场/持久化，这里重点测多周期策略特有的坑：
  1. 缺任何一个周期的数据都必须 hold（三个 *_timeframe 都要被订阅）
  2. 任何一个周期的未闭合 bar 都不能影响判断
  3. 三周期必须共振才出信号，单周期满足不够
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from strategies.example_mtf_trend.example_mtf_trend_core import (
    ExampleMtfTrendCore,
    ExampleMtfTrendState,
)

SYMBOL = "BTCUSDT"
BASE = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


# current_time 锚点：各周期最后一根 bar 的 bar_end 都等于它，
# 再往后追加的 bar 即"未闭合 bar"（与实盘 klines_data 结构一致）
CT = BASE + timedelta(days=60)


def make_klines(closes, tf_minutes, end=CT):
    """按收盘价造 K 线，timestamp 结束锚定在 end：最后一根 bar_end == end。"""
    n = len(closes)
    return pd.DataFrame([
        {
            "timestamp": end - timedelta(minutes=tf_minutes * (n - i)),
            "open": c, "high": c * 1.01, "low": c * 0.99,
            "close": c, "volume": 1000.0,
        }
        for i, c in enumerate(closes)
    ])


@pytest.fixture
def core():
    c = ExampleMtfTrendCore(
        symbols=[SYMBOL],
        timeframes=["4h"],
        params={
            "trend_timeframe": "1d",
            "confirm_timeframe": "1h",
            "trend_ema_period": 50,
            "ma_fast_period": 10,
            "ma_slow_period": 30,
            "rsi_period": 14,
            "rsi_long_threshold": 55,
            "rsi_short_threshold": 45,
            "atr_period": 14,
            "atr_stop_mult": 2.0,
            "leverage": 1,
        },
    )
    c.set_strategy_name("EXAMPLEMTFTREND_4H_1_BTCUSDT_PAPER")
    return c


def long_klines(pollute_4h: bool = False) -> dict:
    """构造三周期共振做多的数据。"""
    # 1d：60 根持续上涨，最后收盘明显在 EMA50 上方
    daily = make_klines([100.0 + i for i in range(60)], 60 * 24)
    # 4h：34 根横盘 + 1 根拉高（fast10 上穿 slow30），最后一根 bar_end == CT
    trigger = make_klines([100.0] * 34 + [130.0], 60 * 4)
    if pollute_4h:
        # 未闭合 bar：bar_start == CT → bar_end = CT+4h > CT，必须被过滤
        polluted = trigger.copy()
        polluted.loc[len(polluted)] = {
            "timestamp": CT, "open": 99999.0, "high": 99999.0,
            "low": 99999.0, "close": 99999.0, "volume": 1.0}
        trigger = polluted
    # 1h：18 根横盘 + 1 根大阳，RSI≈100
    hourly = make_klines([100.0] * 18 + [120.0], 60)
    return {"1d": daily, "4h": trigger, "1h": hourly}


def short_klines() -> dict:
    daily = make_klines([100.0 + (59 - i) for i in range(60)], 60 * 24)
    trigger = make_klines([100.0] * 34 + [70.0], 60 * 4)
    hourly = make_klines([100.0] * 18 + [80.0], 60)
    return {"1d": daily, "4h": trigger, "1h": hourly}


# （CT 定义在 make_klines 上方：所有周期最后一根 bar 的 bar_end）


class TestMultiTimeframeData:

    def test_missing_trend_frame_holds(self, core):
        data = long_klines()
        del data["1d"]
        result = core.analyze(SYMBOL, data, current_time=CT, realtime_price=131.0)
        assert result["action"] == "hold"
        assert "1d" in result["metadata"]["reason"]

    def test_missing_confirm_frame_holds(self, core):
        data = long_klines()
        del data["1h"]
        result = core.analyze(SYMBOL, data, current_time=CT, realtime_price=131.0)
        assert result["action"] == "hold"
        assert "1h" in result["metadata"]["reason"]

    def test_short_trend_frame_holds(self, core):
        """1d 根数不够 EMA50+5 时必须 hold。"""
        data = long_klines()
        data["1d"] = make_klines([100.0 + i for i in range(30)], 60 * 24)
        result = core.analyze(SYMBOL, data, current_time=CT, realtime_price=131.0)
        assert result["action"] == "hold"
        assert "1d" in result["metadata"]["reason"]


class TestTripleConfirmationEntry:

    def test_long_when_all_three_align(self, core):
        result = core.analyze(
            SYMBOL, long_klines(),
            current_time=CT, realtime_price=131.0, current_cash=200.0)

        assert result["action"] == "buy"
        assert result["price"] == 131.0
        state = core._get_state(SYMBOL)
        assert state.position == "long"
        assert state.atr_at_entry > 0
        assert state.trend_ema_at_entry > 0
        # ATR 止损在入场价下方，且 = entry - 2*ATR
        assert state.stop_price == pytest.approx(131.0 - 2.0 * state.atr_at_entry)
        assert result["metadata"]["target_notional"] == 200.0

    def test_short_when_all_three_align(self, core):
        result = core.analyze(
            SYMBOL, short_klines(),
            current_time=CT, realtime_price=69.0)
        assert result["action"] == "sell"
        state = core._get_state(SYMBOL)
        assert state.position == "short"
        assert state.stop_price > 69.0

    def test_trigger_alone_is_not_enough(self, core):
        """4h 金叉但 1d 方向向下、1h 不确认 → hold。"""
        data = {
            "1d": make_klines([100.0 + (59 - i) for i in range(60)], 60 * 24),
            "4h": make_klines([100.0] * 34 + [130.0], 60 * 4),
            "1h": make_klines([100.0] * 19, 60),       # RSI=50，无确认
        }
        result = core.analyze(SYMBOL, data, current_time=CT,
                              realtime_price=131.0)
        assert result["action"] == "hold"
        assert not core._get_state(SYMBOL).is_in_position()

    def test_direction_long_blocks_short_setup(self, core):
        core.direction = "long"
        result = core.analyze(SYMBOL, short_klines(),
                              current_time=CT, realtime_price=69.0)
        assert result["action"] == "hold"


class TestNoLookaheadAcrossFrames:

    def test_unclosed_trigger_bar_ignored(self, core):
        """4h 多喂一根未闭合的极端 bar，结果必须与正常数据一致。"""
        baseline = core.analyze(
            SYMBOL, long_klines(),
            current_time=CT, realtime_price=131.0)
        core._get_state(SYMBOL).clear_position()

        result = core.analyze(
            SYMBOL, long_klines(pollute_4h=True),
            current_time=CT, realtime_price=131.0)

        assert result["action"] == baseline["action"]
        assert result["price"] == baseline["price"]

    def test_unclosed_trend_bar_ignored(self, core):
        """1d 多喂一根暴跌的未闭合 bar，不能把趋势翻空。"""
        data = long_klines()
        daily = data["1d"].copy()
        daily.loc[len(daily)] = {
            "timestamp": CT, "open": 1.0, "high": 1.0,
            "low": 1.0, "close": 1.0, "volume": 1.0}
        data["1d"] = daily
        result = core.analyze(
            SYMBOL, data, current_time=CT, realtime_price=131.0)
        assert result["action"] == "buy"   # 仍是 1d 上涨 + 4h 金叉


class TestExit:

    def test_long_atr_stop(self, core):
        ct = datetime(2026, 3, 5, 12, 0, tzinfo=timezone.utc)
        state = core._get_state(SYMBOL)
        state.position = "long"
        state.entry_price = 131.0
        state.stop_price = 125.0
        state.peak_price = 131.0

        result = core.check_realtime_exit(
            SYMBOL, 126.0, current_time=ct, bar_high=127.0, bar_low=124.0)

        assert result["action"] == "sell_close"
        assert result["price"] == 125.0
        assert result["metadata"]["is_stop_loss"] is True
        assert state.stop_loss_date == ct.date()

    def test_hold_when_stop_not_touched(self, core):
        state = core._get_state(SYMBOL)
        state.position = "long"
        state.entry_price = 100.0
        state.stop_price = 90.0
        result = core.check_realtime_exit(
            SYMBOL, 105.0, bar_high=106.0, bar_low=104.0)
        assert result["action"] == "hold"
        assert state.is_in_position()


class TestPersistence:

    def test_custom_fields_roundtrip(self):
        state = ExampleMtfTrendState()
        state.position = "long"
        state.atr_at_entry = 123.4
        state.trend_ema_at_entry = 456.7
        state.latest_rsi = 71.0

        restored = ExampleMtfTrendState()
        restored.restore_from_dict(state.to_persist_dict())
        assert restored.atr_at_entry == 123.4
        assert restored.trend_ema_at_entry == 456.7

    def test_cache_field_not_persisted(self):
        state = ExampleMtfTrendState()
        state.latest_rsi = 80.0
        assert "latest_rsi" not in state.to_persist_dict()
