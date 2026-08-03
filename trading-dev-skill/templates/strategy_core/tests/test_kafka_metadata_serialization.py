#!/usr/bin/env python3
"""
测试 Kafka 信号元数据序列化修复

覆盖场景:
- metadata 中包含 bytes 值 → from_signal 中解码为字符串
- metadata 中包含 datetime 对象 → from_signal 中转字符串
- metadata 中包含带 .to_dict() 的对象 → from_signal 中转字典
- 完整 pipeline: Signal → CtaSignalCSV.from_signal → to_json → json.dumps 不报错
- _SignalJSONEncoder 作为第二层保险处理意外类型
"""

import json
import os
import tempfile
import pytest
from datetime import datetime, timezone
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV
from strategy_core.signal_logging.kafka_producer import _SignalJSONEncoder


# ---- 辅助：模拟带 .to_dict() 的对象 ----
@dataclass
class FakePriceLines:
    upper_rail: float = 75000.0
    pivot: float = 73000.0
    lower_rail: float = 71000.0

    def to_dict(self):
        return {
            "upper_rail": self.upper_rail,
            "pivot": self.pivot,
            "lower_rail": self.lower_rail,
        }


# ========================================================================
# _SignalJSONEncoder 测试
# ========================================================================

class TestSignalJSONEncoder:
    """测试自定义 JSON 编码器（第二层保险）"""

    def test_encodes_bytes(self):
        """bytes 应被解码为字符串"""
        data = {"raw": b"hello", "ok": True}
        result = json.dumps(data, cls=_SignalJSONEncoder)
        parsed = json.loads(result)
        assert parsed["raw"] == "hello"

    def test_encodes_bytes_with_non_utf8(self):
        """非 UTF-8 bytes 应使用 replace 模式"""
        data = {"raw": b"\xff\xfe"}
        result = json.dumps(data, cls=_SignalJSONEncoder)
        parsed = json.loads(result)
        assert "\ufffd" in parsed["raw"]  # replacement character

    def test_encodes_datetime(self):
        """datetime 应转为字符串"""
        dt = datetime(2026, 4, 14, 23, 0, 0, tzinfo=timezone.utc)
        data = {"ts": dt}
        result = json.dumps(data, cls=_SignalJSONEncoder)
        parsed = json.loads(result)
        assert "2026-04-14" in parsed["ts"]

    def test_encodes_to_dict_object(self):
        """带 .to_dict() 的对象应被转换"""
        pl = FakePriceLines()
        data = {"prices": pl}
        result = json.dumps(data, cls=_SignalJSONEncoder)
        parsed = json.loads(result)
        assert parsed["prices"]["upper_rail"] == 75000.0
        assert parsed["prices"]["pivot"] == 73000.0
        assert parsed["prices"]["lower_rail"] == 71000.0

    def test_fallback_to_parent_for_unknown_types(self):
        """未知类型应回退到父类（抛 TypeError）"""
        class Unserializable:
            pass
        data = {"x": Unserializable()}
        with pytest.raises(TypeError):
            json.dumps(data, cls=_SignalJSONEncoder)


# ========================================================================
# CtaSignalCSV.from_signal 中 metadata 清理测试
# 修复点：csv_adapter.py 中 metadata_dict 的构建逻辑
# ========================================================================

class TestCtaSignalCSVMetadataSerialization:
    """测试 metadata 中非 JSON 类型被清理"""

    def test_metadata_with_bytes_value(self):
        """metadata 中包含 bytes 时，from_signal 应将其解码为字符串"""
        signal = Signal(
            signal_id="sig-bytes-001",
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=75000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
            metadata={"raw_data": b"binary_payload", "reason": "breakout"},
        )
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="test_v1",
            strategy_version="v1",
            interval="1m",
        )
        # metadata 字段应包含解码后的字符串
        assert '"raw_data": "binary_payload"' in cta.metadata
        assert '"reason": "breakout"' in cta.metadata

    def test_metadata_with_datetime_value(self):
        """metadata 中包含 datetime 时，from_signal 应转为字符串"""
        ts = datetime(2026, 4, 14, 10, 30, 0, tzinfo=timezone.utc)
        signal = Signal(
            signal_id="sig-dt-001",
            strategy_id="test_strategy",
            signal_type=SignalType.SELL_CLOSE,
            symbol="BTCUSDT",
            price=74000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
            metadata={"trigger_time": ts},
        )
        cta = CtaSignalCSV.from_signal(signal, strategy_name="test_v1")
        assert "2026-04-14" in cta.metadata

    def test_metadata_with_to_dict_object(self):
        """metadata 中包含 .to_dict() 对象时，from_signal 应转为 dict"""
        prices = FakePriceLines()
        signal = Signal(
            signal_id="sig-obj-001",
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=75000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
            metadata={"price_lines": prices},
        )
        cta = CtaSignalCSV.from_signal(signal, strategy_name="test_v1")
        # 应包含序列化后的 price_lines 数据
        assert "upper_rail" in cta.metadata
        assert "75000" in cta.metadata

    def test_metadata_with_plain_values(self):
        """纯字符串/数字 metadata 应正常保留"""
        signal = Signal(
            signal_id="sig-plain-001",
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=75000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
            metadata={"action": "buy", "adx": 40.6, "reason": "breakout"},
        )
        cta = CtaSignalCSV.from_signal(signal, strategy_name="test_v1")
        assert '"action": "buy"' in cta.metadata
        assert "40.6" in cta.metadata


# ========================================================================
# 完整 pipeline 测试：之前会报 "Object of type bytes is not JSON serializable"
# ========================================================================

class TestFullPipelineJSONSerialization:
    """端到端: Signal → CtaSignalCSV → to_json → json.dumps 不报错"""

    def _make_signal_with_complex_metadata(self) -> Signal:
        return Signal(
            signal_id="sig-pipeline-001",
            strategy_id="cta_rbreaker_v2_1m_btcusdt",
            signal_type=SignalType.REVERSE_SHORT,
            symbol="BTCUSDT",
            price=72000.0,
            strength=0.9,
            direction="short",
            timestamp=datetime(2026, 4, 14, 14, 0, 0, tzinfo=timezone.utc),
            metadata={
                "action": "reverse_short",
                "reason": "价格跌破下轨",
                "price_lines": FakePriceLines(),
                "raw_bytes": b"\x01\x02\x03",
                "event_time": datetime(2026, 4, 14, 14, 0, 0, tzinfo=timezone.utc),
            },
        )

    def test_from_signal_does_not_raise(self):
        """from_signal 不应因 metadata 中的非 JSON 类型报错"""
        signal = self._make_signal_with_complex_metadata()
        # 不应抛异常
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.005},
        )
        assert cta.signal_id == "sig-pipeline-001"

    def test_to_json_does_not_raise(self):
        """to_json 应返回纯 Python dict"""
        signal = self._make_signal_with_complex_metadata()
        cta = CtaSignalCSV.from_signal(signal, strategy_name="cta_rbreaker")
        message = cta.to_json()
        assert isinstance(message, dict)
        assert "SignalID" in message

    def test_json_dumps_does_not_raise(self):
        """json.dumps 不应报 'Object of type bytes is not JSON serializable'"""
        signal = self._make_signal_with_complex_metadata()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.005},
        )
        message = cta.to_json()
        # 这行就是之前报错的地方
        json_str = json.dumps(message, ensure_ascii=False, cls=_SignalJSONEncoder)
        parsed = json.loads(json_str)
        assert parsed["SignalID"] == "sig-pipeline-001"
        assert parsed["symbol"] == "BTCUSDT"

    def test_json_dumps_without_encoder_also_works(self):
        """from_signal 修复后，即使不用自定义 encoder 也应可序列化"""
        signal = self._make_signal_with_complex_metadata()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.005},
        )
        message = cta.to_json()
        # 不使用自定义 encoder 也应成功（因为 from_signal 已经清理了 metadata）
        json_str = json.dumps(message, ensure_ascii=False)
        parsed = json.loads(json_str)
        assert parsed["SignalID"] == "sig-pipeline-001"


# ========================================================================
# Mock Kafka 集成测试
# ========================================================================

class TestKafkaProducerWithComplexMetadata:
    """测试 Kafka Producer 能处理复杂 metadata"""

    @pytest.fixture
    def mock_producer(self):
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        dedup_file = os.path.join(tempfile.gettempdir(), f"test_kafka_meta_dedup_{os.getpid()}.txt")
        config = {
            "enabled": True,
            "bootstrap_servers": "127.0.0.1:9092",
            "topic": "cta_signals",
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

    def test_send_signal_with_bytes_metadata(self, mock_producer):
        """含 bytes 的 metadata 不应导致 Kafka 推送失败"""
        signal = Signal(
            signal_id="sig-kafka-bytes",
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=75000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
            metadata={"raw": b"\x00\x01\x02"},
        )
        result = mock_producer.send_signal(signal)
        assert result is True

    def test_send_signal_with_datetime_metadata(self, mock_producer):
        """含 datetime 的 metadata 不应导致 Kafka 推送失败"""
        signal = Signal(
            signal_id="sig-kafka-dt",
            strategy_id="test_strategy",
            signal_type=SignalType.SELL_CLOSE,
            symbol="BTCUSDT",
            price=74000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
            metadata={"triggered_at": datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc)},
        )
        result = mock_producer.send_signal(signal)
        assert result is True

    def test_send_signal_with_dataclass_metadata(self, mock_producer):
        """含 dataclass 的 metadata 不应导致 Kafka 推送失败"""
        signal = Signal(
            signal_id="sig-kafka-dc",
            strategy_id="test_strategy",
            signal_type=SignalType.REVERSE_LONG,
            symbol="BTCUSDT",
            price=73000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
            metadata={"price_lines": FakePriceLines()},
        )
        result = mock_producer.send_signal(signal)
        assert result is True

    def test_send_signal_value_is_valid_json(self, mock_producer):
        """验证发送的 value 是合法 JSON"""
        captured = {}

        def capture_send(topic, **kwargs):
            captured["topic"] = topic
            captured["value"] = kwargs.get("value")
            return MagicMock()

        mock_producer._kafka_producer.send.side_effect = capture_send

        signal = Signal(
            signal_id="sig-validate",
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=75000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
            metadata={"action": "buy", "raw": b"\x01", "ts": datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc)},
        )
        mock_producer.send_signal(signal)

        value = captured["value"]
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        parsed = json.loads(value)
        assert "SignalID" in parsed
        assert "strategy" in parsed
        assert "signal" in parsed
