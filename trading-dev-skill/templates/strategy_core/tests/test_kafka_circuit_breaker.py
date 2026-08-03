#!/usr/bin/env python3
"""
KafkaSignalProducer Circuit Breaker 测试

测试熔断器行为：
- CLOSED → OPEN（连续失败达阈值）
- OPEN → 跳过发送（不阻塞）
- OPEN → HALF_OPEN（超时后尝试恢复）
- HALF_OPEN → CLOSED（恢复成功）
- HALF_OPEN → OPEN（恢复失败）
- 去重文件 TTL 清理
"""

import os
import tempfile
import time
import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from strategy_core.signal_logging.storage import Signal, SignalType


def _make_signal(sid: str) -> Signal:
    return Signal(
        signal_id=sid,
        strategy_id="test_strategy",
        signal_type=SignalType.BUY,
        symbol="BTCUSDT",
        price=50000.0,
        timestamp=datetime(2026, 4, 14, 10, 0, 0),
    )


class TestCircuitBreakerInitialState:
    """熔断器初始状态测试"""

    def test_default_state_is_closed(self):
        """默认状态为 CLOSED"""
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        config = {
            "enabled": True,
            "bootstrap_servers": "127.0.0.1:9092",
            "topic": "cta_signals",
        }
        with patch("strategy_core.signal_logging.kafka_producer.KafkaProducer") as MockKafka:
            MockKafka.return_value = MagicMock()
            producer = KafkaSignalProducer(config)
            assert producer._circuit_state == "CLOSED"
            assert producer._consecutive_failures == 0

    def test_custom_circuit_breaker_config(self):
        """自定义熔断器配置"""
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        config = {
            "enabled": True,
            "bootstrap_servers": "127.0.0.1:9092",
            "topic": "cta_signals",
            "circuit_breaker_threshold": 10,
            "circuit_reset_timeout": 60.0,
        }
        with patch("strategy_core.signal_logging.kafka_producer.KafkaProducer") as MockKafka:
            MockKafka.return_value = MagicMock()
            producer = KafkaSignalProducer(config)
            assert producer.circuit_breaker_threshold == 10
            assert producer.circuit_reset_timeout == 60.0


class TestCircuitBreakerTrip:
    """熔断器触发测试"""

    @pytest.fixture
    def mock_producer(self):
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        dedup_file = os.path.join(
            tempfile.gettempdir(), f"test_cb_dedup_{os.getpid()}.txt"
        )
        config = {
            "enabled": True,
            "bootstrap_servers": "127.0.0.1:9092",
            "topic": "cta_signals",
            "dedup_file": dedup_file,
            "circuit_breaker_threshold": 3,
            "circuit_reset_timeout": 1.0,  # 1 秒超时用于快速测试
        }
        with patch("strategy_core.signal_logging.kafka_producer.KafkaProducer") as MockKafka:
            mock_kafka = MagicMock()
            MockKafka.return_value = mock_kafka
            producer = KafkaSignalProducer(config)
            producer._kafka_producer = mock_kafka
            yield producer
        if os.path.exists(dedup_file):
            os.unlink(dedup_file)

    def test_trips_to_open_after_consecutive_failures(self, mock_producer):
        """连续失败达到阈值后，状态变为 OPEN"""
        signal = _make_signal("sig-cb-trip")
        mock_producer._kafka_producer.send.side_effect = TimeoutError("timed out")
        mock_producer._kafka_producer.flush.side_effect = lambda: None

        # 发送 3 次（threshold=3），每次失败
        for i in range(3):
            mock_producer.send_signal(_make_signal(f"sig-cb-trip-{i}"))

        assert mock_producer._circuit_state == "OPEN"
        assert mock_producer._consecutive_failures >= 3

    def test_open_circuit_skips_send_without_blocking(self, mock_producer):
        """OPEN 状态下 send_signal 立即返回 False，不阻塞"""
        # 手动设置为 OPEN
        mock_producer._circuit_state = "OPEN"
        mock_producer._circuit_open_time = time.time()

        signal = _make_signal("sig-cb-skip")
        start = time.monotonic()
        result = mock_producer.send_signal(signal)
        elapsed = time.monotonic() - start

        assert result is False
        # 应该立即返回（不 sleep 重试）
        assert elapsed < 0.5

    def test_half_open_after_timeout(self, mock_producer):
        """OPEN 超时后，下一次 send_signal 尝试恢复（HALF_OPEN）"""
        mock_producer._circuit_state = "OPEN"
        mock_producer._circuit_open_time = time.time() - 2.0  # 2 秒前，超过 1s timeout

        # 重置 mock 调用计数
        mock_producer._kafka_producer.send.reset_mock()
        mock_producer._kafka_producer.send.return_value = MagicMock()
        mock_producer._kafka_producer.flush.side_effect = lambda: None

        signal = _make_signal("sig-cb-half-open")
        result = mock_producer.send_signal(signal)

        # 在 HALF_OPEN 状态下应该尝试发送
        assert result is True
        assert mock_producer._circuit_state == "CLOSED"

    def test_half_open_failure_returns_to_open(self, mock_producer):
        """HALF_OPEN 尝试失败后，回到 OPEN"""
        mock_producer._circuit_state = "OPEN"
        mock_producer._circuit_open_time = time.time() - 2.0  # 超过 timeout

        mock_producer._kafka_producer.send.side_effect = TimeoutError("timed out")
        mock_producer._kafka_producer.flush.side_effect = lambda: None

        signal = _make_signal("sig-cb-half-fail")
        result = mock_producer.send_signal(signal)

        assert result is False
        assert mock_producer._circuit_state == "OPEN"
        # circuit_open_time 应被更新
        assert mock_producer._circuit_open_time is not None

    def test_success_resets_consecutive_failures(self, mock_producer):
        """成功后重置连续失败计数"""
        # 第一次发送失败（含重试），consecutive_failures 会增加
        mock_producer._kafka_producer.send.side_effect = TimeoutError("timeout 1")
        mock_producer._kafka_producer.flush.side_effect = lambda: None

        mock_producer.send_signal(_make_signal("sig-fail-1"))
        # consecutive_failures > 0 因为失败（含内部重试）
        assert mock_producer._consecutive_failures > 0

        # 熔断后 _kafka_producer 被置为 None，手动恢复 mock 和状态
        mock_producer._kafka_producer = MagicMock()
        mock_producer._kafka_producer.send.return_value = MagicMock()
        mock_producer._kafka_producer.flush.side_effect = lambda: None
        mock_producer._circuit_state = "CLOSED"

        result = mock_producer.send_signal(_make_signal("sig-success"))

        assert result is True
        assert mock_producer._consecutive_failures == 0
        assert mock_producer._circuit_state == "CLOSED"


class TestDedupFileTTL:
    """去重文件 TTL 清理测试"""

    def test_load_dedup_file_ignores_expired_entries(self, tmp_path):
        """加载去重文件时忽略过期条目"""
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        dedup_file = str(tmp_path / ".kafka_sent_ids")
        now = datetime.now()
        expired = now - timedelta(hours=25)  # 超过 24h
        fresh = now - timedelta(hours=1)

        # 格式: timestamp|signal_id
        with open(dedup_file, "w") as f:
            f.write(f"{expired.strftime('%Y%m%d%H%M%S')}|sig-expired-1\n")
            f.write(f"{expired.strftime('%Y%m%d%H%M%S')}|sig-expired-2\n")
            f.write(f"{fresh.strftime('%Y%m%d%H%M%S')}|sig-fresh-1\n")
            f.write(f"{fresh.strftime('%Y%m%d%H%M%S')}|sig-fresh-2\n")
            # 旧格式（无时间戳前缀）：视为过期
            f.write("sig-old-format\n")

        config = {
            "enabled": True,
            "bootstrap_servers": "127.0.0.1:9092",
            "topic": "cta_signals",
            "dedup_file": dedup_file,
        }
        with patch("strategy_core.signal_logging.kafka_producer.KafkaProducer") as MockKafka:
            MockKafka.return_value = MagicMock()
            producer = KafkaSignalProducer(config)

            # 过期的不应在内存中
            assert producer.has_sent("sig-expired-1") is False
            assert producer.has_sent("sig-expired-2") is False
            assert producer.has_sent("sig-old-format") is False
            # 新鲜的应在内存中
            assert producer.has_sent("sig-fresh-1") is True
            assert producer.has_sent("sig-fresh-2") is True

    def test_record_sent_uses_new_format(self, tmp_path):
        """record_sent 写入带时间戳的新格式"""
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        dedup_file = str(tmp_path / ".kafka_sent_ids")
        config = {
            "enabled": True,
            "bootstrap_servers": "127.0.0.1:9092",
            "topic": "cta_signals",
            "dedup_file": dedup_file,
        }
        with patch("strategy_core.signal_logging.kafka_producer.KafkaProducer") as MockKafka:
            MockKafka.return_value = MagicMock()
            producer = KafkaSignalProducer(config)

            producer._record_sent("sig-new-format-test")

            with open(dedup_file) as f:
                content = f.read().strip()
            # 应包含时间戳前缀：YYYYMMDDHHMMSS|signal_id
            assert "|" in content
            assert "sig-new-format-test" in content
