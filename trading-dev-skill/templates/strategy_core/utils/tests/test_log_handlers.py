"""Tests for DailyDirectoryFileHandler date_override feature."""

import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from strategy_core.utils.log_handlers import DailyDirectoryFileHandler


class TestDailyDirectoryFileHandlerDateOverride:
    """Test date_override parameter for backtest mode."""

    def test_default_uses_current_utc_date(self):
        """Default behavior: use current UTC date for directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = DailyDirectoryFileHandler(
                base_dir=tmpdir,
                filename="test_log",
            )

            # Get the log path
            log_path = Path(handler.baseFilename)

            # Verify directory is today's date in UTC
            today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            assert log_path.parent.name == today_utc
            assert log_path.name == "test_log.log"

            handler.close()

    def test_date_override_uses_specified_date(self):
        """Backtest mode: use date_override for directory naming."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = DailyDirectoryFileHandler(
                base_dir=tmpdir,
                filename="test_log",
                date_override="20260101",
            )

            # Get the log path
            log_path = Path(handler.baseFilename)

            # Verify directory uses override date
            assert log_path.parent.name == "2026-01-01"
            assert log_path.name == "test_log.log"

            handler.close()

    def test_date_override_various_formats(self):
        """Test various date_override formats."""
        test_cases = [
            ("20260101", "2026-01-01"),
            ("20251231", "2025-12-31"),
            ("20240229", "2024-02-29"),  # Leap year
        ]

        for override_date, expected_dir in test_cases:
            with tempfile.TemporaryDirectory() as tmpdir:
                handler = DailyDirectoryFileHandler(
                    base_dir=tmpdir,
                    filename="test_log",
                    date_override=override_date,
                )

                log_path = Path(handler.baseFilename)
                assert log_path.parent.name == expected_dir, \
                    f"Expected {expected_dir} for {override_date}, got {log_path.parent.name}"

                handler.close()

    def test_date_override_creates_directory_if_not_exists(self):
        """Ensure directory is created when using date_override."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_dir = Path(tmpdir)

            handler = DailyDirectoryFileHandler(
                base_dir=str(base_dir),
                filename="test_log",
                date_override="20260615",
            )

            # Directory should exist
            expected_dir = base_dir / "2026-06-15"
            assert expected_dir.exists()
            assert expected_dir.is_dir()

            handler.close()

    def test_log_writes_to_override_directory(self):
        """Verify log records are written to the override directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = DailyDirectoryFileHandler(
                base_dir=tmpdir,
                filename="test_log",
                date_override="20260331",
            )

            # Create a logger and write a record
            logger = logging.getLogger("test_logger")
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)
            logger.info("Test message for backtest")

            handler.flush()

            # Verify file exists and contains the message
            log_path = Path(handler.baseFilename)
            assert log_path.exists()

            content = log_path.read_text()
            assert "Test message for backtest" in content

            handler.close()

    def test_emit_does_not_change_date_with_override(self):
        """With date_override, emit() should not change directory on date rollover."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = DailyDirectoryFileHandler(
                base_dir=tmpdir,
                filename="test_log",
                date_override="20260101",
            )

            initial_path = handler.baseFilename

            # Simulate emit (which normally checks date change)
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="", lineno=1,
                msg="Test", args=(), exc_info=None,
            )
            handler.emit(record)

            # Path should remain the same (no date rollover check)
            assert handler.baseFilename == initial_path

            handler.close()

    def test_none_date_override_uses_current_date(self):
        """None for date_override should behave like default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            handler = DailyDirectoryFileHandler(
                base_dir=tmpdir,
                filename="test_log",
                date_override=None,
            )

            log_path = Path(handler.baseFilename)
            today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            assert log_path.parent.name == today_utc

            handler.close()