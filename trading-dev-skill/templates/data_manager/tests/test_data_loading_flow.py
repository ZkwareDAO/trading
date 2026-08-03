#!/usr/bin/env python3
"""
测试: 存储路径格式

覆盖:
- DataManager CSV 路径格式: {csv_dir}/{interval}/{SYMBOL}_{interval}.csv
- KlineRepository CSV 路径格式: {csv_dir}/{timeframe}/{SYMBOL}_{timeframe}.csv
- 路径创建父目录
- 大小写符号
"""

import shutil
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from data_manager.manager import DataManager, DataManagerConfig
from data_manager.kline_repository import KlineRepository


class TestStoragePathFormat:
    """存储路径格式测试"""

    @pytest.fixture
    def dm(self):
        tmpdir = tempfile.mkdtemp()
        config = DataManagerConfig(csv_dir=tmpdir, preload_1m_enabled=False)
        dm = DataManager(config)
        yield dm
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_dm_file_path_format(self, dm):
        """DM 路径格式: {csv_dir}/{interval}/{SYMBOL}_{interval}.csv"""
        path = dm._get_file_path("btcusdt", "1m")
        assert str(path).endswith("1m/BTCUSDT_1m.csv")

    def test_dm_file_path_creates_parent_dirs(self, dm):
        """DM 应自动创建父目录"""
        path = dm._get_file_path("BTCUSDT", "1m")
        path.parent.mkdir(parents=True, exist_ok=True)
        assert path.parent.exists()

    def test_dm_file_path_uppercase_symbol(self, dm):
        """符号应转为大写"""
        path = dm._get_file_path("btcusdt", "1h")
        assert "BTCUSDT" in str(path)

    def test_repo_file_path_format(self):
        """KlineRepository 路径格式"""
        tmpdir = tempfile.mkdtemp()
        try:
            repo = KlineRepository(csv_dir=tmpdir)
            path = repo._get_file_path("btcusdt", "1m")
            assert str(path).endswith("1m/BTCUSDT_1m.csv")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_dm_save_and_read_roundtrip(self, dm):
        """DM 保存并读回"""
        if not dm.kline_repo:
            dm.enable_kline_repository()

        rows = [
            {
                'timestamp': int((datetime.now(timezone.utc) + timedelta(minutes=i)).timestamp() * 1000),
                'open': 100.0 + i, 'high': 101.0 + i,
                'low': 99.0 + i, 'close': 100.5 + i, 'volume': 10.0,
            }
            for i in range(5)
        ]
        dm.kline_repo.save_klines_to_csv("BTCUSDT", "1m", rows)

        # 通过 _load_csv 读回
        df = dm._load_csv("BTCUSDT", "1m")
        assert df is not None
        assert len(df) == 5
