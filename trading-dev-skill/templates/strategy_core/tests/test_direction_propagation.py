#!/usr/bin/env python3
"""
测试 direction 配置传递到 Core 层

问题：配置文件顶层的 direction 字段未传递到 Core，导致方向过滤失效
"""

import pytest
from strategies.cta_ict_v3.strategy import Strategy as ICTStrategy
from strategies.cta_rbreaker_v3.strategy import Strategy as RBreakerStrategy
from strategies.obs_divergence.strategy import Strategy as OBSStrategy


class TestDirectionPropagation:
    """测试 direction 配置传播"""

    def test_ict_strategy_direction_propagates_to_core(self):
        """
        GIVEN: 配置文件中 direction = "bullish"
        WHEN: 创建 ICT 策略实例
        THEN: Core.direction 应该是 "bullish"
        """
        config = {
            "enabled": True,
            "version": "3",
            "direction": "bullish",  # 顶层配置
            "symbols": ["BTCUSDT"],
            "timeframes": ["1d", "4h", "1h"],
            "params": {
                "fvg_timeframes": "1h",
            }
        }

        strategy = ICTStrategy(
            data_manager=None,
            config=config,
            trading_mode="backtest",
        )

        # Strategy 层应该正确读取
        assert strategy.direction == "bullish", \
            f"Strategy.direction 应该是 'bullish'，实际是 '{strategy.direction}'"

        # Core 层也应该正确读取
        assert strategy._core.direction == "bullish", \
            f"Core.direction 应该是 'bullish'，实际是 '{strategy._core.direction}'"

    def test_rbreaker_strategy_direction_propagates_to_core(self):
        """
        GIVEN: 配置文件中 direction = "bearish"
        WHEN: 创建 RBreaker 策略实例
        THEN: Core.direction 应该是 "bearish"
        """
        config = {
            "enabled": True,
            "version": "3",
            "direction": "bearish",
            "symbols": ["BTCUSDT"],
            "timeframes": ["15m"],
            "params": {}
        }

        strategy = RBreakerStrategy(
            data_manager=None,
            config=config,
            trading_mode="backtest",
        )

        assert strategy.direction == "bearish"
        assert strategy._core.direction == "bearish", \
            f"Core.direction 应该是 'bearish'，实际是 '{strategy._core.direction}'"

    def test_obs_strategy_direction_propagates_to_core(self):
        """
        GIVEN: 配置文件中 direction = "neutral"
        WHEN: 创建 OBS 策略实例
        THEN: Core.direction 应该是 "neutral"
        """
        config = {
            "enabled": True,
            "direction": "neutral",
            "symbols": ["BTCUSDT"],
            "timeframes": ["1h"],
            "params": {}
        }

        strategy = OBSStrategy(
            data_manager=None,
            config=config,
            trading_mode="backtest",
        )

        assert strategy.direction == "neutral"
        assert strategy._core.direction == "neutral"

    def test_direction_default_is_neutral(self):
        """
        GIVEN: 配置文件中没有 direction 字段
        WHEN: 创建策略实例
        THEN: direction 应该默认为 "neutral"
        """
        config = {
            "enabled": True,
            "symbols": ["BTCUSDT"],
            "timeframes": ["1d", "4h", "1h"],
            "params": {}
            # 没有 direction 字段
        }

        strategy = ICTStrategy(
            data_manager=None,
            config=config,
            trading_mode="backtest",
        )

        assert strategy.direction == "neutral"
        assert strategy._core.direction == "neutral"

    def test_direction_case_insensitive(self):
        """
        GIVEN: 配置文件中 direction = "BULLISH" (大写)
        WHEN: 创建策略实例
        THEN: direction 应该转换为小写 "bullish"
        """
        config = {
            "enabled": True,
            "direction": "BULLISH",
            "symbols": ["BTCUSDT"],
            "timeframes": ["1d"],
            "params": {}
        }

        strategy = ICTStrategy(
            data_manager=None,
            config=config,
            trading_mode="backtest",
        )

        assert strategy.direction == "bullish"
        assert strategy._core.direction == "bullish"

    def test_top_level_direction_overrides_params_direction(self):
        """
        GIVEN: params 中已有 direction = "bearish"，顶层 direction = "bullish"
        WHEN: 创建策略实例
        THEN: 顶层 direction 应覆盖 params 中的 direction
        """
        config = {
            "enabled": True,
            "direction": "bullish",  # 顶层
            "symbols": ["BTCUSDT"],
            "timeframes": ["1d"],
            "params": {
                "direction": "bearish",  # params 中也有
            }
        }

        strategy = ICTStrategy(
            data_manager=None,
            config=config,
            trading_mode="backtest",
        )

        # 顶层 direction 应生效
        assert strategy.direction == "bullish"
        assert strategy._core.direction == "bullish"
        # params 也被更新
        assert strategy.params["direction"] == "bullish"

    def test_invalid_direction_defaults_to_neutral(self):
        """
        GIVEN: direction 为无效值（非字符串）
        WHEN: 创建策略实例
        THEN: direction 应默认为 "neutral"
        """
        config = {
            "enabled": True,
            "direction": 123,  # 无效类型
            "symbols": ["BTCUSDT"],
            "timeframes": ["1d"],
            "params": {}
        }

        strategy = ICTStrategy(
            data_manager=None,
            config=config,
            trading_mode="backtest",
        )

        assert strategy.direction == "neutral"
        assert strategy._core.direction == "neutral"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])