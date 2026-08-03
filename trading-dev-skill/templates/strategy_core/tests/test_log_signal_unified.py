#!/usr/bin/env python3
"""
测试 _log_signal_unified 方法的统一存储行为：
1. CSV 成功 → HTTP/Kafka 正常推送
2. CSV 失败 → 跳过 HTTP/Kafka 推送（避免数据不一致）
3. 无 csv_writer → 仅推 HTTP/Kafka
"""

from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

from strategy_core.strategy_engine.engine import StrategyEngine


class TestLogSignalUnified:
    """测试 _log_signal_unified 的 CSV+HTTP/Kafka 协调逻辑"""

    def _make_signal(self):
        signal = MagicMock()
        signal.signal_id = "sig-test-001"
        signal.strategy_id = "TestStrategy_v1_1m_BTCUSDT"  # 策略实例名称
        signal.signal_type = MagicMock()
        signal.signal_type.value = "BUY"
        signal.symbol = "BTCUSDT"
        signal.price = 50000.0
        signal.strength = 0.8
        signal.timestamp = datetime.now(timezone.utc)
        signal.direction = None
        signal.metadata = {}
        return signal

    def _make_entry(self, config=None, strategy_name="TestStrategy_v1_1m_BTCUSDT"):
        entry = MagicMock()
        entry.config = config or {}
        entry.strategy_id = "test_001"
        entry.strategy_name = strategy_name
        return entry

    def _make_engine(self, tmp_path, csv_writer=None, signal_logger=None):
        engine = StrategyEngine(
            strategies_dir=str(tmp_path),
            csv_writer=csv_writer,
            signal_logger=signal_logger,
        )
        return engine

    def test_csv_success_then_http_kafka_push(self, tmp_path):
        """CSV 写入成功时，应继续推送 HTTP/Kafka"""
        csv_writer = MagicMock()
        csv_writer.write_cta_signal.return_value = True

        signal_logger = MagicMock()

        engine = self._make_engine(
            tmp_path, csv_writer=csv_writer,
            signal_logger=signal_logger,
        )
        signal = self._make_signal()
        entry = self._make_entry({"user_id": 42})
        params = {"user_id": 42, "strategy_type": "CTAFutureFactory"}

        # Mock CtaSignalCSV.from_signal
        with patch("strategy_core.signal_logging.csv_adapter.CtaSignalCSV") as mock_cta:
            mock_cta.from_signal.return_value = MagicMock(signal_id="sig-test-001")
            engine._log_signal_unified(signal, params, entry)

        csv_writer.write_cta_signal.assert_called_once()
        signal_logger.log_cta_signal.assert_called_once()

    def test_csv_failure_skips_http_kafka(self, tmp_path):
        """CSV 写入失败时，不应推送 HTTP/Kafka（避免数据不一致）"""
        csv_writer = MagicMock()
        csv_writer.write_cta_signal.return_value = False  # CSV 写入失败

        signal_logger = MagicMock()

        engine = self._make_engine(
            tmp_path, csv_writer=csv_writer,
            signal_logger=signal_logger,
        )
        signal = self._make_signal()
        entry = self._make_entry({"user_id": 42})
        params = {"user_id": 42}

        with patch("strategy_core.signal_logging.csv_adapter.CtaSignalCSV") as mock_cta:
            mock_cta.from_signal.return_value = MagicMock(signal_id="sig-test-001")
            engine._log_signal_unified(signal, params, entry)

        # CSV 写入被尝试
        csv_writer.write_cta_signal.assert_called_once()
        # HTTP/Kafka 不应被调用（CSV 已失败）
        signal_logger.log_cta_signal.assert_not_called()

    def test_no_csv_writer_only_http_kafka(self, tmp_path):
        """没有 csv_writer 时，只推 HTTP/Kafka"""
        signal_logger = MagicMock()

        engine = self._make_engine(
            tmp_path, csv_writer=None,
            signal_logger=signal_logger,
        )
        signal = self._make_signal()
        entry = self._make_entry({})
        params = {}

        with patch("strategy_core.signal_logging.csv_adapter.CtaSignalCSV") as mock_cta:
            mock_cta.from_signal.return_value = MagicMock(signal_id="sig-test-001")
            engine._log_signal_unified(signal, params, entry)

        # HTTP/Kafka 被调用
        signal_logger.log_cta_signal.assert_called_once()

    def test_csv_failure_logs_error(self, tmp_path):
        """CSV 失败时应记录错误日志"""
        csv_writer = MagicMock()
        csv_writer.write_cta_signal.side_effect = RuntimeError("write failed")

        signal_logger = MagicMock()
        signal_logger.log_cta_signal.side_effect = AssertionError(
            "HTTP/Kafka should not be called",
        )

        engine = self._make_engine(
            tmp_path, csv_writer=csv_writer,
            signal_logger=signal_logger,
        )
        signal = self._make_signal()
        entry = self._make_entry({"user_id": 1})
        params = {"user_id": 1}

        with patch("strategy_core.signal_logging.csv_adapter.CtaSignalCSV") as mock_cta:
            mock_cta.from_signal.return_value = MagicMock(signal_id="sig-test-001")
            # 不应抛出异常（错误被捕获并记录日志）
            engine._log_signal_unified(signal, params, entry)
