#!/usr/bin/env python3
"""测试信号存储目录结构使用完整策略实例名

验证：
1. SignalCsvWriter 使用完整策略名（如 ICT_1D_3_BNBUSDT_LIVE）作为目录
2. engine._log_signal_unified 传入完整策略名而非基础名
"""

import csv
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV, SignalCsvWriter


class TestSignalDirectoryUsesFullStrategyName:
    """测试信号目录使用完整策略实例名"""

    def test_csv_writer_uses_full_strategy_name_as_directory(self):
        """SignalCsvWriter 应使用完整策略名作为子目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = SignalCsvWriter(base_dir=tmpdir)

            signal = Signal(
                signal_id="test-001",
                strategy_id="ICT_1D_3_BNBUSDT_LIVE",
                signal_type=SignalType.BUY,
                symbol="BNBUSDT",
                price=580.0,
                strength=0.8,
                direction="long",
                timestamp=datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc),
            )

            writer.write_signal(
                signal=signal,
                strategy_name="ICT_1D_3_BNBUSDT_LIVE",  # 完整策略名
                strategy_version="v3",
                interval="1d",
                trading_mode="live",
            )

            # 验证目录结构
            expected_dir = Path(tmpdir) / "ICT_1D_3_BNBUSDT_LIVE"
            assert expected_dir.exists(), f"目录 {expected_dir} 应存在"

            # 验证文件路径
            expected_file = expected_dir / "20260624.csv"
            assert expected_file.exists(), f"文件 {expected_file} 应存在"

            # 验证内容
            with open(expected_file, newline="") as f:
                reader = csv.DictReader(f)
                row = list(reader)[0]
                assert row["strategy_name"] == "ICT_1D_3_BNBUSDT_LIVE"
                assert row["symbol"] == "BNBUSDT"
                assert row["trading_mode"] == "live"

    def test_different_strategy_instances_have_separate_directories(self):
        """不同策略实例的信号应存储在不同目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = SignalCsvWriter(base_dir=tmpdir)

            # 策略实例 1: ICT_1D_3_NEARUSDT_LIVE
            signal1 = Signal(
                signal_id="test-001",
                strategy_id="ICT_1D_3_NEARUSDT_LIVE",
                signal_type=SignalType.BUY,
                symbol="NEARUSDT",
                price=2.5,
                strength=0.8,
                direction="long",
                timestamp=datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc),
            )

            # 策略实例 2: ICT_1D_3_BNBUSDT_LIVE
            signal2 = Signal(
                signal_id="test-002",
                strategy_id="ICT_1D_3_BNBUSDT_LIVE",
                signal_type=SignalType.BUY,
                symbol="BNBUSDT",
                price=580.0,
                strength=0.7,
                direction="long",
                timestamp=datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc),
            )

            writer.write_signal(
                signal=signal1,
                strategy_name="ICT_1D_3_NEARUSDT_LIVE",
                strategy_version="v3",
                interval="1d",
                trading_mode="live",
            )

            writer.write_signal(
                signal=signal2,
                strategy_name="ICT_1D_3_BNBUSDT_LIVE",
                strategy_version="v3",
                interval="1d",
                trading_mode="live",
            )

            # 验证两个独立目录
            dir1 = Path(tmpdir) / "ICT_1D_3_NEARUSDT_LIVE"
            dir2 = Path(tmpdir) / "ICT_1D_3_BNBUSDT_LIVE"
            assert dir1.exists(), "NEARUSDT 策略目录应存在"
            assert dir2.exists(), "BNBUSDT 策略目录应存在"

            # 验证各自文件
            file1 = dir1 / "20260624.csv"
            file2 = dir2 / "20260624.csv"
            assert file1.exists(), "NEARUSDT 信号文件应存在"
            assert file2.exists(), "BNBUSDT 信号文件应存在"

    def test_strategy_name_not_truncated_to_base_name(self):
        """strategy_name 不应被截断为基础名（如 'ICT'）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = SignalCsvWriter(base_dir=tmpdir)

            full_name = "OBVATR_4H_2_ETHUSDT_LIVE"
            signal = Signal(
                signal_id="test-001",
                strategy_id=full_name,
                signal_type=SignalType.BUY,
                symbol="ETHUSDT",
                price=1800.0,
                strength=0.8,
                direction="long",
                timestamp=datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc),
            )

            writer.write_signal(
                signal=signal,
                strategy_name=full_name,
                strategy_version="v2",
                interval="4h",
                trading_mode="live",
            )

            # 验证不是基础名目录
            base_dir = Path(tmpdir) / "OBVATR"
            assert not base_dir.exists(), f"不应创建基础名目录 {base_dir}"

            # 验证完整名目录
            full_dir = Path(tmpdir) / full_name
            assert full_dir.exists(), f"应创建完整名目录 {full_dir}"


class TestEnginePassesFullStrategyName:
    """测试 engine 传入完整策略名"""

    def test_engine_uses_signal_strategy_id_as_directory(self, tmp_path):
        """
        engine._log_signal_unified 应使用 signal.strategy_id 作为目录名

        当前 engine.py:329 将 strategy_full_name 截断为基础名：
            strategy_base_name = strategy_full_name.split('_')[0]

        应改为直接使用 strategy_full_name
        """
        from unittest.mock import MagicMock, patch
        from strategy_core.strategy_engine.engine import StrategyEngine

        # 创建真实的 csv_writer 以验证目录结构
        from strategy_core.signal_logging.csv_adapter import SignalCsvWriter
        csv_writer = SignalCsvWriter(base_dir=str(tmp_path))

        signal_logger = MagicMock()

        engine = StrategyEngine(
            strategies_dir=str(tmp_path),
            csv_writer=csv_writer,
            signal_logger=signal_logger,
        )

        # 创建 signal，strategy_id 是完整策略名
        signal = MagicMock()
        signal.signal_id = "sig-test-001"
        signal.strategy_id = "ICT_1D_3_NEARUSDT_LIVE"  # 完整策略名
        signal.signal_type = MagicMock()
        signal.signal_type.value = "buy"
        signal.symbol = "NEARUSDT"
        signal.price = 2.5
        signal.strength = 0.8
        signal.timestamp = datetime(2026, 6, 24, 12, 0, tzinfo=timezone.utc)
        signal.direction = "long"
        signal.metadata = {"reason": "test"}

        # 创建 entry
        entry = MagicMock()
        entry.config = {"version": "v3"}
        entry.strategy_id = "test_001"
        entry.strategy_name = "ICT_1D_3_NEARUSDT_LIVE"
        entry.instance = MagicMock()
        entry.instance._trading_mode = "live"

        params = {"user_id": 1, "strategy_type": "CTAFutureFactory"}

        # 调用 _log_signal_unified
        engine._log_signal_unified(signal, params, entry)

        # 验证 CSV 写入到完整策略名目录
        expected_dir = tmp_path / "ICT_1D_3_NEARUSDT_LIVE"
        assert expected_dir.exists(), (
            f"目录应为 ICT_1D_3_NEARUSDT_LIVE，"
            f"但实际目录为: {list(tmp_path.iterdir())}"
        )

        # 验证不是基础名目录
        base_dir = tmp_path / "ICT"
        assert not base_dir.exists(), (
            f"不应创建基础名目录 'ICT'，"
            f"当前 engine.py:336 截断了策略名"
        )