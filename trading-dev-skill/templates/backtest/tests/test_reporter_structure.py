#!/usr/bin/env python3
"""
测试 BacktestReporter 目录结构

TDD: RED 阶段 - 先写测试
"""

import pytest
from pathlib import Path
from datetime import datetime, timezone

from backtest.backtest_reporter import BacktestReporter


class TestBacktestReporterDirectoryStructure:
    """测试目录结构 {strategy}/{date}/{time}/{symbol}/"""

    def test_output_dir_structure_date_time(self, tmp_path):
        """目录结构应为 {strategy}/{date}/{time}/{symbol}/"""
        reporter = BacktestReporter(output_dir=str(tmp_path))

        paths = reporter.generate(
            strategy_name="cta_rbreaker_v2",
            symbol="ETHUSDT",
            config={"data_dir": "./data"},
            accounts=[{"equity": 100000, "cash": 100000, "position_count": 0, "trade_count": 0}],
            daily_equity=[{"date": "2026-01-01", "equity": 100000, "cash": 100000}],
            trades=[],
            klines_processed=100,
            signals_processed=10,
            start_time=datetime(2026, 5, 22, 13, 0, 0),
            end_time=datetime(2026, 5, 22, 13, 56, 29),
        )

        # 验证目录结构包含日期、时间和 symbol 层级
        # 目录应为 {strategy}/{date}/{time}/{symbol}/
        equity_path = paths["equity"]
        # 检查父目录结构
        symbol_dir = equity_path.parent  # 应为 symbol 目录
        time_dir = symbol_dir.parent     # 应为时间目录
        date_dir = time_dir.parent       # 应为日期目录
        strategy_dir = date_dir.parent   # 应为策略目录

        assert symbol_dir.name == "ETHUSDT"
        assert time_dir.name.isdigit() and len(time_dir.name) == 6  # HHMMSS
        assert date_dir.name.isdigit() and len(date_dir.name) == 8  # YYYYMMDD
        assert strategy_dir.name == "cta_rbreaker_v2"

    def test_file_names_simplified(self, tmp_path):
        """文件名应简化为 backtest_*.csv"""
        reporter = BacktestReporter(output_dir=str(tmp_path))

        paths = reporter.generate(
            strategy_name="cta_rbreaker_v2",
            symbol="ETHUSDT",
            config={"data_dir": "./data"},
            accounts=[{"equity": 100000, "cash": 100000, "position_count": 0, "trade_count": 0}],
            daily_equity=[{"date": "2026-01-01", "equity": 100000, "cash": 100000}],
            trades=[],
            klines_processed=100,
            signals_processed=10,
            start_time=datetime(2026, 5, 22, 13, 0, 0),
            end_time=datetime(2026, 5, 22, 13, 56, 29),
        )

        # 验证文件名简化
        assert paths["equity"].name == "backtest_equity.csv"
        assert paths["trades"].name == "backtest_trades.csv"
        assert paths["result"].name == "backtest_result.json"
        assert paths["report"].name == "backtest_report.txt"

    def test_charts_directory_inside_run_dir(self, tmp_path):
        """charts 目录应在回测目录内"""
        reporter = BacktestReporter(output_dir=str(tmp_path))

        paths = reporter.generate(
            strategy_name="cta_rbreaker_v2",
            symbol="ETHUSDT",
            config={"data_dir": "./data"},
            accounts=[{"equity": 100000, "cash": 100000, "position_count": 0, "trade_count": 0}],
            daily_equity=[{"date": "2026-01-01", "equity": 100000, "cash": 100000}],
            trades=[],
            klines_processed=100,
            signals_processed=10,
            start_time=datetime(2026, 5, 22, 13, 0, 0),
            end_time=datetime(2026, 5, 22, 13, 56, 29),
        )

        # 验证 charts 目录位置
        equity_path = paths["equity"]
        run_dir = equity_path.parent  # 时间目录即为回测目录
        charts_dir = run_dir / "charts"
        assert charts_dir.exists()

    def test_analysis_report_inside_run_dir(self, tmp_path):
        """分析报告应在回测目录内"""
        reporter = BacktestReporter(output_dir=str(tmp_path))

        paths = reporter.generate(
            strategy_name="cta_rbreaker_v2",
            symbol="ETHUSDT",
            config={"data_dir": "./data"},
            accounts=[{"equity": 100000, "cash": 100000, "position_count": 0, "trade_count": 0}],
            daily_equity=[{"date": "2026-01-01", "equity": 100000, "cash": 100000}],
            trades=[],
            klines_processed=100,
            signals_processed=10,
            start_time=datetime(2026, 5, 22, 13, 0, 0),
            end_time=datetime(2026, 5, 22, 13, 56, 29),
        )

        # 验证分析报告位置
        if "analysis_report" in paths:
            equity_path = paths["equity"]
            run_dir = equity_path.parent
            assert paths["analysis_report"].parent == run_dir


class TestBacktestReporterSymbolDirectory:
    """测试 {strategy}/{date}/{time}/{symbol}/ 目录结构"""

    def test_create_run_dir_with_symbol(self, tmp_path):
        """create_run_dir 应创建 {strategy}/{date}/{time}/{symbol}/ 目录"""
        reporter = BacktestReporter(output_dir=str(tmp_path))
        run_dir = reporter.create_run_dir("cta_rbreaker_v2", symbol="ETHUSDT")

        # 验证目录结构: {strategy}/{date}/{time}/{symbol}/
        assert run_dir.name == "ETHUSDT"
        assert run_dir.parent.name.isdigit() and len(run_dir.parent.name) == 6  # HHMMSS
        assert run_dir.parent.parent.name.isdigit() and len(run_dir.parent.parent.name) == 8  # YYYYMMDD
        assert run_dir.parent.parent.parent.name == "cta_rbreaker_v2"

    def test_generate_uses_existing_run_dir(self, tmp_path):
        """generate 应复用 create_run_dir 创建的目录"""
        reporter = BacktestReporter(output_dir=str(tmp_path))

        # 先创建目录
        run_dir = reporter.create_run_dir("cta_rbreaker_v2", symbol="ETHUSDT")

        # generate 应复用该目录
        paths = reporter.generate(
            strategy_name="cta_rbreaker_v2",
            symbol="ETHUSDT",
            config={"data_dir": "./data"},
            accounts=[{"equity": 100000, "cash": 100000, "position_count": 0, "trade_count": 0}],
            daily_equity=[{"date": "2026-01-01", "equity": 100000, "cash": 100000}],
            trades=[],
            klines_processed=100,
            signals_processed=10,
            start_time=datetime(2026, 5, 22, 13, 0, 0),
            end_time=datetime(2026, 5, 22, 13, 56, 29),
        )

        # 所有文件应在 run_dir 内
        assert paths["equity"].parent == run_dir
        assert paths["trades"].parent == run_dir

    def test_directory_structure_with_symbol(self, tmp_path):
        """完整目录结构应为 {strategy}/{date}/{time}/{symbol}/"""
        reporter = BacktestReporter(output_dir=str(tmp_path))

        paths = reporter.generate(
            strategy_name="cta_rbreaker_v2",
            symbol="ETHUSDT",
            config={"data_dir": "./data"},
            accounts=[{"equity": 100000, "cash": 100000, "position_count": 0, "trade_count": 0}],
            daily_equity=[{"date": "2026-01-01", "equity": 100000, "cash": 100000}],
            trades=[],
            klines_processed=100,
            signals_processed=10,
            start_time=datetime(2026, 5, 22, 13, 0, 0),
            end_time=datetime(2026, 5, 22, 13, 56, 29),
        )

        equity_path = paths["equity"]
        symbol_dir = equity_path.parent
        time_dir = symbol_dir.parent
        date_dir = time_dir.parent
        strategy_dir = date_dir.parent

        assert symbol_dir.name == "ETHUSDT"
        assert time_dir.name.isdigit() and len(time_dir.name) == 6
        assert date_dir.name.isdigit() and len(date_dir.name) == 8
        assert strategy_dir.name == "cta_rbreaker_v2"


class TestBacktestReporterBacktestDate:
    """测试 backtest_date 参数"""

    def test_create_run_dir_with_backtest_date(self, tmp_path):
        """指定 backtest_date 时应使用该日期作为目录名"""
        reporter = BacktestReporter(output_dir=str(tmp_path))
        run_dir = reporter.create_run_dir(
            "cta_rbreaker_v2",
            symbol="BTCUSDT",
            backtest_date="20260615",
        )

        # 验证日期目录为指定的 backtest_date
        date_dir = run_dir.parent.parent  # {strategy}/{date}/{time}/{symbol}/
        assert date_dir.name == "20260615"

    def test_create_run_dir_without_backtest_date_uses_utc_today(self, tmp_path):
        """不指定 backtest_date 时应使用 UTC 当前日期"""
        reporter = BacktestReporter(output_dir=str(tmp_path))
        run_dir = reporter.create_run_dir("cta_rbreaker_v2", symbol="BTCUSDT")

        today_utc = datetime.now(timezone.utc).strftime("%Y%m%d")
        date_dir = run_dir.parent.parent
        assert date_dir.name == today_utc

    def test_create_run_dir_backtest_date_different_from_today(self, tmp_path):
        """回测历史日期时目录应为历史日期，而非当前日期"""
        reporter = BacktestReporter(output_dir=str(tmp_path))

        # 模拟回测 2026-06-15 的数据
        run_dir = reporter.create_run_dir(
            "cta_ict_v3",
            symbol="ETHUSDT",
            backtest_date="20260615",
        )

        # 验证目录路径包含正确的日期
        assert "20260615" in str(run_dir)
        date_dir = run_dir.parent.parent
        assert date_dir.name == "20260615"