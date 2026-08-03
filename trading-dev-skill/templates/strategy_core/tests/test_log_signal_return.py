#!/usr/bin/env python3
"""
测试 SignalLogger.log_signal 的返回值语义：
- 有 Kafka 且可用 → 返回推送结果
- 无 Kafka → 返回 True（无操作视为成功）
"""

from unittest.mock import MagicMock
from datetime import datetime, timezone

from strategy_core.signal_logging.logger import SignalLogger
from strategy_core.signal_logging.storage import Signal


class TestLogSignalReturnValue:
    """测试 log_signal 返回值语义"""

    def _make_signal(self):
        signal = MagicMock(spec=Signal)
        signal.signal_id = "sig-test-001"
        signal.signal_type = "BUY"
        signal.symbol = "BTCUSDT"
        signal.price = 50000.0
        signal.strength = 0.8
        signal.timestamp = datetime.now(timezone.utc)
        signal.metadata = {}
        return signal

    def test_no_kafka_returns_true(self, tmp_path):
        """没有 Kafka 时返回 True（无操作视为成功）"""
        from strategy_core.signal_logging.logger import SignalStorage
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        logger = SignalLogger(storage=storage, kafka_producer=None)

        signal = self._make_signal()
        result = logger.log_signal(signal)

        assert result is True

    def test_kafka_available_returns_true(self, tmp_path):
        """Kafka 可用且推送成功时返回 True"""
        from strategy_core.signal_logging.logger import SignalStorage
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        kafka_producer = MagicMock()
        kafka_producer.is_available.return_value = True
        logger = SignalLogger(storage=storage, kafka_producer=kafka_producer)

        signal = self._make_signal()
        result = logger.log_signal(signal, strategy_params={"user_id": 1})

        assert result is True
        kafka_producer.send_signal.assert_called_once()

    def test_kafka_unavailable_returns_true(self, tmp_path):
        """Kafka 不可用时返回 True（跳过不视为失败）"""
        from strategy_core.signal_logging.logger import SignalStorage
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        kafka_producer = MagicMock()
        kafka_producer.is_available.return_value = False
        logger = SignalLogger(storage=storage, kafka_producer=kafka_producer)

        signal = self._make_signal()
        result = logger.log_signal(signal)

        assert result is True
        kafka_producer.send_signal.assert_not_called()

    def test_kafka_push_exception_returns_false(self, tmp_path):
        """Kafka 推送异常时返回 False"""
        from strategy_core.signal_logging.logger import SignalStorage
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        kafka_producer = MagicMock()
        kafka_producer.is_available.return_value = True
        kafka_producer.send_signal.side_effect = RuntimeError("connection lost")
        logger = SignalLogger(storage=storage, kafka_producer=kafka_producer)

        signal = self._make_signal()
        result = logger.log_signal(signal)

        assert result is False
