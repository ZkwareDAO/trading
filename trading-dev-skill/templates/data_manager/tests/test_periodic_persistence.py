#!/usr/bin/env python3
"""
定时持久化测试
"""

import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from data_manager.manager import DataManager, DataManagerConfig


@pytest.fixture
def dm(tmp_path):
    config = DataManagerConfig(
        csv_dir=str(tmp_path / "klines"),
        klines_service_enabled=True,
        klines_service_http_url="http://test:17081",
        auto_sync_on_connect=False,
        persistence_interval_minutes=1,  # 缩短间隔用于测试
    )
    dm_inst = DataManager(config)
    dm_inst.enable_kline_repository()
    return dm_inst


class TestPeriodicPersistence:
    """定时持久化测试"""

    def test_flush_all_cache_to_csv(self, dm):
        """将所有缓存数据持久化到 CSV"""
        now = datetime.now(timezone.utc)
        ts = [now - timedelta(minutes=i) for i in range(10, 0, -1)]
        df = pd.DataFrame({
            'timestamp': ts,
            'open': [100.0 + i for i in range(10)],
            'high': [101.0 + i for i in range(10)],
            'low': [99.0 + i for i in range(10)],
            'close': [100.5 + i for i in range(10)],
            'volume': [1000.0] * 10,
        })
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        result = dm._flush_all_cache_to_csv()

        assert "BTCUSDT" in result
        assert result["BTCUSDT"] is True

        # 验证 CSV 文件已创建
        csv_file = dm.csv_dir / "1m" / "BTCUSDT_1m.csv"
        assert csv_file.exists()

        saved = pd.read_csv(csv_file)
        assert len(saved) == 10
        assert 'timestamp' in saved.columns

    def test_flush_empty_cache(self, dm):
        """空缓存时返回空结果"""
        result = dm._flush_all_cache_to_csv()
        assert result == {}

    def test_flush_without_kline_repo(self, dm):
        """未启用 KlineRepo 时返回空"""
        dm.kline_repo = None
        dm.cache.put("BTCUSDT", "1m", pd.DataFrame(), force_1m=True)
        result = dm._flush_all_cache_to_csv()
        assert result == {}

    def test_flush_multiple_symbols(self, dm):
        """多个 symbol 同时持久化"""
        now = datetime.now(timezone.utc)
        for symbol in ["BTCUSDT", "ETHUSDT"]:
            df = pd.DataFrame({
                'timestamp': [now],
                'open': [100.0], 'high': [101.0], 'low': [99.0],
                'close': [100.5], 'volume': [1000.0],
            })
            dm.cache.put(symbol, "1m", df, force_1m=True)

        result = dm._flush_all_cache_to_csv()

        assert "BTCUSDT" in result
        assert "ETHUSDT" in result
        assert result["BTCUSDT"] is True
        assert result["ETHUSDT"] is True

        btc_csv = dm.csv_dir / "1m" / "BTCUSDT_1m.csv"
        eth_csv = dm.csv_dir / "1m" / "ETHUSDT_1m.csv"
        assert btc_csv.exists()
        assert eth_csv.exists()

    @pytest.mark.asyncio
    async def test_start_periodic_persistence_creates_task(self, dm):
        """启动定时持久化创建后台任务"""
        with patch.object(dm, '_flush_all_cache_to_csv', return_value={}) as mock_flush:
            task = dm.start_periodic_persistence()

            assert task in dm._background_tasks
            assert not task.done()

            # 手动取消，避免影响其他测试
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @pytest.mark.asyncio
    async def test_persistence_loop_runs_periodically(self, dm):
        """定时持久化循环周期性执行"""
        # 使用极短间隔
        dm.config.persistence_interval_minutes = 0  # 0 分钟 = 立即
        call_count = 0

        original_flush = dm._flush_all_cache_to_csv

        def counting_flush():
            nonlocal call_count
            call_count += 1
            return {}

        with patch.object(dm, '_flush_all_cache_to_csv', side_effect=counting_flush):
            task = dm.start_periodic_persistence()

            # 等待几个周期
            await asyncio.sleep(0.3)

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert call_count >= 1

    @pytest.mark.asyncio
    async def test_close_cancels_persistence_tasks(self, dm):
        """close() 取消所有后台任务"""
        task = dm.start_periodic_persistence()
        assert not task.done()

        await dm.close()

        assert len(dm._background_tasks) == 0
        assert task.cancelled() or task.done()
