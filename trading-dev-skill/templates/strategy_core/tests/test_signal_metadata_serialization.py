#!/usr/bin/env python3
"""
测试信号元数据序列化（CtaSignalCSV.from_signal 的 metadata 清理）

覆盖场景:
- metadata 中包含 bytes 值 → from_signal 中解码为字符串
- metadata 中包含 datetime 对象 → from_signal 中转字符串
- metadata 中包含带 .to_dict() 的对象 → from_signal 中转字典
- 完整 pipeline: Signal → CtaSignalCSV.from_signal → to_json → json.dumps 不报错

原名 test_kafka_metadata_serialization.py：这些用例最初是为 Kafka 推送写的，但
清理逻辑在 CtaSignalCSV.from_signal 里，后续每个信号出口都依赖它 ——
下单 payload 直接 json.dumps(cta_signal.to_json())，metadata 没清理干净就会
抛 "Object of type bytes is not JSON serializable" 并丢掉信号。
（Kafka / signal_hub HTTP 通道均已随单体化移除，from_signal 的清理成为唯一
防线，故这些用例比以前更重要。）

随 Kafka 通道一并删除的两个类：
- TestKafkaProducerWithComplexMetadata（4 个用例）测 KafkaSignalProducer.send_signal
- TestSignalJSONEncoder（5 个用例）测 _SignalJSONEncoder
两者的被测对象都已不存在。它们断言的"复杂 metadata 不导致推送失败"，
根因覆盖仍在本文件 TestFullPipelineJSONSerialization：
不依赖任何自定义 encoder，裸 json.dumps 即可序列化。
"""

import json
from datetime import datetime, timezone
from dataclasses import dataclass

from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV


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
        json_str = json.dumps(message, ensure_ascii=False)
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
