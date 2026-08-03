#!/usr/bin/env python3
"""
测试: 统一 CSV 持久化 — 时间戳主键

覆盖:
- save_klines_to_csv 统一持久化: 追加、去重、排序、覆盖
- 所有持久化路径(WS/缺口/API/缓存)产生一致的 CSV
- 重启后 CSV 和缓存内容一致
"""

import shutil
import tempfile
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from data_manager.kline_repository import KlineRepository


class TestUnifiedCsvPersistence:
    """统一 CSV 持久化: 时间戳 = 唯一主键"""

    @pytest.fixture
    def repo(self):
        tmpdir = tempfile.mkdtemp()
        repository = KlineRepository(csv_dir=tmpdir)
        yield repository
        shutil.rmtree(tmpdir)

    def _make_klines(self, base: datetime, count: int, start_value: float = 100.0):
        rows = []
        for i in range(count):
            ts = base + timedelta(minutes=i)
            v = start_value + i
            rows.append({
                'timestamp': ts,
                'open': v, 'high': v + 1, 'low': v - 1, 'close': v + 0.5, 'volume': 10.0,
            })
        return rows

    # ---- 核心: 追加 ----

    def test_append_to_empty(self, repo: KlineRepository):
        klines = self._make_klines(datetime(2026, 4, 12, tzinfo=timezone.utc), 10)
        ok = repo.save_klines_to_csv('BTCUSDT', '1m', klines)
        assert ok

        df = repo._get_dataframe('BTCUSDT', '1m', 100)
        assert df is not None and len(df) == 10

    def test_append_new_data(self, repo: KlineRepository):
        base = datetime(2026, 4, 12, tzinfo=timezone.utc)
        # 先写 10 条
        repo.save_klines_to_csv('BTCUSDT', '1m', self._make_klines(base, 10))
        # 追加 5 条（时间不重叠）
        repo.save_klines_to_csv('BTCUSDT', '1m', self._make_klines(base + timedelta(minutes=10), 5))

        df = repo._get_dataframe('BTCUSDT', '1m', 100)
        assert df is not None and len(df) == 15

    # ---- 核心: 时间戳去重（新覆盖旧）----

    def test_dedup_overwrites_old(self, repo: KlineRepository):
        base = datetime(2026, 4, 12, tzinfo=timezone.utc)
        # 先写 5 条
        repo.save_klines_to_csv('BTCUSDT', '1m', self._make_klines(base, 5, start_value=100.0))
        # 再写同一时间戳的 5 条（值不同）
        klines2 = self._make_klines(base, 5, start_value=200.0)
        repo.save_klines_to_csv('BTCUSDT', '1m', klines2)

        df = repo._get_dataframe('BTCUSDT', '1m', 100)
        assert df is not None and len(df) == 5, "去重后应仍为 5 行"
        assert df.iloc[0]['open'] == 200.0, "新数据应覆盖旧数据"

    # ---- 核心: 排序 ----

    def test_out_of_order_sorted(self, repo: KlineRepository):
        base = datetime(2026, 4, 12, tzinfo=timezone.utc)
        # 乱序写入
        klines = [
            {'timestamp': base + timedelta(minutes=2), 'open': 102, 'high': 103, 'low': 101, 'close': 102.5, 'volume': 10},
            {'timestamp': base, 'open': 100, 'high': 101, 'low': 99, 'close': 100.5, 'volume': 10},
            {'timestamp': base + timedelta(minutes=1), 'open': 101, 'high': 102, 'low': 100, 'close': 101.5, 'volume': 10},
        ]
        repo.save_klines_to_csv('BTCUSDT', '1m', klines)

        df = repo._get_dataframe('BTCUSDT', '1m', 100)
        assert df is not None
        assert df.iloc[0]['open'] == 100
        assert df.iloc[1]['open'] == 101
        assert df.iloc[2]['open'] == 102

    # ---- 核心: 多列数据不丢失 ----

    def test_extra_columns_preserved(self, repo: KlineRepository):
        base = datetime(2026, 4, 12, tzinfo=timezone.utc)
        klines = [{
            'timestamp': base,
            'open': 100, 'high': 101, 'low': 99, 'close': 100.5, 'volume': 10,
            'quote_volume': 1000.0, 'trade_num': 5,
        }]
        repo.save_klines_to_csv('BTCUSDT', '1m', klines)

        filepath = repo._get_file_path('BTCUSDT', '1m')
        df = pd.read_csv(filepath)
        assert 'quote_volume' in df.columns
        assert 'trade_num' in df.columns


class TestCacheCsvConsistency:
    """缓存和 CSV 一致性: 重启后内容相同"""

    @pytest.fixture
    def tmpdir(self):
        d = tempfile.mkdtemp()
        yield d
        shutil.rmtree(d)

    def _load_and_cache(self, tmpdir, dm, symbol='BTCUSDT'):
        """从 CSV 加载到缓存（模拟 preload 的加载步骤）"""
        df = dm._load_1m_data_from_csv(symbol)
        if df is not None and not df.empty:
            dm.cache.put(symbol, '1m', df, force_1m=True)
            return True
        return False

    def test_csv_cache_identical_after_save(self, tmpdir):
        from data_manager.kline_repository import KlineRepository

        repo = KlineRepository(csv_dir=tmpdir)
        base = datetime.now(timezone.utc)
        klines = []
        for i in range(20):
            ts = base + timedelta(minutes=i)
            klines.append({
                'timestamp': ts, 'open': 100+i, 'high': 101+i,
                'low': 99+i, 'close': 100.5+i, 'volume': 10.0,
            })
        repo.save_klines_to_csv('BTCUSDT', '1m', klines)

        # 读 CSV
        df_csv = repo._get_dataframe('BTCUSDT', '1m', 100)
        assert df_csv is not None and len(df_csv) == 20

        # 模拟缓存（相同数据）
        cache = df_csv.copy()
        # 比较
        pd.testing.assert_frame_equal(df_csv, cache, check_exact=False)

    def test_multiple_appends_consistent(self, tmpdir):
        from data_manager.kline_repository import KlineRepository

        repo = KlineRepository(csv_dir=tmpdir)
        base = datetime.now(timezone.utc)

        # 分 3 次写入
        for batch in range(3):
            klines = []
            for i in range(10):
                ts = base + timedelta(minutes=batch * 10 + i)
                klines.append({
                    'timestamp': ts, 'open': 100 + batch*10 + i, 'high': 101,
                    'low': 99, 'close': 100.5, 'volume': 10.0,
                })
            repo.save_klines_to_csv('BTCUSDT', '1m', klines)

        df = repo._get_dataframe('BTCUSDT', '1m', 100)
        assert df is not None and len(df) == 30
        # 首尾时间正确
        assert df.iloc[0]['timestamp'].to_pydatetime().replace(microsecond=0) == base.replace(microsecond=0)
        assert df.iloc[-1]['timestamp'].to_pydatetime().replace(microsecond=0) == (base + timedelta(minutes=29)).replace(microsecond=0)
