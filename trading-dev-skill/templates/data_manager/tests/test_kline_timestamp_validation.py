"""
K 线时间戳验证测试

测试 _on_kline_received 中的时间戳验证逻辑：
- K 线时间戳滞后超过 5 分钟时跳过处理
- K 线时间戳在 5 分钟内正常处理
"""

import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch
import asyncio

import pytest

from data_manager.manager import DataManager, DataManagerConfig
from data_manager.klines_data import Kline


class TestKlineTimestampValidation:
    """K 线时间戳验证测试"""

    @pytest.fixture
    def dm(self):
        tmpdir = tempfile.mkdtemp()
        config = DataManagerConfig(
            csv_dir=tmpdir,
            preload_1m_enabled=False,
            klines_service_enabled=False,  # 禁用 WS
        )
        dm = DataManager(config)
        dm.connect()
        dm.enable_kline_repository()
        dm._ws_subscribed_symbols = {"BTCUSDT"}  # 模拟已订阅
        yield dm
        shutil.rmtree(tmpdir)

    def test_kline_within_5_minutes_is_processed(self, dm):
        """K 线时间戳在 5 分钟内应正常处理"""
        now = datetime.now(timezone.utc)
        kline = Kline(
            symbol="BTCUSDT",
            interval="1m",
            timestamp=now - timedelta(minutes=2),  # 2 分钟前
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
        )

        # 设置回调来验证是否被调用
        callback = MagicMock()
        dm.set_kline_dispatch_callback(callback)

        # 调用 _on_kline_received
        dm._on_kline_received(kline)

        # 回调应该被调用
        callback.assert_called_once_with(kline)

    def test_kline_exactly_5_minutes_is_skipped(self, dm):
        """K 线时间戳恰好 5 分钟应跳过（边界值：保守处理）"""
        now = datetime.now(timezone.utc)
        kline = Kline(
            symbol="BTCUSDT",
            interval="1m",
            timestamp=now - timedelta(minutes=5),  # 恰好 5 分钟
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
        )

        callback = MagicMock()
        dm.set_kline_dispatch_callback(callback)

        dm._on_kline_received(kline)

        # 恰好 5 分钟（>= 300 秒）跳过
        callback.assert_not_called()

    def test_kline_just_under_5_minutes_is_processed(self, dm):
        """K 线时间戳略小于 5 分钟应正常处理"""
        now = datetime.now(timezone.utc)
        kline = Kline(
            symbol="BTCUSDT",
            interval="1m",
            timestamp=now - timedelta(minutes=4, seconds=59),  # 4 分 59 秒
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
        )

        callback = MagicMock()
        dm.set_kline_dispatch_callback(callback)

        dm._on_kline_received(kline)

        # 略小于 5 分钟应该处理
        callback.assert_called_once()

    def test_kline_over_5_minutes_is_skipped(self, dm):
        """K 线时间戳超过 5 分钟应跳过处理"""
        now = datetime.now(timezone.utc)
        kline = Kline(
            symbol="BTCUSDT",
            interval="1m",
            timestamp=now - timedelta(minutes=10),  # 10 分钟前
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
        )

        callback = MagicMock()
        dm.set_kline_dispatch_callback(callback)

        dm._on_kline_received(kline)

        # 超过 5 分钟不应调用回调
        callback.assert_not_called()

    def test_kline_21_hours_ago_is_skipped(self, dm):
        """K 线时间戳 21 小时前应跳过（重现日志中的问题）"""
        now = datetime.now(timezone.utc)
        kline = Kline(
            symbol="BTCUSDT",
            interval="1m",
            timestamp=now - timedelta(hours=21),  # 21 小时前
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
        )

        callback = MagicMock()
        dm.set_kline_dispatch_callback(callback)

        dm._on_kline_received(kline)

        # 超过 5 分钟不应调用回调
        callback.assert_not_called()

    def test_kline_future_timestamp_is_processed(self, dm):
        """K 线时间戳在未来应正常处理（可能是时钟同步问题）"""
        now = datetime.now(timezone.utc)
        kline = Kline(
            symbol="BTCUSDT",
            interval="1m",
            timestamp=now + timedelta(minutes=2),  # 2 分钟后
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
        )

        callback = MagicMock()
        dm.set_kline_dispatch_callback(callback)

        dm._on_kline_received(kline)

        # 未来时间应该处理（可能是时钟偏差）
        callback.assert_called_once()

    def test_kline_without_timezone_is_handled(self, dm):
        """K 线时间戳无时区信息应正确处理"""
        now = datetime.now(timezone.utc)
        # 创建无时区的时间戳
        kline = Kline(
            symbol="BTCUSDT",
            interval="1m",
            timestamp=(now - timedelta(minutes=10)).replace(tzinfo=None),
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
        )

        callback = MagicMock()
        dm.set_kline_dispatch_callback(callback)

        dm._on_kline_received(kline)

        # 无时区时间戳应被视为 UTC，超过 5 分钟跳过
        callback.assert_not_called()


class TestKlineTimestampValidationBacktestMode:
    """回测模式下时间戳验证测试"""

    @pytest.fixture
    def dm_backtest(self):
        """创建回测模式的 DataManager"""
        tmpdir = tempfile.mkdtemp()
        config = DataManagerConfig(
            csv_dir=tmpdir,
            preload_1m_enabled=False,
            klines_service_enabled=False,
            backtest_mode=True,  # 回测模式
        )
        dm = DataManager(config)
        dm.connect()
        dm.enable_kline_repository()
        dm._ws_subscribed_symbols = {"BTCUSDT"}
        yield dm
        shutil.rmtree(tmpdir)

    def test_backtest_mode_historical_kline_is_processed(self, dm_backtest):
        """回测模式：历史 K 线应正常处理（跳过时间戳验证）"""
        now = datetime.now(timezone.utc)
        kline = Kline(
            symbol="BTCUSDT",
            interval="1m",
            timestamp=now - timedelta(hours=21),  # 21 小时前的历史数据
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
        )

        callback = MagicMock()
        dm_backtest.set_kline_dispatch_callback(callback)

        dm_backtest._on_kline_received(kline)

        # 回测模式下，历史数据应该被处理
        callback.assert_called_once_with(kline)

    def test_backtest_mode_week_old_kline_is_processed(self, dm_backtest):
        """回测模式：一周前的 K 线也应正常处理"""
        now = datetime.now(timezone.utc)
        kline = Kline(
            symbol="BTCUSDT",
            interval="1m",
            timestamp=now - timedelta(days=7),  # 一周前的历史数据
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.0,
        )

        callback = MagicMock()
        dm_backtest.set_kline_dispatch_callback(callback)

        dm_backtest._on_kline_received(kline)

        # 回测模式下，任意历史数据都应被处理
        callback.assert_called_once_with(kline)
