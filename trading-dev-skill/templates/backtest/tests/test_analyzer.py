#!/usr/bin/env python3
"""
测试回测分析器

TDD: RED 阶段 - 先写测试
"""

import math
import warnings

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


class TestMaxDrawdownUsesRollingPeak:
    """最大回撤必须用滚动峰值，而非全局 max-min

    全局 max-min 会把「靠后的峰值」和「更早的谷值」配对，报出一个
    从未真实发生过的回撤。只有当谷值出现在峰值**之后**才构成回撤。
    """

    def _analyzer_for(self, tmp_path, equity_values):
        dates = pd.date_range("2026-01-01", periods=len(equity_values), freq="D")
        equity_df = pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "equity": equity_values,
            "cash": equity_values,
        })
        equity_csv = tmp_path / "eq.csv"
        equity_df.to_csv(equity_csv, index=False)
        analyzer = BacktestAnalyzer(equity_csv=str(equity_csv), symbol="ETHUSDT")
        analyzer.load_equity_data()
        return analyzer

    def test_early_dip_then_new_high_is_not_a_drawdown_from_the_later_peak(
        self, tmp_path
    ):
        """先跌到谷底、随后创新高：回撤只能按「早期峰→谷」计算

        曲线: 100000 → 80000 → 200000
        - 真实最大回撤 = (100000-80000)/100000 = 20%
          （谷值 80000 出现在 200000 之前，与它无关）
        - 全局 max-min 会算成 (200000-80000)/200000 = 60% —— 从未发生
        """
        analyzer = self._analyzer_for(tmp_path, [100000, 80000, 200000])
        metrics = analyzer.calculate_metrics()

        assert metrics["max_drawdown"] == pytest.approx(20.0, abs=0.01), (
            f"最大回撤应为 20%（早期峰 100000 → 谷 80000），"
            f"实得 {metrics['max_drawdown']}%。若为 60% 说明用了全局 "
            f"max-min，把末期峰值 200000 与它之前的谷值错误配对。"
        )

    def test_monotonically_rising_equity_has_zero_drawdown(self, tmp_path):
        """单调上涨的曲线，最大回撤必须为 0"""
        analyzer = self._analyzer_for(tmp_path, [100000, 110000, 120000, 130000])
        metrics = analyzer.calculate_metrics()

        assert metrics["max_drawdown"] == pytest.approx(0.0, abs=0.01), (
            f"单调上涨却报出 {metrics['max_drawdown']}% 回撤"
        )

    def test_trough_date_must_not_precede_peak_date(self, tmp_path):
        """谷值日期不能早于峰值日期（回撤的定义要求谷在峰之后）"""
        analyzer = self._analyzer_for(tmp_path, [100000, 80000, 200000])
        metrics = analyzer.calculate_metrics()

        assert metrics["trough_date"] >= metrics["peak_date"], (
            f"谷值日期 {metrics['trough_date']} 早于峰值日期 "
            f"{metrics['peak_date']} —— 这不构成回撤"
        )

    def test_deepest_of_multiple_drawdowns_wins(self, tmp_path):
        """存在多段回撤时取最深的那一段

        曲线: 100 → 90 (回撤 10%) → 150 → 105 (回撤 30%) → 120
        最深应为第二段的 30%
        """
        analyzer = self._analyzer_for(
            tmp_path, [100000, 90000, 150000, 105000, 120000]
        )
        metrics = analyzer.calculate_metrics()

        assert metrics["max_drawdown"] == pytest.approx(30.0, abs=0.01), (
            f"应取最深回撤 30%（150000→105000），实得 "
            f"{metrics['max_drawdown']}%"
        )


class TestMaxDrawdownNonPositiveEquity:
    """权益 <= 0 时的回撤计算（除零守卫分支）

    滚动峰值 <= 0 时无法定义百分比回撤（分母为 0 或负），实现里用
    `if running_peak <= 0: continue` 跳过。爆仓归零、数据缺失填 0 等
    场景会走到这里，若守卫失效会抛 ZeroDivisionError 或产出 inf/nan。
    """

    def _analyzer_for(self, tmp_path, equity_values):
        dates = pd.date_range("2026-01-01", periods=len(equity_values), freq="D")
        equity_df = pd.DataFrame({
            "date": dates.strftime("%Y-%m-%d"),
            "equity": equity_values,
            "cash": equity_values,
        })
        equity_csv = tmp_path / "eq.csv"
        equity_df.to_csv(equity_csv, index=False)
        analyzer = BacktestAnalyzer(equity_csv=str(equity_csv), symbol="ETHUSDT")
        analyzer.load_equity_data()
        return analyzer

    def test_all_zero_equity_yields_zero_drawdown(self, tmp_path):
        """全零权益：回撤为 0，且不得发生无效除法

        守卫 `running_peak <= 0: continue` 的作用不是改变结果（0/0 得 nan，
        而 nan 不满足 `> max_drawdown`，结果恰好仍是 0.0），而是**避免执行
        无效除法**。所以断言必须盯住 RuntimeWarning，否则移除守卫测试照样绿。
        """
        analyzer = self._analyzer_for(tmp_path, [0, 0, 0])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            metrics = analyzer.calculate_metrics()
        divide_warns = [
            str(w.message) for w in caught
            if issubclass(w.category, RuntimeWarning)
            and "divide" in str(w.message)
        ]

        dd = metrics["max_drawdown"]
        assert dd == pytest.approx(0.0, abs=0.01), f"全零权益回撤应为 0，实得 {dd}"
        assert math.isfinite(dd), f"回撤为非有限值 {dd} —— 除零守卫失效"
        assert not divide_warns, (
            f"回撤计算发生了无效除法：{divide_warns} —— "
            f"running_peak <= 0 守卫失效"
        )

    def test_zero_prefix_then_positive_equity(self, tmp_path):
        """权益从 0 起步后转正：0 段被跳过，只按正值段算回撤

        曲线: 0 → 0 → 100000 → 75000
        正值段峰 100000 → 谷 75000 = 25%
        """
        analyzer = self._analyzer_for(tmp_path, [0, 0, 100000, 75000])
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            metrics = analyzer.calculate_metrics()
        divide_warns = [
            str(w.message) for w in caught
            if issubclass(w.category, RuntimeWarning)
            and "divide" in str(w.message)
        ]

        assert metrics["max_drawdown"] == pytest.approx(25.0, abs=0.01), (
            f"应为 25%（100000→75000），实得 {metrics['max_drawdown']}%"
        )
        assert not divide_warns, (
            f"0 段未被守卫跳过，发生无效除法：{divide_warns}"
        )

    def test_negative_equity_does_not_crash(self, tmp_path):
        """负权益（穿仓）不得抛异常，且回撤保持有限值"""
        analyzer = self._analyzer_for(tmp_path, [-500, -1000, -200])
        metrics = analyzer.calculate_metrics()

        assert math.isfinite(metrics["max_drawdown"])
        # 峰谷索引须有默认值，否则 peak_date/trough_date 会 KeyError
        assert metrics["peak_date"] is not None
        assert metrics["trough_date"] is not None

    def test_single_row_equity_is_handled(self, tmp_path):
        """单行权益：循环体只跑一次，峰谷索引须落在同一点"""
        analyzer = self._analyzer_for(tmp_path, [100000])
        metrics = analyzer.calculate_metrics()

        assert metrics["max_drawdown"] == pytest.approx(0.0, abs=0.01)
        assert metrics["peak_date"] == metrics["trough_date"]

    def test_total_return_is_finite_when_initial_equity_is_zero(self, tmp_path):
        """初始权益为 0 时 total_return 不得为 nan/inf

        `(final - initial) / initial` 在 initial=0 时产出 inf 或 nan，
        会原样写进 Markdown 报告（"总收益率 | inf"）。回撤计算有
        `running_peak <= 0` 守卫，但 total_return 没有对应守卫。
        """
        analyzer = self._analyzer_for(tmp_path, [0, 0, 100000])
        metrics = analyzer.calculate_metrics()

        tr = metrics["total_return"]
        assert math.isfinite(tr), (
            f"initial=0 时 total_return={tr!r} 非有限值 —— 缺除零守卫，"
            f"该值会原样进入回测报告"
        )

    def test_total_return_is_finite_when_all_equity_zero(self, tmp_path):
        """全零权益时 total_return 应为 0 而非 nan"""
        analyzer = self._analyzer_for(tmp_path, [0, 0, 0])
        metrics = analyzer.calculate_metrics()

        tr = metrics["total_return"]
        assert math.isfinite(tr), f"total_return={tr!r} 非有限值"
        assert tr == pytest.approx(0.0, abs=0.01), (
            f"权益从 0 到 0，收益率应为 0，实得 {tr}"
        )


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