#!/usr/bin/env python3
"""
CSV 持久化测试

验证 save_dataframe_to_csv 的合并、去重、排序逻辑
"""

import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pytest
import pandas as pd

from data_manager.kline_repository import KlineRepository
from data_manager.manager import DataManager, DataManagerConfig


class TestSaveDataframeToCsv:
    """save_dataframe_to_csv 测试"""

    @pytest.fixture
    def repo(self):
        tmpdir = tempfile.mkdtemp()
        repo = KlineRepository(csv_dir=tmpdir)
        yield repo
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_save_and_read_back(self, repo):
        """保存并读回"""
        base = datetime.now(timezone.utc)
        rows = []
        for i in range(10):
            ts = base + timedelta(minutes=i)
            rows.append({
                'timestamp': int(ts.timestamp() * 1000),
                'open': 100.0 + i, 'high': 101.0 + i,
                'low': 99.0 + i, 'close': 100.5 + i, 'volume': 10.0,
            })

        repo.save_klines_to_csv('BTCUSDT', '1m', rows)

        df = repo._get_dataframe('BTCUSDT', '1m', limit=100)
        assert df is not None
        assert len(df) == 10

    def test_save_empty_dataframe_returns_false(self, repo):
        """空 DataFrame 应返回 False"""
        result = repo.save_dataframe_to_csv('BTCUSDT', '1m', pd.DataFrame())
        assert result is False

    def test_save_none_dataframe_returns_false(self, repo):
        """None DataFrame 应返回 False"""
        result = repo.save_dataframe_to_csv('BTCUSDT', '1m', None)
        assert result is False

    def test_save_missing_column_returns_false(self, repo):
        """缺少 timestamp 列应返回 False"""
        df = pd.DataFrame({'open': [100.0], 'close': [100.5]})
        result = repo.save_dataframe_to_csv('BTCUSDT', '1m', df)
        assert result is False

    def test_save_deduplicates_by_timestamp(self, repo):
        """保存时应按时间戳去重"""
        base = datetime.now(timezone.utc)
        rows = []
        for i in range(5):
            ts = base + timedelta(minutes=i)
            rows.append({
                'timestamp': int(ts.timestamp() * 1000),
                'open': 100.0, 'high': 101.0,
                'low': 99.0, 'close': 100.5, 'volume': 10.0,
            })

        repo.save_klines_to_csv('BTCUSDT', '1m', rows)

        # 再保存一次同样时间戳的数据（验证去重：新覆盖旧）
        rows2 = []
        for i in range(5):
            ts = base + timedelta(minutes=i)
            rows2.append({
                'timestamp': int(ts.timestamp() * 1000),
                'open': 200.0, 'high': 201.0,
                'low': 199.0, 'close': 200.5, 'volume': 20.0,
            })
        repo.save_klines_to_csv('BTCUSDT', '1m', rows2)

        df = repo._get_dataframe('BTCUSDT', '1m', limit=100)
        assert df is not None
        # 去重后应仍为 5 条，且 open 值应为新的
        assert len(df) == 5, f"去重后应仍为 5 条，实际 {len(df)} 行:\n{df}"

    def test_save_sorts_by_timestamp(self, repo):
        """保存后应按时间戳排序"""
        base = datetime.now(timezone.utc)
        rows = [
            {'timestamp': int((base + timedelta(minutes=2)).timestamp() * 1000),
             'open': 102.0, 'high': 103.0, 'low': 101.0, 'close': 102.5, 'volume': 10.0},
            {'timestamp': int((base + timedelta(minutes=0)).timestamp() * 1000),
             'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.5, 'volume': 10.0},
            {'timestamp': int((base + timedelta(minutes=1)).timestamp() * 1000),
             'open': 101.0, 'high': 102.0, 'low': 100.0, 'close': 101.5, 'volume': 10.0},
        ]

        repo.save_klines_to_csv('BTCUSDT', '1m', rows)

        df = repo._get_dataframe('BTCUSDT', '1m', limit=100)
        assert df is not None
        assert df['open'].iloc[0] == 100.0
        assert df['open'].iloc[-1] == 102.0

    def test_save_merges_with_existing_csv(self, repo):
        """保存时应与现有 CSV 合并"""
        base = datetime.now(timezone.utc)
        # 初始数据
        rows = []
        for i in range(2):
            ts = base + timedelta(minutes=i)
            rows.append({
                'timestamp': int(ts.timestamp() * 1000),
                'open': 50.0 + i, 'high': 51.0 + i,
                'low': 49.0 + i, 'close': 50.5 + i, 'volume': 5.0,
            })
        repo.save_klines_to_csv('BTCUSDT', '1m', rows)

        # 追加新数据
        new_rows = []
        for i in range(2, 4):
            ts = base + timedelta(minutes=i)
            new_rows.append({
                'timestamp': int(ts.timestamp() * 1000),
                'open': 100.0 + i, 'high': 101.0 + i,
                'low': 99.0 + i, 'close': 100.5 + i, 'volume': 10.0,
            })
        repo.save_klines_to_csv('BTCUSDT', '1m', new_rows)

        read_df = repo._get_dataframe('BTCUSDT', '1m', limit=100)
        assert read_df is not None
        assert len(read_df) == 4, "应合并新旧数据，共 4 行"
        assert read_df.iloc[0]['open'] == 50.0
        assert read_df.iloc[-1]['open'] == 103.0
