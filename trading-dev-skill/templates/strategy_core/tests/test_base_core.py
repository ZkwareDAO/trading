#!/usr/bin/env python3
"""
BaseStrategyCore 单元测试
"""

import pytest
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional
import pandas as pd

from strategy_core.base.core import BaseStrategyCore
from strategy_core.base.state import BaseState


class MockState(BaseState):
    """测试用状态类"""
    custom_field: float = 0.0

    def _get_state(self, symbol: str) -> "MockState":
        if symbol not in self._state:
            self._state[symbol] = MockState()
        return self._state[symbol]


class MockStrategyCore(BaseStrategyCore[MockState]):
    """测试用策略核心类"""

    def _get_state(self, symbol: str) -> MockState:
        if symbol not in self._state:
            self._state[symbol] = MockState()
        return self._state[symbol]

    def analyze(
        self,
        symbol: str,
        klines_data: Dict[str, pd.DataFrame],
        current_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        state = self._get_state(symbol)
        if state.is_in_position():
            return {"action": "hold", "price": 0, "strength": 0, "metadata": {"reason": "已有持仓"}}
        return {"action": "hold", "price": 100.0, "strength": 0, "metadata": {"reason": "测试"}}

    def check_realtime_exit(
        self,
        symbol: str,
        current_price: float,
        current_time: Optional[datetime] = None,
        bar_high: Optional[float] = None,
        bar_low: Optional[float] = None,
    ) -> Dict[str, Any]:
        state = self._get_state(symbol)
        if not state.is_in_position():
            return {"action": "hold", "price": current_price, "strength": 0, "metadata": {"reason": "无持仓"}}
        return {"action": "hold", "price": current_price, "strength": 0, "metadata": {"reason": "持仓中"}}

    def get_status(self) -> Dict[str, Any]:
        return {"positions": {s: st.position for s, st in self._state.items() if st.position}}


class TestBaseStrategyCore:
    """BaseStrategyCore 基类测试"""

    @pytest.fixture
    def core(self):
        return MockStrategyCore(
            symbols=["BTCUSDT"],
            timeframes=["1h"],
            params={"test_param": 10},
        )

    def test_init(self, core):
        """测试初始化"""
        assert core.symbols == ["BTCUSDT"]
        assert core.timeframes == ["1h"]
        assert core.params == {"test_param": 10}
        assert core._strategy_name == ""
        assert core._backtest_mode is False

    def test_set_strategy_name(self, core):
        """测试设置策略名称"""
        core.set_strategy_name("OBVATRv1_1h_BTCUSDT")
        assert core._strategy_name == "OBVATRv1_1h_BTCUSDT"

    def test_set_backtest_mode(self, core):
        """测试设置回测模式"""
        core.set_backtest_mode(True)
        assert core._backtest_mode is True

    def test_parse_interval_to_minutes_minutes(self):
        """测试解析分钟周期"""
        assert BaseStrategyCore.parse_interval_to_minutes("1m") == 1
        assert BaseStrategyCore.parse_interval_to_minutes("15m") == 15
        assert BaseStrategyCore.parse_interval_to_minutes("60m") == 60

    def test_parse_interval_to_minutes_hours(self):
        """测试解析小时周期"""
        assert BaseStrategyCore.parse_interval_to_minutes("1h") == 60
        assert BaseStrategyCore.parse_interval_to_minutes("4h") == 240
        assert BaseStrategyCore.parse_interval_to_minutes("24h") == 1440

    def test_parse_interval_to_minutes_days(self):
        """测试解析天周期"""
        assert BaseStrategyCore.parse_interval_to_minutes("1d") == 1440
        assert BaseStrategyCore.parse_interval_to_minutes("7d") == 10080

    def test_get_expected_last_closed_timestamp(self):
        """测试计算期望的最后一根闭合 K 线时间戳"""
        # 10:30 → 期望最后一根 1h K 线是 09:00
        current_time = datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc)
        expected = BaseStrategyCore.get_expected_last_closed_timestamp(current_time, 60)
        assert expected == datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)

        # 11:00 → 期望最后一根 1h K 线是 10:00
        current_time = datetime(2024, 1, 1, 11, 0, 0, tzinfo=timezone.utc)
        expected = BaseStrategyCore.get_expected_last_closed_timestamp(current_time, 60)
        assert expected == datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)

        # 09:30 → 期望最后一根 4h K 线是 04:00
        current_time = datetime(2024, 1, 1, 9, 30, 0, tzinfo=timezone.utc)
        expected = BaseStrategyCore.get_expected_last_closed_timestamp(current_time, 240)
        assert expected == datetime(2024, 1, 1, 4, 0, 0, tzinfo=timezone.utc)

    def test_get_closed_data_filters_by_time(self, core):
        """测试根据时间过滤已闭合 K 线"""
        # 创建测试数据
        timestamps = [
            datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc),
            datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
        ]
        df = pd.DataFrame({
            "timestamp": timestamps,
            "open": [100.0, 101.0, 102.0],
            "high": [105.0, 106.0, 107.0],
            "low": [95.0, 96.0, 97.0],
            "close": [101.0, 102.0, 103.0],
            "volume": [1000, 1000, 1000],
        })
        klines_data = {"1h": df}

        # 当前时间 10:30 → 应过滤掉 10:00 的 bar（未闭合）
        current_time = datetime(2024, 1, 1, 10, 30, 0, tzinfo=timezone.utc)
        closed_df = core.get_closed_data(klines_data, "1h", current_time=current_time)

        assert len(closed_df) == 2
        assert closed_df["timestamp"].iloc[-1] == datetime(2024, 1, 1, 9, 0, 0, tzinfo=timezone.utc)

    def test_get_closed_data_returns_empty_when_insufficient_data(self, core):
        """测试数据不足时返回空 DataFrame"""
        df = pd.DataFrame({
            "timestamp": [datetime(2024, 1, 1, 8, 0, 0, tzinfo=timezone.utc)],
            "close": [100.0],
        })
        klines_data = {"1h": df}

        closed_df = core.get_closed_data(klines_data, "1h", min_rows=3)
        assert closed_df.empty

    def test_position_callbacks_not_called_in_backtest_mode(self, core):
        """回测模式下不触发仓位回调"""
        core.set_backtest_mode(True)
        callback_called = False

        def callback(symbol, state):
            callback_called = True

        core.set_position_callbacks(on_enter=callback)

        # 即使设置了回调，回测模式也不应该触发
        state = core._get_state("BTCUSDT")
        core._notify_position_enter("BTCUSDT", state)

        assert callback_called is False

    def test_position_callbacks_called_in_live_mode(self, core):
        """实盘模式下触发仓位回调"""
        core.set_backtest_mode(False)
        callback_results = {"called": False}

        def callback(symbol, state):
            callback_results["called"] = True

        core.set_position_callbacks(on_enter=callback)

        state = core._get_state("BTCUSDT")
        core._notify_position_enter("BTCUSDT", state)

        assert callback_results["called"] is True

    def test_format_bar_ts_with_aware_datetime(self, core):
        """带时区的时间戳格式化为 YYYY-MM-DD HH:MM"""
        ts = datetime(2026, 7, 22, 14, 30, tzinfo=timezone.utc)
        assert core._format_bar_ts(ts) == "2026-07-22 14:30"

    def test_format_bar_ts_with_naive_datetime(self, core):
        """无时区的时间戳也能正常格式化"""
        ts = datetime(2026, 7, 22, 9, 5)
        assert core._format_bar_ts(ts) == "2026-07-22 09:05"

    def test_format_bar_ts_returns_na_for_none(self, core):
        """None 时间戳返回 'N/A'，用于诊断日志占位"""
        assert core._format_bar_ts(None) == "N/A"


class TestExitDetectionMode:
    """止损止盈检测模式测试"""

    def test_default_mode_is_bar_high_low(self):
        """默认使用 bar_high/bar_low 模式"""
        core = MockStrategyCore(symbols=["BTCUSDT"], timeframes=["1h"])
        assert core.use_bar_high_low_for_exit is True

    def test_mode_from_global_config_enabled(self):
        """从全局配置读取启用模式"""
        global_config = {"strategy_engine": {"use_bar_high_low_for_exit": True}}
        core = MockStrategyCore(
            symbols=["BTCUSDT"],
            timeframes=["1h"],
            global_config=global_config,
        )
        assert core.use_bar_high_low_for_exit is True

    def test_mode_from_global_config_disabled(self):
        """从全局配置读取禁用模式"""
        global_config = {"strategy_engine": {"use_bar_high_low_for_exit": False}}
        core = MockStrategyCore(
            symbols=["BTCUSDT"],
            timeframes=["1h"],
            global_config=global_config,
        )
        assert core.use_bar_high_low_for_exit is False

    def test_get_exit_detection_prices_with_bar_high_low(self):
        """使用 bar_high/bar_low 时返回正确价格"""
        global_config = {"strategy_engine": {"use_bar_high_low_for_exit": True}}
        core = MockStrategyCore(
            symbols=["BTCUSDT"],
            timeframes=["1h"],
            global_config=global_config,
        )
        check_high, check_low = core._get_exit_detection_prices(
            current_price=100.0,
            bar_high=105.0,
            bar_low=95.0,
        )
        assert check_high == 105.0
        assert check_low == 95.0

    def test_get_exit_detection_prices_without_bar_high_low(self):
        """禁用 bar_high/bar_low 时使用 current_price"""
        global_config = {"strategy_engine": {"use_bar_high_low_for_exit": False}}
        core = MockStrategyCore(
            symbols=["BTCUSDT"],
            timeframes=["1h"],
            global_config=global_config,
        )
        check_high, check_low = core._get_exit_detection_prices(
            current_price=100.0,
            bar_high=105.0,
            bar_low=95.0,
        )
        assert check_high == 100.0
        assert check_low == 100.0

    def test_get_exit_detection_prices_fallback_when_bar_data_missing(self):
        """bar_high/bar_low 缺失时回退到 current_price"""
        global_config = {"strategy_engine": {"use_bar_high_low_for_exit": True}}
        core = MockStrategyCore(
            symbols=["BTCUSDT"],
            timeframes=["1h"],
            global_config=global_config,
        )
        # bar_high 缺失
        check_high, check_low = core._get_exit_detection_prices(
            current_price=100.0,
            bar_high=None,
            bar_low=95.0,
        )
        assert check_high == 100.0
        assert check_low == 100.0

        # bar_low 缺失
        check_high, check_low = core._get_exit_detection_prices(
            current_price=100.0,
            bar_high=105.0,
            bar_low=None,
        )
        assert check_high == 100.0
        assert check_low == 100.0