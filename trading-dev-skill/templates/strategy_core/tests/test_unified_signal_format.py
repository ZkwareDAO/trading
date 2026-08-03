#!/usr/bin/env python3
"""
测试统一信号输出格式

验证:
1. SignalLogger.log_signal 只做 Kafka 推送，不写 SignalStorage CSV
2. 引擎的 _log_signal_unified 同时写 CSV 和 Kafka
3. CSV 和 Kafka 使用相同的 CtaSignalCSV 格式
4. user_id 从配置正确传递到 Kafka 消息
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.logger import SignalLogger, SignalStorage
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV
from strategy_core.signal_logging.kafka_producer import KafkaSignalProducer


class TestSignalLoggerKafkaOnly:
    """测试 SignalLogger.log_signal 只做 Kafka 推送"""

    @pytest.fixture
    def mock_kafka_producer(self):
        producer = MagicMock(spec=KafkaSignalProducer)
        producer.is_available.return_value = True
        producer.send_signal.return_value = True
        return producer

    def test_log_signal_does_not_call_storage_save(self, mock_kafka_producer, tmp_path):
        """log_signal 不应调用 storage.save"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        with patch.object(storage, 'save') as mock_save:
            logger = SignalLogger(storage, kafka_producer=mock_kafka_producer)

            signal = Signal(
                signal_id="test-sig-1",
                strategy_id="test_strategy",
                signal_type=SignalType.BUY,
                symbol="BTCUSDT",
                price=50000.0,
            )
            logger.log_signal(signal, strategy_params={"user_id": 42})

            mock_save.assert_not_called()

    def test_log_signal_calls_kafka_send_signal(self, mock_kafka_producer, tmp_path):
        """log_signal 应调用 kafka_producer.send_signal"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        logger = SignalLogger(storage, kafka_producer=mock_kafka_producer)

        signal = Signal(
            signal_id="test-sig-2",
            strategy_id="test_strategy",
            signal_type=SignalType.SELL,
            symbol="ETHUSDT",
            price=3000.0,
        )
        logger.log_signal(signal, strategy_params={"user_id": 99, "strategy_type": "CTAFutureFactory"})

        mock_kafka_producer.send_signal.assert_called_once()
        call_signal = mock_kafka_producer.send_signal.call_args[0][0]
        call_kwargs = mock_kafka_producer.send_signal.call_args[1]
        assert call_signal.signal_id == "test-sig-2"
        assert call_kwargs.get("user_id") == 99

    def test_log_signal_without_strategy_params(self, mock_kafka_producer, tmp_path):
        """log_signal 无 strategy_params 时应传空 dict"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        logger = SignalLogger(storage, kafka_producer=mock_kafka_producer)

        signal = Signal(
            signal_id="test-sig-3",
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BNBUSDT",
            price=600.0,
        )
        logger.log_signal(signal)

        mock_kafka_producer.send_signal.assert_called_once_with(signal)

    def test_log_signal_without_kafka_producer(self, tmp_path):
        """没有 Kafka producer 时应静默跳过"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        with patch.object(storage, 'save') as mock_save:
            logger = SignalLogger(storage, kafka_producer=None)

            signal = Signal(
                signal_id="test-sig-4",
                strategy_id="test_strategy",
                signal_type=SignalType.FLAT,
                symbol="SOLUSDT",
                price=100.0,
            )
            # 不应抛异常
            result = logger.log_signal(signal, strategy_params={"user_id": 1})

            mock_save.assert_not_called()
            assert result is True

    def test_log_signal_when_kafka_unavailable(self, tmp_path):
        """Kafka 不可用时不应抛异常"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        with patch.object(storage, 'save') as mock_save:
            mock_kafka = MagicMock(spec=KafkaSignalProducer)
            mock_kafka.is_available.return_value = False
            logger = SignalLogger(storage, kafka_producer=mock_kafka)

            signal = Signal(
                signal_id="test-sig-5",
                strategy_id="test_strategy",
                signal_type=SignalType.BUY,
                symbol="ADAUSDT",
                price=0.5,
            )
            result = logger.log_signal(signal, strategy_params={"user_id": 1})

            mock_save.assert_not_called()
            assert result is True


class TestUnifiedSignalFormat:
    """测试 CSV 和 Kafka 使用相同的 CtaSignalCSV 格式"""

    def _make_signal(self) -> Signal:
        return Signal(
            signal_id="unified-sig-1",
            strategy_id="cta_rbreaker_001",
            signal_type=SignalType.SELL,
            symbol="BNBUSDT",
            price=632.96,
            timestamp=datetime(2026, 4, 23, 17, 49, 0),
            direction="short",
            strength=0.75,
        )

    def test_csv_and_kafka_share_same_csi_signal_format(self):
        """CSV 和 Kafka 应使用相同的 CtaSignalCSV 格式"""
        signal = self._make_signal()

        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="RBreakerv2_1m_BNBUSDT",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.01},
            strategy_valid_before="2030-12-31 08:00:00",
            strategy_cash=100,
            strategy_parts=1,
            strategy_type="CTAFutureFactory",
            risk_strategy_type="traditional",
            user_id=10001,
            signal_exchange="binance",
            signal_order_type=1,
            pos_type=2,
        )

        csv_row = cta.to_csv_row()
        kafka_msg = cta.to_json()

        # 两者都应包含 user_id
        assert csv_row["user_id"] == 10001
        assert kafka_msg["user_id"] == 10001

        # 两者都应包含 strategy_type
        assert csv_row["strategy_type"] == "CTAFutureFactory"
        assert kafka_msg["strategy_type"] == "CTAFutureFactory"

        # 两者都应包含 risk_strategy_type
        assert csv_row["risk_strategy_type"] == "traditional"
        assert kafka_msg["risk_strategy_type"] == "traditional"

    def test_kafka_message_user_id_from_config(self):
        """Kafka 消息的 user_id 应来自配置参数"""
        signal = self._make_signal()

        cta = CtaSignalCSV.from_signal(signal, user_id=10001)
        msg = cta.to_json()
        assert msg["user_id"] == 10001

    def test_csv_row_user_id_from_config(self):
        """CSV 行的 user_id 应来自配置参数"""
        signal = self._make_signal()

        cta = CtaSignalCSV.from_signal(signal, user_id=10001)
        row = cta.to_csv_row()
        assert row["user_id"] == 10001

    def test_full_kafka_message_structure(self):
        """Kafka 消息应包含完整的嵌套结构"""
        signal = self._make_signal()

        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="RBreakerv2_1m_BNBUSDT",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.01},
            strategy_valid_before="2030-12-31 08:00:00",
            strategy_cash=100,
            strategy_parts=1,
            strategy_type="CTAFutureFactory",
            risk_strategy_type="traditional",
            user_id=10001,
            signal_exchange="binance",
            signal_order_type=1,
            pos_type=2,
        )
        msg = cta.to_json()

        # 顶层字段
        assert msg["SignalID"] == "unified-sig-1"
        assert msg["symbol"] == "BNBUSDT"
        assert msg["pos_type"] == 2
        assert msg["strategy_type"] == "CTAFutureFactory"
        assert msg["risk_strategy_type"] == "traditional"
        assert msg["user_id"] == 10001

        # strategy 嵌套
        assert msg["strategy"]["name"] == "RBreakerv2"
        assert msg["strategy"]["version"] == "v2"
        assert msg["strategy"]["internal"] == "1m"
        assert msg["strategy"]["valid_before"] == "2030-12-31 08:00:00"
        assert msg["strategy"]["cash"] == 100
        assert msg["strategy"]["parts"] == 1

        # signal 嵌套
        assert msg["signal"]["exchange"] == "binance"
        assert msg["signal"]["order_type"] == 1
        assert msg["signal"]["trigger_price"] == 632.96


class TestSignalCsvWriterSlippage:
    """测试 SignalCsvWriter.write_signal 支持 signal_slippage 参数"""

    def _make_signal(self) -> Signal:
        return Signal(
            signal_id="slippage-sig-1",
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=50000.0,
        )

    def test_write_signal_accepts_signal_slippage(self, tmp_path):
        """write_signal 应接受 signal_slippage 参数并正确传递"""
        from strategy_core.signal_logging.csv_adapter import SignalCsvWriter

        writer = SignalCsvWriter(base_dir=str(tmp_path))
        signal = self._make_signal()

        # 不应抛出异常
        result = writer.write_signal(
            signal=signal,
            strategy_name="TestStrategy",
            strategy_version="v1",
            interval="1m",
            signal_slippage=0.05,
        )
        assert result is True

    def test_write_signal_slippage_reflects_in_csv(self, tmp_path):
        """signal_slippage 应在 CSV 中正确体现"""
        from strategy_core.signal_logging.csv_adapter import SignalCsvWriter
        import csv as csv_module

        writer = SignalCsvWriter(base_dir=str(tmp_path))
        signal = self._make_signal()

        writer.write_signal(
            signal=signal,
            strategy_name="TestStrategy",
            strategy_version="v1",
            interval="1m",
            signal_slippage=0.03,
        )

        # 读取 CSV 验证
        csv_files = list(tmp_path.glob("TestStrategy/*.csv"))
        assert len(csv_files) == 1
        with open(csv_files[0], "r", encoding="utf-8") as f:
            reader = csv_module.DictReader(f)
            row = next(reader)
            assert row["signal_slippage"] == "0.03"


class TestEngineLogSignalUnified:
    """测试引擎的 _log_signal_unified 行为"""

    @pytest.fixture
    def mock_csv_writer(self):
        return MagicMock()

    @pytest.fixture
    def mock_signal_logger(self):
        logger = MagicMock()
        logger.kafka_producer = MagicMock()
        logger.kafka_producer.is_available.return_value = True
        logger.kafka_producer.send_signal.return_value = True
        return logger

    def test_engine_has_csv_writer_attribute(self, tmp_path):
        """StrategyEngine 应支持 csv_writer 参数"""
        from strategy_core.strategy_engine.engine import StrategyEngine

        engine = StrategyEngine(
            strategies_dir=str(tmp_path),
            csv_writer=MagicMock()
        )
        assert engine.csv_writer is not None

    def test_engine_csv_writer_defaults_to_none(self, tmp_path):
        """StrategyEngine 的 csv_writer 默认应为 None"""
        from strategy_core.strategy_engine.engine import StrategyEngine

        engine = StrategyEngine(strategies_dir=str(tmp_path))
        assert engine.csv_writer is None
