"""BacktestReporter 测试 — 验证 4 个输出文件的格式和目录结构."""

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backtest.backtest_reporter import BacktestReporter


@pytest.fixture
def tmp_output(tmp_path):
    return str(tmp_path)


@pytest.fixture
def sample_trades():
    return [
        {
            "trade_id": "T00000001",
            "strategy_id": "ICTv1_1d_BTCUSDT",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 1.409137,
            "price": 70965.4,
            "commission": 0.0,
            "slippage": 0.0,
            "pnl": 0.0,
            "timestamp": "2026-03-14T23:00:00+00:00",
            "comment": "buy",
        },
        {
            "trade_id": "T00000002",
            "strategy_id": "ICTv1_1d_BTCUSDT",
            "symbol": "BTCUSDT",
            "side": "SELL_CLOSE",
            "quantity": 1.409137,
            "price": 70991.8,
            "commission": 0.0,
            "slippage": 0.0,
            "pnl": 37.2,
            "timestamp": "2026-03-14T23:15:00+00:00",
            "comment": "sell_close",
        },
        {
            "trade_id": "T00000003",
            "strategy_id": "ICTv1_1d_BTCUSDT",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 1.408613,
            "price": 70991.8,
            "commission": 0.0,
            "slippage": 0.0,
            "pnl": 0.0,
            "timestamp": "2026-03-15T02:00:00+00:00",
            "comment": "buy",
        },
        {
            "trade_id": "T00000004",
            "strategy_id": "ICTv1_1d_BTCUSDT",
            "symbol": "BTCUSDT",
            "side": "SELL_CLOSE",
            "quantity": 1.408613,
            "price": 71267.9,
            "commission": 0.0,
            "slippage": 0.0,
            "pnl": 388.92,
            "timestamp": "2026-03-15T02:00:00+00:00",
            "comment": "sell_close",
        },
    ]


@pytest.fixture
def sample_daily_equity():
    return [
        {"date": "2026-03-14", "equity": 100000.0, "cash": 100000.0},
        {"date": "2026-03-15", "equity": 100037.2, "cash": 100037.2},
        {"date": "2026-03-16", "equity": 100426.12, "cash": 100426.12},
    ]


@pytest.fixture
def sample_config():
    return {
        "name": "ICTv1_1d_BTCUSDT 回测",
        "start_date": "2026-03-14",
        "end_date": "2026-03-16",
        "initial_cash": 100000.0,
    }


@pytest.fixture
def sample_accounts():
    return [
        {
            "strategy_id": "ICTv1_1d_BTCUSDT",
            "cash": 100426.12,
            "frozen_cash": 0.0,
            "total_equity": 100426.12,
            "peak_equity": 100426.12,
            "max_drawdown": 0.0,
            "position_count": 0,
            "trade_count": 4,
        }
    ]


# ── 目录结构测试 ──────────────────────────────────────────────

class TestDirectoryStructure:

    def test_output_dir_is_strategy_date_nested(self, tmp_output, sample_trades,
                                                  sample_daily_equity, sample_config,
                                                  sample_accounts):
        """输出目录应为 {strategy}/{date}/{time}/{symbol}/ 结构."""
        reporter = BacktestReporter(output_dir=tmp_output)
        paths = reporter.generate(
            strategy_name="cta_ict",
            symbol="BTCUSDT",
            config=sample_config,
            accounts=sample_accounts,
            daily_equity=sample_daily_equity,
            trades=sample_trades,
            klines_processed=1000,
            signals_processed=4,
            start_time=datetime(2026, 3, 14, 10, 0, 0),
            end_time=datetime(2026, 3, 14, 10, 30, 0),
        )
        for path in paths.values():
            if isinstance(path, dict):
                continue  # 跳过 charts 字典
            parts = Path(path).relative_to(tmp_output).parts
            assert parts[0] == "cta_ict"
            assert len(parts[1]) == 8  # YYYYMMDD
            assert len(parts[2]) == 6  # HHMMSS
            assert parts[3] == "BTCUSDT"  # symbol

    def test_filenames_follow_convention(self, tmp_output, sample_trades,
                                          sample_daily_equity, sample_config,
                                          sample_accounts):
        """文件名应为 backtest_{type}.{ext}."""
        reporter = BacktestReporter(output_dir=tmp_output)
        paths = reporter.generate(
            strategy_name="cta_ict",
            symbol="BTCUSDT",
            config=sample_config,
            accounts=sample_accounts,
            daily_equity=sample_daily_equity,
            trades=sample_trades,
            klines_processed=1000,
            signals_processed=4,
            start_time=datetime(2026, 3, 14, 10, 0, 0),
            end_time=datetime(2026, 3, 14, 10, 30, 0),
        )
        for key, path in paths.items():
            if isinstance(path, dict):
                continue  # 跳过 charts 字典
            name = Path(path).name
            assert name.startswith("backtest_")

    def test_generates_4_files(self, tmp_output, sample_trades,
                                sample_daily_equity, sample_config,
                                sample_accounts):
        """应生成核心文件: equity, report, result, trades（外加 charts 和 analysis_report）."""
        reporter = BacktestReporter(output_dir=tmp_output)
        paths = reporter.generate(
            strategy_name="cta_ict",
            symbol="BTCUSDT",
            config=sample_config,
            accounts=sample_accounts,
            daily_equity=sample_daily_equity,
            trades=sample_trades,
            klines_processed=1000,
            signals_processed=4,
            start_time=datetime(2026, 3, 14, 10, 0, 0),
            end_time=datetime(2026, 3, 14, 10, 30, 0),
        )
        # 核心文件
        assert "equity" in paths
        assert "report" in paths
        assert "result" in paths
        assert "trades" in paths
        for key in ["equity", "report", "result", "trades"]:
            assert Path(paths[key]).exists()


# ── equity.csv 格式测试 ──────────────────────────────────────

class TestEquityCSV:

    def test_equity_csv_columns(self, tmp_output, sample_trades,
                                 sample_daily_equity, sample_config,
                                 sample_accounts):
        """equity.csv 应有 date,equity,cash 三列."""
        reporter = BacktestReporter(output_dir=tmp_output)
        paths = reporter.generate(
            strategy_name="cta_ict",
            symbol="BTCUSDT",
            config=sample_config,
            accounts=sample_accounts,
            daily_equity=sample_daily_equity,
            trades=sample_trades,
            klines_processed=1000,
            signals_processed=4,
            start_time=datetime(2026, 3, 14, 10, 0, 0),
            end_time=datetime(2026, 3, 14, 10, 30, 0),
        )
        with open(paths["equity"], "r") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == ["date", "equity", "cash"]

    def test_equity_csv_row_count(self, tmp_output, sample_trades,
                                   sample_daily_equity, sample_config,
                                   sample_accounts):
        """equity.csv 行数应等于 daily_equity 天数."""
        reporter = BacktestReporter(output_dir=tmp_output)
        paths = reporter.generate(
            strategy_name="cta_ict",
            symbol="BTCUSDT",
            config=sample_config,
            accounts=sample_accounts,
            daily_equity=sample_daily_equity,
            trades=sample_trades,
            klines_processed=1000,
            signals_processed=4,
            start_time=datetime(2026, 3, 14, 10, 0, 0),
            end_time=datetime(2026, 3, 14, 10, 30, 0),
        )
        with open(paths["equity"], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 3

    def test_equity_csv_values(self, tmp_output, sample_trades,
                                sample_daily_equity, sample_config,
                                sample_accounts):
        """equity.csv 数值应与输入匹配."""
        reporter = BacktestReporter(output_dir=tmp_output)
        paths = reporter.generate(
            strategy_name="cta_ict",
            symbol="BTCUSDT",
            config=sample_config,
            accounts=sample_accounts,
            daily_equity=sample_daily_equity,
            trades=sample_trades,
            klines_processed=1000,
            signals_processed=4,
            start_time=datetime(2026, 3, 14, 10, 0, 0),
            end_time=datetime(2026, 3, 14, 10, 30, 0),
        )
        with open(paths["equity"], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows[0]["date"] == "2026-03-14"
        assert float(rows[0]["equity"]) == 100000.0
        assert float(rows[2]["equity"]) == 100426.12


# ── trades.csv 格式测试 ──────────────────────────────────────

class TestTradesCSV:

    def test_trades_csv_columns(self, tmp_output, sample_trades,
                                 sample_daily_equity, sample_config,
                                 sample_accounts):
        """trades.csv 应有 11 列: trade_id,...,comment."""
        reporter = BacktestReporter(output_dir=tmp_output)
        paths = reporter.generate(
            strategy_name="cta_ict",
            symbol="BTCUSDT",
            config=sample_config,
            accounts=sample_accounts,
            daily_equity=sample_daily_equity,
            trades=sample_trades,
            klines_processed=1000,
            signals_processed=4,
            start_time=datetime(2026, 3, 14, 10, 0, 0),
            end_time=datetime(2026, 3, 14, 10, 30, 0),
        )
        expected_cols = [
            "trade_id", "strategy_id", "symbol", "side", "quantity",
            "price", "commission", "slippage", "pnl", "timestamp", "comment",
        ]
        with open(paths["trades"], "r") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == expected_cols

    def test_trades_csv_row_count(self, tmp_output, sample_trades,
                                   sample_daily_equity, sample_config,
                                   sample_accounts):
        """trades.csv 行数应等于 trades 列表长度."""
        reporter = BacktestReporter(output_dir=tmp_output)
        paths = reporter.generate(
            strategy_name="cta_ict",
            symbol="BTCUSDT",
            config=sample_config,
            accounts=sample_accounts,
            daily_equity=sample_daily_equity,
            trades=sample_trades,
            klines_processed=1000,
            signals_processed=4,
            start_time=datetime(2026, 3, 14, 10, 0, 0),
            end_time=datetime(2026, 3, 14, 10, 30, 0),
        )
        with open(paths["trades"], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 4

    def test_trades_csv_pnl_values(self, tmp_output, sample_trades,
                                    sample_daily_equity, sample_config,
                                    sample_accounts):
        """trades.csv 中 pnl 值应正确."""
        reporter = BacktestReporter(output_dir=tmp_output)
        paths = reporter.generate(
            strategy_name="cta_ict",
            symbol="BTCUSDT",
            config=sample_config,
            accounts=sample_accounts,
            daily_equity=sample_daily_equity,
            trades=sample_trades,
            klines_processed=1000,
            signals_processed=4,
            start_time=datetime(2026, 3, 14, 10, 0, 0),
            end_time=datetime(2026, 3, 14, 10, 30, 0),
        )
        with open(paths["trades"], "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert float(rows[1]["pnl"]) == 37.2
        assert float(rows[3]["pnl"]) == 388.92


# ── result.json 格式测试 ─────────────────────────────────────

class TestResultJSON:

    def _generate_and_load(self, tmp_output, sample_trades, sample_daily_equity,
                           sample_config, sample_accounts):
        reporter = BacktestReporter(output_dir=tmp_output)
        paths = reporter.generate(
            strategy_name="cta_ict",
            symbol="BTCUSDT",
            config=sample_config,
            accounts=sample_accounts,
            daily_equity=sample_daily_equity,
            trades=sample_trades,
            klines_processed=1000,
            signals_processed=4,
            start_time=datetime(2026, 3, 14, 10, 0, 0),
            end_time=datetime(2026, 3, 14, 10, 30, 0),
        )
        with open(paths["result"], "r") as f:
            return json.load(f)

    def test_result_has_config(self, tmp_output, sample_trades,
                                sample_daily_equity, sample_config,
                                sample_accounts):
        """result.json 应包含 config 字段."""
        result = self._generate_and_load(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert "config" in result
        assert result["config"]["name"] == "ICTv1_1d_BTCUSDT 回测"
        assert result["config"]["initial_cash"] == 100000.0

    def test_result_has_timing(self, tmp_output, sample_trades,
                                sample_daily_equity, sample_config,
                                sample_accounts):
        """result.json 应包含 start_time, end_time, duration_seconds."""
        result = self._generate_and_load(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert "start_time" in result
        assert "end_time" in result
        assert "duration_seconds" in result
        assert result["duration_seconds"] == pytest.approx(1800.0, abs=1)

    def test_result_has_accounts(self, tmp_output, sample_trades,
                                  sample_daily_equity, sample_config,
                                  sample_accounts):
        """result.json 应包含 accounts 数组."""
        result = self._generate_and_load(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert "accounts" in result
        assert len(result["accounts"]) == 1
        assert result["accounts"][0]["strategy_id"] == "ICTv1_1d_BTCUSDT"

    def test_result_has_metrics(self, tmp_output, sample_trades,
                                 sample_daily_equity, sample_config,
                                 sample_accounts):
        """result.json 应包含 metrics 字段."""
        result = self._generate_and_load(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert "metrics" in result
        metrics = result["metrics"]
        for key in ["total_return", "total_trades", "winning_trades",
                     "losing_trades", "win_rate"]:
            assert key in metrics, f"metrics 缺少 {key}"

    def test_result_has_daily_equity(self, tmp_output, sample_trades,
                                      sample_daily_equity, sample_config,
                                      sample_accounts):
        """result.json 应包含 daily_equity 数组."""
        result = self._generate_and_load(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert "daily_equity" in result
        assert len(result["daily_equity"]) == 3

    def test_result_has_counts(self, tmp_output, sample_trades,
                                sample_daily_equity, sample_config,
                                sample_accounts):
        """result.json 应包含统计计数."""
        result = self._generate_and_load(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert result["trades_count"] == 4
        assert result["klines_processed"] == 1000
        assert result["signals_processed"] == 4
        assert result["status"] == "success"

    def test_result_has_performance_summary(self, tmp_output, sample_trades,
                                             sample_daily_equity, sample_config,
                                             sample_accounts):
        """result.json 应包含 performance_summary 文本."""
        result = self._generate_and_load(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert "performance_summary" in result
        assert isinstance(result["performance_summary"], str)
        assert len(result["performance_summary"]) > 0


# ── report.txt 格式测试 ──────────────────────────────────────

class TestReportTXT:

    def _generate_and_read(self, tmp_output, sample_trades, sample_daily_equity,
                           sample_config, sample_accounts):
        reporter = BacktestReporter(output_dir=tmp_output)
        paths = reporter.generate(
            strategy_name="cta_ict",
            symbol="BTCUSDT",
            config=sample_config,
            accounts=sample_accounts,
            daily_equity=sample_daily_equity,
            trades=sample_trades,
            klines_processed=1000,
            signals_processed=4,
            start_time=datetime(2026, 3, 14, 10, 0, 0),
            end_time=datetime(2026, 3, 14, 10, 30, 0),
        )
        return Path(paths["report"]).read_text(encoding="utf-8")

    def test_report_has_title(self, tmp_output, sample_trades,
                               sample_daily_equity, sample_config,
                               sample_accounts):
        """report.txt 应包含标题."""
        text = self._generate_and_read(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert "CTA 策略回测报告" in text

    def test_report_has_overview_section(self, tmp_output, sample_trades,
                                          sample_daily_equity, sample_config,
                                          sample_accounts):
        """report.txt 应包含回测概况区域."""
        text = self._generate_and_read(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert "回测概况" in text
        assert "回测名称" in text
        assert "初始资金" in text

    def test_report_has_account_section(self, tmp_output, sample_trades,
                                         sample_daily_equity, sample_config,
                                         sample_accounts):
        """report.txt 应包含账户摘要区域."""
        text = self._generate_and_read(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert "账户摘要" in text
        assert "期末权益" in text

    def test_report_has_metrics_section(self, tmp_output, sample_trades,
                                         sample_daily_equity, sample_config,
                                         sample_accounts):
        """report.txt 应包含绩效指标区域."""
        text = self._generate_and_read(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert "绩效指标" in text
        assert "总收益率" in text

    def test_report_has_trade_stats_section(self, tmp_output, sample_trades,
                                             sample_daily_equity, sample_config,
                                             sample_accounts):
        """report.txt 应包含交易统计区域."""
        text = self._generate_and_read(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert "交易统计" in text
        assert "胜率" in text

    def test_report_has_recent_trades(self, tmp_output, sample_trades,
                                       sample_daily_equity, sample_config,
                                       sample_accounts):
        """report.txt 应包含最近交易记录."""
        text = self._generate_and_read(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert "最近交易记录" in text

    def test_report_has_generation_time(self, tmp_output, sample_trades,
                                         sample_daily_equity, sample_config,
                                         sample_accounts):
        """report.txt 应包含报告生成时间."""
        text = self._generate_and_read(
            tmp_output, sample_trades, sample_daily_equity,
            sample_config, sample_accounts,
        )
        assert "报告生成时间" in text


# ── 边界条件测试 ─────────────────────────────────────────────

class TestEdgeCases:

    def test_empty_trades(self, tmp_output, sample_daily_equity, sample_config,
                           sample_accounts):
        """空 trades 列表应正常生成."""
        reporter = BacktestReporter(output_dir=tmp_output)
        paths = reporter.generate(
            strategy_name="cta_ict",
            symbol="BTCUSDT",
            config=sample_config,
            accounts=sample_accounts,
            daily_equity=sample_daily_equity,
            trades=[],
            klines_processed=0,
            signals_processed=0,
            start_time=datetime(2026, 3, 14, 10, 0, 0),
            end_time=datetime(2026, 3, 14, 10, 30, 0),
        )
        # 核心文件 + charts + analysis_report
        assert "equity" in paths
        assert "trades" in paths
        with open(paths["trades"], "r") as f:
            reader = csv.DictReader(f)
            assert len(list(reader)) == 0

    def test_empty_daily_equity(self, tmp_output, sample_trades, sample_config,
                                 sample_accounts):
        """空 daily_equity 应正常生成."""
        reporter = BacktestReporter(output_dir=tmp_output)
        paths = reporter.generate(
            strategy_name="cta_ict",
            symbol="BTCUSDT",
            config=sample_config,
            accounts=sample_accounts,
            daily_equity=[],
            trades=sample_trades,
            klines_processed=1000,
            signals_processed=4,
            start_time=datetime(2026, 3, 14, 10, 0, 0),
            end_time=datetime(2026, 3, 14, 10, 30, 0),
        )
        with open(paths["equity"], "r") as f:
            reader = csv.DictReader(f)
            assert len(list(reader)) == 0
