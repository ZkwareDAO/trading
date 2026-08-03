#!/usr/bin/env python3
"""
1m 缓存限制测试

验证 manage_memory_cache 方法 enforce 行数和年龄限制
"""

import tempfile
import shutil
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from data_manager.manager import DataManager, DataManagerConfig, DataCache


class TestCacheLimits:
    """缓存限制通过 manage_memory_cache 执行"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_row_limit_enforcement(self):
        config = DataManagerConfig(
            csv_dir=self.tmpdir,
            cache_1m_max_rows=1000,
            klines_service_enabled=False,
        )
        dm = DataManager(config)
        dm.connect()

        df = pd.DataFrame({
            'timestamp': pd.date_range(
                start=datetime.now(timezone.utc) - timedelta(minutes=1499),
                periods=1500, freq='1min', tz='UTC',
            ),
            'open': [float(i) for i in range(1500)],
            'high': [float(i + 100) for i in range(1500)],
            'low': [float(i - 100) for i in range(1500)],
            'close': [float(i + 200) for i in range(1500)],
            'volume': [1000.0 + i for i in range(1500)],
        })
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        dm.manage_memory_cache("BTCUSDT")

        cached_df = dm.cache.get_1m_data("BTCUSDT")
        assert cached_df is not None
        assert len(cached_df) <= 1000

    def test_age_limit_enforcement(self):
        config = DataManagerConfig(
            csv_dir=self.tmpdir,
            cache_1m_max_age_days=30,
            klines_service_enabled=False,
        )
        dm = DataManager(config)
        dm.connect()

        old_df = pd.DataFrame({
            'timestamp': pd.date_range('2020-01-01', periods=100, freq='1min', tz='UTC'),
            'open': [float(i) for i in range(100)],
            'high': [float(i + 10) for i in range(100)],
            'low': [float(i - 10) for i in range(100)],
            'close': [float(i + 20) for i in range(100)],
            'volume': [100.0] * 100,
        })
        dm.cache.put("OLDUSDT", "1m", old_df, force_1m=True)

        dm.manage_memory_cache("OLDUSDT")

        cached_df = dm.cache.get_1m_data("OLDUSDT")
        assert cached_df is None or len(cached_df) == 0

    def test_recent_data_kept(self):
        config = DataManagerConfig(csv_dir=self.tmpdir, klines_service_enabled=False)
        dm = DataManager(config)
        dm.connect()

        now = datetime.now(timezone.utc)
        df = pd.DataFrame({
            'timestamp': [now - timedelta(minutes=i) for i in range(50, 0, -1)],
            'open': [float(i) for i in range(50)],
            'high': [float(i + 1) for i in range(50)],
            'low': [float(i - 1) for i in range(50)],
            'close': [float(i + 0.5) for i in range(50)],
            'volume': [100.0] * 50,
        })
        dm.cache.put("RECENTUSDT", "1m", df, force_1m=True)

        dm.manage_memory_cache("RECENTUSDT")

        cached = dm.cache.get_1m_data("RECENTUSDT")
        assert cached is not None
        assert len(cached) == 50

    def test_cache_status_format(self):
        config = DataManagerConfig(csv_dir=self.tmpdir, klines_service_enabled=False)
        dm = DataManager(config)
        dm.connect()

        df = pd.DataFrame({
            'timestamp': pd.date_range('2026-01-01', periods=10, freq='1min', tz='UTC'),
            'open': [1.0] * 10, 'high': [2.0] * 10,
            'low': [0.5] * 10, 'close': [1.5] * 10, 'volume': [100.0] * 10,
        })
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)
        dm.cache.put("ETHUSDT", "1m", df.copy(), force_1m=True)

        status = dm.cache.get_status()
        assert len(status["1m_cache_symbols"]) == 2
        assert len(status["1m_cache_sizes"]) == 2

    def test_multiple_symbols_row_limit(self):
        config = DataManagerConfig(
            csv_dir=self.tmpdir,
            cache_1m_max_rows=100,
            klines_service_enabled=False,
        )
        dm = DataManager(config)
        dm.connect()

        for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            df = pd.DataFrame({
                'timestamp': pd.date_range('2026-01-01', periods=200, freq='1min', tz='UTC'),
                'open': [float(i) for i in range(200)],
                'high': [float(i + 1) for i in range(200)],
                'low': [float(i - 1) for i in range(200)],
                'close': [float(i + 0.5) for i in range(200)],
                'volume': [100.0] * 200,
            })
            dm.cache.put(symbol, "1m", df, force_1m=True)
            dm.manage_memory_cache(symbol)

            cached = dm.cache.get_1m_data(symbol)
            assert cached is not None
            assert len(cached) <= 100

        status = dm.cache.get_status()
        assert len(status["1m_cache_symbols"]) == 3

    def test_config_defaults(self):
        config = DataManagerConfig()
        assert config.cache_1m_max_rows > 0
        assert config.cache_1m_max_age_days > 0

    def test_cache_without_config(self):
        cache = DataCache(max_size=10, preload_1m=True)
        dates = pd.date_range('2026-01-01', periods=1000, freq='1min', tz='UTC')
        df = pd.DataFrame({
            'timestamp': dates,
            'open': [float(i) for i in range(1000)],
            'high': [float(i + 10) for i in range(1000)],
            'low': [float(i - 10) for i in range(1000)],
            'close': [float(i + 20) for i in range(1000)],
            'volume': [float(i + 100) for i in range(1000)],
        })
        cache.put("NOCONFIG", "1m", df, force_1m=True)

        cached_df = cache.get("NOCONFIG", "1m")
        assert cached_df is not None
        assert len(cached_df) == 1000
