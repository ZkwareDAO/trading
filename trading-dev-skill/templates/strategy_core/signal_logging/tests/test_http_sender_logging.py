# NOTE: IP addresses in this test are mock values, not real endpoints
#!/usr/bin/env python3
"""
测试 HTTP 信号发送器日志功能

验证：
1. 发送请求时记录 INFO 日志（请求参数）
2. 收到响应时记录 INFO 日志（响应结果）
3. 失败时记录 WARNING 日志
"""

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from strategy_core.signal_logging.http_sender import HttpSignalSender
from strategy_core.signal_logging.storage import Signal, SignalType


class TestHttpSenderLogging:
    """测试 HTTP 信号发送器日志"""

    def _make_signal(self) -> Signal:
        return Signal(
            signal_id="test_001",
            strategy_id="RBreaker_v2_1m_BTCUSDT",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            strength=0.8,
            timestamp=datetime.now(timezone.utc),
        )

    def test_log_request_params_on_send(self, caplog):
        """发送请求时应记录请求参数"""
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888")

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"status": "success"}'
            mock_post.return_value = mock_resp

            with caplog.at_level(logging.INFO, logger="strategy_core.signal_logging.http_sender"):
                sender.send_signal(signal, topic="strategy_signals")

        log_text = caplog.text

        # 验证请求日志
        assert "HTTP 信号发送请求" in log_text, f"应记录请求日志，实际：{log_text}"
        assert "signal_id=test_001" in log_text, f"应记录 signal_id，实际：{log_text}"
        assert "url=http://127.0.0.1:18888/api/v1/kafka/message" in log_text, f"应记录 URL，实际：{log_text}"
        assert "symbol=BTCUSDT" in log_text, f"应记录 symbol，实际：{log_text}"

    def test_log_response_on_success(self, caplog):
        """收到成功响应时应记录响应结果"""
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888")

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"status": "success", "message_id": "12345"}'
            mock_post.return_value = mock_resp

            with caplog.at_level(logging.INFO, logger="strategy_core.signal_logging.http_sender"):
                result = sender.send_signal(signal, topic="strategy_signals")

        assert result is True
        log_text = caplog.text

        # 验证响应日志
        assert "HTTP 信号发送响应" in log_text, f"应记录响应日志，实际：{log_text}"
        assert "status=200" in log_text, f"应记录状态码，实际：{log_text}"

    def test_log_response_on_failure(self, caplog):
        """收到失败响应时应记录 WARNING 日志"""
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888")

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.text = '{"error": "internal server error"}'
            mock_post.return_value = mock_resp

            with caplog.at_level(logging.WARNING, logger="strategy_core.signal_logging.http_sender"):
                result = sender.send_signal(signal, topic="strategy_signals")

        assert result is False
        log_text = caplog.text

        # 验证失败日志
        assert "HTTP 信号发送失败" in log_text, f"应记录失败日志，实际：{log_text}"
        assert "status=500" in log_text, f"应记录状态码，实际：{log_text}"

    def test_log_on_exception(self, caplog):
        """发生异常时应记录 WARNING 日志"""
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888")

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_post.side_effect = Exception("connection timeout")

            with caplog.at_level(logging.WARNING, logger="strategy_core.signal_logging.http_sender"):
                result = sender.send_signal(signal, topic="strategy_signals")

        assert result is False
        log_text = caplog.text

        # 验证异常日志
        assert "HTTP 信号发送异常" in log_text, f"应记录异常日志，实际：{log_text}"
        assert "connection timeout" in log_text, f"应记录异常信息，实际：{log_text}"
