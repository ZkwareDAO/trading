# NOTE: IP addresses in this test are mock values, not real endpoints
#!/usr/bin/env python3
"""
测试 HTTP 信号发送器支持 V1/V2 不同 payload 格式

验证：
1. V1 API 使用包装格式 {"topic": ..., "message": ...}
2. V2+ API 直接使用 cta_signal.to_json() 作为 payload
3. 版本自动从 api_path 提取
4. 向后兼容：无版本号时默认 V1
"""

import json
import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from strategy_core.signal_logging.http_sender import HttpSignalSender, RetryConfig
from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV


class TestApiVersionExtraction:
    """测试 API 版本提取"""

    def test_extract_v1_from_path(self):
        """从 /api/v1/kafka/message 提取版本 1"""
        sender = HttpSignalSender(
            base_url="http://127.0.0.1:18888",
            api_path="/api/v1/kafka/message",
        )
        assert sender._extract_api_version() == 1

    def test_extract_v2_from_path(self):
        """从 /api/v2/signals 提取版本 2"""
        sender = HttpSignalSender(
            base_url="http://127.0.0.1:18888",
            api_path="/api/v2/signals",
        )
        assert sender._extract_api_version() == 2

    def test_extract_v3_from_path(self):
        """从 /api/v3/signals 提取版本 3"""
        sender = HttpSignalSender(
            base_url="http://127.0.0.1:18888",
            api_path="/api/v3/signals",
        )
        assert sender._extract_api_version() == 3

    def test_default_version_when_no_version_in_path(self):
        """无版本号时默认返回 1"""
        sender = HttpSignalSender(
            base_url="http://127.0.0.1:18888",
            api_path="/api/kafka/message",
        )
        assert sender._extract_api_version() == 1

    def test_default_version_when_empty_path(self):
        """空路径时默认返回 1"""
        sender = HttpSignalSender(
            base_url="http://127.0.0.1:18888",
            api_path="",
        )
        assert sender._extract_api_version() == 1


class TestV1PayloadFormat:
    """测试 V1 payload 格式（包装结构）"""

    def _make_signal(self) -> Signal:
        return Signal(
            signal_id="test_v1_payload_001",
            strategy_id="RBreaker_v2_1m_BTCUSDT",
            strategy_type="cta_rbreaker",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            strength=0.8,
            timestamp=datetime.now(timezone.utc),
        )

    def test_v1_payload_wraps_topic_and_message(self, caplog):
        """V1 格式应包装为 {"topic": ..., "message": ...}"""
        sender = HttpSignalSender(
            base_url="http://127.0.0.1:18888",
            api_path="/api/v1/kafka/message",
        )

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"status": "success"}'
            mock_post.return_value = mock_resp

            with caplog.at_level(logging.INFO, logger="strategy_core.signal_logging.http_sender"):
                result = sender.send_signal(signal, topic="strategy_signals")

        assert result is True

        # 验证 payload 格式
        call_args = mock_post.call_args
        payload_str = call_args[1]["data"]
        payload = json.loads(payload_str)

        assert "topic" in payload
        assert "message" in payload
        assert payload["topic"] == "strategy_signals"

        # message 应为 JSON 字符串
        message_data = json.loads(payload["message"])
        assert "SignalID" in message_data
        assert message_data["SignalID"] == "test_v1_payload_001"

    def test_v1_send_cta_signal_wraps_correctly(self, caplog):
        """V1 格式 send_cta_signal 也应包装"""
        sender = HttpSignalSender(
            base_url="http://127.0.0.1:18888",
            api_path="/api/v1/kafka/message",
        )

        signal = self._make_signal()
        cta_signal = CtaSignalCSV.from_signal(
            signal,
            strategy_name="RBreaker_v2_1m_BTCUSDT",
            strategy_version="v2",
            interval="1m",
        )

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"status": "success"}'
            mock_post.return_value = mock_resp

            result = sender.send_cta_signal(cta_signal, topic="test_topic")

        assert result is True

        payload_str = mock_post.call_args[1]["data"]
        payload = json.loads(payload_str)

        assert payload["topic"] == "test_topic"
        assert "message" in payload


class TestV2PayloadFormat:
    """测试 V2+ payload 格式（直接 to_json）"""

    def _make_signal(self) -> Signal:
        return Signal(
            signal_id="test_v2_payload_001",
            strategy_id="RBreaker_v2_1m_BTCUSDT",
            strategy_type="cta_rbreaker",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            strength=0.8,
            timestamp=datetime.now(timezone.utc),
        )

    def test_v2_payload_is_direct_to_json(self, caplog):
        """V2 格式应直接使用 cta_signal.to_json()，不包装"""
        sender = HttpSignalSender(
            base_url="http://127.0.0.1:18888",
            api_path="/api/v2/signals",
        )

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"status": "success"}'
            mock_post.return_value = mock_resp

            with caplog.at_level(logging.INFO, logger="strategy_core.signal_logging.http_sender"):
                result = sender.send_signal(signal, topic="strategy_signals")

        assert result is True

        # 验证 payload 格式
        call_args = mock_post.call_args
        payload_str = call_args[1]["data"]
        payload = json.loads(payload_str)

        # V2 格式不应有 topic/message 包装
        assert "topic" not in payload
        assert "message" not in payload

        # 应直接是 Signal 结构
        assert "SignalID" in payload
        assert "SignalTimestamp" in payload
        assert "symbol" in payload
        assert "strategy" in payload
        assert "signal" in payload
        assert payload["SignalID"] == "test_v2_payload_001"

    def test_v2_send_cta_signal_is_direct(self, caplog):
        """V2 格式 send_cta_signal 也应直接序列化"""
        sender = HttpSignalSender(
            base_url="http://127.0.0.1:18888",
            api_path="/api/v2/signals",
        )

        signal = self._make_signal()
        cta_signal = CtaSignalCSV.from_signal(
            signal,
            strategy_name="RBreaker_v2_1m_BTCUSDT",
            strategy_version="v2",
            interval="1m",
        )

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"status": "success"}'
            mock_post.return_value = mock_resp

            result = sender.send_cta_signal(cta_signal, topic="test_topic")

        assert result is True

        payload_str = mock_post.call_args[1]["data"]
        payload = json.loads(payload_str)

        # 不应有包装
        assert "topic" not in payload
        assert "message" not in payload

        # 直接是信号数据
        assert "SignalID" in payload
        assert "strategy" in payload

    def test_v3_payload_same_as_v2(self, caplog):
        """V3 格式与 V2 相同（直接 to_json）"""
        sender = HttpSignalSender(
            base_url="http://127.0.0.1:18888",
            api_path="/api/v3/signals",
        )

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"status": "success"}'
            mock_post.return_value = mock_resp

            result = sender.send_signal(signal, topic="strategy_signals")

        assert result is True

        payload_str = mock_post.call_args[1]["data"]
        payload = json.loads(payload_str)

        # V3 与 V2 格式相同
        assert "topic" not in payload
        assert "SignalID" in payload


class TestBackwardCompatibility:
    """测试向后兼容性"""

    def _make_signal(self) -> Signal:
        return Signal(
            signal_id="test_compat_001",
            strategy_id="RBreaker_v2_1m_BTCUSDT",
            strategy_type="cta_rbreaker",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            strength=0.8,
            timestamp=datetime.now(timezone.utc),
        )

    def test_default_api_path_uses_v1_format(self, caplog):
        """默认 api_path 应使用 V1 格式（向后兼容）"""
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888")
        # 默认 api_path 是 /api/v1/kafka/message

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"status": "success"}'
            mock_post.return_value = mock_resp

            result = sender.send_signal(signal, topic="strategy_signals")

        assert result is True

        payload_str = mock_post.call_args[1]["data"]
        payload = json.loads(payload_str)

        # 默认行为应为 V1 包装格式
        assert "topic" in payload
        assert "message" in payload


class TestPayloadBuilderMethods:
    """测试 payload 构建方法"""

    def test_build_v1_payload_structure(self):
        """_build_v1_payload 应返回正确包装结构"""
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888")

        topic = "test_topic"
        message = '{"SignalID": "test_001"}'

        payload = sender._build_v1_payload(topic, message)
        data = json.loads(payload)

        assert data["topic"] == topic
        assert data["message"] == message

    def test_build_v2_payload_structure(self):
        """_build_v2_payload 应直接序列化 to_json"""
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888")

        signal = Signal(
            signal_id="test_build_v2_001",
            strategy_id="RBreaker_v2_1m_BTCUSDT",
            strategy_type="cta_rbreaker",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            timestamp=datetime.now(timezone.utc),
        )
        cta_signal = CtaSignalCSV.from_signal(
            signal,
            strategy_name="RBreaker_v2_1m_BTCUSDT",
            strategy_version="v2",
            interval="1m",
        )

        payload = sender._build_v2_payload(cta_signal)
        data = json.loads(payload)

        # 应直接是 to_json 结果
        assert "SignalID" in data
        assert "strategy" in data
        assert "signal" in data
        assert data["SignalID"] == "test_build_v2_001"
