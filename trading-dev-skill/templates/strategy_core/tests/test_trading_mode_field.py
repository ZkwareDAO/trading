#!/usr/bin/env python3
"""测试 trading_mode 字段功能

覆盖三个存储位置：
1. PositionPersistence.save_on_entry() - 当前仓位 JSON
2. HistoryPositionLogger.log_position_exit() - 历史仓位 CSV
3. CtaSignalCSV - 信号 CSV/JSON
"""

import csv
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from strategy_core.position_persistence import PositionPersistence
from strategy_core.history_position_logger import HistoryPositionLogger
from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV, SignalCsvWriter


class TestPositionPersistenceTradingMode:
    """测试 PositionPersistence 的 trading_mode 字段"""

    def test_save_on_entry_includes_trading_mode_live(self, tmp_path: Path):
        """开仓持久化应包含 trading_mode = live"""
        persistence = PositionPersistence(base_path=tmp_path)

        persistence.save_on_entry(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_1716028200",
            state={"position": "long", "entry_price": 31000.0},
            trading_mode="live",
        )

        saved = persistence.load("test_strategy")
        assert saved is not None
        assert saved["trading_mode"] == "live"

    def test_save_on_entry_includes_trading_mode_paper_trading(self, tmp_path: Path):
        """开仓持久化应包含 trading_mode = paper_trading"""
        persistence = PositionPersistence(base_path=tmp_path)

        persistence.save_on_entry(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_1716028200",
            state={"position": "long", "entry_price": 31000.0},
            trading_mode="paper_trading",
        )

        saved = persistence.load("test_strategy")
        assert saved is not None
        assert saved["trading_mode"] == "paper_trading"

    def test_save_on_entry_defaults_to_live(self, tmp_path: Path):
        """未传入 trading_mode 时默认为 live"""
        persistence = PositionPersistence(base_path=tmp_path)

        persistence.save_on_entry(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_1716028200",
            state={"position": "long", "entry_price": 31000.0},
        )

        saved = persistence.load("test_strategy")
        assert saved is not None
        assert saved["trading_mode"] == "live"

    def test_save_includes_trading_mode(self, tmp_path: Path):
        """save 方法应包含 trading_mode"""
        persistence = PositionPersistence(base_path=tmp_path)

        persistence.save(
            strategy_name="test_strategy",
            state={"position": "long", "entry_price": 31000.0},
            trading_mode="paper_trading",
        )

        saved = persistence.load("test_strategy")
        assert saved is not None
        assert saved["trading_mode"] == "paper_trading"


class TestHistoryPositionLoggerTradingMode:
    """测试 HistoryPositionLogger 的 trading_mode 字段"""

    @pytest.fixture
    def temp_base_path(self):
        """临时目录 fixture"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def logger(self, temp_base_path):
        """历史仓位记录器 fixture"""
        return HistoryPositionLogger(base_path=temp_base_path)

    def test_log_includes_trading_mode_live(self, logger, temp_base_path):
        """历史仓位 CSV 应包含 trading_mode = live"""
        logger.log_position_exit(
            strategy_name="test_strategy",
            symbol="BTCUSDT",
            position_id="test_123",
            position_type="long",
            entry_price=100.0,
            exit_price=110.0,
            entry_time=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            exit_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            entry_timestamp=1735725600,
            exit_timestamp=1735732800,
            peak_price=115.0,
            stop_price=95.0,
            trading_mode="live",
        )

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filepath = temp_base_path / "test_strategy" / f"{date_str}.csv"

        with open(filepath, newline="") as f:
            reader = csv.DictReader(f)
            row = list(reader)[0]
            assert row["trading_mode"] == "live"

    def test_log_includes_trading_mode_paper_trading(self, logger, temp_base_path):
        """历史仓位 CSV 应包含 trading_mode = paper_trading"""
        logger.log_position_exit(
            strategy_name="test_strategy",
            symbol="BTCUSDT",
            position_id="test_123",
            position_type="long",
            entry_price=100.0,
            exit_price=110.0,
            entry_time=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            exit_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            entry_timestamp=1735725600,
            exit_timestamp=1735732800,
            peak_price=115.0,
            stop_price=95.0,
            trading_mode="paper_trading",
        )

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filepath = temp_base_path / "test_strategy" / f"{date_str}.csv"

        with open(filepath, newline="") as f:
            reader = csv.DictReader(f)
            row = list(reader)[0]
            assert row["trading_mode"] == "paper_trading"

    def test_log_defaults_to_live(self, logger, temp_base_path):
        """未传入 trading_mode 时默认为 live"""
        logger.log_position_exit(
            strategy_name="test_strategy",
            symbol="BTCUSDT",
            position_id="test_123",
            position_type="long",
            entry_price=100.0,
            exit_price=110.0,
            entry_time=None,
            exit_time=None,
            entry_timestamp=None,
            exit_timestamp=0,
            peak_price=0,
            stop_price=0,
        )

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filepath = temp_base_path / "test_strategy" / f"{date_str}.csv"

        with open(filepath, newline="") as f:
            reader = csv.DictReader(f)
            row = list(reader)[0]
            assert row["trading_mode"] == "live"

    def test_csv_has_trading_mode_header(self, logger, temp_base_path):
        """CSV 文件表头应包含 trading_mode"""
        logger.log_position_exit(
            strategy_name="test",
            symbol="BTCUSDT",
            position_id="test_headers",
            position_type="long",
            entry_price=100.0,
            exit_price=110.0,
            entry_time=None,
            exit_time=None,
            entry_timestamp=None,
            exit_timestamp=0,
            peak_price=0,
            stop_price=0,
        )

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filepath = temp_base_path / "test" / f"{date_str}.csv"

        with open(filepath, newline="") as f:
            reader = csv.DictReader(f)
            assert "trading_mode" in reader.fieldnames


class TestCtaSignalCSVTradingMode:
    """测试 CtaSignalCSV 的 trading_mode 字段"""

    def test_cta_signal_has_trading_mode_field(self):
        """CtaSignalCSV 应有 trading_mode 字段"""
        signal = CtaSignalCSV(
            symbol="BTCUSDT",
            strategy_name="RBREAKER_15M_3_BTCUSDT",
            trading_mode="live",
        )
        assert signal.trading_mode == "live"

    def test_cta_signal_defaults_to_live(self):
        """CtaSignalCSV 默认 trading_mode 为 live"""
        signal = CtaSignalCSV(symbol="BTCUSDT", strategy_name="test")
        assert signal.trading_mode == "live"

    def test_to_csv_row_includes_trading_mode(self):
        """to_csv_row 应包含 trading_mode"""
        signal = CtaSignalCSV(
            symbol="BTCUSDT",
            strategy_name="RBREAKER_15M_3_BTCUSDT",
            trading_mode="paper_trading",
        )
        row = signal.to_csv_row()
        assert row["trading_mode"] == "paper_trading"

    def test_to_json_includes_trading_mode(self):
        """to_json 应在 strategy 字典中包含 trading_mode"""
        signal = CtaSignalCSV(
            symbol="BTCUSDT",
            strategy_name="RBREAKER_15M_3_BTCUSDT",
            trading_mode="paper_trading",
        )
        json_data = signal.to_json()
        assert json_data["strategy"]["trading_mode"] == "paper_trading"

    def test_from_signal_accepts_trading_mode(self):
        """from_signal 方法应接受 trading_mode 参数"""
        signal = Signal(
            signal_id="test-001",
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=63000.0,
            strength=0.8,
            direction="long",
            timestamp=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
        )

        cta_signal = CtaSignalCSV.from_signal(
            signal=signal,
            strategy_name="RBREAKER_15M_3_BTCUSDT",
            trading_mode="paper_trading",
        )

        assert cta_signal.trading_mode == "paper_trading"


class TestSignalCsvWriterTradingMode:
    """测试 SignalCsvWriter 的 trading_mode 写入"""

    def test_fieldnames_includes_trading_mode(self):
        """FIELDNAMES 应包含 trading_mode"""
        assert "trading_mode" in SignalCsvWriter.FIELDNAMES

    def test_write_signal_includes_trading_mode(self):
        """write_signal 应写入 trading_mode"""
        with tempfile.TemporaryDirectory() as tmpdir:
            writer = SignalCsvWriter(base_dir=tmpdir)

            signal = Signal(
                signal_id="test-001",
                strategy_id="test_strategy",
                signal_type=SignalType.BUY,
                symbol="BTCUSDT",
                price=63000.0,
                strength=0.8,
                direction="long",
                timestamp=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
            )

            writer.write_signal(
                signal=signal,
                strategy_name="RBREAKER_15M_3_BTCUSDT",
                strategy_version="v3",
                interval="15m",
                trading_mode="paper_trading",
            )

            # 读取验证
            date_str = "20260612"
            filepath = Path(tmpdir) / "RBREAKER_15M_3_BTCUSDT" / f"{date_str}.csv"

            with open(filepath, newline="") as f:
                reader = csv.DictReader(f)
                row = list(reader)[0]
                assert row["trading_mode"] == "paper_trading"