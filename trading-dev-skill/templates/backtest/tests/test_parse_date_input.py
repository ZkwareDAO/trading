"""Tests for date/timestamp parsing in run_backtest.py"""

from datetime import datetime, timezone


from backtest.run_backtest import parse_date_input


class TestParseDateInput:
    """Test parse_date_input function."""

    def test_parse_yyyymmdd_format(self):
        """应正确解析 YYYYMMDD 格式"""
        date_str, dt = parse_date_input("20260508")
        assert date_str == "20260508"
        assert dt == datetime(2026, 5, 8, tzinfo=timezone.utc)

    def test_parse_millisecond_timestamp(self):
        """应正确解析 13 位毫秒时间戳"""
        # 2026-05-08 12:00:00 UTC = 1778241600000 ms
        date_str, dt = parse_date_input("1778241600000")
        assert date_str == "20260508"
        assert dt == datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)

    def test_parse_second_timestamp(self):
        """应正确解析 10 位秒时间戳"""
        # 2026-05-08 12:00:00 UTC = 1778241600 s
        date_str, dt = parse_date_input("1778241600")
        assert date_str == "20260508"
        assert dt == datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)

    def test_parse_timestamp_with_fractional_hours(self):
        """应正确解析带小数小时的时间戳"""
        # 2026-05-08 14:30:00 UTC
        ts_ms = int(datetime(2026, 5, 8, 14, 30, 0, tzinfo=timezone.utc).timestamp() * 1000)
        date_str, dt = parse_date_input(str(ts_ms))
        assert dt.hour == 14
        assert dt.minute == 30

    def test_parse_preserves_timezone(self):
        """解析结果应为 UTC 时区"""
        _, dt = parse_date_input("20260508")
        assert dt.tzinfo == timezone.utc

        _, dt2 = parse_date_input("1778458800000")
        assert dt2.tzinfo == timezone.utc
