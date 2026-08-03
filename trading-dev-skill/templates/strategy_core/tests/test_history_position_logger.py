#!/usr/bin/env python3
"""历史仓位记录器测试"""

import csv
import pytest
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator
import tempfile

from strategy_core.history_position_logger import HistoryPositionLogger


@pytest.fixture
def temp_base_path() -> Generator[Path, None, None]:
    """临时目录 fixture"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def logger(temp_base_path: Path) -> HistoryPositionLogger:
    """历史仓位记录器 fixture"""
    return HistoryPositionLogger(base_path=temp_base_path)


class TestHistoryPositionLogger:
    """历史仓位记录器测试"""

    def test_log_creates_csv_file(self, logger: HistoryPositionLogger, temp_base_path: Path):
        """记录平仓时创建 CSV 文件"""
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
            exit_reason="移动止盈",
            is_stop_loss=False,
        )

        # 验证文件存在
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filepath = temp_base_path / "test_strategy" / f"{date_str}.csv"
        assert filepath.exists(), f"CSV 文件应存在: {filepath}"

    def test_calculates_pnl_correctly_for_long(self, logger: HistoryPositionLogger, temp_base_path: Path):
        """做多时正确计算盈亏"""
        logger.log_position_exit(
            strategy_name="test",
            symbol="BTCUSDT",
            position_id="test_long",
            position_type="long",
            entry_price=100.0,
            exit_price=110.0,
            entry_time=None,
            exit_time=None,
            entry_timestamp=None,
            exit_timestamp=0,
            peak_price=0,
            stop_price=0,
            exit_reason="",
            is_stop_loss=False,
        )

        # 读取验证
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filepath = temp_base_path / "test" / f"{date_str}.csv"
        with open(filepath, newline="") as f:
            reader = csv.DictReader(f)
            row = list(reader)[0]
            assert float(row["price_diff"]) == 10.0, "做多盈亏 = exit - entry"
            assert float(row["pnl_pct"]) == 10.0, "盈亏百分比 = price_diff / entry * 100"

    def test_calculates_pnl_correctly_for_short(self, logger: HistoryPositionLogger, temp_base_path: Path):
        """做空时正确计算盈亏"""
        logger.log_position_exit(
            strategy_name="test",
            symbol="BTCUSDT",
            position_id="test_short",
            position_type="short",
            entry_price=100.0,
            exit_price=90.0,
            entry_time=None,
            exit_time=None,
            entry_timestamp=None,
            exit_timestamp=0,
            peak_price=0,
            stop_price=0,
            exit_reason="",
            is_stop_loss=False,
        )

        # 读取验证
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filepath = temp_base_path / "test" / f"{date_str}.csv"
        with open(filepath, newline="") as f:
            reader = csv.DictReader(f)
            row = list(reader)[0]
            assert float(row["price_diff"]) == 10.0, "做空盈亏 = entry - exit"
            assert float(row["pnl_pct"]) == 10.0

    def test_appends_to_existing_file(self, logger: HistoryPositionLogger, temp_base_path: Path):
        """追加到已有文件"""
        # 第一次记录
        logger.log_position_exit(
            strategy_name="test",
            symbol="BTCUSDT",
            position_id="pos_1",
            position_type="long",
            entry_price=100.0,
            exit_price=110.0,
            entry_time=None,
            exit_time=None,
            entry_timestamp=None,
            exit_timestamp=0,
            peak_price=0,
            stop_price=0,
            exit_reason="止盈",
            is_stop_loss=False,
        )

        # 第二次记录
        logger.log_position_exit(
            strategy_name="test",
            symbol="ETHUSDT",
            position_id="pos_2",
            position_type="short",
            entry_price=200.0,
            exit_price=190.0,
            entry_time=None,
            exit_time=None,
            entry_timestamp=None,
            exit_timestamp=0,
            peak_price=0,
            stop_price=0,
            exit_reason="止损",
            is_stop_loss=True,
        )

        # 验证两行数据
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filepath = temp_base_path / "test" / f"{date_str}.csv"
        with open(filepath, newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 2, "应有两条记录"
            assert rows[0]["position_id"] == "pos_1"
            assert rows[1]["position_id"] == "pos_2"

    def test_calculates_duration_seconds(self, logger: HistoryPositionLogger, temp_base_path: Path):
        """正确计算持仓时长"""
        logger.log_position_exit(
            strategy_name="test",
            symbol="BTCUSDT",
            position_id="test_duration",
            position_type="long",
            entry_price=100.0,
            exit_price=110.0,
            entry_time=None,
            exit_time=None,
            entry_timestamp=1735725600,  # 2025-01-01 10:00:00
            exit_timestamp=1735732800,   # 2025-01-01 12:00:00
            peak_price=0,
            stop_price=0,
            exit_reason="",
            is_stop_loss=False,
        )

        # 验证持仓时长 = 2 小时 = 7200 秒
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filepath = temp_base_path / "test" / f"{date_str}.csv"
        with open(filepath, newline="") as f:
            reader = csv.DictReader(f)
            row = list(reader)[0]
            assert int(row["duration_seconds"]) == 7200

    def test_handles_zero_entry_price(self, logger: HistoryPositionLogger, temp_base_path: Path):
        """处理入场价格为 0 的情况"""
        logger.log_position_exit(
            strategy_name="test",
            symbol="BTCUSDT",
            position_id="test_zero",
            position_type="long",
            entry_price=0.0,
            exit_price=110.0,
            entry_time=None,
            exit_time=None,
            entry_timestamp=None,
            exit_timestamp=0,
            peak_price=0,
            stop_price=0,
            exit_reason="",
            is_stop_loss=False,
        )

        # 盈亏百分比应为 0（避免除零）
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filepath = temp_base_path / "test" / f"{date_str}.csv"
        with open(filepath, newline="") as f:
            reader = csv.DictReader(f)
            row = list(reader)[0]
            assert float(row["pnl_pct"]) == 0.0

    def test_csv_has_correct_headers(self, logger: HistoryPositionLogger, temp_base_path: Path):
        """CSV 文件包含正确的表头"""
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
            exit_reason="",
            is_stop_loss=False,
        )

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        filepath = temp_base_path / "test" / f"{date_str}.csv"
        with open(filepath, newline="") as f:
            reader = csv.DictReader(f)
            expected_fields = {
                "position_id", "strategy_name", "symbol", "position_type",
                "entry_price", "exit_price", "entry_time", "exit_time",
                "entry_timestamp", "exit_timestamp", "peak_price", "stop_price",
                "max_pnl_pct", "min_pnl_pct",
                "exit_reason", "is_stop_loss", "price_diff", "pnl_pct",
                "atr_at_entry", "trail_activated", "duration_seconds",
                "trading_mode",
            }
            assert set(reader.fieldnames) == expected_fields
