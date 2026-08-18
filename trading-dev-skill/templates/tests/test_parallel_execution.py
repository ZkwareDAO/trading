"""
测试并发安全性

验证 DataManager 和 SignalLogger 的并发安全
"""

import asyncio
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


class TestDataManagerConcurrency:
    """测试 DataManager 并发安全性"""

    @pytest.mark.asyncio
    async def test_get_klines_thread_safe(self):
        """测试 get_klines 的线程安全性"""
        from data_manager.manager import DataManager, DataManagerConfig

        config = DataManagerConfig(csv_dir="./data/klines", preload_1m_enabled=False)
        dm = DataManager(config)
        dm.connect()

        # 模拟并发访问
        async def concurrent_access(symbol: str):
            return dm.get_klines(symbol, "1m", limit=10)

        # 多个协程同时访问
        tasks = [
            concurrent_access("BTCUSDT"),
            concurrent_access("ETHUSDT"),
            concurrent_access("SOLUSDT"),
        ]

        # 不应抛出竞态条件错误
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 验证所有请求都成功
        errors = [r for r in results if isinstance(r, Exception)]
        assert len(errors) == 0, f"并发访问失败：{errors}"


class TestSignalLoggerConcurrency:
    """测试 SignalLogger 并发安全性"""

    @pytest.mark.asyncio
    async def test_log_signals_batch_thread_safe(self):
        """测试批量日志的线程安全性"""
        from strategy_core.signal_logging.logger import SignalLogger, SignalStorage
        from strategy_core.signal_logging.storage import Signal, SignalType

        storage = SignalStorage(base_dir="./data/test_signals")
        logger = SignalLogger(storage)

        # 创建多个信号
        signals = [
            Signal(
                signal_id=f"signal_{i}",
                strategy_id="test_strategy",
                signal_type=SignalType.BUY,
                symbol="BTCUSDT",
                price=50000.0,
                volume=1.0,
                strength=0.8,
                timestamp=datetime.now(timezone.utc)
            )
            for i in range(10)
        ]

        # 并发写入
        async def concurrent_log(signal):
            return logger.log_signal(signal)

        tasks = [concurrent_log(signal) for signal in signals]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 验证所有信号都成功写入
        errors = [r for r in results if isinstance(r, Exception)]
        assert len(errors) == 0, f"并发写入失败：{errors}"

        # 清理测试数据
        storage.clear("test_strategy")
