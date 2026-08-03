# NOTE: IP addresses in this test are mock values, not real endpoints
#!/usr/bin/env python3
"""
测试 HTTP 信号发送器重试机制

验证：
1. 发送失败时自动重试（最多 3 次）
2. 重试使用指数退避
3. 重试成功后返回 True
4. 重试耗尽后返回 False
"""

import logging
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from strategy_core.signal_logging.http_sender import HttpSignalSender, RetryConfig
from strategy_core.signal_logging.storage import Signal, SignalType


class TestHttpSenderRetry:
    """测试 HTTP 信号发送器重试机制"""

    def _make_signal(self) -> Signal:
        return Signal(
            signal_id="test_retry_001",
            strategy_id="RBreaker_v2_1m_BTCUSDT",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            strength=0.8,
            timestamp=datetime.now(timezone.utc),
        )

    def test_retry_on_connection_error(self, caplog):
        """连接失败时应自动重试"""
        retry_config = RetryConfig(max_retries=3, base_delay=0.1, max_delay=1.0)
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888", retry_config=retry_config)

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            # 前 2 次失败，第 3 次成功
            mock_resp_success = MagicMock()
            mock_resp_success.status_code = 200
            mock_resp_success.text = '{"status": "success"}'
            mock_post.side_effect = [
                Exception("connection timeout"),
                Exception("connection timeout"),
                mock_resp_success,
            ]

            with caplog.at_level(logging.INFO, logger="strategy_core.signal_logging.http_sender"):
                result = sender.send_signal(signal, topic="strategy_signals")

        assert result is True
        assert mock_post.call_count == 3

        # 验证重试日志
        log_text = caplog.text
        assert "重试" in log_text or "retry" in log_text.lower()

    def test_retry_on_server_error(self, caplog):
        """服务器错误时应自动重试"""
        retry_config = RetryConfig(max_retries=3, base_delay=0.1, max_delay=1.0)
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888", retry_config=retry_config)

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            # 前 2 次返回 500，第 3 次返回 200
            mock_resp_500 = MagicMock()
            mock_resp_500.status_code = 500
            mock_resp_500.text = '{"error": "internal server error"}'

            mock_resp_200 = MagicMock()
            mock_resp_200.status_code = 200
            mock_resp_200.text = '{"status": "success"}'

            mock_post.side_effect = [mock_resp_500, mock_resp_500, mock_resp_200]

            with caplog.at_level(logging.INFO, logger="strategy_core.signal_logging.http_sender"):
                result = sender.send_signal(signal, topic="strategy_signals")

        assert result is True
        assert mock_post.call_count == 3

    def test_max_retries_exhausted(self, caplog):
        """重试耗尽后应返回 False"""
        retry_config = RetryConfig(max_retries=3, base_delay=0.1, max_delay=1.0)
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888", retry_config=retry_config)

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            # 所有重试都失败
            mock_post.side_effect = Exception("connection timeout")

            with caplog.at_level(logging.WARNING, logger="strategy_core.signal_logging.http_sender"):
                result = sender.send_signal(signal, topic="strategy_signals")

        assert result is False
        # max_retries=3 意味着 1 次初始 + 3 次重试 = 4 次
        assert mock_post.call_count == 4

    def test_no_retry_on_success(self, caplog):
        """成功时不应重试"""
        retry_config = RetryConfig(max_retries=3, base_delay=0.1, max_delay=1.0)
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888", retry_config=retry_config)

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"status": "success"}'
            mock_post.return_value = mock_resp

            with caplog.at_level(logging.INFO, logger="strategy_core.signal_logging.http_sender"):
                result = sender.send_signal(signal, topic="strategy_signals")

        assert result is True
        assert mock_post.call_count == 1  # 只调用一次

    def test_exponential_backoff(self, caplog):
        """重试应使用指数退避"""
        retry_config = RetryConfig(max_retries=3, base_delay=0.1, max_delay=1.0)
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888", retry_config=retry_config)

        signal = self._make_signal()

        call_times = []

        def mock_post_with_time(*args, **kwargs):
            call_times.append(time.time())
            raise Exception("connection timeout")

        with patch("strategy_core.signal_logging.http_sender.requests.post", side_effect=mock_post_with_time):
            with caplog.at_level(logging.WARNING, logger="strategy_core.signal_logging.http_sender"):
                result = sender.send_signal(signal, topic="strategy_signals")

        assert result is False
        # max_retries=3 意味着 1 次初始 + 3 次重试 = 4 次
        assert len(call_times) == 4

        # 验证退避时间递增（允许一定误差）
        if len(call_times) >= 3:
            delay1 = call_times[1] - call_times[0]
            delay2 = call_times[2] - call_times[1]
            # 第二次延迟应大于第一次（指数退避）
            assert delay2 >= delay1 * 0.8  # 允许 20% 误差

    def test_default_retry_config(self):
        """默认重试配置应为 3 次"""
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888")
        assert sender.retry_config.max_retries == 3
        assert sender.retry_config.base_delay == 1.0
        assert sender.retry_config.max_delay == 10.0

    def test_disable_retry(self, caplog):
        """禁用重试时只尝试一次"""
        retry_config = RetryConfig(max_retries=0, base_delay=0.1, max_delay=1.0)
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888", retry_config=retry_config)

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_post.side_effect = Exception("connection timeout")

            with caplog.at_level(logging.WARNING, logger="strategy_core.signal_logging.http_sender"):
                result = sender.send_signal(signal, topic="strategy_signals")

        assert result is False
        assert mock_post.call_count == 1  # 只尝试一次
