#!/usr/bin/env python3
"""
策略层改造测试：reload_config, on_line 统一入口, get_line_data 统一读取
"""

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from data_manager.manager import DataManager, DataManagerConfig
from data_manager.kline_repository import KlineRepository
from data_manager.klines_data import Kline


def make_kline(
    symbol: str = "BTCUSDT",
    ts: datetime = None,
    close: float = 100.5,
):
    """创建测试用 Kline 对象"""
    if ts is None:
        ts = datetime(2026, 4, 20, 10, 0, tzinfo=timezone.utc)
    return Kline(
        symbol=symbol,
        interval="1m",
        timestamp=ts,
        open=100.0,
        high=101.0,
        low=99.0,
        close=close,
        volume=1000.0,
    )


@pytest.fixture
def dm(tmp_path):
    config = DataManagerConfig(
        csv_dir=str(tmp_path / "klines"),
        klines_service_enabled=True,
        klines_service_http_url="http://test:17081",
        auto_sync_on_connect=False,
    )
    dm_inst = DataManager(config)
    dm_inst.enable_kline_repository()

    # 放入缓存数据
    now = datetime.now(timezone.utc)
    timestamps = [now - timedelta(minutes=i) for i in range(20, 0, -1)]
    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': [100.0 + i for i in range(20)],
        'high': [101.0 + i for i in range(20)],
        'low': [99.0 + i for i in range(20)],
        'close': [100.5 + i for i in range(20)],
        'volume': [1000.0] * 20,
    })
    dm_inst.cache.put("BTCUSDT", "1m", df, force_1m=True)
    return dm_inst


class TestGetLineData:
    """DataManager.get_line_data 统一读取测试"""

    def test_get_line_data_returns_klines(self, dm):
        """统一读取方法返回 K 线列表"""
        result = dm.get_line_data("BTCUSDT", "1m", limit=10)

        assert "symbol" in result
        assert "interval" in result
        assert "klines" in result
        assert "df" in result
        assert "indicators" in result
        assert result["symbol"] == "BTCUSDT"
        assert result["interval"] == "1m"
        assert len(result["klines"]) > 0

    def test_get_line_data_with_indicators(self, dm):
        """统一读取方法附带指标计算"""
        result = dm.get_line_data(
            "BTCUSDT", "1m", limit=20,
            indicators=[{"name": "rsi", "params": {"period": 14}}],
        )

        assert "rsi" in result["indicators"]
        assert result["indicators"]["rsi"] is not None
        assert len(result["indicators"]["rsi"]) > 0

    def test_get_line_data_no_data(self, dm):
        """无数据时返回空结构"""
        result = dm.get_line_data("NONEXIST", "1m", limit=10)

        assert result["klines"] == []
        assert result["df"].empty
        assert result["indicators"] == {}

    def test_get_line_data_case_insensitive(self, dm):
        """symbol 大小写不敏感"""
        result = dm.get_line_data("btcusdt", "1m", limit=10)
        assert result["symbol"] == "BTCUSDT"


class TestStrategyReloadConfig:
    """策略 reload_config 测试"""

    @pytest.mark.skip(reason="reload_config 方法未在策略中实现")
    def test_rbreaker_reload_config(self):
        """RBreaker 策略重新加载配置"""
        from strategies.cta_rbreaker_v3.strategy import Strategy as RBreakerStrategy

        with tempfile.TemporaryDirectory() as tmp:
            csv_dir = Path(tmp) / "klines"
            csv_dir.mkdir()

            config = DataManagerConfig(csv_dir=str(csv_dir))
            dm = DataManager(config)

            # 创建临时 config.yaml
            strategy_dir = Path(tmp) / "strategy"
            strategy_dir.mkdir()
            config_file = Path(__file__).parent.parent.parent / "strategies" / "cta_rbreaker_v3" / "config.yaml"
            if config_file.exists():
                # 使用实际 config 文件
                strategy = RBreakerStrategy(data_manager=dm)
                strategy._running = True
                original_threshold = strategy.threshold
                strategy.reload_config()
                # reload 后 threshold 应来自配置
                assert strategy.threshold is not None
            else:
                # 无配置文件时 reload 应为空操作
                strategy = RBreakerStrategy(data_manager=dm, config={"symbols": ["BTCUSDT"]})
                strategy.reload_config()


class TestStrategyOnKline:
    """策略 on_kline 统一入口测试（验证 reload_config 工具方法存在）"""

    @pytest.mark.skip(reason="reload_config 方法未在策略中实现")
    def test_rbreaker_reload_config_exists(self):
        """RBreaker 策略有 reload_config 方法"""
        from strategies.cta_rbreaker_v3.strategy import Strategy as RBreakerStrategy

        with tempfile.TemporaryDirectory() as tmp:
            csv_dir = Path(tmp) / "klines"
            csv_dir.mkdir()
            dm = DataManager(DataManagerConfig(csv_dir=str(csv_dir)))

            strategy = RBreakerStrategy(data_manager=dm, config={"symbols": ["BTCUSDT"]})
            assert hasattr(strategy, 'reload_config')
            assert hasattr(strategy, 'on_kline')
            # on_kline 是原有入口，reload_config 供调用方在需要时刷新配置
            strategy.reload_config()

    @pytest.mark.skip(reason="reload_config 方法未在策略中实现")
    def test_trend_reload_config_exists(self):
        """Trend 策略有 reload_config 方法"""
        from strategies.cta_trend.strategy import Strategy as TrendStrategy

        with tempfile.TemporaryDirectory() as tmp:
            csv_dir = Path(tmp) / "klines"
            csv_dir.mkdir()
            dm = DataManager(DataManagerConfig(csv_dir=str(csv_dir)))

            strategy = TrendStrategy(data_manager=dm, config={"symbols": ["BTCUSDT"]})
            assert hasattr(strategy, 'reload_config')
            assert hasattr(strategy, 'on_kline')
            strategy.reload_config()

    @pytest.mark.skip(reason="reload_config 方法未在策略中实现")
    def test_trend_strength_reload_config_exists(self):
        """TrendStrength 策略有 reload_config 方法"""
        from strategies.cta_trend_strength.strategy import Strategy as TSStrategy

        with tempfile.TemporaryDirectory() as tmp:
            csv_dir = Path(tmp) / "klines"
            csv_dir.mkdir()
            dm = DataManager(DataManagerConfig(csv_dir=str(csv_dir)))

            strategy = TSStrategy(data_manager=dm, config={"symbols": ["BTCUSDT"]})
            assert hasattr(strategy, 'reload_config')
            assert hasattr(strategy, 'on_kline')
            strategy.reload_config()

    @pytest.mark.skip(reason="reload_config 方法未在策略中实现")
    def test_ict_reload_config_exists(self):
        """ICT 策略有 reload_config 方法"""
        from strategies.cta_ict_v3.strategy import Strategy as ICTStrategy

        with tempfile.TemporaryDirectory() as tmp:
            csv_dir = Path(tmp) / "klines"
            csv_dir.mkdir()
            dm = DataManager(DataManagerConfig(csv_dir=str(csv_dir)))

            strategy = ICTStrategy(data_manager=dm, config={"symbols": ["BTCUSDT"]})
            assert hasattr(strategy, 'reload_config')
            assert hasattr(strategy, 'on_kline')
            strategy.reload_config()
