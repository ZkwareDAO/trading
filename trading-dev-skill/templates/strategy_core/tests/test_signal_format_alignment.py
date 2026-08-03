#!/usr/bin/env python3
"""
测试信号格式对齐设计文档

根据项目设计文档（策略信号.md）

需要验证的格式差异:
1. 顶层 strategy_type 字段 (如 "CTAFuture")
2. 顶层 risk_strategy_type 字段 (如 "cta_intraday")
3. strategy.internal (非 interval)
4. signal.action 字段 (如 "buy", "sell_close" 等)
5. user_id 从配置传入 (非硬编码)
"""

import json
import os
import tempfile
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV


def _make_signal() -> Signal:
    return Signal(
        signal_id="sig-format-test",
        strategy_id="cta_rbreaker_v2_1m_btcusdt",
        signal_type=SignalType.BUY,
        symbol="BTCUSDT",
        price=75000.0,
        strength=0.8,
        direction="long",
        timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
        metadata={"reason": "breakout"},
    )


class TestDesignDocSignalFormat:
    """验证信号 JSON 格式与设计文档一致"""

    def test_top_level_strategy_type(self):
        """JSON 顶层应包含 strategy_type 字段"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.005},
            strategy_type="CTAFuture",
            risk_strategy_type="cta_intraday",
            user_id=1,
        )
        msg = cta.to_json(user_id=1)
        assert "strategy_type" in msg, "顶层应包含 strategy_type 字段"
        assert msg["strategy_type"] == "CTAFuture"

    def test_top_level_risk_strategy_type(self):
        """JSON 顶层应包含 risk_strategy_type 字段"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.005},
            strategy_type="CTAFuture",
            risk_strategy_type="cta_intraday",
            user_id=1,
        )
        msg = cta.to_json(user_id=1)
        assert "risk_strategy_type" in msg, "顶层应包含 risk_strategy_type 字段"
        assert msg["risk_strategy_type"] == "cta_intraday"

    def test_strategy_internal_not_interval(self):
        """strategy 对象应使用 internal 而非 interval"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="15m",
            strategy_params={"threshold": 0.005},
        )
        msg = cta.to_json()
        assert "internal" in msg["strategy"], "strategy 应包含 internal 字段"
        assert msg["strategy"]["internal"] == "15m"
        assert "interval" not in msg["strategy"], "strategy 不应包含 interval 字段"

    def test_signal_action_field(self):
        """signal 对象应包含 action 字段"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.005},
        )
        msg = cta.to_json()
        assert "action" in msg["signal"], "signal 应包含 action 字段"
        assert msg["signal"]["action"] == "buy"

    def test_signal_action_sell_close(self):
        """SELL_CLOSE 信号 action 应为 sell_close"""
        signal = Signal(
            signal_id="sig-sell-close",
            strategy_id="test_strategy",
            signal_type=SignalType.SELL_CLOSE,
            symbol="BTCUSDT",
            price=74000.0,
            direction="long",
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
        )
        cta = CtaSignalCSV.from_signal(signal, strategy_name="test_v1")
        msg = cta.to_json()
        assert msg["signal"]["action"] == "sell_close"

    def test_signal_action_reverse_long(self):
        """REVERSE_LONG 信号 action 应为 reverse_long"""
        signal = Signal(
            signal_id="sig-reverse-long",
            strategy_id="test_strategy",
            signal_type=SignalType.REVERSE_LONG,
            symbol="BTCUSDT",
            price=73000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
        )
        cta = CtaSignalCSV.from_signal(signal, strategy_name="test_v1")
        msg = cta.to_json()
        assert msg["signal"]["action"] == "reverse_long"

    def test_signal_action_reverse_short(self):
        """REVERSE_SHORT 信号 action 应为 reverse_short"""
        signal = Signal(
            signal_id="sig-reverse-short",
            strategy_id="test_strategy",
            signal_type=SignalType.REVERSE_SHORT,
            symbol="BTCUSDT",
            price=73000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
        )
        cta = CtaSignalCSV.from_signal(signal, strategy_name="test_v1")
        msg = cta.to_json()
        assert msg["signal"]["action"] == "reverse_short"

    def test_user_id_from_config(self):
        """user_id 应从配置传入，默认值为 1"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            user_id=42,
        )
        msg = cta.to_json(user_id=42)
        assert msg["user_id"] == 42

    def test_full_json_structure_matches_design_doc(self):
        """完整 JSON 结构应匹配设计文档"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.005},
            strategy_valid_before="2030-12-31 08:00:00",
            strategy_cash=100,
            strategy_parts=1,
            strategy_type="CTAFuture",
            risk_strategy_type="cta_intraday",
            user_id=1,
        )
        msg = cta.to_json(user_id=1)

        # 顶层字段
        assert "SignalID" in msg
        assert "SignalTimestamp" in msg
        assert "symbol" in msg
        assert "user_id" in msg
        assert "pos_type" in msg
        assert "strategy_type" in msg
        assert "risk_strategy_type" in msg

        # strategy 子字段
        s = msg["strategy"]
        assert "name" in s
        assert "version" in s
        assert "internal" in s
        assert "description" in s
        assert "params" in s
        assert "valid_before" in s
        assert "cash" in s
        assert "parts" in s
        assert "interval" not in s  # 确保旧的字段名不存在

        # signal 子字段
        sig = msg["signal"]
        assert "side" in sig
        assert "action" in sig
        assert "exchange" in sig
        assert "valid_before" in sig
        assert "trigger_price" in sig
        assert "slippage" in sig
        assert "order_type" in sig


class TestKafkaFormatAlignment:
    """Kafka 推送应发送与设计文档一致的格式"""

    @pytest.fixture
    def mock_producer(self):
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        dedup_file = os.path.join(tempfile.gettempdir(), f"test_kafka_fmt_dedup_{os.getpid()}.txt")
        config = {
            "enabled": True,
            "bootstrap_servers": "127.0.0.1:9092",
            "topic": "strategy_signals",
            "dedup_file": dedup_file,
        }
        with patch("strategy_core.signal_logging.kafka_producer.KafkaProducer") as MockKafka:
            mock_kafka = MagicMock()
            MockKafka.return_value = mock_kafka
            producer = KafkaSignalProducer(config)
            producer._kafka_producer = mock_kafka
            yield producer
        if os.path.exists(dedup_file):
            os.unlink(dedup_file)

    def test_kafka_message_has_strategy_type(self, mock_producer):
        """Kafka 消息应包含 strategy_type"""
        captured = {}

        def capture_send(topic, **kwargs):
            captured["value"] = kwargs.get("value")
            return MagicMock()

        mock_producer._kafka_producer.send.side_effect = capture_send

        signal = _make_signal()
        mock_producer.send_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.005},
            strategy_type="CTAFuture",
            risk_strategy_type="cta_intraday",
            user_id=1,
        )

        value = captured["value"]
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        parsed = json.loads(value)
        assert parsed["strategy_type"] == "CTAFuture"
        assert parsed["risk_strategy_type"] == "cta_intraday"

    def test_kafka_message_has_signal_action(self, mock_producer):
        """Kafka 消息的 signal 对象应包含 action"""
        captured = {}

        def capture_send(topic, **kwargs):
            captured["value"] = kwargs.get("value")
            return MagicMock()

        mock_producer._kafka_producer.send.side_effect = capture_send

        signal = Signal(
            signal_id="sig-action-test",
            strategy_id="test",
            signal_type=SignalType.REVERSE_SHORT,
            symbol="BTCUSDT",
            price=72000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
        )
        mock_producer.send_signal(signal)

        value = captured["value"]
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        parsed = json.loads(value)
        assert parsed["signal"]["action"] == "reverse_short"

    def test_kafka_message_uses_internal_not_interval(self, mock_producer):
        """Kafka 消息应使用 strategy.internal 而非 strategy.interval"""
        captured = {}

        def capture_send(topic, **kwargs):
            captured["value"] = kwargs.get("value")
            return MagicMock()

        mock_producer._kafka_producer.send.side_effect = capture_send

        signal = _make_signal()
        mock_producer.send_signal(signal, interval="15m")

        value = captured["value"]
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        parsed = json.loads(value)
        assert "internal" in parsed["strategy"]
        assert "interval" not in parsed["strategy"]
        assert parsed["strategy"]["internal"] == "15m"

    def test_kafka_message_user_id(self, mock_producer):
        """Kafka 消息 user_id 应来自配置"""
        captured = {}

        def capture_send(topic, **kwargs):
            captured["value"] = kwargs.get("value")
            return MagicMock()

        mock_producer._kafka_producer.send.side_effect = capture_send

        signal = _make_signal()
        mock_producer.send_signal(signal, user_id=99)

        value = captured["value"]
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        parsed = json.loads(value)
        assert parsed["user_id"] == 99
