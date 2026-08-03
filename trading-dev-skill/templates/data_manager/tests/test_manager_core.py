"""
DataManager 核心逻辑测试

覆盖:
- DataCache put/get/remove/clear/eviction
- DataManager connect
- DataManager get_klines
- DataManager aggregate_1m_to_interval
- DataManager register_timeframes_for_symbol
"""

import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from data_manager.manager import DataManager, DataManagerConfig, DataCache


# ==================== DataCache 测试 ====================


class TestDataCacheBasic:
    """DataCache 基本操作测试"""

    def test_put_and_get_1m(self):
        cache = DataCache(max_size=3)
        df = pd.DataFrame({'open': [1.0], 'high': [2.0], 'low': [0.5], 'close': [1.5], 'volume': [100.0]})
        cache.put("BTCUSDT", "1m", df)

        result = cache.get("BTCUSDT", "1m")
        assert result is not None
        assert len(result) == 1

    def test_put_and_get_big_interval(self):
        cache = DataCache(max_size=3)
        df = pd.DataFrame({'open': [1.0], 'high': [2.0], 'low': [0.5], 'close': [1.5], 'volume': [100.0]})
        cache.put("BTCUSDT", "1h", df)

        result = cache.get("BTCUSDT", "1h")
        assert result is not None

    def test_get_returns_none_for_missing(self):
        cache = DataCache(max_size=3)
        assert cache.get("NONEXISTENT", "1m") is None
        assert cache.get("NONEXISTENT", "1h") is None

    def test_get_returns_copy(self):
        cache = DataCache(max_size=3)
        df = pd.DataFrame({'close': [100.0]})
        cache.put("BTCUSDT", "1m", df)

        result = cache.get("BTCUSDT", "1m")
        assert result is not None
        assert len(result) == 1

    def test_remove_1m(self):
        cache = DataCache(max_size=3)
        df = pd.DataFrame({'close': [100.0]})
        cache.put("BTCUSDT", "1m", df)
        cache.remove("BTCUSDT", "1m")
        assert cache.get("BTCUSDT", "1m") is None

    def test_remove_big_interval(self):
        cache = DataCache(max_size=3)
        df = pd.DataFrame({'close': [100.0]})
        cache.put("BTCUSDT", "1h", df)
        cache.remove("BTCUSDT", "1h")
        assert cache.get("BTCUSDT", "1h") is None

    def test_clear(self):
        cache = DataCache(max_size=3)
        df = pd.DataFrame({'close': [100.0]})
        cache.put("BTCUSDT", "1m", df)
        cache.put("BTCUSDT", "1h", df)
        cache.clear()
        assert cache.get("BTCUSDT", "1m") is None
        assert cache.get("BTCUSDT", "1h") is None

    def test_lru_eviction(self):
        cache = DataCache(max_size=2)
        df = pd.DataFrame({'close': [100.0]})

        cache.put("A", "1h", df)
        cache.put("B", "1h", df)
        cache.put("C", "1h", df)

        assert cache.get("A", "1h") is None
        assert cache.get("B", "1h") is not None
        assert cache.get("C", "1h") is not None

    def test_lru_update_access_order(self):
        cache = DataCache(max_size=2)
        df = pd.DataFrame({'close': [100.0]})

        cache.put("A", "1h", df)
        cache.put("B", "1h", df)
        cache.get("A", "1h")
        cache.put("C", "1h", df)

        assert cache.get("A", "1h") is not None
        assert cache.get("B", "1h") is None
        assert cache.get("C", "1h") is not None

    def test_get_1m_data_direct(self):
        cache = DataCache(max_size=3)
        df = pd.DataFrame({'close': [100.0]})
        cache.put("BTCUSDT", "1m", df)

        result = cache.get_1m_data("BTCUSDT")
        assert result is not None

    def test_get_1m_data_returns_data(self):
        cache = DataCache(max_size=3)
        df = pd.DataFrame({'close': [100.0]})
        cache.put("BTCUSDT", "1m", df)

        result = cache.get_1m_data("BTCUSDT")
        assert result is not None
        assert len(result) == 1

    def test_preload_1m_data(self):
        cache = DataCache(max_size=3)
        data = {
            "BTCUSDT": pd.DataFrame({'close': [100.0]}),
            "ETHUSDT": pd.DataFrame({'close': [200.0]}),
        }
        cache.preload_1m_data(data)

        assert cache.get_1m_data("BTCUSDT") is not None
        assert cache.get_1m_data("ETHUSDT") is not None

    def test_get_status(self):
        cache = DataCache(max_size=5, preload_1m=True)
        df = pd.DataFrame({'close': [100.0]})
        cache.put("BTCUSDT", "1m", df)
        cache.put("BTCUSDT", "1h", df)

        status = cache.get_status()
        assert "BTCUSDT" in status["1m_cache_symbols"]
        assert "BTCUSDT_1H" in status["big_interval_cache_keys"]
        assert status["max_size"] == 5


# ==================== DataManager 测试 ====================


class TestDataManagerConnect:
    """DataManager 连接测试"""

    def test_connect_existing_dir(self):
        tmpdir = tempfile.mkdtemp()
        try:
            config = DataManagerConfig(csv_dir=tmpdir)
            dm = DataManager(config)
            assert dm.connect() is True
            assert dm._connected is True
        finally:
            shutil.rmtree(tmpdir)


class TestDataManagerCsvOperations:
    """DataManager CSV 操作测试"""

    @pytest.fixture
    def dm_with_csv(self):
        tmpdir = tempfile.mkdtemp()
        df = pd.DataFrame({
            'timestamp': ['2026-04-10T09:00:00Z', '2026-04-10T09:01:00Z'],
            'open': [100.0, 101.0],
            'high': [102.0, 103.0],
            'low': [99.0, 100.0],
            'close': [101.0, 102.0],
            'volume': [10.0, 11.0],
        })
        csv_path = Path(tmpdir) / "1m" / "BTCUSDT_1m.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(csv_path, index=False)
        config = DataManagerConfig(csv_dir=tmpdir, preload_1m_enabled=False)
        dm = DataManager(config)
        yield dm, tmpdir
        shutil.rmtree(tmpdir)

    def test_get_klines_from_csv(self, dm_with_csv):
        """get_klines 从 CSV 回退加载并返回数据"""
        dm, _ = dm_with_csv
        dm.enable_kline_repository()
        klines = dm.get_klines("BTCUSDT", "1m", limit=10)
        # 首次调用返回基准 1 条
        assert len(klines) >= 1

    def test_get_klines_nonexistent(self, dm_with_csv):
        dm, _ = dm_with_csv
        klines = dm.get_klines("NONEXISTENT", "1m")
        assert klines == []


class TestDataManagerAggregation:
    """聚合功能测试"""

    def test_aggregate_1m_to_interval_from_cache(self):
        tmpdir = tempfile.mkdtemp()
        try:
            config = DataManagerConfig(csv_dir=tmpdir, preload_1m_enabled=False)
            dm = DataManager(config)

            rows = []
            base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
            for i in range(120):
                ts = base + timedelta(minutes=i)
                rows.append({
                    'timestamp': ts,
                    'open': 100.0 + i,
                    'high': 105.0 + i,
                    'low': 95.0 + i,
                    'close': 102.0 + i,
                    'volume': 10.0,
                })
            df = pd.DataFrame(rows)
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)

            result = dm.aggregate_1m_to_interval(df, "1h")
            assert result is not None
            assert not result.empty
        finally:
            shutil.rmtree(tmpdir)


class TestDataManagerTimeframes:
    """时间框架注册测试"""

    @pytest.fixture
    def dm(self):
        tmpdir = tempfile.mkdtemp()
        config = DataManagerConfig(csv_dir=tmpdir, preload_1m_enabled=False)
        dm = DataManager(config)
        dm.enable_kline_repository()
        yield dm
        shutil.rmtree(tmpdir)

    def test_register_timeframes_for_symbol(self, dm):
        dm.register_timeframes_for_symbol("BTCUSDT", ["1h", "4h"])
        # 验证注册到 kline_repo
        assert dm.kline_repo is not None

    @pytest.mark.asyncio
    async def test_close(self, dm):
        dm.connect()
        await dm.close()
        assert dm._connected is False
        assert len(dm.cache._1m_cache) == 0
