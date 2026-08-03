"""Tests for tf_equity feature in bt_strategy.py — TDD approach."""

import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest
import backtrader as bt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


class TestTfEquityFeature:
    """Test timeframe-based equity curve recording."""

    def _sample_csv_path(self) -> str:
        """Generate sample CSV file path."""
        csv_path = Path(__file__).parent / "sample_data.csv"
        if not csv_path.exists():
            csv_path.write_text(
                "datetime,open,high,low,close,volume\n"
                "2026-01-01 00:00:00,100,105,95,102,1000\n"
                "2026-01-01 00:01:00,102,108,100,106,1200\n"
                "2026-01-01 00:02:00,106,110,104,108,800\n"
            )
        return str(csv_path)

    def _make_mock_strategy(self):
        """创建模拟策略实例."""
        class MockStrategy:
            def __init__(self):
                self.on_start_called = False
                self.on_stop_called = False
                self.on_kline_calls = []

            def on_start(self):
                self.on_start_called = True

            def on_stop(self):
                self.on_stop_called = True

            def on_kline(self, kline):
                self.on_kline_calls.append(kline)
                return None  # No signal

            @property
            def strategy_name(self):
                return "MockStrategy"

        return MockStrategy()

    def _run_with_strategy(self, strategy_config=None):
        """Helper: run backtest with mock strategy and return strat instance."""
        from backtest.bt_strategy import BacktestBTStrategy

        cerebro = bt.Cerebro()
        data = bt.feeds.GenericCSVData(
            dataname=self._sample_csv_path(),
            dtformat="%Y-%m-%d %H:%M:%S",
            datetime=0, open=1, high=2, low=3, close=4, volume=5,
            openinterest=-1,
        )
        cerebro.adddata(data)
        cerebro.addstrategy(
            BacktestBTStrategy,
            cta_strategy=self._make_mock_strategy(),
            strategy_config=strategy_config,
        )
        results = cerebro.run()
        return results[0]

    def test_extract_min_timeframe_from_list(self):
        """_extract_min_timeframe should return smallest timeframe from list."""
        strat = self._run_with_strategy({"timeframes": ["4h", "1h", "1d"]})
        assert strat._tf_key == "1h", f"Expected '1h', got {strat._tf_key}"

    def test_extract_min_timeframe_from_string(self):
        """_extract_min_timeframe should handle string timeframe."""
        strat = self._run_with_strategy({"timeframes": "15m"})
        assert strat._tf_key == "15m", f"Expected '15m', got {strat._tf_key}"

    def test_extract_min_timeframe_empty_config(self):
        """_extract_min_timeframe should return None for empty config."""
        strat = self._run_with_strategy(None)
        assert strat._tf_key is None, f"Expected None, got {strat._tf_key}"

    def test_extract_min_timeframe_invalid_tf(self):
        """_extract_min_timeframe should ignore invalid timeframes."""
        strat = self._run_with_strategy({"timeframes": ["invalid", "1h"]})
        assert strat._tf_key == "1h", "Should filter out invalid timeframes"

    def test_get_tf_datetime_format_minute(self):
        """_get_tf_datetime_format returns correct format for minute TFs."""
        strat = self._run_with_strategy(None)
        assert strat._get_tf_datetime_format("1m") == "%Y-%m-%d %H:%M"
        assert strat._get_tf_datetime_format("15m") == "%Y-%m-%d %H:%M"
        assert strat._get_tf_datetime_format("30m") == "%Y-%m-%d %H:%M"

    def test_get_tf_datetime_format_hour(self):
        """_get_tf_datetime_format returns correct format for hour TFs."""
        strat = self._run_with_strategy(None)
        assert strat._get_tf_datetime_format("1h") == "%Y-%m-%d %H:00"
        assert strat._get_tf_datetime_format("4h") == "%Y-%m-%d %H:00"

    def test_get_tf_datetime_format_day(self):
        """_get_tf_datetime_format returns correct format for day TF."""
        strat = self._run_with_strategy(None)
        assert strat._get_tf_datetime_format("1d") == "%Y-%m-%d"

    def test_tf_equity_recorded_when_configured(self):
        """_tf_equity should be recorded when timeframe is configured."""
        strat = self._run_with_strategy({"timeframes": ["1m"]})

        tf_equity = strat.get_tf_equity()
        assert len(tf_equity) > 0, "Should record tf_equity when configured"
        assert "datetime" in tf_equity[0]
        assert "equity" in tf_equity[0]
        assert "cash" in tf_equity[0]

    def test_tf_equity_not_recorded_when_not_configured(self):
        """_tf_equity should be empty when no timeframe configured."""
        strat = self._run_with_strategy(None)
        tf_equity = strat.get_tf_equity()
        assert len(tf_equity) == 0, "Should not record tf_equity without config"

    def test_tf_equity_datetime_format_matches_timeframe(self):
        """tf_equity datetime format should match the configured timeframe."""
        strat = self._run_with_strategy({"timeframes": ["1h"]})

        tf_equity = strat.get_tf_equity()
        for entry in tf_equity:
            assert entry["datetime"].endswith(":00"), \
                f"Hourly datetime should end with ':00', got {entry['datetime']}"

    def test_get_tf_key_returns_configured_value(self):
        """get_tf_key should return the configured timeframe key."""
        strat = self._run_with_strategy({"timeframes": ["4h", "1d"]})
        assert strat.get_tf_key() == "4h"


class TestReporterTfEquity:
    """Test BacktestReporter tf_equity output."""

    def test_write_tf_equity_creates_file(self, tmp_path):
        """_write_tf_equity should create CSV file with correct format."""
        from backtest.backtest_reporter import BacktestReporter

        reporter = BacktestReporter(output_dir=str(tmp_path))
        tf_equity = [
            {"datetime": "2026-01-01 10:00", "equity": 5000.0, "cash": 5000.0},
            {"datetime": "2026-01-01 11:00", "equity": 5100.0, "cash": 5100.0},
        ]

        path = reporter._write_tf_equity(tmp_path, "1h", tf_equity)

        assert path.exists()
        content = path.read_text()
        assert "datetime,equity,cash" in content
        assert "2026-01-01 10:00,5000.0,5000.0" in content

    def test_generate_includes_tf_equity_when_provided(self, tmp_path):
        """generate() should include tf_equity file when provided."""
        from backtest.backtest_reporter import BacktestReporter
        from datetime import datetime, timezone

        reporter = BacktestReporter(output_dir=str(tmp_path))
        reporter.create_run_dir("test_strategy", symbol="BTCUSDT")

        daily_equity = [{"date": "2026-01-01", "equity": 5000, "cash": 5000}]
        tf_equity = [{"datetime": "2026-01-01 10:00", "equity": 5000, "cash": 5000}]

        paths = reporter.generate(
            strategy_name="test_strategy",
            symbol="BTCUSDT",
            config={"name": "test"},
            accounts=[],
            daily_equity=daily_equity,
            trades=[],
            klines_processed=10,
            signals_processed=5,
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
            tf_equity=tf_equity,
            tf_key="1h",
        )

        assert "1h_equity" in paths
        assert paths["1h_equity"].exists()

    def test_generate_without_tf_equity(self, tmp_path):
        """generate() should work without tf_equity (backward compatible)."""
        from backtest.backtest_reporter import BacktestReporter
        from datetime import datetime, timezone

        reporter = BacktestReporter(output_dir=str(tmp_path))
        reporter.create_run_dir("test_strategy", symbol="BTCUSDT")

        daily_equity = [{"date": "2026-01-01", "equity": 5000, "cash": 5000}]

        paths = reporter.generate(
            strategy_name="test_strategy",
            symbol="BTCUSDT",
            config={"name": "test"},
            accounts=[],
            daily_equity=daily_equity,
            trades=[],
            klines_processed=10,
            signals_processed=5,
            start_time=datetime.now(timezone.utc),
            end_time=datetime.now(timezone.utc),
            # No tf_equity/tf_key
        )

        # Should still have equity file
        assert "equity" in paths
        # No tf_equity file
        assert not any("equity" in k and k != "equity" for k in paths)


class TestTfEquityChart:
    """Test generate_tf_equity_chart functionality."""

    def test_generate_tf_equity_chart_creates_file(self, tmp_path):
        """generate_tf_equity_chart should create chart file."""
        from backtest.analyzer import BacktestAnalyzer

        # Create tf_equity CSV
        tf_csv = tmp_path / "1h_equity.csv"
        tf_csv.write_text(
            "datetime,equity,cash\n"
            "2026-01-01 10:00,5000,5000\n"
            "2026-01-01 11:00,5100,5100\n"
            "2026-01-01 12:00,5050,5050\n"
        )

        analyzer = BacktestAnalyzer(
            equity_csv=str(tf_csv),
            symbol="BTCUSDT",
        )

        chart_path = analyzer.generate_tf_equity_chart(
            tf_equity_csv=str(tf_csv),
            output_dir=str(tmp_path),
            tf_key="1h",
            prefix="backtest",
        )

        assert chart_path, "Should return chart path"
        assert Path(chart_path).exists(), "Chart file should exist"
        assert "1h_equity_curve" in chart_path

    def test_generate_tf_equity_chart_empty_csv(self, tmp_path):
        """generate_tf_equity_chart should return empty string for empty CSV."""
        from backtest.analyzer import BacktestAnalyzer

        tf_csv = tmp_path / "1h_equity.csv"
        tf_csv.write_text("datetime,equity,cash\n")  # Header only, no data

        analyzer = BacktestAnalyzer(
            equity_csv=str(tf_csv),
            symbol="BTCUSDT",
        )

        chart_path = analyzer.generate_tf_equity_chart(
            tf_equity_csv=str(tf_csv),
            output_dir=str(tmp_path),
            tf_key="1h",
        )

        assert chart_path == "", "Should return empty string for empty data"

    def test_generate_tf_equity_chart_missing_datetime(self, tmp_path):
        """generate_tf_equity_chart should handle missing datetime column."""
        from backtest.analyzer import BacktestAnalyzer

        tf_csv = tmp_path / "1h_equity.csv"
        tf_csv.write_text(
            "equity,cash\n"
            "5000,5000\n"
        )  # No datetime column

        analyzer = BacktestAnalyzer(
            equity_csv=str(tf_csv),
            symbol="BTCUSDT",
        )

        chart_path = analyzer.generate_tf_equity_chart(
            tf_equity_csv=str(tf_csv),
            output_dir=str(tmp_path),
            tf_key="1h",
        )

        assert chart_path == "", "Should return empty string for missing datetime"

    def test_tf_chart_formats_constant(self):
        """TF_CHART_FORMATS should have correct mappings."""
        from backtest.analyzer import BacktestAnalyzer

        formats = BacktestAnalyzer.TF_CHART_FORMATS

        # Minute timeframes
        assert formats["1m"] == "%Y-%m-%d %H:%M"
        assert formats["15m"] == "%Y-%m-%d %H:%M"
        assert formats["30m"] == "%Y-%m-%d %H:%M"

        # Hour timeframes
        assert formats["1h"] == "%Y-%m-%d %H:00"
        assert formats["4h"] == "%Y-%m-%d %H:00"

        # Day timeframe
        assert formats["1d"] == "%Y-%m-%d"

    def test_generate_tf_equity_chart_date_column(self, tmp_path):
        """generate_tf_equity_chart should handle 'date' column as datetime."""
        from backtest.analyzer import BacktestAnalyzer

        tf_csv = tmp_path / "1d_equity.csv"
        tf_csv.write_text(
            "date,equity,cash\n"
            "2026-01-01,5000,5000\n"
            "2026-01-02,5100,5100\n"
        )

        analyzer = BacktestAnalyzer(
            equity_csv=str(tf_csv),
            symbol="BTCUSDT",
        )

        chart_path = analyzer.generate_tf_equity_chart(
            tf_equity_csv=str(tf_csv),
            output_dir=str(tmp_path),
            tf_key="1d",
        )

        assert chart_path, "Should handle 'date' column"
        assert Path(chart_path).exists()

    def test_chart_filename_with_prefix(self, tmp_path):
        """Chart filename should include prefix when provided."""
        from backtest.analyzer import BacktestAnalyzer

        tf_csv = tmp_path / "15m_equity.csv"
        tf_csv.write_text(
            "datetime,equity,cash\n"
            "2026-01-01 10:00,5000,5000\n"
        )

        analyzer = BacktestAnalyzer(
            equity_csv=str(tf_csv),
            symbol="BTCUSDT",
        )

        chart_path = analyzer.generate_tf_equity_chart(
            tf_equity_csv=str(tf_csv),
            output_dir=str(tmp_path),
            tf_key="15m",
            prefix="backtest_BTCUSDT",
        )

        assert "backtest_BTCUSDT_15m_equity_curve" in chart_path

    def test_chart_filename_without_prefix(self, tmp_path):
        """Chart filename should not have prefix when not provided."""
        from backtest.analyzer import BacktestAnalyzer

        tf_csv = tmp_path / "4h_equity.csv"
        tf_csv.write_text(
            "datetime,equity,cash\n"
            "2026-01-01 10:00,5000,5000\n"
        )

        analyzer = BacktestAnalyzer(
            equity_csv=str(tf_csv),
            symbol="BTCUSDT",
        )

        chart_path = analyzer.generate_tf_equity_chart(
            tf_equity_csv=str(tf_csv),
            output_dir=str(tmp_path),
            tf_key="4h",
        )

        assert "4h_equity_curve" in chart_path
        assert "backtest" not in chart_path
