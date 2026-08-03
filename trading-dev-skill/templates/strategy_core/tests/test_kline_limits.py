#!/usr/bin/env python3
"""
测试 kline_limits 配置功能

测试策略可以通过配置指定每个周期需要的 K 线根数
"""

import pytest
from unittest.mock import MagicMock
import pandas as pd

from strategy_core.base.strategy import BaseStrategy


class MockStrategy(BaseStrategy):
    """测试用策略类"""

    STRATEGY_TYPE = "test_strategy"
    STRATEGY_PREFIX = "TEST"
    DEFAULT_TIMEFRAME = "1h"

    def _create_core(self):
        """创建核心逻辑实例"""
        mock_core = MagicMock()
        mock_core.analyze.return_value = {"action": "hold", "price": 0, "strength": 0}
        return mock_core

    def _get_indicator_timeframes(self) -> set:
        """返回策略使用的周期"""
        return set(self.timeframes)


def _extract_called_limits(call_args_list):
    """提取调用参数中的 interval 和 limit"""
    return {
        call.kwargs["interval"]: call.kwargs["limit"]
        for call in call_args_list
    }


def _create_mock_df(rows: int):
    """创建模拟 K 线数据"""
    timestamps = pd.date_range(start="2024-01-01", periods=rows, freq="1h", tz="UTC")
    return pd.DataFrame({
        "timestamp": timestamps,
        "open": [100.0] * rows,
        "high": [105.0] * rows,
        "low": [95.0] * rows,
        "close": [102.0] * rows,
        "volume": [1000] * rows,
    })


class TestKlineLimitsConfig:
    """测试 kline_limits 配置功能"""

    @pytest.fixture
    def mock_data_manager(self):
        """创建模拟 DataManager"""
        dm = MagicMock()
        dm.get_dataframe_cached.return_value = _create_mock_df(200)
        return dm

    def test_no_kline_limits_uses_default_200(self, mock_data_manager):
        """无 kline_limits 配置时，使用默认 200 根"""
        config = {"symbols": ["BTCUSDT"], "timeframes": ["1h"], "params": {}}
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)

        strategy._fetch_multi_timeframe_data("BTCUSDT")

        assert mock_data_manager.get_dataframe_cached.call_args.kwargs["limit"] == 200

    def test_kline_limits_uses_configured_value(self, mock_data_manager):
        """有 kline_limits 配置时，使用配置的值"""
        config = {
            "symbols": ["BTCUSDT"],
            "timeframes": ["1d", "4h", "15m"],
            "params": {"kline_limits": {"1d": 30, "4h": 50, "15m": 100}},
        }
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)

        strategy._fetch_multi_timeframe_data("BTCUSDT")

        called_limits = _extract_called_limits(
            mock_data_manager.get_dataframe_cached.call_args_list
        )
        assert called_limits == {"1d": 30, "4h": 50, "15m": 100}

    def test_partial_kline_limits_uses_default_for_missing(self, mock_data_manager):
        """部分周期有配置，缺失的使用默认值 200"""
        config = {
            "symbols": ["BTCUSDT"],
            "timeframes": ["1d", "4h", "15m"],
            "params": {"kline_limits": {"1d": 30}},
        }
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)

        strategy._fetch_multi_timeframe_data("BTCUSDT")

        called_limits = _extract_called_limits(
            mock_data_manager.get_dataframe_cached.call_args_list
        )
        assert called_limits == {"1d": 30, "4h": 200, "15m": 200}

    def test_empty_kline_limits_uses_default(self, mock_data_manager):
        """kline_limits 为空字典时，使用默认值"""
        config = {
            "symbols": ["BTCUSDT"],
            "timeframes": ["1h"],
            "params": {"kline_limits": {}},
        }
        strategy = MockStrategy(data_manager=mock_data_manager, config=config)

        strategy._fetch_multi_timeframe_data("BTCUSDT")

        assert mock_data_manager.get_dataframe_cached.call_args.kwargs["limit"] == 200
