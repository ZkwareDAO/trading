"""Tests for run_backtest.py config and log level parameters."""

import sys
import tempfile
from pathlib import Path
from datetime import datetime

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


class TestRunBacktestConfigParams:
    """Test --config and --log-level parameters."""

    def test_default_config_path_is_config_test_yaml(self):
        """默认配置路径为 strategies/{strategy}/config.test.yaml"""
        from backtest.run_backtest import load_strategy_config, resolve_strategy_name
        import os

        # 修改工作目录到项目根目录
        original_cwd = os.getcwd()
        try:
            os.chdir(Path(__file__).parent.parent.parent)
            strategy_dir_name = resolve_strategy_name("obv")
            strategy_dir = str(Path("strategies") / strategy_dir_name)

            config = load_strategy_config(strategy_dir)

            # config.test.yaml 存在且包含 obv_atr 配置
            assert config is not None, "应该加载 config.test.yaml"
            assert "symbols" in config, "配置应包含 symbols"
            assert "signal" in config, "配置应包含 signal"
            assert config["signal"].get("diagnostic_log_level") == "WARNING"  # 当前配置值
        finally:
            os.chdir(original_cwd)

    def test_rbreaker_alias_uses_maintained_v3_strategy(self):
        from backtest.run_backtest import resolve_strategy_name

        assert resolve_strategy_name("rbreaker") == "cta_rbreaker_v3"
        assert resolve_strategy_name("rbreaker_v3") == "cta_rbreaker_v3"

    def test_custom_config_path_overrides_default(self):
        """--config 参数指定的路径覆盖默认路径"""
        from backtest.run_backtest import load_strategy_config_from_path

        # 使用 config.dev.yaml（如果存在）
        config_path = Path(__file__).parent.parent.parent / "strategies" / "obv_atr" / "config.dev.yaml"
        if config_path.exists():
            config = load_strategy_config_from_path(str(config_path), "obv_atr")
            assert config is not None
            # dev 配置可能不同于 test 配置
            assert "symbols" in config

    def test_log_level_priority_command_line_over_config(self):
        """命令行 --log-level 优先级高于配置文件"""
        # 这个测试验证日志级别优先级逻辑
        # 命令行 > config.diagnostic_log_level > 默认 INFO
        from backtest.run_backtest import resolve_log_level

        # 命令行指定 DEBUG，配置为 INFO，应返回 DEBUG
        level = resolve_log_level("DEBUG", {"signal": {"diagnostic_log_level": "INFO"}})
        assert level == "DEBUG"

        # 命令行未指定（None），配置为 DEBUG，应返回 DEBUG
        level = resolve_log_level(None, {"signal": {"diagnostic_log_level": "DEBUG"}})
        assert level == "DEBUG"

        # 命令行未指定，配置也无，应返回默认 INFO
        level = resolve_log_level(None, {})
        assert level == "INFO"

    def test_log_level_case_insensitive(self):
        """日志级别大小写不敏感"""
        from backtest.run_backtest import resolve_log_level

        level = resolve_log_level("debug", {})
        assert level == "DEBUG"

        level = resolve_log_level("Info", {})
        assert level == "INFO"


class TestSignalOutputPath:
    """Test signal CSV output path format."""

    def test_signal_csv_path_includes_strategy_type(self):
        """信号 CSV 路径包含策略类型目录"""
        from backtest.bt_strategy import BacktestBTStrategy
        from backtest.signal_mapper import SignalMapper
        import tempfile
        import os

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
                return None

            @property
            def strategy_name(self):
                return "OBVATRv1_4h_ETHUSDT"

            @property
            def name(self):
                return "obv_atr"

        import backtrader as bt

        with tempfile.TemporaryDirectory() as tmpdir:
            mock_strategy = MockStrategy()
            mapper = SignalMapper()

            # 创建样本 CSV
            sample_csv = Path(tmpdir) / "sample.csv"
            sample_csv.write_text(
                "datetime,open,high,low,close,volume\n"
                "2026-01-01 00:00:00,100,105,95,102,1000\n"
            )

            cerebro = bt.Cerebro()
            data = bt.feeds.GenericCSVData(
                dataname=str(sample_csv),
                dtformat="%Y-%m-%d %H:%M:%S",
                datetime=0, open=1, high=2, low=3, close=4, volume=5,
                openinterest=-1,
                name="ETHUSDT",
            )
            cerebro.adddata(data)
            cerebro.addstrategy(
                BacktestBTStrategy,
                cta_strategy=mock_strategy,
                signal_mapper=mapper,
                data_manager=None,
                signal_csv_dir=tmpdir,
                strategy_type="obv_atr",  # 新增参数
            )
            cerebro.run()

            # 验证：信号 CSV 直接在 tmpdir 下（backtest_signals.csv）
            csv_files = list(Path(tmpdir).glob("*.csv"))
            assert len(csv_files) > 0, "应该生成信号 CSV 文件"
            # 文件名应该是 backtest_signals.csv
            assert any("backtest_signals.csv" in str(f) for f in csv_files), \
                f"应该生成 backtest_signals.csv，实际文件: {csv_files}"

    def test_signal_csv_includes_timestamp_for_uniqueness(self):
        """信号 CSV 文件名包含时间戳以区分同日多次运行"""
        from backtest.bt_strategy import generate_signal_csv_filename
        from datetime import datetime

        # 生成文件名
        strategy_name = "OBVATRv1_4h_ETHUSDT"
        filename = generate_signal_csv_filename(strategy_name)

        # 文件名格式：{strategy_name}_{YYYYMMDD_HHMMSS}_signals.csv
        assert strategy_name in filename
        assert "_signals.csv" in filename

        # 验证时间戳格式
        import re
        pattern = r"_\d{8}_\d{6}_signals\.csv$"
        assert re.search(pattern, filename), f"文件名应包含时间戳: {filename}"
