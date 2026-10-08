#!/usr/bin/env python3
"""
测试 SignalLogger 的返回值语义（单体模式）：
- 未配置 direct_trader → 返回 True（只落存储，不下单）
- direct_trader 下单成功 → 返回 True
- direct_trader 下单失败 → 返回 False
- direct_trader 抛异常 → 不打断主循环，返回 False

原文件测的是 HTTP 推送通道的返回值语义。HTTP 推送通道已随
单体模式重构移除，现在唯一的下发通道是 direct_trader 直连下单。
"""

from unittest.mock import MagicMock
from datetime import datetime, timezone

from strategy_core.signal_logging.logger import SignalLogger, SignalStorage
from strategy_core.signal_logging.storage import Signal, SignalType


class TestLogSignalReturnValue:
    """测试 log_signal / log_cta_signal 返回值语义"""

    def _make_signal(self):
        return Signal(
            signal_id="sig-test-001",
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=50000.0,
            strength=0.8,
            timestamp=datetime(2026, 5, 8, 1, 43, 0, tzinfo=timezone.utc),
        )

    def test_no_trader_returns_true(self, tmp_path):
        """未配置 direct_trader 时返回 True（只落存储，不下单）"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        logger = SignalLogger(storage=storage)

        result = logger.log_signal(self._make_signal())

        assert result is True

    def test_direct_trader_success_returns_true(self, tmp_path):
        """直连下单成功时返回 True"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        trader = MagicMock()
        trader.execute.return_value = True
        logger = SignalLogger(storage=storage, direct_trader=trader)

        result = logger.log_signal(self._make_signal(), strategy_params={"user_id": 1})

        assert result is True
        trader.execute.assert_called_once()

    def test_direct_trader_failure_returns_false(self, tmp_path):
        """直连下单失败时返回 False —— 下单类失败必须如实上报"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        trader = MagicMock()
        trader.execute.return_value = False
        logger = SignalLogger(storage=storage, direct_trader=trader)

        result = logger.log_signal(self._make_signal())

        assert result is False
        trader.execute.assert_called_once()

    def test_direct_trader_exception_does_not_propagate(self, tmp_path):
        """直连下单抛异常时不应打断策略主循环，返回 False"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        trader = MagicMock()
        trader.execute.side_effect = RuntimeError("connection lost")
        logger = SignalLogger(storage=storage, direct_trader=trader)

        # 不应抛出
        result = logger.log_signal(self._make_signal())

        assert result is False

    def test_log_cta_signal_no_trader_returns_true(self, tmp_path):
        """log_cta_signal 未配置 direct_trader 时恒返回 True"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        logger = SignalLogger(storage=storage)

        assert logger.log_cta_signal(self._make_signal()) is True

    def test_log_cta_signal_trader_failure_returns_false(self, tmp_path):
        """log_cta_signal 直连下单失败时返回 False"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        trader = MagicMock()
        trader.execute.return_value = False
        logger = SignalLogger(storage=storage, direct_trader=trader)

        assert logger.log_cta_signal(self._make_signal()) is False
