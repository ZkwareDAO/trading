#!/usr/bin/env python3
"""测试 BaseStrategyCore._notify_exit_and_clear 方法"""

import pytest
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from strategy_core.base.core import BaseStrategyCore
from strategy_core.base.state import BaseState


class MockState(BaseState):
    """测试用的状态类"""
    pass


class MockCore(BaseStrategyCore[MockState]):
    """测试用的 Core 类"""

    def __init__(self):
        super().__init__(
            symbols=["BTCUSDT"],
            timeframes=["1h"],
            params=None,
        )
        self.exit_notified = False
        self.exit_params = {}

    def _get_state(self, symbol: str) -> MockState:
        if symbol not in self._state:
            self._state[symbol] = MockState()
        return self._state[symbol]

    def analyze(self, symbol: str, klines_data: Dict[str, Any], current_time: Optional[datetime] = None) -> Dict[str, Any]:
        return {"action": "hold"}

    def check_realtime_exit(self, symbol: str, current_price: float, current_time: Optional[datetime] = None, bar_high: Optional[float] = None, bar_low: Optional[float] = None) -> Dict[str, Any]:
        return {"action": "hold"}

    def get_status(self) -> Dict[str, Any]:
        return {}

    def _notify_position_exit(self, symbol: str, state, exit_price: float, exit_reason: str, is_stop_loss: bool, exit_time: Optional[Any] = None):
        """重写以记录调用参数"""
        self.exit_notified = True
        self.exit_params = {
            "symbol": symbol,
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "is_stop_loss": is_stop_loss,
            "exit_time": exit_time,
        }


class TestNotifyExitAndClear:
    """测试 _notify_exit_and_clear 方法"""

    def test_returns_sell_close_for_long_position(self):
        """多头仓位返回 sell_close"""
        core = MockCore()
        state = core._get_state("BTCUSDT")
        state.position = "long"
        state.position_id = "test_123"
        state.entry_price = 50000.0

        action = core._notify_exit_and_clear(
            symbol="BTCUSDT",
            state=state,
            exit_price=51000.0,
            exit_reason="止盈",
            is_stop_loss=False,
            exit_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )

        assert action == "sell_close"

    def test_returns_buy_close_for_short_position(self):
        """空头仓位返回 buy_close"""
        core = MockCore()
        state = core._get_state("BTCUSDT")
        state.position = "short"
        state.position_id = "test_456"
        state.entry_price = 50000.0

        action = core._notify_exit_and_clear(
            symbol="BTCUSDT",
            state=state,
            exit_price=49000.0,
            exit_reason="止盈",
            is_stop_loss=False,
            exit_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )

        assert action == "buy_close"

    def test_calls_notify_position_exit_before_clear(self):
        """在清除状态之前调用 _notify_position_exit"""
        core = MockCore()
        state = core._get_state("BTCUSDT")
        state.position = "long"
        state.position_id = "test_789"
        state.entry_price = 50000.0

        core._notify_exit_and_clear(
            symbol="BTCUSDT",
            state=state,
            exit_price=51000.0,
            exit_reason="移动止盈",
            is_stop_loss=False,
            exit_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )

        assert core.exit_notified is True
        assert core.exit_params["symbol"] == "BTCUSDT"
        assert core.exit_params["exit_price"] == 51000.0
        assert core.exit_params["exit_reason"] == "移动止盈"
        assert core.exit_params["is_stop_loss"] is False

    def test_clears_position_state(self):
        """清除仓位状态"""
        core = MockCore()
        state = core._get_state("BTCUSDT")
        state.position = "long"
        state.position_id = "test_abc"
        state.entry_price = 50000.0
        state.peak_price = 52000.0
        state.stop_price = 48000.0
        state.entry_timestamp = 1735725600
        state.max_pnl_pct = 4.0
        state.min_pnl_pct = -2.0

        core._notify_exit_and_clear(
            symbol="BTCUSDT",
            state=state,
            exit_price=51000.0,
            exit_reason="止盈",
            is_stop_loss=False,
            exit_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )

        assert state.position is None
        assert state.position_id is None
        assert state.entry_price == 0.0
        assert state.peak_price == 0.0
        assert state.stop_price == 0.0
        assert state.entry_timestamp is None
        assert state.max_pnl_pct == 0.0
        assert state.min_pnl_pct == 0.0

    def test_records_stop_loss_date_when_is_stop_loss(self):
        """止损时记录止损日期"""
        core = MockCore()
        state = core._get_state("BTCUSDT")
        state.position = "long"
        state.position_id = "test_def"
        state.entry_price = 50000.0

        exit_time = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
        core._notify_exit_and_clear(
            symbol="BTCUSDT",
            state=state,
            exit_price=48000.0,
            exit_reason="止损",
            is_stop_loss=True,
            exit_time=exit_time,
        )

        assert state.stop_loss_date == exit_time.date()

    def test_does_not_record_stop_loss_date_when_not_stop_loss(self):
        """非止损时不记录止损日期"""
        core = MockCore()
        state = core._get_state("BTCUSDT")
        state.position = "long"
        state.position_id = "test_ghi"
        state.entry_price = 50000.0

        core._notify_exit_and_clear(
            symbol="BTCUSDT",
            state=state,
            exit_price=52000.0,
            exit_reason="止盈",
            is_stop_loss=False,
            exit_time=datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc),
        )

        assert state.stop_loss_date is None

    def test_skips_notify_when_no_position_id(self):
        """无 position_id 时跳过通知"""
        core = MockCore()
        state = core._get_state("BTCUSDT")
        state.position = "long"
        state.position_id = None  # 无 ID
        state.entry_price = 50000.0

        core._notify_exit_and_clear(
            symbol="BTCUSDT",
            state=state,
            exit_price=51000.0,
            exit_reason="止盈",
            is_stop_loss=False,
            exit_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )

        assert core.exit_notified is False

    def test_passes_all_params_to_notify(self):
        """传递所有参数到 _notify_position_exit"""
        core = MockCore()
        state = core._get_state("BTCUSDT")
        state.position = "short"
        state.position_id = "test_jkl"
        state.entry_price = 50000.0

        exit_time = datetime(2026, 3, 15, 14, 30, tzinfo=timezone.utc)
        core._notify_exit_and_clear(
            symbol="BTCUSDT",
            state=state,
            exit_price=48000.0,
            exit_reason="时间止损",
            is_stop_loss=True,
            exit_time=exit_time,
        )

        assert core.exit_params["symbol"] == "BTCUSDT"
        assert core.exit_params["exit_price"] == 48000.0
        assert core.exit_params["exit_reason"] == "时间止损"
        assert core.exit_params["is_stop_loss"] is True
        assert core.exit_params["exit_time"] == exit_time
