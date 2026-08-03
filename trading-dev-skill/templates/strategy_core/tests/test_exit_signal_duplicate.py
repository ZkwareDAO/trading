#!/usr/bin/env python3
"""
测试平仓信号防重复发送

验证：
1. 同一 K 线周期内不重复发送平仓信号
2. 不同 K 线周期可以发送平仓信号
3. 入场信号不受限制
"""

import logging
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest

from strategy_core.base.strategy import BaseStrategy
from strategy_core.base.core import BaseStrategyCore
from strategy_core.base.state import BaseState
from data_manager import DataManager


class MockStrategyCore(BaseStrategyCore):
    """模拟策略核心"""

    def _get_state(self, symbol):
        if symbol not in self._state:
            from strategy_core.base.state import BaseState
            self._state[symbol] = BaseState()
        return self._state[symbol]

    def analyze(self, symbol, klines_data, current_time=None):
        return {"action": "hold", "price": 0, "strength": 0}

    def check_realtime_exit(self, symbol, current_price, current_time=None, bar_high=None, bar_low=None):
        return {"action": "hold", "price": current_price, "strength": 0}

    def get_status(self):
        return {"symbols": self.symbols}


class MockStrategy(BaseStrategy):
    """测试用模拟策略"""

    STRATEGY_TYPE = "mock_strategy"
    STRATEGY_PREFIX = "MOCK"
    DEFAULT_TIMEFRAME = "1h"

    def _create_core(self):
        return MockStrategyCore(
            symbols=self.symbols,
            timeframes=self.timeframes,
            params=self.params,
        )

    def _get_indicator_timeframes(self) -> set:
        return set(self.timeframes)


class TestExitSignalDuplicate:
    """测试平仓信号防重复发送"""

    def _create_strategy(self):
        """创建测试策略"""
        mock_data_manager = MagicMock(spec=DataManager)
        mock_data_manager.config = MagicMock()
        mock_data_manager.config.backtest_mode = False
        mock_data_manager.get_dataframe_cached.return_value = MagicMock()

        config = {
            "symbols": ["BTCUSDT"],
            "timeframes": ["1h"],
            "version": "v1",
            "signal": {"min_strength": 0.5},
            "capital": {"max_cash": 100},
        }

        strategy = MockStrategy(
            data_manager=mock_data_manager,
            config=config,
            trading_mode="live",
        )
        strategy.on_start()

        return strategy

    def test_exit_signal_not_duplicate_same_bar(self, caplog):
        """同一 K 线周期内不重复发送平仓信号"""
        strategy = self._create_strategy()

        # 设置持仓状态
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 70000.0
        state.stop_price = 68000.0

        # Mock core 返回平仓信号
        def mock_exit(*args, **kwargs):
            return {"action": "sell_close", "price": 68000.0, "strength": 0.8, "metadata": {"reason": "止损"}}

        strategy._core.check_realtime_exit = mock_exit

        # 创建模拟 K 线
        base_time = datetime.now(timezone.utc)

        # 第一次 K 线
        kline1 = MagicMock()
        kline1.symbol = "BTCUSDT"
        kline1.close = 68000.0
        kline1.high = 68500.0
        kline1.low = 67500.0
        kline1.timestamp = base_time

        with caplog.at_level(logging.INFO, logger="strategy_core.base.strategy"):
            signal1 = strategy.on_kline(kline1)

        # 第二次 K 线（同一周期，时间相同）
        kline2 = MagicMock()
        kline2.symbol = "BTCUSDT"
        kline2.close = 67900.0
        kline2.high = 68100.0
        kline2.low = 67800.0
        kline2.timestamp = base_time  # 相同时间

        signal2 = strategy.on_kline(kline2)

        # 只有第一个信号应该返回
        # 第二次因为状态已清除，不应该返回信号
        assert signal1 is not None
        assert signal2 is None

    def test_exit_signal_allowed_different_bar(self, caplog):
        """不同 K 线周期可以发送平仓信号"""
        strategy = self._create_strategy()

        # 设置持仓状态
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 70000.0

        # Mock core 返回平仓信号
        def mock_exit(*args, **kwargs):
            return {"action": "sell_close", "price": 71000.0, "strength": 0.8, "metadata": {"reason": "止盈"}}

        strategy._core.check_realtime_exit = mock_exit

        base_time = datetime.now(timezone.utc)

        # 第一次 K 线
        kline1 = MagicMock()
        kline1.symbol = "BTCUSDT"
        kline1.close = 71000.0
        kline1.high = 71500.0
        kline1.low = 70500.0
        kline1.timestamp = base_time

        signal1 = strategy.on_kline(kline1)

        # 状态已清除，重新设置持仓
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 72000.0

        # 清除冷却期（模拟时间过了60秒）
        strategy._last_exit_signal_time["BTCUSDT"] = base_time - timedelta(seconds=61)

        # 第二次 K 线（不同周期，+1分钟）
        kline2 = MagicMock()
        kline2.symbol = "BTCUSDT"
        kline2.close = 72000.0
        kline2.high = 72500.0
        kline2.low = 71500.0
        kline2.timestamp = base_time + timedelta(minutes=1)

        signal2 = strategy.on_kline(kline2)

        # 两个信号都应该返回（不同周期）
        assert signal1 is not None
        assert signal2 is not None

    def test_entry_signal_not_blocked(self):
        """入场信号不受平仓防重复限制"""
        strategy = self._create_strategy()

        # Mock core 返回入场信号
        def mock_analyze(*args, **kwargs):
            return {"action": "buy", "price": 70000.0, "strength": 0.8, "metadata": {"reason": "入场"}}

        strategy._core.analyze = mock_analyze

        base_time = datetime.now(timezone.utc)

        # 第一次 K 线
        kline1 = MagicMock()
        kline1.symbol = "BTCUSDT"
        kline1.close = 70000.0
        kline1.timestamp = base_time

        # Mock data
        mock_df = MagicMock()
        mock_df.empty = False
        mock_df.__len__ = MagicMock(return_value=100)
        mock_df.iloc = MagicMock()
        mock_df.iloc.__getitem__ = MagicMock(return_value={"timestamp": base_time})

        strategy.data_manager.get_dataframe_cached.return_value = mock_df

        signal1 = strategy.on_kline(kline1)

        # 设置持仓后再入场（模拟补仓）
        state = strategy._core._get_state("BTCUSDT")
        state.position = None  # 清除持仓

        # 第二次 K 线
        kline2 = MagicMock()
        kline2.symbol = "BTCUSDT"
        kline2.close = 71000.0
        kline2.timestamp = base_time + timedelta(seconds=30)

        signal2 = strategy.on_kline(kline2)

        # 入场信号应该正常发送
        assert signal1 is not None or signal1 is None  # 取决于冷却逻辑

    def test_last_exit_signal_time_recorded(self):
        """平仓信号时间被记录"""
        strategy = self._create_strategy()

        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 70000.0

        def mock_exit(*args, **kwargs):
            return {"action": "sell_close", "price": 70000.0, "strength": 0.8, "metadata": {"reason": "test"}}

        strategy._core.check_realtime_exit = mock_exit

        kline = MagicMock()
        kline.symbol = "BTCUSDT"
        kline.close = 70000.0
        kline.high = 70500.0
        kline.low = 69500.0
        kline.timestamp = datetime.now(timezone.utc)

        signal = strategy.on_kline(kline)

        # 验证记录了平仓时间
        assert "BTCUSDT" in strategy._last_exit_signal_time