#!/usr/bin/env python3
"""
测试: DataManager.manage_memory_cache 方法

按 cache_1m_max_age_days / cache_1m_max_rows 裁剪 1m 内存缓存
"""

import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from data_manager.manager import DataManager, DataManagerConfig


class TestManageMemoryCache:

    def _make_manager(self, tmp_path: Path,
                      max_age_days: int | None = None) -> DataManager:
        kwargs = {}
        if max_age_days is not None:
            kwargs["cache_1m_max_age_days"] = max_age_days
        config = DataManagerConfig(
            csv_dir=str(tmp_path / "klines"),
            realtime_enabled=True,
            **kwargs,
        )
        dm = DataManager(config)
        dm.enable_kline_repository()
        return dm

    def _make_mixed_age_df(self):
        """生成包含新旧混合数据的 DataFrame"""
        now = datetime.now(timezone.utc)
        rows = []
        # 旧数据：3 天前
        for i in range(10):
            ts = now - timedelta(days=3, minutes=i)
            rows.append({
                'timestamp': ts,
                'open': 49000.0, 'high': 49100.0, 'low': 48900.0,
                'close': 49050.0, 'volume': 50.0,
            })
        # 新数据：最近 10 分钟
        for i in range(20):
            ts = now - timedelta(minutes=20 - i)
            rows.append({
                'timestamp': ts,
                'open': 50000.0, 'high': 50100.0, 'low': 49900.0,
                'close': 50050.0, 'volume': 100.0,
            })
        return pd.DataFrame(rows)

    def test_manage_memory_cache_removes_old_data(self, tmp_path):
        """测试淘汰超过 cache_1m_max_age_days 的旧数据"""
        dm = self._make_manager(tmp_path, max_age_days=2)
        df = self._make_mixed_age_df()
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        # 初始有 30 条
        assert len(dm.cache.get_1m_data("BTCUSDT")) == 30

        dm.manage_memory_cache("BTCUSDT")

        # 应该只保留近 2 天内的数据（20 条新数据）
        cached = dm.cache.get_1m_data("BTCUSDT")
        assert cached is not None
        assert len(cached) == 20

        # 验证保留的都是近 2 天内的
        cutoff = datetime.now(timezone.utc) - timedelta(days=2)
        for ts in cached['timestamp']:
            ts_dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            assert ts_dt >= cutoff

    def test_age_limit_follows_config(self, tmp_path):
        """max_age_days 必须来自配置，不得硬编码。

        同一份数据（含 3 天前的旧数据）在 max_age_days=2 时被裁剪，
        在 max_age_days=90 时应完整保留。
        """
        dm_strict = self._make_manager(tmp_path, max_age_days=2)
        dm_strict.cache.put("BTCUSDT", "1m", self._make_mixed_age_df(),
                            force_1m=True)
        dm_strict.manage_memory_cache("BTCUSDT")
        assert len(dm_strict.cache.get_1m_data("BTCUSDT")) == 20

        dm_loose = self._make_manager(tmp_path, max_age_days=90)
        dm_loose.cache.put("BTCUSDT", "1m", self._make_mixed_age_df(),
                           force_1m=True)
        dm_loose.manage_memory_cache("BTCUSDT")
        assert len(dm_loose.cache.get_1m_data("BTCUSDT")) == 30

    def test_manage_memory_cache_no_data(self, tmp_path):
        """测试无数据时不报错"""
        dm = self._make_manager(tmp_path)
        # 不应该抛异常
        dm.manage_memory_cache("BTCUSDT")

    def test_manage_memory_cache_all_fresh(self, tmp_path):
        """测试数据全部在 2 天内时不被淘汰"""
        dm = self._make_manager(tmp_path)
        now = datetime.now(timezone.utc)
        rows = []
        for i in range(100):
            ts = now - timedelta(minutes=i)
            rows.append({
                'timestamp': ts,
                'open': 50000.0, 'high': 50100.0, 'low': 49900.0,
                'close': 50050.0, 'volume': 100.0,
            })
        df = pd.DataFrame(rows)
        dm.cache.put("ETHUSDT", "1m", df, force_1m=True)

        dm.manage_memory_cache("ETHUSDT")

        cached = dm.cache.get_1m_data("ETHUSDT")
        assert cached is not None
        assert len(cached) == 100

    def test_manage_memory_cache_enforces_row_limit(self, tmp_path):
        """测试超过行数上限时裁剪"""
        dm = self._make_manager(tmp_path)
        now = datetime.now(timezone.utc)
        # 生成超过 500,000 行（用较少的行模拟，通过降低配置阈值）
        dm.config.cache_1m_max_rows = 100
        rows = []
        for i in range(200):
            ts = now - timedelta(minutes=i)
            rows.append({
                'timestamp': ts,
                'open': 50000.0, 'high': 50100.0, 'low': 49900.0,
                'close': 50050.0, 'volume': 100.0,
            })
        df = pd.DataFrame(rows)
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        dm.manage_memory_cache("BTCUSDT")

        cached = dm.cache.get_1m_data("BTCUSDT")
        assert cached is not None
        assert len(cached) == 100
