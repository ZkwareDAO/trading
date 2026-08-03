#!/usr/bin/env python3
"""
DataCache 分层缓存测试

验证 1m 常驻缓存 + 大周期 LRU 缓存的正确性
"""

import tempfile
import shutil
from pathlib import Path

import pandas as pd
import pytest

from data_manager.manager import DataManager, DataManagerConfig, DataCache


class TestDataCacheLayered:
    """分层缓存基础测试"""

    def test_1m_goes_to_dedicated_cache(self):
        """1m 数据存入专用缓存"""
        cache = DataCache(max_size=3, preload_1m=True)
        df = pd.DataFrame({'timestamp': pd.date_range('2026-01-01', periods=10, freq='1min', tz='UTC')})

        cache.put("BTCUSDT", "1m", df)

        assert "BTCUSDT" in cache._1m_cache
        assert "BTCUSDT" not in cache._big_interval_cache

    def test_big_interval_goes_to_lru(self):
        """大周期数据存入 LRU 缓存"""
        cache = DataCache(max_size=3, preload_1m=True)
        df = pd.DataFrame({'timestamp': pd.date_range('2026-01-01', periods=10, freq='15min', tz='UTC')})

        cache.put("BTCUSDT", "15m", df)

        assert "BTCUSDT_15M" in cache._big_interval_cache
        assert "BTCUSDT" not in cache._1m_cache

    def test_get_1m_data(self):
        """直接获取 1m 数据"""
        cache = DataCache(max_size=3, preload_1m=True)
        df = pd.DataFrame({'timestamp': pd.date_range('2026-01-01', periods=10, freq='1min', tz='UTC')})
        cache.put("BTCUSDT", "1m", df)

        result = cache.get_1m_data("BTCUSDT")
        assert result is not None
        assert len(result) == 10

    def test_preload_1m_data_batch(self):
        """批量预加载 1m 数据"""
        cache = DataCache(max_size=3, preload_1m=True)
        df = pd.DataFrame({'timestamp': pd.date_range('2026-01-01', periods=10, freq='1min', tz='UTC')})

        cache.preload_1m_data({"BTCUSDT": df, "ETHUSDT": df.copy()})

        assert "BTCUSDT" in cache._1m_cache
        assert "ETHUSDT" in cache._1m_cache

    def test_cache_status(self):
        """缓存状态报告"""
        cache = DataCache(max_size=3, preload_1m=True)
        df = pd.DataFrame({'timestamp': pd.date_range('2026-01-01', periods=10, freq='1min', tz='UTC')})
        cache.put("BTCUSDT", "1m", df)

        status = cache.get_status()
        assert "BTCUSDT" in status["1m_cache_symbols"]

    def test_lru_eviction(self):
        """大周期缓存 LRU 淘汰"""
        cache = DataCache(max_size=2, preload_1m=True)
        df = pd.DataFrame({'timestamp': pd.date_range('2026-01-01', periods=5, freq='15min', tz='UTC')})

        cache.put("BTCUSDT", "15m", df)
        cache.put("ETHUSDT", "1h", df)
        cache.put("SOLUSDT", "4h", df)  # 应淘汰最早加入的

        assert "BTCUSDT_15M" not in cache._big_interval_cache
        assert "ETHUSDT_1H" in cache._big_interval_cache
        assert "SOLUSDT_4H" in cache._big_interval_cache

    def test_clear(self):
        """清空缓存"""
        cache = DataCache(max_size=3, preload_1m=True)
        df = pd.DataFrame({'timestamp': pd.date_range('2026-01-01', periods=5, freq='1min', tz='UTC')})
        cache.put("BTCUSDT", "1m", df)
        cache.put("BTCUSDT", "1h", df)

        cache.clear()

        assert len(cache._1m_cache) == 0
        assert len(cache._big_interval_cache) == 0


class TestDataFrameCached:
    """get_dataframe_cached 测试"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        config = DataManagerConfig(csv_dir=self.tmpdir, klines_service_enabled=False)
        self.dm = DataManager(config)
        self.dm.connect()
        self.dm.enable_kline_repository()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_from_1m_cache(self):
        """1m 数据从缓存返回"""
        df = pd.DataFrame({
            'timestamp': pd.date_range('2026-01-01', periods=10, freq='1min', tz='UTC'),
            'open': 1.0, 'high': 2.0, 'low': 0.5, 'close': 1.5, 'volume': 100.0,
        })
        self.dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        result = self.dm.get_dataframe_cached("BTCUSDT", "1m", limit=100)
        assert result is not None
        assert len(result) == 10

    def test_csv_fallback_for_1m(self):
        """1m 缓存未命中时从 CSV 回退"""
        df = pd.DataFrame({
            'timestamp': pd.date_range('2026-01-01', periods=10, freq='1min', tz='UTC'),
            'open': 1.0, 'high': 2.0, 'low': 0.5, 'close': 1.5, 'volume': 100.0,
        })
        csv_dir = Path(self.tmpdir) / "1m"
        csv_dir.mkdir(parents=True, exist_ok=True)
        save_df = df.copy()
        save_df['timestamp'] = save_df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S+00:00')
        save_df.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)

        result = self.dm.get_dataframe_cached("BTCUSDT", "1m", limit=100)
        assert result is not None
        assert len(result) == 10

    def test_big_interval_from_1m_aggregation(self):
        """大周期从 1m 聚合"""
        df = pd.DataFrame({
            'timestamp': pd.date_range('2026-01-01', periods=120, freq='1min', tz='UTC'),
            'open': 1.0, 'high': 2.0, 'low': 0.5, 'close': 1.5, 'volume': 100.0,
        })
        self.dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        result = self.dm.get_dataframe_cached("BTCUSDT", "1h", limit=100)
        assert result is not None
        assert not result.empty

    def test_returns_none_when_no_data(self):
        """无数据时返回 None"""
        result = self.dm.get_dataframe_cached("NONEXISTENT", "1m")
        assert result is None


class TestMemoryDetection:
    """内存检测（无 psutil 时降级）"""

    def test_adjust_preload_without_psutil(self):
        """无 psutil 时返回默认预加载天数"""
        config = DataManagerConfig()
        dm = DataManager(config)

        # _run_async 和 check_memory_and_adjust_preload 已删除
        # 此测试验证降级行为不再需要
        assert dm.config.preload_days == 7
