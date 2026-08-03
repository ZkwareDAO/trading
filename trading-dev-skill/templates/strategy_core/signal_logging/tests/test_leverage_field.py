#!/usr/bin/env python3
"""
测试 Leverage 字段功能

TDD 流程:
1. RED - 写失败测试
2. GREEN - 实现代码
3. REFACTOR - 优化代码
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV, SignalCsvWriter
from strategy_core.base.strategy import BaseStrategy


def _make_signal() -> Signal:
    """创建测试信号"""
    return Signal(
        signal_id="test-signal-001",
        strategy_id="TestStrategy_15m_BTCUSDT",
        strategy_type="test_strategy",
        signal_type=SignalType.BUY,
        symbol="BTCUSDT",
        price=50000.0,
        strength=0.8,
        direction="long",
        timestamp=datetime(2026, 5, 29, 12, 0, 0, tzinfo=timezone.utc),
        metadata={"reason": "breakout"},
    )


@pytest.fixture
def mock_data_manager():
    """Mock DataManager"""
    dm = MagicMock()
    dm.config = MagicMock()
    dm.config.backtest_mode = False
    return dm


@pytest.fixture
def concrete_strategy_class():
    """返回可用于测试的具体策略类"""
    class _ConcreteStrategy(BaseStrategy):
        STRATEGY_TYPE = "test"
        STRATEGY_PREFIX = "TEST"
        DEFAULT_TIMEFRAME = "15m"

        def _create_core(self):
            return MagicMock()

        def _get_indicator_timeframes(self):
            return {"15m"}
    return _ConcreteStrategy


class TestCtaSignalCSVLeverage:
    """测试 CtaSignalCSV 的 leverage 字段"""

    def test_leverage_field_exists_in_dataclass(self):
        """CtaSignalCSV 应包含 leverage 字段，默认值为 5"""
        cta = CtaSignalCSV()
        assert hasattr(cta, "leverage")
        assert cta.leverage == 5

    def test_leverage_in_to_csv_row(self):
        """to_csv_row() 应包含 leverage 列"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(signal, leverage=3)
        row = cta.to_csv_row()
        assert "leverage" in row
        assert row["leverage"] == 3

    def test_leverage_in_to_json(self):
        """to_json() 应在 strategy 部分包含 leverage"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(signal, leverage=5)
        json_data = cta.to_json()
        assert "leverage" in json_data["strategy"]
        assert json_data["strategy"]["leverage"] == 5

    def test_leverage_default_value(self):
        """未指定 leverage 时，应使用默认值 5"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(signal)
        assert cta.leverage == 5
        json_data = cta.to_json()
        assert json_data["strategy"]["leverage"] == 5

    def test_csv_json_http_kafka_consistency(self):
        """CSV、JSON(HTTP/Kafka) 输出的 leverage 应一致"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(signal, leverage=10)

        csv_row = cta.to_csv_row()
        json_data = cta.to_json()

        assert csv_row["leverage"] == 10
        assert json_data["strategy"]["leverage"] == 10


class TestLeverageDefaultValues:
    """测试 leverage 默认值逻辑"""

    def test_default_leverage_live_mode(self, mock_data_manager, concrete_strategy_class):
        """实盘模式默认 leverage 应为 5"""
        strategy = concrete_strategy_class(
            data_manager=mock_data_manager,
            config={"capital": {}},
            trading_mode="live"
        )
        assert strategy.leverage == 5

    def test_default_leverage_paper_trading_mode(self, mock_data_manager, concrete_strategy_class):
        """冒烟模式默认 leverage 应为 1"""
        strategy = concrete_strategy_class(
            data_manager=mock_data_manager,
            config={"capital": {}},
            trading_mode="paper_trading"
        )
        assert strategy.leverage == 1

    def test_leverage_from_config_overrides_default(self, mock_data_manager, concrete_strategy_class):
        """配置文件中的 leverage 应覆盖默认值"""
        strategy = concrete_strategy_class(
            data_manager=mock_data_manager,
            config={"capital": {"leverage": 10}},
            trading_mode="live"
        )
        assert strategy.leverage == 10

    def test_leverage_in_signal_fields(self, mock_data_manager, concrete_strategy_class):
        """leverage 应出现在 signal_fields 中"""
        strategy = concrete_strategy_class(
            data_manager=mock_data_manager,
            config={"capital": {"leverage": 8}},
            trading_mode="live"
        )
        fields = strategy.signal_fields
        assert "leverage" in fields
        assert fields["leverage"] == 8


class TestLeverageFieldInFieldnames:
    """测试 FIELDNAMES 包含 leverage"""

    def test_leverage_in_fieldnames(self):
        """SignalCsvWriter.FIELDNAMES 应包含 leverage"""
        assert "leverage" in SignalCsvWriter.FIELDNAMES
