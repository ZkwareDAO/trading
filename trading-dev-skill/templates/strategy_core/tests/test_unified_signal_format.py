#!/usr/bin/env python3
"""
测试统一信号输出格式

验证:
1. SignalLogger.log_signal 只做直连下单（配置 direct_trader 时），不写 SignalStorage CSV
2. 引擎的 _log_signal_unified 统一写 CSV 并触发下单
3. CSV 和下单 payload 使用相同的 CtaSignalCSV 格式
4. user_id 从配置正确传递到下单 payload

通道沿革：Kafka → signal_hub HTTP 推送 → 单体直连下单（direct_trader），
前两代已随单体化移除；"log_signal 不写 CSV" 的不变量与通道无关，跨代保留，
现用 direct_trader 验证。
"""

import json
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.logger import SignalLogger, SignalStorage
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV


class TestSignalLoggerDirectRouting:
    """测试 SignalLogger.log_signal 直连路由语义（单体模式）

    不变量（与通道无关，跨 Kafka→HTTP→direct_trader 三代沿革保留）：
    1. log_signal 不落 SignalStorage CSV —— CSV 由引擎的 _log_signal_unified
       统一写（走 SignalCsvWriter），log_signal 再写会产生两份格式不同的记录
    2. 配置 direct_trader 时经 CtaSignalCSV 转换后调用 execute 下单
    3. 未配置 direct_trader 时不下单、不报错（只落 JSON 备份）
    4. 下单失败如实返回 False（单体后没有第二条通道兜底，失败不许伪装成功）
    """

    @pytest.fixture
    def mock_direct_trader(self):
        trader = MagicMock()
        trader.execute.return_value = True
        return trader

    def _make_logger(self, storage, direct_trader=None):
        return SignalLogger(storage, direct_trader=direct_trader)

    def test_log_signal_does_not_call_storage_save(self, mock_direct_trader, tmp_path):
        """log_signal 不应调用 storage.save"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        with patch.object(storage, 'save') as mock_save:
            logger = self._make_logger(storage, mock_direct_trader)

            signal = Signal(
                signal_id="test-sig-1",
                strategy_id="test_strategy",
                signal_type=SignalType.BUY,
                symbol="BTCUSDT",
                price=50000.0,
            )
            logger.log_signal(signal, strategy_params={"user_id": 42})

            mock_save.assert_not_called()

    def test_log_signal_routes_to_direct_trader(self, mock_direct_trader, tmp_path):
        """log_signal 应把 Signal 转成 CtaSignalCSV 交给 direct_trader.execute"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        logger = self._make_logger(storage, mock_direct_trader)

        signal = Signal(
            signal_id="test-sig-2",
            strategy_id="test_strategy",
            signal_type=SignalType.SELL,
            symbol="ETHUSDT",
            price=3000.0,
        )
        logger.log_signal(signal, strategy_params={"user_id": 7})

        mock_direct_trader.execute.assert_called_once()
        cta = mock_direct_trader.execute.call_args[0][0]
        assert cta.signal_id == "test-sig-2"

    def test_log_signal_without_direct_trader(self, tmp_path):
        """未配置 direct_trader 时不下单、不报错，且不落 CSV"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        with patch.object(storage, 'save') as mock_save:
            logger = SignalLogger(storage)

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
            # 无直连执行器 = 不下单部署（如 paper_trading），信号不出进程属预期，恒返回 True
            assert result is True

    def test_log_signal_when_direct_execute_fails(self, tmp_path):
        """下单失败时如实返回 False，不抛异常，也不落 CSV"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        with patch.object(storage, 'save') as mock_save:
            failing_trader = MagicMock()
            failing_trader.execute.return_value = False
            logger = self._make_logger(storage, failing_trader)

            signal = Signal(
                signal_id="test-sig-5",
                strategy_id="test_strategy",
                signal_type=SignalType.BUY,
                symbol="ADAUSDT",
                price=0.5,
            )
            result = logger.log_signal(signal, strategy_params={"user_id": 1})

            mock_save.assert_not_called()
            failing_trader.execute.assert_called_once()
            assert result is False


class TestUnifiedSignalFormat:
    """测试 CSV 和外发 payload 使用相同的 CtaSignalCSV 格式"""

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

    def test_csv_and_order_payload_share_same_csi_signal_format(self):
        """CSV 和下单 payload 应使用相同的 CtaSignalCSV 格式"""
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
