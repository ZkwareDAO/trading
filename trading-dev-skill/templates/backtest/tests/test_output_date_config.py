"""测试 use_today_as_output_date 配置."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from backtest.backtest_reporter import BacktestReporter


class TestUseTodayAsOutputDate:
    """测试输出目录日期配置."""

    def test_output_dir_uses_backtest_date_when_config_false(self, tmp_path: Path):
        """use_today_as_output_date=False 时，使用 backtest_date 参数."""
        reporter = BacktestReporter(output_dir=str(tmp_path))

        # 使用固定的回测结束日期
        backtest_date = "20260701"
        run_dir = reporter.create_run_dir(
            strategy_name="test_strategy",
            symbol="BTCUSDT",
            backtest_date=backtest_date
        )

        # 验证目录包含 backtest_date
        assert backtest_date in str(run_dir)
        assert "20260701" in str(run_dir)

    def test_output_dir_uses_today_when_backtest_date_is_none(self, tmp_path: Path):
        """backtest_date=None 时，使用当天日期（UTC）."""
        reporter = BacktestReporter(output_dir=str(tmp_path))

        # 不传 backtest_date
        run_dir = reporter.create_run_dir(
            strategy_name="test_strategy",
            symbol="BTCUSDT",
            backtest_date=None
        )

        # 验证目录包含今天的日期
        today = datetime.now(timezone.utc).strftime("%Y%m%d")
        assert today in str(run_dir)

    def test_output_dir_structure(self, tmp_path: Path):
        """验证输出目录结构: {strategy}/{date}/{time}/{symbol}/"""
        reporter = BacktestReporter(output_dir=str(tmp_path))

        run_dir = reporter.create_run_dir(
            strategy_name="cta_ict_v5",
            symbol="ETHUSDT",
            backtest_date="20260715"
        )

        # 验证目录结构
        # 路径应包含: cta_ict_v5/20260715/{HHMMSS}/ETHUSDT
        parts = run_dir.parts
        assert "cta_ict_v5" in parts
        assert "20260715" in parts
        assert "ETHUSDT" in parts

        # 时间目录应该是 6 位数字
        time_dir = run_dir.parent.name
        assert len(time_dir) == 6
        assert time_dir.isdigit()
