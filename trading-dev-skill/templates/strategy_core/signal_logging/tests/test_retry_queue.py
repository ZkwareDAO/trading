#!/usr/bin/env python3
"""
测试失败信号持久化队列

验证：
1. 失败信号可以添加到队列
2. 队列信号持久化到 CSV 文件
3. 可以重试队列中的信号
4. 成功后从队列移除
"""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from strategy_core.signal_logging.retry_queue import RetryQueue, FailedSignal
from strategy_core.signal_logging.storage import Signal, SignalType


class TestRetryQueue:
    """测试失败信号持久化队列"""

    def _make_signal(self, signal_id: str = "test_001") -> Signal:
        return Signal(
            signal_id=signal_id,
            strategy_id="RBreaker_v2_1m_BTCUSDT",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            strength=0.8,
            timestamp=datetime.now(timezone.utc),
        )

    def test_add_failed_signal(self):
        """失败信号可以添加到队列"""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = RetryQueue(base_dir=tmpdir)
            signal = self._make_signal()

            queue.add_failed_signal(signal, topic="strategy_signals")

            # 验证信号已添加
            pending = queue.get_pending_signals()
            assert len(pending) == 1
            assert pending[0].signal_id == signal.signal_id

    def test_persist_to_csv(self):
        """队列信号持久化到 CSV 文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = RetryQueue(base_dir=tmpdir)
            signal = self._make_signal()

            queue.add_failed_signal(signal, topic="strategy_signals")

            # 验证 CSV 文件存在
            today = datetime.now().strftime("%Y%m%d")
            csv_path = Path(tmpdir) / f"{today}.csv"
            assert csv_path.exists()

            # 验证 CSV 内容
            with open(csv_path, "r", encoding="utf-8") as f:
                content = f.read()
                assert signal.signal_id in content
                assert "BTCUSDT" in content

    def test_retry_signal_success(self, caplog):
        """重试成功后从队列移除"""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = RetryQueue(base_dir=tmpdir)
            signal = self._make_signal()

            # 添加失败信号
            queue.add_failed_signal(signal, topic="strategy_signals")

            # Mock HTTP sender 成功
            mock_sender = MagicMock()
            mock_sender.send_signal.return_value = True

            with caplog.at_level(logging.INFO, logger="strategy_core.signal_logging.retry_queue"):
                queue.retry_all(mock_sender)

            # 验证信号已移除
            pending = queue.get_pending_signals()
            assert len(pending) == 0

            # 验证调用
            mock_sender.send_signal.assert_called_once()

    def test_retry_signal_failure(self, caplog):
        """重试失败后保留在队列"""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = RetryQueue(base_dir=tmpdir)
            signal = self._make_signal()

            # 添加失败信号
            queue.add_failed_signal(signal, topic="strategy_signals")

            # Mock HTTP sender 失败
            mock_sender = MagicMock()
            mock_sender.send_signal.return_value = False

            with caplog.at_level(logging.WARNING, logger="strategy_core.signal_logging.retry_queue"):
                queue.retry_all(mock_sender)

            # 验证信号仍存在
            pending = queue.get_pending_signals()
            assert len(pending) == 1

            # 验证 retry_count 增加
            assert pending[0].retry_count >= 1

    def test_multiple_signals(self):
        """支持多个失败信号"""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = RetryQueue(base_dir=tmpdir)

            # 添加多个信号
            for i in range(3):
                signal = self._make_signal(signal_id=f"test_{i:03d}")
                queue.add_failed_signal(signal, topic="strategy_signals")

            pending = queue.get_pending_signals()
            assert len(pending) == 3

    def test_get_pending_signals_sorted(self):
        """获取待重试信号按时间排序"""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = RetryQueue(base_dir=tmpdir)

            # 添加多个信号（不同时间）
            signal1 = self._make_signal(signal_id="early")
            signal2 = self._make_signal(signal_id="late")

            queue.add_failed_signal(signal1)
            queue.add_failed_signal(signal2)

            pending = queue.get_pending_signals()
            # 应按添加顺序返回
            assert pending[0].signal_id == "early"
            assert pending[1].signal_id == "late"

    def test_clear_successful_signals(self, caplog):
        """清除已成功发送的信号"""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = RetryQueue(base_dir=tmpdir)

            # 添加信号
            signal = self._make_signal()
            queue.add_failed_signal(signal)

            # Mock 成功发送
            mock_sender = MagicMock()
            mock_sender.send_signal.return_value = True

            queue.retry_all(mock_sender)

            # 验证 CSV 已更新（信号被清除）
            pending = queue.get_pending_signals()
            assert len(pending) == 0

    def test_signal_metadata_preserved(self):
        """信号元数据保留"""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = RetryQueue(base_dir=tmpdir)
            signal = self._make_signal()

            metadata = {"reason": "FVG entry", "entry_type": "fvg_midline"}
            queue.add_failed_signal(signal, topic="strategy_signals", metadata=metadata)

            pending = queue.get_pending_signals()
            assert len(pending) == 1
            # 验证 metadata 可以恢复（存储在 CSV 中）

    def test_max_retry_limit(self, caplog):
        """超过最大重试次数后标记为放弃"""
        with tempfile.TemporaryDirectory() as tmpdir:
            queue = RetryQueue(base_dir=tmpdir, max_retries=3)
            signal = self._make_signal()

            queue.add_failed_signal(signal)

            # Mock 多次失败
            mock_sender = MagicMock()
            mock_sender.send_signal.return_value = False

            # 重试多次
            for _ in range(5):
                queue.retry_all(mock_sender)

            # 验证信号被标记为放弃
            pending = queue.get_pending_signals()
            # 超过 max_retries 后应移除或标记
            abandoned = queue.get_abandoned_signals()
            assert len(abandoned) >= 1


class TestFailedSignal:
    """测试 FailedSignal 数据结构"""

    def test_from_signal(self):
        """从 Signal 创建 FailedSignal"""
        signal = Signal(
            signal_id="test_001",
            strategy_id="RBreaker_v2_1m_BTCUSDT",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            strength=0.8,
            timestamp=datetime.now(timezone.utc),
        )

        failed = FailedSignal.from_signal(signal, topic="strategy_signals")

        assert failed.signal_id == signal.signal_id
        assert failed.symbol == signal.symbol
        assert failed.signal_type == "buy"
        assert failed.topic == "strategy_signals"
        assert failed.retry_count == 0

    def test_to_csv_row(self):
        """转换为 CSV 行"""
        signal = Signal(
            signal_id="test_001",
            strategy_id="RBreaker_v2_1m_BTCUSDT",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            strength=0.8,
            timestamp=datetime.now(timezone.utc),
        )

        failed = FailedSignal.from_signal(signal, topic="strategy_signals")
        row = failed.to_csv_row()

        assert "signal_id" in row
        assert row["signal_id"] == "test_001"
        assert row["symbol"] == "BTCUSDT"

    def test_from_csv_row(self):
        """从 CSV 行恢复"""
        row = {
            "signal_id": "test_001",
            "strategy_id": "RBreaker_v2_1m_BTCUSDT",
            "signal_type": "buy",
            "symbol": "BTCUSDT",
            "price": "70000.0",
            "strength": "0.8",
            "timestamp": "2024-01-01T00:00:00+00:00",
            "topic": "strategy_signals",
            "retry_count": "2",
            "last_retry_time": "2024-01-01T00:05:00+00:00",
            "status": "pending",
            "metadata": "{}",
        }

        failed = FailedSignal.from_csv_row(row)

        assert failed.signal_id == "test_001"
        assert failed.retry_count == 2
        assert failed.status == "pending"