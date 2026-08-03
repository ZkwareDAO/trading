"""Tests for _calc_sync_days — 根据 start_date 计算需要同步的天数."""

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from backtest.run_backtest import _calc_sync_days


class TestCalcSyncDays:
    """_calc_sync_days 应根据 start_date 到今天的天数 + buffer 计算同步天数."""

    @patch("backtest.run_backtest.datetime")
    def test_start_date_60_days_ago(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 29)
        mock_dt.strptime = datetime.strptime
        result = _calc_sync_days("20260301")
        # 2026-03-01 到 2026-04-29 = 59 天, + buffer
        assert result >= 59

    @patch("backtest.run_backtest.datetime")
    def test_start_date_yesterday(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 29)
        mock_dt.strptime = datetime.strptime
        result = _calc_sync_days("20260428")
        assert result >= 1

    @patch("backtest.run_backtest.datetime")
    def test_start_date_one_year_ago(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 29)
        mock_dt.strptime = datetime.strptime
        result = _calc_sync_days("20250429")
        assert result >= 365

    @patch("backtest.run_backtest.datetime")
    def test_buffer_days_added(self, mock_dt):
        mock_dt.now.return_value = datetime(2026, 4, 29)
        mock_dt.strptime = datetime.strptime
        result = _calc_sync_days("20260401")
        # 28 天 + buffer(至少 5 天)
        assert result >= 33

    @patch("backtest.run_backtest.datetime")
    def test_minimum_30_days(self, mock_dt):
        """即使 start_date 很近，也应至少返回 30 天."""
        mock_dt.now.return_value = datetime(2026, 4, 29)
        mock_dt.strptime = datetime.strptime
        result = _calc_sync_days("20260429")
        assert result >= 30
