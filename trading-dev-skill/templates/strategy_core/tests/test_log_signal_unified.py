#!/usr/bin/env python3
"""
测试 StrategyProcessRunner._handle_signal 的统一存储行为：
1. CSV 成功 → 直连下单正常执行
2. CSV 失败 → 跳过直连下单（避免数据不一致）
3. 无 csv_writer → 仅直连下单
"""

from unittest.mock import MagicMock, patch

from run_strategy import StrategyProcessRunner


def _make_runner(tmp_path, csv_writer=None, signal_logger=None):
    """构建最小 Runner（绕过 __init__ 的 DataManager/SignalLogger 初始化）"""
    runner = StrategyProcessRunner.__new__(StrategyProcessRunner)
    runner.strategy_name = "TestStrategy_v1_1m_BTCUSDT"
    runner.strategy_config = {"user_id": 42}
    runner.strategy = None
    runner.csv_writer = csv_writer
    runner.signal_logger = signal_logger
    return runner


def _make_signal():
    signal = MagicMock()
    signal.signal_id = "sig-test-001"
    signal.strategy_id = "TestStrategy_v1_1m_BTCUSDT"  # 策略实例名称
    signal.signal_type = MagicMock()
    signal.signal_type.value = "BUY"
    signal.symbol = "BTCUSDT"
    signal.price = 50000.0
    signal.strength = 0.8
    signal.direction = None
    signal.metadata = {}
    return signal


class TestHandleSignal:
    """测试 _handle_signal 的 CSV+直连下单协调逻辑"""

    def test_csv_success_then_direct_order(self, tmp_path):
        """CSV 写入成功时，应继续直连下单"""
        csv_writer = MagicMock()
        csv_writer.write_cta_signal.return_value = True

        signal_logger = MagicMock()

        runner = _make_runner(
            tmp_path, csv_writer=csv_writer,
            signal_logger=signal_logger,
        )
        signal = _make_signal()

        # Mock CtaSignalCSV.from_signal
        with patch("run_strategy.CtaSignalCSV") as mock_cta:
            mock_cta.from_signal.return_value = MagicMock(signal_id="sig-test-001")
            runner._handle_signal(signal)

        csv_writer.write_cta_signal.assert_called_once()
        signal_logger.log_cta_signal.assert_called_once()

    def test_csv_failure_skips_direct_order(self, tmp_path):
        """CSV 写入失败时，不应直连下单（避免数据不一致）"""
        csv_writer = MagicMock()
        csv_writer.write_cta_signal.return_value = False  # CSV 写入失败

        signal_logger = MagicMock()

        runner = _make_runner(
            tmp_path, csv_writer=csv_writer,
            signal_logger=signal_logger,
        )
        signal = _make_signal()

        with patch("run_strategy.CtaSignalCSV") as mock_cta:
            mock_cta.from_signal.return_value = MagicMock(signal_id="sig-test-001")
            runner._handle_signal(signal)

        # CSV 写入被尝试
        csv_writer.write_cta_signal.assert_called_once()
        # 直连下单不应被调用（CSV 已失败）
        signal_logger.log_cta_signal.assert_not_called()

    def test_no_csv_writer_only_direct_order(self, tmp_path):
        """没有 csv_writer 时，只走直连下单"""
        signal_logger = MagicMock()

        runner = _make_runner(
            tmp_path, csv_writer=None,
            signal_logger=signal_logger,
        )
        signal = _make_signal()

        with patch("run_strategy.CtaSignalCSV") as mock_cta:
            mock_cta.from_signal.return_value = MagicMock(signal_id="sig-test-001")
            runner._handle_signal(signal)

        # 直连下单被调用
        signal_logger.log_cta_signal.assert_called_once()

    def test_csv_failure_logs_error(self, tmp_path):
        """CSV 失败时应记录错误日志且不抛出异常"""
        csv_writer = MagicMock()
        csv_writer.write_cta_signal.side_effect = RuntimeError("write failed")

        signal_logger = MagicMock()
        signal_logger.log_cta_signal.side_effect = AssertionError(
            "direct order should not be called",
        )

        runner = _make_runner(
            tmp_path, csv_writer=csv_writer,
            signal_logger=signal_logger,
        )
        signal = _make_signal()

        with patch("run_strategy.CtaSignalCSV") as mock_cta:
            mock_cta.from_signal.return_value = MagicMock(signal_id="sig-test-001")
            # 不应抛出异常（错误被捕获并记录日志）
            runner._handle_signal(signal)
