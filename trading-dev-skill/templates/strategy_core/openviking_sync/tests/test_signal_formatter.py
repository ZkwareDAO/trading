"""
信号格式转换器测试

测试 CSV → Markdown 转换功能：
- csv_to_markdown: CSV 文件转 Markdown
- generate_summary_stats: 生成统计摘要
"""

import csv
from datetime import datetime
from pathlib import Path

import pytest

from strategy_core.openviking_sync.formatter.signal_formatter import SignalFormatter


class TestSignalFormatterCsvToMarkdown:
    """CSV 转 Markdown 测试"""

    @pytest.fixture
    def sample_csv_path(self, tmp_path: Path) -> Path:
        """创建示例 CSV 文件"""
        csv_path = tmp_path / "20260529.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "signal_id", "signal_timestamp", "symbol", "pos_type",
                "strategy_type", "risk_strategy_type", "user_id",
                "strategy_name", "strategy_version", "strategy_internal",
                "strategy_params", "strategy_valid_before", "strategy_cash", "strategy_parts",
                "leverage", "signal_side", "signal_action", "signal_exchange",
                "signal_valid_before", "signal_trigger_price", "signal_slippage",
                "signal_order_type", "signal_quantity", "signal_cash",
                "strength", "metadata"
            ])
            writer.writerow([
                "sig_71fe150f5d7d1bf7", "1780061400000", "BTCUSDT", "2",
                "CTAFutureFactory", "traditional", "10002",
                "RBREAKER", "3", "15m",
                '{"threshold": 0.005}', "2030-12-31 08:00:00", "100", "1",
                "5", "2", "sell", "binance",
                "2026-05-30 21:31:01", "72973.1", "0",
                "1", "0", "100.0",
                "0.8", '{"type": "sell", "reason": "价格跌破下轨"}'
            ])
            writer.writerow([
                "sig_e271459a0da6b5f7", "1780063680000", "ETHUSDT", "2",
                "CTAFutureFactory", "traditional", "10002",
                "RBREAKER", "3", "15m",
                '{"threshold": 0.005}', "2030-12-31 08:00:00", "100", "1",
                "5", "2", "sell", "binance",
                "2026-05-30 22:09:00", "1991.17", "0",
                "1", "0", "100.0",
                "0.8", '{"type": "sell", "reason": "价格跌破下轨"}'
            ])
            writer.writerow([
                "sig_48a4d36e02901495", "1780067280000", "ETHUSDT", "2",
                "CTAFutureFactory", "traditional", "10002",
                "RBREAKER", "3", "15m",
                '{"threshold": 0.005}', "2030-12-31 08:00:00", "100", "1",
                "5", "1", "buy_close", "binance",
                "2026-05-30 23:09:00", "2013.36", "0",
                "1", "0", "100.0",
                "0.9", '{"type": "buy_close", "reason": "平空反手做多"}'
            ])
        return csv_path

    def test_csv_to_markdown_basic(self, sample_csv_path: Path):
        """基本转换测试"""
        date = datetime(2026, 5, 29)
        markdown = SignalFormatter.csv_to_markdown(
            str(sample_csv_path), "RBREAKER", date
        )

        assert "# CTA 交易信号 - RBREAKER - 2026-05-29" in markdown
        assert "**策略**: RBREAKER" in markdown
        assert "**日期**: 2026-05-29" in markdown
        assert "**信号数量**: 3" in markdown

    def test_csv_to_markdown_contains_signals(self, sample_csv_path: Path):
        """Markdown 包含信号列表"""
        date = datetime(2026, 5, 29)
        markdown = SignalFormatter.csv_to_markdown(
            str(sample_csv_path), "RBREAKER", date
        )

        # 检查表格头
        assert "| signal_id |" in markdown
        assert "| 动作 |" in markdown
        assert "| 价格 |" in markdown

        # 检查信号数据 (ID 被截断为 16 字符 + "...")
        assert "sig_71fe150f5d7d..." in markdown
        assert "BTCUSDT" in markdown
        assert "ETHUSDT" in markdown
        assert "卖出" in markdown  # 动作已转换为中文
        assert "平多" in markdown  # buy_close -> 平多

    def test_csv_to_markdown_contains_stats(self, sample_csv_path: Path):
        """Markdown 包含统计信息"""
        date = datetime(2026, 5, 29)
        markdown = SignalFormatter.csv_to_markdown(
            str(sample_csv_path), "RBREAKER", date
        )

        assert "## 统计" in markdown
        assert "卖出信号" in markdown
        assert "平空信号" in markdown
        assert "涉及标的" in markdown

    def test_csv_to_markdown_contains_params(self, sample_csv_path: Path):
        """Markdown 包含策略参数"""
        date = datetime(2026, 5, 29)
        markdown = SignalFormatter.csv_to_markdown(
            str(sample_csv_path), "RBREAKER", date
        )

        assert "## 策略参数" in markdown
        assert '"threshold": 0.005' in markdown

    def test_csv_to_markdown_empty_file(self, tmp_path: Path):
        """空 CSV 文件"""
        csv_path = tmp_path / "empty.csv"
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "signal_id", "signal_timestamp", "symbol"
            ])

        date = datetime(2026, 5, 29)
        markdown = SignalFormatter.csv_to_markdown(
            str(csv_path), "RBREAKER", date
        )

        assert "**信号数量**: 0" in markdown

    def test_csv_to_markdown_file_not_found(self):
        """文件不存在"""
        date = datetime(2026, 5, 29)

        with pytest.raises(FileNotFoundError):
            SignalFormatter.csv_to_markdown(
                "/nonexistent/file.csv", "RBREAKER", date
            )


class TestSignalFormatterStats:
    """统计摘要测试"""

    def test_generate_summary_stats(self):
        """生成统计摘要"""
        csv_data = [
            {"signal_action": "buy", "symbol": "BTCUSDT", "strength": "0.8"},
            {"signal_action": "buy", "symbol": "ETHUSDT", "strength": "0.7"},
            {"signal_action": "sell", "symbol": "BTCUSDT", "strength": "0.9"},
            {"signal_action": "buy_close", "symbol": "ETHUSDT", "strength": "0.85"},
        ]

        stats = SignalFormatter.generate_summary_stats(csv_data)

        assert stats["total"] == 4
        assert stats["buy"] == 2
        assert stats["sell"] == 1
        assert stats["buy_close"] == 1
        assert stats["sell_close"] == 0
        assert "BTCUSDT" in stats["symbols"]
        assert "ETHUSDT" in stats["symbols"]
        assert stats["avg_strength"] == pytest.approx(0.8125, rel=0.01)

    def test_generate_summary_stats_empty(self):
        """空数据统计"""
        stats = SignalFormatter.generate_summary_stats([])

        assert stats["total"] == 0
        assert stats["buy"] == 0
        assert stats["sell"] == 0
        assert stats["symbols"] == []


class TestSignalFormatterTimestamp:
    """时间戳转换测试"""

    def test_timestamp_to_time(self):
        """毫秒时间戳转时间字符串"""
        # 2026-05-29 21:31:00 的毫秒时间戳
        ts_ms = 1780061460000
        time_str = SignalFormatter.timestamp_to_time(ts_ms)

        assert ":" in time_str  # 包含时间格式

    def test_timestamp_zero(self):
        """零时间戳处理"""
        time_str = SignalFormatter.timestamp_to_time(0)
        # 应该返回有效时间字符串，不崩溃
        assert isinstance(time_str, str)
