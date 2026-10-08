#!/usr/bin/env python3
"""example_mtf_trend 信号格式测试（与框架的返回值契约）"""

from datetime import timedelta

import pandas as pd
import pytest

from strategies.example_mtf_trend.example_mtf_trend_core import ExampleMtfTrendCore

SYMBOL = "BTCUSDT"
BASE = pd.Timestamp("2026-01-01", tz="UTC")
REQUIRED_KEYS = {"action", "price", "strength", "metadata"}
VALID_ACTIONS = {"hold", "buy", "sell", "buy_close", "sell_close"}


def make_klines(closes, tf_minutes):
    return pd.DataFrame([
        {"timestamp": BASE + timedelta(minutes=tf_minutes * i),
         "open": c, "high": c * 1.01, "low": c * 0.99,
         "close": c, "volume": 1000.0}
        for i, c in enumerate(closes)
    ])


@pytest.fixture
def core():
    c = ExampleMtfTrendCore(
        symbols=[SYMBOL], timeframes=["4h"],
        params={"trend_timeframe": "1d", "confirm_timeframe": "1h"},
    )
    c.set_strategy_name("EXAMPLEMTFTREND_4H_1_BTCUSDT_PAPER")
    return c


def long_data():
    return {
        "1d": make_klines([100.0 + i for i in range(60)], 60 * 24),
        "4h": make_klines([100.0] * 34 + [130.0], 60 * 4),
        "1h": make_klines([100.0] * 18 + [120.0], 60),
    }


class TestReturnShape:

    def test_hold_shape(self, core):
        result = core.analyze(SYMBOL, {}, current_time=None)
        assert REQUIRED_KEYS <= result.keys()
        assert result["action"] == "hold"

    def test_entry_action_whitelisted(self, core):
        ct = BASE + timedelta(days=60)
        result = core.analyze(SYMBOL, long_data(), current_time=ct,
                              realtime_price=131.0, current_cash=200.0)
        assert result["action"] in VALID_ACTIONS
        assert result["action"] not in ("buy_close", "sell_close")
        assert result["metadata"]["target_notional"] > 0

    def test_exit_shape(self, core):
        state = core._get_state(SYMBOL)
        state.position, state.entry_price, state.stop_price = "long", 131.0, 125.0
        ct = pd.Timestamp("2026-03-05 12:00", tz="UTC")
        result = core.check_realtime_exit(
            SYMBOL, 126.0, current_time=ct, bar_high=127.0, bar_low=124.0)
        assert REQUIRED_KEYS <= result.keys()
        assert result["action"] in ("sell_close", "hold")
        if result["action"] == "sell_close":
            assert result["metadata"]["is_stop_loss"] is True

    def test_get_status(self, core):
        status = core.get_status()
        assert {"symbols", "timeframes", "states"} <= status.keys()
        assert SYMBOL in status["states"]
