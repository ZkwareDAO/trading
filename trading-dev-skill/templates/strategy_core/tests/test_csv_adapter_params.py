#!/usr/bin/env python3
"""
测试 CtaSignalCSV 中的异常处理

覆盖:
- strategy_params 包含有效 JSON 字符串时正常解析
- strategy_params 包含无效 JSON 时不抛异常（优雅降级）
- strategy_params 为 None 时正常处理
"""

import pytest
from datetime import datetime, timezone

from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV
from strategy_core.signal_logging.storage import Signal, SignalType


class TestStrategyParamsParsing:
    """测试策略参数解析的异常处理"""

    def _make_signal(self) -> Signal:
        return Signal(
            signal_id="sig-test-params",
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=75000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
            metadata={"reason": "breakout"},
        )

    def test_valid_strategy_params_json(self):
        """有效 JSON 策略参数应正确解析"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="test_v1",
            strategy_params={"threshold": 0.005, "direction": "neutral"},
        )
        msg = cta.to_json()
        assert msg["strategy"]["params"]["threshold"] == 0.005
        assert msg["strategy"]["params"]["direction"] == "neutral"

    def test_empty_strategy_params(self):
        """空策略参数应返回仅含风控字段的字典"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(signal, strategy_name="test_v1")
        msg = cta.to_json()
        params = msg["strategy"]["params"]
        # Kafka 使用小数形式（0.2 表示 20%）
        assert params["StopLossThreshold"] == -0.2
        assert params["TakeProfitBackThreshold"] == 0.2
        assert params["TakeProfitBackDynamicFallPercent"] == 0.05

    def test_none_strategy_params(self):
        """None 策略参数应返回仅含风控字段的字典"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(signal, strategy_name="test_v1", strategy_params=None)
        msg = cta.to_json()
        params = msg["strategy"]["params"]
        assert params["StopLossThreshold"] == -0.2
        assert params["TakeProfitBackThreshold"] == 0.2
        assert params["TakeProfitBackDynamicFallPercent"] == 0.05

    def test_invalid_strategy_params_does_not_crash(self):
        """无效策略参数不应崩溃（优雅降级为空字典）"""
        signal = self._make_signal()
        # 传一个包含不可序列化对象的情况 — from_signal 内部会 json.dumps
        # 如果 to_json 内部 json.loads 失败，不应崩溃
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="test_v1",
            strategy_params={"ok": "value"},  # 正常值，确保路径被覆盖
        )
        msg = cta.to_json()
        params = msg["strategy"]["params"]
        assert params["ok"] == "value"
        assert params["StopLossThreshold"] == -0.2

    def test_strategy_params_with_complex_values(self):
        """包含嵌套 dict/list 的复杂策略参数应正确序列化"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="test_v1",
            strategy_params={
                "threshold": 0.005,
                "levels": [100, 200, 300],
                "nested": {"key": "value"},
            },
        )
        msg = cta.to_json()
        assert msg["strategy"]["params"]["levels"] == [100, 200, 300]
        assert msg["strategy"]["params"]["nested"]["key"] == "value"

    def test_to_json_with_malformed_strategy_params_json(self):
        """如果 strategy_params 字符串格式损坏，to_json 不应崩溃"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="test_v1",
            strategy_params={"valid": True},
        )
        # 手动损坏 strategy_params 字符串
        cta.strategy_params = "{invalid json!!!"
        # 不应抛异常
        msg = cta.to_json()
        params = msg["strategy"]["params"]
        # 风控字段始终注入（小数形式，0.2 表示 20%）
        assert params["StopLossThreshold"] == -0.2
        assert params["TakeProfitBackThreshold"] == 0.2
        assert params["TakeProfitBackDynamicFallPercent"] == 0.05


class TestSignalCashCalculation:
    """测试 signal.cash 自动计算为 strategy.cash / strategy.parts"""

    def _make_signal(self):
        from strategy_core.signal_logging.storage import Signal, SignalType
        from datetime import datetime, timezone
        return Signal(
            signal_id="test-sig",
            strategy_id="test_v1",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=74315.0,
            timestamp=datetime(2026, 4, 15, 12, 16, tzinfo=timezone.utc),
        )

    def test_signal_cash_defaults_to_strategy_cash_divided_by_parts(self):
        """未指定 signal_cash 时，应自动计算为 strategy_cash / strategy_parts"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="test_v1",
            strategy_cash=100,
            strategy_parts=2,
        )
        msg = cta.to_json()
        assert msg["signal"]["cash"] == 50.0  # 100 / 2

    def test_signal_cash_with_parts_one(self):
        """strategy_parts=1 时，signal_cash = strategy_cash"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="test_v1",
            strategy_cash=100,
            strategy_parts=1,
        )
        msg = cta.to_json()
        assert msg["signal"]["cash"] == 100.0

    def test_explicit_signal_cash_overrides_calculated(self):
        """显式指定 signal_cash 时应覆盖自动计算值"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="test_v1",
            strategy_cash=100,
            strategy_parts=2,
            signal_cash=30.0,  # 显式指定
        )
        msg = cta.to_json()
        assert msg["signal"]["cash"] == 30.0

    def test_zero_strategy_cash_results_in_none_cash(self):
        """strategy_cash=0 时，signal.cash 应为 None"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="test_v1",
            strategy_cash=0,
            strategy_parts=1,
        )
        msg = cta.to_json()
        assert msg["signal"]["cash"] is None


class TestSignalValidBeforeHours:
    """测试 signal_valid_before_hours 参数控制订单有效时间"""

    def _make_signal(self) -> Signal:
        return Signal(
            signal_id="sig-test-vbh",
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=75000.0,
            timestamp=datetime.now(),
        )

    def test_default_valid_before_is_24_hours(self):
        """默认有效时间应为 24 小时"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="test_v1",
        )
        msg = cta.to_json()
        valid_before = datetime.strptime(msg["signal"]["valid_before"], "%Y-%m-%d %H:%M:%S")
        diff = valid_before - signal.timestamp
        assert 23 <= diff.total_seconds() / 3600 <= 25

    def test_custom_valid_before_hours(self):
        """自定义有效时间应生效"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="test_v1",
            signal_valid_before_hours=48,
        )
        msg = cta.to_json()
        valid_before = datetime.strptime(msg["signal"]["valid_before"], "%Y-%m-%d %H:%M:%S")
        diff = valid_before - signal.timestamp
        assert 47 <= diff.total_seconds() / 3600 <= 49

    def test_explicit_valid_before_overrides_hours(self):
        """显式指定 signal_valid_before 时应覆盖小时计算"""
        signal = self._make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="test_v1",
            signal_valid_before_hours=48,
            signal_valid_before="2026-12-31 08:00:00",
        )
        msg = cta.to_json()
        assert msg["signal"]["valid_before"] == "2026-12-31 08:00:00"
