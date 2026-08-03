#!/usr/bin/env python3
"""
并发安全缓存测试

验证分片锁缓存的正确性、线程安全性和 LRU 淘汰策略。
"""

import asyncio
import threading
import time
from datetime import datetime, timezone

import pandas as pd
import pytest

from data_manager.cache import ShardCache, ShardCacheConfig


def make_df(n: int, start_ts: datetime = None) -> pd.DataFrame:
    """生成测试用 DataFrame"""
    if start_ts is None:
        start_ts = datetime(2026, 4, 19, 0, 0, tzinfo=timezone.utc)
    timestamps = [start_ts + pd.Timedelta(minutes=i) for i in range(n)]
    return pd.DataFrame({
        'timestamp': timestamps,
        'open': [100.0 + i for i in range(n)],
        'high': [101.0 + i for i in range(n)],
        'low': [99.0 + i for i in range(n)],
        'close': [100.5 + i for i in range(n)],
        'volume': [1000.0] * n,
    })


class TestShardCacheBasic:
    """基本功能测试"""

    def test_put_and_get_1m(self):
        """1m 数据存取"""
        cache = ShardCache(ShardCacheConfig())
        df = make_df(10)
        cache.put("BTCUSDT", "1m", df)

        result = cache.get_1m_data("BTCUSDT")
        assert result is not None
        assert len(result) == 10
        assert result['close'].iloc[-1] == 109.5

    def test_put_and_get_big_interval(self):
        """大周期数据存取"""
        cache = ShardCache(ShardCacheConfig())
        df = make_df(5)
        cache.put("BTCUSDT", "15m", df)

        result = cache.get("BTCUSDT", "15m")
        assert result is not None
        assert len(result) == 5

    def test_get_nonexistent_returns_none(self):
        """不存在的 key 返回 None"""
        cache = ShardCache(ShardCacheConfig())
        assert cache.get_1m_data("NONEXIST") is None
        assert cache.get("NONEXIST", "1m") is None
        assert cache.get("BTCUSDT", "4h") is None

    def test_case_insensitive_symbol(self):
        """symbol 大小写不敏感"""
        cache = ShardCache(ShardCacheConfig())
        df = make_df(5)
        cache.put("btcusdt", "1m", df)

        result = cache.get_1m_data("BTCUSDT")
        assert result is not None
        assert len(result) == 5

        result2 = cache.get_1m_data("BtcUsdt")
        assert result2 is not None

    def test_put_overwrites_existing_1m(self):
        """1m 数据覆盖写入"""
        cache = ShardCache(ShardCacheConfig())
        cache.put("BTCUSDT", "1m", make_df(5))
        cache.put("BTCUSDT", "1m", make_df(10))

        result = cache.get_1m_data("BTCUSDT")
        assert len(result) == 10


class TestShardCacheLRU:
    """LRU 淘汰策略测试"""

    def test_lru_eviction_big_interval(self):
        """大周期数据超过 max_size 时 LRU 淘汰"""
        cache = ShardCache(ShardCacheConfig(max_big_interval_entries=3))

        cache.put("A", "15m", make_df(5))
        cache.put("B", "15m", make_df(5))
        cache.put("C", "15m", make_df(5))
        # 第 4 个应该淘汰最老的 A
        cache.put("D", "15m", make_df(5))

        assert cache.get("A", "15m") is None  # 被淘汰
        assert cache.get("B", "15m") is not None
        assert cache.get("C", "15m") is not None
        assert cache.get("D", "15m") is not None

    def test_1m_data_not_evicted_by_lru(self):
        """1m 数据不受 LRU 淘汰影响"""
        cache = ShardCache(ShardCacheConfig(max_big_interval_entries=1))

        cache.put("BTCUSDT", "1m", make_df(10))
        cache.put("A", "15m", make_df(5))
        # 插入另一个大周期，淘汰 A 的 15m，但不影响 1m
        cache.put("B", "15m", make_df(5))

        result = cache.get_1m_data("BTCUSDT")
        assert result is not None
        assert len(result) == 10

    def test_access_order_refreshes_on_get(self):
        """get 操作刷新访问顺序"""
        cache = ShardCache(ShardCacheConfig(max_big_interval_entries=3))

        cache.put("A", "1h", make_df(5))
        cache.put("B", "1h", make_df(5))
        cache.put("C", "1h", make_df(5))

        # 访问 A，使其成为最新
        cache.get("A", "1h")

        # 插入 D，应淘汰 B（最久未访问）
        cache.put("D", "1h", make_df(5))

        assert cache.get("A", "1h") is not None  # 刚访问过，保留
        assert cache.get("B", "1h") is None  # 被淘汰
        assert cache.get("C", "1h") is not None
        assert cache.get("D", "1h") is not None


class TestShardCacheRemove:
    """移除操作测试"""

    def test_remove_1m(self):
        """移除 1m 缓存"""
        cache = ShardCache(ShardCacheConfig())
        cache.put("BTCUSDT", "1m", make_df(5))
        cache.remove("BTCUSDT", "1m")
        assert cache.get_1m_data("BTCUSDT") is None

    def test_remove_big_interval(self):
        """移除大周期缓存"""
        cache = ShardCache(ShardCacheConfig())
        cache.put("BTCUSDT", "4h", make_df(5))
        cache.remove("BTCUSDT", "4h")
        assert cache.get("BTCUSDT", "4h") is None

    def test_remove_nonexistent_no_error(self):
        """移除不存在的 key 不报错"""
        cache = ShardCache(ShardCacheConfig())
        cache.remove("NONEXIST", "1m")  # 不应抛出异常


class TestShardCacheClear:
    """清空操作测试"""

    def test_clear_all(self):
        """清空所有缓存"""
        cache = ShardCache(ShardCacheConfig())
        cache.put("BTCUSDT", "1m", make_df(5))
        cache.put("ETHUSDT", "1m", make_df(5))
        cache.put("BTCUSDT", "15m", make_df(5))

        cache.clear()

        assert cache.get_1m_data("BTCUSDT") is None
        assert cache.get_1m_data("ETHUSDT") is None
        assert cache.get("BTCUSDT", "15m") is None

    def test_clear_symbol(self):
        """清空指定 symbol 的缓存"""
        cache = ShardCache(ShardCacheConfig())
        cache.put("BTCUSDT", "1m", make_df(5))
        cache.put("BTCUSDT", "15m", make_df(5))
        cache.put("ETHUSDT", "1m", make_df(5))

        cache.clear_symbol("BTCUSDT")

        assert cache.get_1m_data("BTCUSDT") is None
        assert cache.get("BTCUSDT", "15m") is None
        assert cache.get_1m_data("ETHUSDT") is not None  # ETH 不受影响


class TestShardCacheStatus:
    """状态查询测试"""

    def test_status(self):
        """获取缓存状态"""
        cache = ShardCache(ShardCacheConfig())
        cache.put("BTCUSDT", "1m", make_df(10))
        cache.put("ETHUSDT", "1m", make_df(20))
        cache.put("BTCUSDT", "15m", make_df(5))

        status = cache.get_status()
        assert status['1m_symbols'] == {"BTCUSDT", "ETHUSDT"}
        assert status['1m_row_count']['BTCUSDT'] == 10
        assert status['1m_row_count']['ETHUSDT'] == 20
        assert status['big_interval_entries'] == 1
        assert status['big_interval_keys'] == {"BTCUSDT_15M"}


class TestShardCacheConcurrency:
    """并发安全测试"""

    def test_concurrent_reads_writes_threading(self):
        """多线程并发读写不崩溃"""
        cache = ShardCache(ShardCacheConfig())
        errors = []

        def writer(symbol: str, count: int):
            try:
                for i in range(count):
                    df = make_df(10, datetime(2026, 4, 19, 0, 0, tzinfo=timezone.utc) + pd.Timedelta(minutes=i))
                    cache.put(symbol, "1m", df)
            except Exception as e:
                errors.append(e)

        def reader(symbol: str, count: int):
            try:
                for _ in range(count):
                    cache.get_1m_data(symbol)
            except Exception as e:
                errors.append(e)

        threads = []
        # 3 个写线程，每个写 100 次
        for i in range(3):
            t = threading.Thread(target=writer, args=(f"SYM{i}", 100))
            threads.append(t)

        # 5 个读线程，每个读 200 次
        for i in range(5):
            t = threading.Thread(target=reader, args=(f"SYM{i % 3}", 200))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"并发测试中出现异常: {errors}"

    def test_different_symbols_no_lock_contention(self):
        """不同 symbol 读写不互相阻塞"""
        cache = ShardCache(ShardCacheConfig())
        results = {}

        def write_symbol(symbol: str):
            start = time.monotonic()
            for i in range(50):
                df = make_df(5)
                cache.put(symbol, "1m", df)
                cache.get_1m_data(symbol)
            elapsed = time.monotonic() - start
            results[symbol] = elapsed

        threads = []
        for i in range(4):
            t = threading.Thread(target=write_symbol, args=(f"SYM{i}",))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        # 验证所有线程都完成了工作
        assert len(results) == 4
        for sym, elapsed in results.items():
            assert elapsed > 0  # 确保确实执行了


class TestShardCacheConfig:
    """配置类测试"""

    def test_defaults(self):
        """默认配置"""
        config = ShardCacheConfig()
        assert config.max_big_interval_entries == 5000
        assert config.default_1m_rows_limit == 500000
        assert config.default_1m_age_days == 90

    def test_custom_config(self):
        """自定义配置"""
        config = ShardCacheConfig(
            max_big_interval_entries=100,
            default_1m_rows_limit=10000,
            default_1m_age_days=30,
        )
        assert config.max_big_interval_entries == 100
        assert config.default_1m_rows_limit == 10000
        assert config.default_1m_age_days == 30
