#!/usr/bin/env python3
"""
测试回测分析器

TDD: RED 阶段 - 先写测试
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import pandas as pd

from backtest.analyzer import BacktestAnalyzer


class TestBacktestAnalyzerInit:
    """测试 BacktestAnalyzer 初始化"""

    def test_init_with_equity_csv(self):
        """使用权益 CSV 文件初始化"""
        equity_csv = "backtest_output/test_equity.csv"
        analyzer = BacktestAnalyzer(equity_csv=equity_csv, symbol="ETHUSDT")
        assert analyzer.equity_csv == equity_csv
        assert analyzer.symbol == "ETHUSDT"

    def test_init_without_symbol_raises(self):
        """缺少 symbol 时抛出异常"""
        with pytest.raises((ValueError, TypeError)):
            BacktestAnalyzer(equity_csv="test.csv")


class TestLoadEquityData:
    """测试加载权益数据"""

    def test_load_equity_csv_success(self, tmp_path):
        """成功加载权益 CSV"""
        # 创建测试数据
        equity_df = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02"],
            "equity": [100000, 101000],
            "cash": [100000, 101000],
        })
        equity_csv = tmp_path / "test_equity.csv"
        equity_df.to_csv(equity_csv, index=False)

        analyzer = BacktestAnalyzer(equity_csv=str(equity_csv), symbol="ETHUSDT")
        df = analyzer.load_equity_data()

        assert len(df) == 2
        assert "equity" in df.columns
        assert df["equity"].iloc[0] == 100000

    def test_load_equity_csv_file_not_found(self):
        """文件不存在时抛出异常"""
        analyzer = BacktestAnalyzer(equity_csv="not_exist.csv", symbol="ETHUSDT")
        with pytest.raises(FileNotFoundError):
            analyzer.load_equity_data()


class TestLoadDailyKlines:
    """测试加载日线数据"""

    def test_load_daily_klines_success(self, tmp_path):
        """成功加载日线数据"""
        # 创建权益数据
        equity_df = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02"],
            "equity": [100000, 101000],
            "cash": [100000, 101000],
        })
        equity_csv = tmp_path / "test_equity.csv"
        equity_df.to_csv(equity_csv, index=False)

        # 创建测试数据目录结构: {data_dir}/1d/{symbol}_1d.csv
        klines_df = pd.DataFrame({
            "timestamp": ["2026-01-01 00:00:00+00:00", "2026-01-02 00:00:00+00:00"],
            "open": [2300, 2350],
            "high": [2400, 2450],
            "low": [2250, 2300],
            "close": [2350, 2400],
            "volume": [1000, 1100],
        })
        # 创建正确的目录结构
        klines_dir = tmp_path / "1d"
        klines_dir.mkdir()
        klines_csv = klines_dir / "ETHUSDT_1d.csv"
        klines_df.to_csv(klines_csv, index=False)

        analyzer = BacktestAnalyzer(equity_csv=str(equity_csv), symbol="ETHUSDT", data_dir=str(tmp_path))
        df = analyzer.load_daily_klines()

        assert df is not None
        assert len(df) == 2
        assert "close" in df.columns

    def test_load_daily_klines_not_found_returns_none(self, tmp_path):
        """日线数据不存在时返回 None"""
        # 创建权益数据
        equity_df = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02"],
            "equity": [100000, 101000],
            "cash": [100000, 101000],
        })
        equity_csv = tmp_path / "test_equity.csv"
        equity_df.to_csv(equity_csv, index=False)

        analyzer = BacktestAnalyzer(equity_csv=str(equity_csv), symbol="NOTEXIST", data_dir=str(tmp_path))
        df = analyzer.load_daily_klines()
        assert df is None


class TestCalculateMetrics:
    """测试计算指标"""

    def test_calculate_metrics_basic(self, tmp_path):
        """计算基本指标"""
        equity_df = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
            "equity": [100000, 105000, 103000],
            "cash": [100000, 105000, 103000],
        })
        equity_csv = tmp_path / "test_equity.csv"
        equity_df.to_csv(equity_csv, index=False)

        analyzer = BacktestAnalyzer(equity_csv=str(equity_csv), symbol="ETHUSDT")
        analyzer.load_equity_data()
        metrics = analyzer.calculate_metrics()

        assert "total_return" in metrics
        assert "max_drawdown" in metrics
        assert "peak_equity" in metrics
        assert "trough_equity" in metrics
        assert metrics["total_return"] == 3.0  # (103000 - 100000) / 100000 * 100


class TestGenerateCharts:
    """测试生成图表"""

    @patch("matplotlib.pyplot.savefig")
    def test_generate_charts_creates_files(self, mock_savefig, tmp_path):
        """生成图表文件"""
        equity_df = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02"],
            "equity": [100000, 105000],
            "cash": [100000, 105000],
        })
        equity_csv = tmp_path / "test_equity.csv"
        equity_df.to_csv(equity_csv, index=False)

        analyzer = BacktestAnalyzer(equity_csv=str(equity_csv), symbol="ETHUSDT")
        analyzer.load_equity_data()

        output_dir = tmp_path / "charts"
        output_dir.mkdir()
        analyzer.generate_charts(str(output_dir), prefix="backtest_test_ETHUSDT_20260101")

        # 验证 savefig 被调用
        assert mock_savefig.called


class TestGenerateReport:
    """测试生成报告"""

    def test_generate_report_creates_markdown(self, tmp_path):
        """生成 Markdown 报告"""
        equity_df = pd.DataFrame({
            "date": ["2026-01-01", "2026-01-02"],
            "equity": [100000, 105000],
            "cash": [100000, 105000],
        })
        equity_csv = tmp_path / "test_equity.csv"
        equity_df.to_csv(equity_csv, index=False)

        analyzer = BacktestAnalyzer(equity_csv=str(equity_csv), symbol="ETHUSDT")
        analyzer.load_equity_data()
        analyzer.calculate_metrics()

        output_dir = tmp_path
        report_path = analyzer.generate_report(str(output_dir), prefix="backtest_test_ETHUSDT_20260101")

        assert "backtest_test_ETHUSDT_20260101_analysis_report.md" in report_path
        assert Path(report_path).exists()

        # 检查报告内容
        content = Path(report_path).read_text()
        assert "# 回测分析报告" in content
        assert "ETHUSDT" in content