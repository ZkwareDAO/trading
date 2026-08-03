#!/usr/bin/env python3
"""
测试 Kafka 消息中 strategy 字段的来源

验证:
- strategy.name 来自配置的 strategy_type_name，而不是从 strategy_name 硬解析
- strategy.internal 来自配置的 timeframe
- strategy_type 固定为 CTAFutureFactory
"""

import pytest
from datetime import datetime, timezone

from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV


class TestKafkaMessageStrategyFields:
    """测试 Kafka 消息中 strategy 相关字段"""

    def _make_signal(self) -> Signal:
        return Signal(
            signal_id="sig-test-kafka-fields",
            strategy_id="RBreakerv2_15m_BTCUSDT",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=74315.0,
            timestamp=datetime(2026, 4, 15, 12, 16, 0, tzinfo=timezone.utc),
            metadata={"reason": "breakout"},
        )

    def test_strategy_name_from_config_not_split(self):
        """strategy.name 应来自传入的 strategy_type_name，而不是从 strategy_name split 得到"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="RBreakerv2_15m_BTCUSDT",
            strategy_version="v2",
            interval="15m",
            strategy_params={"threshold": 0.005},
            strategy_type_name="cta_rbreaker",  # 新增参数
        )
        msg = cta.to_json()
        # 应该是配置传入的 cta_rbreaker，而不是 RBreakerv2
        assert msg["strategy"]["name"] == "cta_rbreaker"

    def test_strategy_internal_from_config(self):
        """strategy.internal 应来自传入的 timeframe 配置"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="RBreakerv2_15m_BTCUSDT",
            strategy_version="v2",
            interval="15m",
            strategy_params={},
            strategy_type_name="cta_rbreaker",
        )
        msg = cta.to_json()
        assert msg["strategy"]["internal"] == "15m"

    def test_strategy_type_fixed_to_ctafuturefactory(self):
        """strategy_type 应固定为 CTAFutureFactory"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="RBreakerv2_15m_BTCUSDT",
            strategy_version="v2",
            interval="15m",
            strategy_params={},
            strategy_type="CTAFutureFactory",
        )
        msg = cta.to_json()
        assert msg["strategy_type"] == "CTAFutureFactory"

    def test_backward_compat_strategy_name_defaults_to_split(self):
        """向后兼容：不传 strategy_type_name 时，保持旧的 split 行为"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="RBreakerv2_15m_BTCUSDT",
            strategy_version="v2",
            interval="15m",
            strategy_params={},
        )
        msg = cta.to_json()
        # 旧行为：split 得到 RBreakerv2
        assert msg["strategy"]["name"] == "RBreakerv2"

    def test_risk_fields_in_params(self):
        """Kafka 消息的 params 应包含风控字段（小数形式）"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="RBreakerv2_15m_BTCUSDT",
            strategy_version="v2",
            interval="15m",
            strategy_params={"threshold": 0.01},
            strategy_type_name="cta_rbreaker",
            risk_stop_loss_pct=2.0,  # 2% -> 小数 0.02
            risk_trailing_profit_activation=5.0,  # 5% -> 小数 0.05
            risk_trailing_profit_drawdown=5.0,  # 5% -> 小数 0.05
        )
        msg = cta.to_json()
        params = msg["strategy"]["params"]
        # StopLossThreshold 使用负值表示止损方向（小数形式）
        assert params["StopLossThreshold"] == -0.02
        assert params["TakeProfitBackThreshold"] == 0.05
        assert params["TakeProfitBackDynamicFallPercent"] == 0.05
        # 原有参数也应保留
        assert params["threshold"] == 0.01

    def test_risk_fields_default_values(self):
        """不传风控参数时，应使用默认值（小数形式）"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="RBreakerv2_15m_BTCUSDT",
            strategy_version="v2",
            interval="15m",
            strategy_params={},
        )
        msg = cta.to_json()
        params = msg["strategy"]["params"]
        # 默认值: 20% 止损 -> 0.2, 20% 激活阈值 -> 0.2, 5% 回落 -> 0.05
        assert params["StopLossThreshold"] == -0.2
        assert params["TakeProfitBackThreshold"] == 0.2
        assert params["TakeProfitBackDynamicFallPercent"] == 0.05
