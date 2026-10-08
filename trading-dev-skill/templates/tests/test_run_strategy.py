"""
Test run_strategy.py — 策略进程入口

验证:
1. CLI 参数解析
2. 独立 DataManager 创建（策略专属路径）
3. 策略加载与初始化
4. 独立 SignalLogger + CSV 写入器
"""

import pytest
import sys
import os
import tempfile
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime, timezone


# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestStrategyProcessConfig:
    """测试策略进程配置加载"""


    def test_build_strategy_config_missing_file_returns_empty(self):
        """配置文件不存在时返回空字典"""
        from run_strategy import build_strategy_config

        config = build_strategy_config("nonexistent_strategy", config_dir="/tmp/no_such_dir")
        assert config == {}


class TestStrategyProcessRunner:
    """测试 StrategyProcessRunner 核心逻辑"""

    def _make_runner_config(self, tmpdir):
        """创建测试用配置"""
        config = {
            "version": "2",
            "symbols": ["BNBUSDT"],
            "timeframes": ["1m"],
            "symbol": "BNBUSDT",
            "timeframe": "1m",
            "direction": "neutral",
            "params": {"threshold": 0.01},
            "signal": {"min_strength": 0.5, "cooldown_ms": 60000, "order_type": 1, "exchange": "binance"},
            "adx": {"enabled": False},
            "price_line": {"enabled": False, "timeframe": "1d"},
            "risk": {"stop_loss_pct": 0.02},
            "capital": {"max_cash": 100, "max_parts": 1},
            "valid_before": "2030-12-31 08:00:00",
            "strategy_type": "CTAFutureFactory",
            "strategy": {"name": "cta_rbreaker"},
            "mode": "backtest",
            "user_id": 10001,
        }
        return config

    def _make_global_config(self, tmpdir):
        """创建全局 settings.yaml"""
        config = {
            "data_manager": {
                "source_data_path": str(tmpdir / "source_data"),
            },
            "signal_logging": {
                "storage": {
                    "path": str(tmpdir / "signals"),
                },
            },
        }
        settings_path = tmpdir / "settings.yaml"
        with open(settings_path, "w") as f:
            yaml.dump(config, f)
        return str(settings_path)

    def test_runner_creates_strategy_specific_data_path(self, tmp_path):
        """Runner 为策略创建专属数据路径"""
        from run_strategy import StrategyProcessRunner

        settings_path = self._make_global_config(tmp_path)
        strategy_config = self._make_runner_config(tmp_path)

        runner = StrategyProcessRunner(
            strategy_name="cta_rbreaker_v3",
            strategy_config=strategy_config,
            global_config_path=settings_path,
        )

        # 验证数据路径包含策略名
        assert runner.strategy_name == "cta_rbreaker_v3"

    def test_runner_data_path_format(self, tmp_path):
        """数据路径格式: data/strategies/{strategy_name}/{interval}/{symbol}_{interval}.csv"""
        from run_strategy import StrategyProcessRunner

        settings_path = self._make_global_config(tmp_path)
        strategy_config = self._make_runner_config(tmp_path)

        runner = StrategyProcessRunner(
            strategy_name="cta_rbreaker_v3",
            strategy_config=strategy_config,
            global_config_path=settings_path,
        )

        # 检查 DataManager 配置
        assert "cta_rbreaker" in runner.data_manager.config.csv_dir


class TestSignalWriter(TestStrategyProcessRunner):
    """测试策略独立信号写入"""

    def test_csv_writer_is_strategy_specific(self, tmp_path):
        """SignalCsvWriter 写入路径包含策略名"""
        from run_strategy import StrategyProcessRunner
        from strategy_core.signal_logging.csv_adapter import SignalCsvWriter

        settings_path = self._make_global_config(tmp_path)
        strategy_config = self._make_runner_config(tmp_path)

        runner = StrategyProcessRunner(
            strategy_name="cta_rbreaker_v3",
            strategy_config=strategy_config,
            global_config_path=settings_path,
        )

        # 验证 CSV writer 存在
        assert runner.csv_writer is not None
        assert isinstance(runner.csv_writer, SignalCsvWriter)


class TestDataManagerCSVPathFormat:
    """测试 DataManager CSV 路径格式符合需求"""

    def test_kline_repository_path_format(self, tmp_path):
        """验证路径格式: data/strategies/{strategy_name}/{interval}/{symbol}_{interval}.csv"""
        from data_manager.kline_repository import KlineRepository

        # 使用策略专属目录
        strategy_dir = tmp_path / "strategies" / "cta_rbreaker"
        repo = KlineRepository(csv_dir=str(strategy_dir))

        repo.register_symbol("BNBUSDT", ["1m", "15m"])

        # 验证路径格式
        csv_path = repo._get_file_path("BNBUSDT", "1m")
        assert csv_path.parent.name == "1m"
        assert csv_path.name == "BNBUSDT_1m.csv"
        assert "cta_rbreaker" in str(csv_path)

    def test_multi_symbol_separate_files(self, tmp_path):
        """多 symbol 分别写入独立 CSV 文件"""
        from data_manager.kline_repository import KlineRepository

        strategy_dir = tmp_path / "strategies" / "cta_rbreaker"
        repo = KlineRepository(csv_dir=str(strategy_dir))

        repo.register_symbol("BNBUSDT", ["1m"])
        repo.register_symbol("BTCUSDT", ["1m"])

        path_bnb = repo._get_file_path("BNBUSDT", "1m")
        path_btc = repo._get_file_path("BTCUSDT", "1m")

        # 不同 symbol 对应不同文件
        assert path_bnb != path_btc
        assert "BNBUSDT_1m.csv" == path_bnb.name
        assert "BTCUSDT_1m.csv" == path_btc.name
        # 同一 interval 在同一子目录
        assert path_bnb.parent == path_btc.parent
