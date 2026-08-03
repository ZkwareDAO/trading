#!/usr/bin/env python3
"""
BaseStrategy 单元测试
"""

import pytest
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from unittest.mock import MagicMock, patch
import pandas as pd

from strategy_core.base.strategy import BaseStrategy
from strategy_core.base.core import BaseStrategyCore
from strategy_core.base.state import BaseState
from strategy_core.signal_logging import Signal, SignalType


class MockState(BaseState):
    """测试用状态类"""
    pass


class MockCore(BaseStrategyCore[MockState]):
    """测试用策略核心"""

    def _get_state(self, symbol: str) -> MockState:
        if symbol not in self._state:
            self._state[symbol] = MockState()
        return self._state[symbol]

    def analyze(self, symbol: str, klines_data: Dict[str, pd.DataFrame],
                current_time: Optional[datetime] = None) -> Dict[str, Any]:
        state = self._get_state(symbol)
        if state.is_in_position():
            return {"action": "hold", "price": 0, "strength": 0, "metadata": {"reason": "已有持仓"}}
        return {"action": "buy", "price": 100.0, "strength": 0.7,
                "metadata": {"reason": "测试入场"}}

    def check_realtime_exit(self, symbol: str, current_price: float,
                            current_time: Optional[datetime] = None,
                            bar_high: Optional[float] = None,
                            bar_low: Optional[float] = None) -> Dict[str, Any]:
        state = self._get_state(symbol)
        if not state.is_in_position():
            return {"action": "hold", "price": current_price, "strength": 0, "metadata": {"reason": "无持仓"}}
        return {"action": "sell_close", "price": current_price, "strength": 0.8,
                "metadata": {"reason": "测试出场"}}

    def get_status(self) -> Dict[str, Any]:
        return {"positions": {}}


class MockStrategy(BaseStrategy):
    """测试用策略类"""

    STRATEGY_TYPE = "mock_strategy"
    STRATEGY_PREFIX = "MOCK"
    DEFAULT_TIMEFRAME = "1h"

    def _create_core(self):
        return MockCore(
            symbols=self.symbols,
            timeframes=self.timeframes,
            params=self.params,
        )

    def _get_indicator_timeframes(self) -> set:
        tf_set = set(self.timeframes)
        p = self.params or {}
        tf_set.add(p.get("indicator_timeframes", "1h"))
        return tf_set


@pytest.fixture
def mock_data_manager():
    """模拟 DataManager"""
    dm = MagicMock()
    dm.config = MagicMock()
    dm.config.backtest_mode = False

    # 模拟 get_dataframe_cached 返回数据
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
    dm.get_dataframe_cached.return_value = df
    dm._get_file_path.return_value = MagicMock(exists=MagicMock(return_value=True))

    return dm


class TestBaseStrategy:
    """BaseStrategy 基类测试"""

    @pytest.fixture
    def strategy(self, mock_data_manager):
        """创建测试策略"""
        config = {
            "version": "1",
            "symbols": ["BTCUSDT"],
            "timeframes": ["1h"],
            "params": {"test_param": 10},
            "signal": {"min_strength": 0.5},
        }
        return MockStrategy(data_manager=mock_data_manager, config=config)

    def test_strategy_name_single_symbol(self, strategy):
        """测试单标策略名称"""
        assert strategy.strategy_name == "MOCK_1H_1_BTCUSDT"

    def test_strategy_name_multi_symbols(self, mock_data_manager):
        """测试多标的策略名称"""
        config = {
            "version": "2",
            "symbols": ["BTCUSDT", "ETHUSDT"],
            "timeframes": ["1h"],
        }
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)
        assert strategy.strategy_name == "MOCK_1H_2"

    def test_strategy_name_for(self, strategy):
        """测试指定标的策略名称"""
        assert strategy.strategy_name_for("ETHUSDT") == "MOCK_1H_1_ETHUSDT"

    def test_subscribed_symbols(self, strategy):
        """测试订阅标的集合"""
        assert strategy.subscribed_symbols == {"BTCUSDT"}

    def test_poll_timeframes(self, strategy):
        """测试轮询周期"""
        assert strategy.poll_timeframes == ["1m"]

    def test_on_start_sets_running(self, strategy, mock_data_manager):
        """测试 on_start 设置运行状态"""
        strategy.on_start()
        assert strategy._running is True
        assert strategy._paused is False

    def test_on_stop_clears_running(self, strategy):
        """测试 on_stop 清除运行状态"""
        strategy._running = True
        strategy.on_stop()
        assert strategy._running is False

    def test_on_pause_sets_paused(self, strategy):
        """测试 on_pause 设置暂停状态"""
        strategy.on_pause()
        assert strategy._paused is True

    def test_on_resume_clears_paused(self, strategy):
        """测试 on_resume 清除暂停状态"""
        strategy._paused = True
        strategy.on_resume()
        assert strategy._paused is False

    def test_backtest_mode_from_attribute(self, mock_data_manager):
        """测试从属性设置回测模式"""
        config = {"version": "1", "symbols": ["BTCUSDT"]}
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)
        strategy._bt_backtest_mode = True  # 回测框架设置
        strategy.on_start()
        assert strategy._backtest_mode is True

    def test_backtest_mode_from_config(self, mock_data_manager):
        """测试从配置读取回测模式"""
        mock_data_manager.config.backtest_mode = True
        config = {"version": "1", "symbols": ["BTCUSDT"]}
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)
        strategy.on_start()
        assert strategy._backtest_mode is True

    def test_create_signal_buy(self, strategy):
        """测试创建买入信号"""
        strategy._current_kline_timestamp = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        signal = strategy._create_signal("BTCUSDT", "buy", 100.0, 0.7, {"reason": "test"})

        assert signal is not None
        assert signal.signal_type == SignalType.BUY
        assert signal.symbol == "BTCUSDT"
        assert signal.price == 100.0
        assert signal.strength == 0.7
        assert signal.direction == "long"

    def test_create_signal_sell_close(self, strategy):
        """测试创建平空信号"""
        strategy._current_kline_timestamp = datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc)
        signal = strategy._create_signal("BTCUSDT", "sell_close", 100.0, 0.8, {"reason": "test"})

        assert signal is not None
        assert signal.signal_type == SignalType.SELL_CLOSE
        assert signal.direction == "long"

    def test_on_kline_returns_none_when_not_running(self, strategy):
        """测试未运行时不处理 K 线"""
        strategy._running = False
        kline = MagicMock(symbol="BTCUSDT", close=100.0, timestamp=datetime.now(timezone.utc))
        result = strategy.on_kline(kline)
        assert result is None

    def test_on_kline_returns_none_when_paused(self, strategy):
        """测试暂停时不处理 K 线"""
        strategy._running = True
        strategy._paused = True
        kline = MagicMock(symbol="BTCUSDT", close=100.0, timestamp=datetime.now(timezone.utc))
        result = strategy.on_kline(kline)
        assert result is None

    def test_on_kline_filters_unsubscribed_symbol(self, strategy):
        """测试过滤未订阅标的"""
        strategy._running = True
        kline = MagicMock(symbol="ETHUSDT", close=100.0, timestamp=datetime.now(timezone.utc))
        result = strategy.on_kline(kline)
        assert result is None


class TestCalcRequiredHistoryDays:
    """测试策略数据需求声明"""

    def test_default_calculation_based_on_max_timeframe(self, mock_data_manager):
        """测试默认计算：基于最大周期"""
        config = {
            "version": "1",
            "symbols": ["BTCUSDT"],
            "timeframes": ["4h"],  # 4h 周期
        }
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)

        # 4h 周期 15 根 K 线 = 15 * 4h = 60h = 2.5 天
        # 加 5 天缓冲 = 7.5 天，取整 8 天，但最少 7 天
        days = strategy._calc_required_history_days()
        assert days >= 7

    def test_1d_timeframe_requires_more_days(self, mock_data_manager):
        """测试 1d 周期需要更多天数"""
        config = {
            "version": "1",
            "symbols": ["BTCUSDT"],
            "timeframes": ["1d"],
        }
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)

        # 1d 周期 15 根 K 线 = 15 天
        # 加 5 天缓冲 = 20 天
        days = strategy._calc_required_history_days()
        assert days >= 15

    def test_empty_timeframes_returns_minimum(self, mock_data_manager):
        """测试空时间框架返回最小值"""
        config = {
            "version": "1",
            "symbols": ["BTCUSDT"],
            "timeframes": [],
        }
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)

        days = strategy._calc_required_history_days()
        assert days == 7  # 最小默认值

    def test_15m_timeframe_returns_minimum(self, mock_data_manager):
        """测试 15m 周期返回最小值"""
        config = {
            "version": "1",
            "symbols": ["BTCUSDT"],
            "timeframes": ["15m"],
        }
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)

        # 15m 周期 15 根 K 线 = 15 * 15m = 225m = 3.75 小时 < 1 天
        # 最少 7 天
        days = strategy._calc_required_history_days()
        assert days == 7

    def test_strategy_can_override_calculation(self, mock_data_manager):
        """测试策略可重写计算方法"""

        class CustomStrategy(MockStrategy):
            """自定义数据需求的策略"""

            def _calc_required_history_days(self) -> int:
                """需要 30 天数据"""
                return 30

        config = {
            "version": "1",
            "symbols": ["BTCUSDT"],
            "timeframes": ["4h"],
        }
        strategy = CustomStrategy(data_manager=mock_data_manager, config=config)

        days = strategy._calc_required_history_days()
        assert days == 30

    def test_multi_timeframes_uses_max(self, mock_data_manager):
        """测试多时间框架使用最大周期"""
        config = {
            "version": "1",
            "symbols": ["BTCUSDT"],
            "timeframes": ["1d", "4h", "15m"],
        }
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)

        # 最大周期 1d，需要 15 根 = 15 天 + 5 缓冲 = 20 天
        days = strategy._calc_required_history_days()
        assert days >= 15


class TestAutoLoadDataUsesRequiredDays:
    """测试自动加载使用声明天数"""

    def test_auto_load_calls_with_calc_days(self, mock_data_manager):
        """测试自动加载调用使用计算天数"""
        config = {
            "version": "1",
            "symbols": ["BTCUSDT"],
            "timeframes": ["1d"],  # 1d 周期需要更多数据
        }
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)

        # 模拟文件不存在，触发加载
        mock_path = MagicMock()
        mock_path.exists.return_value = False
        mock_data_manager._get_file_path.return_value = mock_path

        # 设置 auto_load_missing_data 的返回值
        mock_data_manager.auto_load_missing_data.return_value = {"1d": True}

        # 调用自动加载
        strategy._auto_load_data_if_needed()

        # 检查调用参数：应该使用计算的天数而非固定 7 天
        call_args = mock_data_manager.auto_load_missing_data.call_args
        called_days = call_args.kwargs.get('days', call_args.args[2] if len(call_args.args) > 2 else 7)

        # 1d 周期应该需要 >= 15 天
        assert called_days >= 15

    def test_auto_load_when_data_insufficient(self, mock_data_manager):
        """测试数据量不足时自动补齐"""
        config = {
            "version": "1",
            "symbols": ["BTCUSDT"],
            "timeframes": ["1d"],
        }
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)

        # 模拟文件存在但数据量不足
        mock_path = MagicMock()
        mock_path.exists.return_value = True
        mock_data_manager._get_file_path.return_value = mock_path

        # 模拟只有 5 根 K 线（不足 11 根）
        short_df = pd.DataFrame({
            "timestamp": [
                datetime(2024, 1, 1, tzinfo=timezone.utc) + timedelta(days=i)
                for i in range(5)
            ],
            "open": [100.0] * 5,
            "high": [105.0] * 5,
            "low": [95.0] * 5,
            "close": [102.0] * 5,
            "volume": [1000] * 5,
        })
        mock_data_manager.get_dataframe_cached.return_value = short_df
        mock_data_manager.auto_load_missing_data.return_value = {"1d": True}

        # 调用自动加载
        strategy._auto_load_data_if_needed()

        # 应该触发补齐
        assert mock_data_manager.auto_load_missing_data.called
        call_args = mock_data_manager.auto_load_missing_data.call_args
        called_days = call_args.kwargs.get('days', call_args.args[2] if len(call_args.args) > 2 else 7)
        assert called_days >= 15