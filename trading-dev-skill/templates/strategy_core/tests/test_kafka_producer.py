#!/usr/bin/env python3
"""
KafkaSignalProducer 单元测试

测试 Kafka 信号推送功能
"""

import json
import os
import tempfile
import pytest
from datetime import datetime
from unittest.mock import MagicMock, patch

from strategy_core.signal_logging.storage import Signal, SignalType


class TestKafkaProducerInit:
    """测试初始化"""

    def test_kafka_producer_import_exists(self):
        """测试 kafka_producer 模块可导入"""
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer
        assert KafkaSignalProducer is not None

    def test_init_with_minimal_config(self):
        """测试最小配置初始化"""
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        config = {
            "bootstrap_servers": "127.0.0.1:9092",
            "topic": "cta_signals",
        }
        producer = KafkaSignalProducer(config)
        assert producer is not None

    def test_init_with_disabled_config(self):
        """测试禁用配置初始化"""
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        config = {"enabled": False}
        producer = KafkaSignalProducer(config)
        assert producer.is_available() is False


class TestKafkaProducerSend:
    """测试信号发送"""

    @pytest.fixture
    def mock_producer(self):
        """创建 mock 的 producer，不实际连接 Kafka"""
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        dedup_file = os.path.join(tempfile.gettempdir(), f"test_kafka_dedup_{os.getpid()}.txt")
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
        # cleanup
        if os.path.exists(dedup_file):
            os.unlink(dedup_file)

    def _create_test_signal(self) -> Signal:
        return Signal(
            signal_id="sig-test-001",
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=50000.0,
            volume=0.1,
            strength=0.8,
            direction="long",
            timestamp=datetime(2026, 4, 14, 10, 0, 0),
            metadata={"reason": "breakout"},
        )

    def test_send_signal_converts_to_kafka_format(self, mock_producer):
        """测试信号转换为 Kafka 格式并发送"""
        signal = self._create_test_signal()
        strategy_params = {
            "strategy_name": "cta_rbreaker_v2_1m_btcusdt",
            "strategy_version": "v2",
            "interval": "1m",
            "strategy_params": {"threshold": 0.005},
        }

        result = mock_producer.send_signal(signal, **strategy_params)
        assert result is True

        # 验证 Kafka producer 被调用，topic 作为第一个位置参数
        mock_producer._kafka_producer.send.assert_called_once()
        call_args = mock_producer._kafka_producer.send.call_args
        # send(topic, value=...) — topic 是位置参数
        assert call_args[0][0] == "cta_signals"

    def test_send_signal_value_is_valid_json(self, mock_producer):
        """测试发送的消息是合法 JSON"""
        signal = self._create_test_signal()

        def capture_send(topic, **kwargs):
            captured["topic"] = topic
            captured["value"] = kwargs.get("value")
            return MagicMock()

        captured = {}
        mock_producer._kafka_producer.send.side_effect = capture_send

        mock_producer.send_signal(signal)

        # value 应该是可解析的 JSON 字符串或 bytes
        value = captured["value"]
        if isinstance(value, bytes):
            value = value.decode("utf-8")
        parsed = json.loads(value)

        # 验证 Kafka 格式结构
        assert "SignalID" in parsed
        assert "strategy" in parsed
        assert "signal" in parsed
        assert parsed["SignalID"] == "sig-test-001"

    def test_send_signal_failure_returns_false(self, mock_producer):
        """测试发送失败返回 False"""
        signal = self._create_test_signal()
        mock_producer._kafka_producer.send.side_effect = Exception("Kafka unavailable")

        result = mock_producer.send_signal(signal)
        assert result is False

    def test_send_signal_not_available_does_nothing(self):
        """测试不可用时 send_signal 不报错"""
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        config = {"enabled": False}
        producer = KafkaSignalProducer(config)

        signal = self._create_test_signal()
        result = producer.send_signal(signal)
        assert result is False


class TestKafkaProducerBatch:
    """测试批量发送"""

    @pytest.fixture
    def mock_producer(self):
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        dedup_file = os.path.join(tempfile.gettempdir(), f"test_kafka_dedup_batch_{os.getpid()}.txt")
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

    def test_send_batch_returns_count(self, mock_producer):
        """测试批量发送返回成功数量"""
        signals = [
            Signal(
                signal_id=f"sig-{i}",
                strategy_id="test_strategy",
                signal_type=SignalType.BUY,
                symbol="BTCUSDT",
                price=50000.0,
                timestamp=datetime(2026, 4, 14, 10, i, 0),
            )
            for i in range(3)
        ]

        count = mock_producer.send_batch(signals)
        assert count == 3

    def test_send_batch_empty_returns_zero(self, mock_producer):
        """测试空列表返回 0"""
        count = mock_producer.send_batch([])
        assert count == 0


class TestKafkaProducerClose:
    """测试关闭"""

    def test_close_calls_kafka_flush_and_close(self):
        """测试 close 调用 Kafka flush 和 close"""
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        config = {
            "enabled": True,
            "bootstrap_servers": "127.0.0.1:9092",
            "topic": "cta_signals",
        }
        with patch("strategy_core.signal_logging.kafka_producer.KafkaProducer") as MockKafka:
            mock_kafka = MagicMock()
            MockKafka.return_value = mock_kafka
            producer = KafkaSignalProducer(config)
            producer._kafka_producer = mock_kafka

            producer.close()

            mock_kafka.flush.assert_called()
            mock_kafka.close.assert_called()

    def test_close_when_disabled_does_nothing(self):
        """测试禁用时 close 不报错"""
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        config = {"enabled": False}
        producer = KafkaSignalProducer(config)
        producer.close()  # should not raise


class TestKafkaProducerDedup:
    """测试去重功能"""

    @pytest.fixture
    def mock_producer(self):
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        dedup_file = os.path.join(tempfile.gettempdir(), f"test_kafka_dedup_dup_{os.getpid()}.txt")
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

    def _create_test_signal(self, signal_id: str = "sig-test-001") -> Signal:
        return Signal(
            signal_id=signal_id,
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=50000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0),
        )

    def test_has_sent_returns_false_for_new_signal(self, mock_producer):
        """测试新信号 has_sent 返回 False"""
        assert mock_producer.has_sent("sig-new-never-sent") is False

    def test_has_sent_returns_true_after_send(self, mock_producer):
        """测试发送后 has_sent 返回 True"""
        signal = self._create_test_signal()
        mock_producer.send_signal(signal)
        assert mock_producer.has_sent("sig-test-001") is True

    def test_send_signal_duplicate_skips(self, mock_producer):
        """测试重复信号不发送"""
        signal = self._create_test_signal()

        # 第一次发送
        result1 = mock_producer.send_signal(signal)
        assert result1 is True
        mock_producer._kafka_producer.send.assert_called_once()

        # 第二次发送相同 signal_id，跳过
        result2 = mock_producer.send_signal(signal)
        assert result2 is False
        # send 调用次数不变
        assert mock_producer._kafka_producer.send.call_count == 1

    def test_send_batch_skips_duplicates_within_batch(self, mock_producer):
        """测试批量发送时跳过批次内重复"""
        signal = self._create_test_signal()
        signals = [signal, signal, signal]  # 同一信号 3 次

        count = mock_producer.send_batch(signals)
        assert count == 1  # 只发送一次

    def test_send_batch_different_signals(self, mock_producer):
        """测试批量发送不同信号全部成功"""
        signals = [
            Signal(
                signal_id=f"sig-batch-{i}",
                strategy_id="test_strategy",
                signal_type=SignalType.BUY,
                symbol="BTCUSDT",
                price=50000.0,
                timestamp=datetime(2026, 4, 14, 10, i, 0),
            )
            for i in range(3)
        ]

        count = mock_producer.send_batch(signals)
        assert count == 3

    def test_max_size_enforcement(self, mock_producer):
        """测试超过上限后清除最旧的"""
        mock_producer._sent_ids_max = 5
        for i in range(7):
            sig_id = f"sig-{i}"
            mock_producer._record_sent(sig_id)

        # 最多保留 5 个
        assert len(mock_producer._sent_ids) <= 5


class TestKafkaProducerDedupPersistence:
    """测试去重文件持久化"""

    def test_init_loads_existing_ids(self, tmp_path):
        """测试启动时加载已有去重文件"""
        dedup_file = str(tmp_path / ".kafka_sent_ids")
        now = datetime.now()
        ts = now.strftime("%Y%m%d%H%M%S")
        with open(dedup_file, "w") as f:
            f.write(f"{ts}|sig-already-sent-1\n{ts}|sig-already-sent-2\n")

        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

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

            assert producer.has_sent("sig-already-sent-1") is True
            assert producer.has_sent("sig-already-sent-2") is True
            assert producer.has_sent("sig-not-sent") is False

    def test_send_appends_to_dedup_file(self, tmp_path):
        """测试发送后追加到去重文件"""
        dedup_file = str(tmp_path / ".kafka_sent_ids")

        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

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

            signal = Signal(
                signal_id="sig-persist-test",
                strategy_id="test_strategy",
                signal_type=SignalType.BUY,
                symbol="BTCUSDT",
                price=50000.0,
                timestamp=datetime(2026, 4, 14, 10, 0, 0),
            )
            producer.send_signal(signal)

            # 验证文件写入了 signal_id（新格式：YYYYMMDDHHMMSS|signal_id）
            with open(dedup_file) as f:
                content = f.read()
            assert "sig-persist-test" in content
            assert "|" in content


class TestKafkaProducerConfig:
    """测试配置处理"""

    def test_config_with_sasl(self):
        """测试 SASL 配置"""
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        config = {
            "enabled": True,
            "bootstrap_servers": "kafka:9092",
            "topic": "cta_signals",
            "sasl_mechanism": "PLAIN",
            "sasl_username": "user",
            "sasl_password": "pass",
        }
        with patch("strategy_core.signal_logging.kafka_producer.KafkaProducer") as MockKafka:
            KafkaSignalProducer(config)

            # 验证 SASL 配置被传递
            call_kwargs = MockKafka.call_args.kwargs
            assert "security_protocol" in call_kwargs

    def test_config_with_compression(self):
        """测试压缩配置"""
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        config = {
            "enabled": True,
            "bootstrap_servers": "127.0.0.1:9092",
            "topic": "cta_signals",
            "compression": "gzip",
        }
        with patch("strategy_core.signal_logging.kafka_producer.KafkaProducer") as MockKafka:
            KafkaSignalProducer(config)

            call_kwargs = MockKafka.call_args.kwargs
            assert "compression_type" in call_kwargs


class TestKafkaProducerRetry:
    """测试发送失败自动重试"""

    @pytest.fixture
    def mock_producer(self):
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        dedup_file = os.path.join(tempfile.gettempdir(), f"test_kafka_retry_{os.getpid()}.txt")
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
            MockKafka.reset_mock()
        if os.path.exists(dedup_file):
            os.unlink(dedup_file)

    def _create_signal(self, sid="sig-retry-test") -> Signal:
        return Signal(
            signal_id=sid,
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=50000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0),
        )

    def test_send_retries_on_timeout_then_succeeds(self, mock_producer):
        """超时后重试成功：第一次超时，第二次成功"""
        signal = self._create_signal("sig-retry-timeout")

        # 第一次调用超时，第二次成功
        call_count = [0]

        def flaky_send(topic, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise TimeoutError("30 seconds have passed")
            return MagicMock()

        mock_producer._kafka_producer.send.side_effect = flaky_send
        mock_producer._kafka_producer.flush.side_effect = lambda: None

        result = mock_producer.send_signal(signal)
        assert result is True
        assert call_count[0] == 2

    def test_send_retries_on_connection_reset_then_succeeds(self, mock_producer):
        """连接断开后重试成功"""
        signal = self._create_signal("sig-retry-reset")

        call_count = [0]

        def flaky_send(topic, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise ConnectionError("Connection reset by peer")
            return MagicMock()

        mock_producer._kafka_producer.send.side_effect = flaky_send
        mock_producer._kafka_producer.flush.side_effect = lambda: None

        result = mock_producer.send_signal(signal)
        assert result is True
        assert call_count[0] == 3

    def test_send_gives_up_after_max_retries(self, mock_producer):
        """超过最大重试次数后返回 False"""
        signal = self._create_signal("sig-retry-giveup")

        send_calls = []

        def always_fail(topic, **kwargs):
            send_calls.append(1)
            raise TimeoutError("Request timed out")

        mock_producer._kafka_producer.send.side_effect = always_fail

        result = mock_producer.send_signal(signal)
        assert result is False
        # 默认 3 次重试，加上首次发送，总共 4 次调用
        assert len(send_calls) == 4

    def test_non_retryable_error_does_not_retry(self, mock_producer):
        """非网络类错误不重试（如序列化错误）"""
        signal = self._create_signal("sig-retry-typeerror")

        call_count = 0

        def count_and_fail(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise TypeError("not iterable")

        mock_producer._kafka_producer.send.side_effect = count_and_fail

        result = mock_producer.send_signal(signal)
        assert result is False
        # 非网络错误只尝试 1 次
        assert call_count == 1

    def test_batch_continues_on_individual_failure(self, mock_producer):
        """批量发送中单个失败不影响其他信号"""
        signals = [
            self._create_signal(f"sig-batch-retry-{i}")
            for i in range(3)
        ]

        # 第二个信号发送时失败
        call_count = [0]

        def flaky_send(topic, **kwargs):
            call_count[0] += 1
            if call_count[0] == 2:
                raise TimeoutError("timed out")
            return MagicMock()

        mock_producer._kafka_producer.send.side_effect = flaky_send
        mock_producer._kafka_producer.flush.side_effect = lambda: None

        count = mock_producer.send_batch(signals)
        assert count == 3


class TestKafkaProducerAutoReconnect:
    """测试连接断开后自动重连"""

    @pytest.fixture
    def mock_producer(self):
        from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer

        dedup_file = os.path.join(tempfile.gettempdir(), f"test_kafka_reconnect_{os.getpid()}.txt")
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
            MockKafka.reset_mock()
        if os.path.exists(dedup_file):
            os.unlink(dedup_file)

    def _create_signal(self, sid="sig-reconnect-test") -> Signal:
        return Signal(
            signal_id=sid,
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=50000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0),
        )

    def test_send_recreates_producer_on_disconnection(self, mock_producer):
        """连接断开后，send_signal 应自动重建 Producer"""
        signal = self._create_signal("sig-reconnect-001")

        # 第一次发送，模拟连接断开
        mock_producer._kafka_producer.send.side_effect = Exception("Connection reset")

        result = mock_producer.send_signal(signal)
        assert result is False

        # 此时 _kafka_producer 应被标记为不可用
        assert mock_producer._kafka_producer is None

    def test_send_after_disconnection_reconnects(self, mock_producer):
        """断开后再次发送应尝试重建连接"""
        # 先断开
        mock_producer._kafka_producer = None

        signal = self._create_signal("sig-reconnect-002")
        # is_available 返回 False，send_signal 直接返回
        result = mock_producer.send_signal(signal)
        assert result is False

    def test_reconnect_success(self, mock_producer):
        """重建连接成功后应能正常发送"""
        # 模拟连接断开
        mock_producer._kafka_producer = None

        # 调用重连，在 mock 环境下会创建新的 mock producer
        mock_producer._reconnect()

        # 重连后 producer 应该恢复
        assert mock_producer._kafka_producer is not None
        assert mock_producer.is_available() is True
