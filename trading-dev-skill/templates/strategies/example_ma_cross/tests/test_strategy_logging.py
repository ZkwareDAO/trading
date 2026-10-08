#!/usr/bin/env python3
"""example_ma_cross 信号格式测试（参考实现）

每个策略都该有这个文件。它测的不是交易逻辑，而是**和框架之间的契约**：
返回值少一个键、action 拼错一个字母，运行时不会报错，只会静默不发信号。
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from strategies.example_ma_cross.example_ma_cross_core import ExampleMaCrossCore

SYMBOL = "BTCUSDT"
TF = "4h"
BASE = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

# 基类 _create_signal() 的 action_map 白名单（strategy.py:667-672）。
# 不在这个集合里的 action 会让 _create_signal() 返回 None —— 信号被丢弃。
VALID_ACTIONS = {"hold", "buy", "sell", "buy_close", "sell_close"}
REQUIRED_KEYS = {"action", "price", "strength", "metadata"}


def make_klines(closes):
    return pd.DataFrame([
        {
            "timestamp": BASE + timedelta(hours=4 * i),
            "open": c, "high": c * 1.01, "low": c * 0.99,
            "close": c, "volume": 1000.0,
        }
        for i, c in enumerate(closes)
    ])


@pytest.fixture
def core():
    c = ExampleMaCrossCore(
        symbols=[SYMBOL],
        timeframes=[TF],
        params={"ma_timeframes": TF, "ma_fast_period": 3,
                "ma_slow_period": 5, "stop_loss_pct": 2.0},
    )
    c.set_strategy_name("EXAMPLEMACROSS_4H_1_BTCUSDT_PAPER")
    return c


class TestReturnShape:
    """四个键一个都不能少 —— 基类会直接下标取 result["action"] / result["price"]。"""

    def test_hold_result_shape(self, core):
        result = core._hold_result("测试原因")
        assert REQUIRED_KEYS <= result.keys()
        assert result["action"] == "hold"
        assert "reason" in result["metadata"]

    def test_analyze_shape_and_action(self, core):
        result = core.analyze(
            SYMBOL, {TF: make_klines([100.0] * 10 + [130.0])},
            current_time=BASE + timedelta(hours=44),
            realtime_price=131.0, current_cash=200.0)
        assert REQUIRED_KEYS <= result.keys()
        assert result["action"] in VALID_ACTIONS
        # analyze() 只能产出入场或 hold，不能产出平仓 action
        assert result["action"] not in ("buy_close", "sell_close")
        assert isinstance(result["strength"], (int, float))

    def test_exit_shape_and_action(self, core):
        state = core._get_state(SYMBOL)
        state.position = "long"
        state.entry_price = 100.0
        state.stop_price = 98.0

        result = core.check_realtime_exit(
            SYMBOL, 97.0,
            current_time=datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc),
            bar_high=99.0, bar_low=96.0)

        assert REQUIRED_KEYS <= result.keys()
        assert result["action"] in VALID_ACTIONS
        # check_realtime_exit() 只能产出平仓或 hold，不能产出入场 action
        assert result["action"] not in ("buy", "sell")
        if result["action"] in ("buy_close", "sell_close"):
            assert "is_stop_loss" in result["metadata"]
            assert "reason" in result["metadata"]

    def test_entry_metadata_carries_order_size(self, core):
        """入场 metadata 必须带下单量，否则下游不知道下多大。"""
        result = core.analyze(
            SYMBOL, {TF: make_klines([100.0] * 10 + [130.0])},
            current_time=BASE + timedelta(hours=44),
            realtime_price=131.0, current_cash=200.0)
        assert result["action"] == "buy"
        assert "target_notional" in result["metadata"]
        assert result["metadata"]["target_notional"] > 0

    def test_strength_clears_min_strength_gate(self, core):
        """strength 必须 ≥ overrides 里的 signal.min_strength，否则信号被丢。"""
        result = core.analyze(
            SYMBOL, {TF: make_klines([100.0] * 10 + [130.0])},
            current_time=BASE + timedelta(hours=44), realtime_price=131.0)
        assert result["strength"] >= 0.5   # overrides/BTCUSDT.yaml 配的门槛


class TestStatus:

    def test_get_status_shape(self, core):
        status = core.get_status()
        assert "symbols" in status
        assert "timeframes" in status
        assert "states" in status
        assert SYMBOL in status["states"]
