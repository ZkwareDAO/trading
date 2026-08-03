"""
main.py 数据完整性阻断测试

覆盖:
- _check_data_completeness 调用 is_data_complete 并返回 bool
- 数据完整时 _data_ready = True
- 数据不完整时 _data_ready = False
"""

import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock, PropertyMock

import pandas as pd
import pytest

from data_manager.manager import DataManager, DataManagerConfig


class TestDataReadyFlag:
    """_data_ready 标志设置测试"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_data_ready_true_when_complete(self):
        """数据完整时 _data_ready = True"""
        config = DataManagerConfig(
            csv_dir=self.tmpdir,
            preload_1m_enabled=False,
        )
        dm = DataManager(config)
        dm.connect()

        # 放入完整数据
        now = datetime.now(timezone.utc)
        dates = pd.date_range(now - timedelta(minutes=51), periods=50, freq='1min', tz='UTC')
        df = pd.DataFrame({
            'timestamp': dates,
            'open': [100.0] * 50, 'high': [101.0] * 50,
            'low': [99.0] * 50, 'close': [100.5] * 50, 'volume': [10.0] * 50,
        })
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        result = dm.is_data_complete(["BTCUSDT"])
        assert result["BTCUSDT"] is True

    def test_data_ready_false_when_stale(self):
        """数据过期时 _data_ready = False"""
        config = DataManagerConfig(
            csv_dir=self.tmpdir,
            preload_1m_enabled=False,
        )
        dm = DataManager(config)
        dm.connect()

        # 放入过期数据
        old_base = datetime.now(timezone.utc) - timedelta(minutes=30)
        dates = pd.date_range(old_base - timedelta(minutes=50), periods=50, freq='1min', tz='UTC')
        df = pd.DataFrame({
            'timestamp': dates,
            'open': [100.0] * 50, 'high': [101.0] * 50,
            'low': [99.0] * 50, 'close': [100.5] * 50, 'volume': [10.0] * 50,
        })
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        result = dm.is_data_complete(["BTCUSDT"])
        assert result["BTCUSDT"] is False

    def test_data_ready_false_when_no_cache(self):
        """无缓存时 _data_ready = False"""
        config = DataManagerConfig(
            csv_dir=self.tmpdir,
            preload_1m_enabled=False,
        )
        dm = DataManager(config)
        dm.connect()

        result = dm.is_data_complete(["BTCUSDT"])
        assert result["BTCUSDT"] is False

    def test_data_ready_partial_completeness(self):
        """部分 symbol 完整，部分不完整"""
        config = DataManagerConfig(
            csv_dir=self.tmpdir,
            preload_1m_enabled=False,
        )
        dm = DataManager(config)
        dm.connect()

        # BTCUSDT 完整
        now = datetime.now(timezone.utc)
        dates = pd.date_range(now - timedelta(minutes=51), periods=50, freq='1min', tz='UTC')
        df = pd.DataFrame({
            'timestamp': dates,
            'open': [100.0] * 50, 'high': [101.0] * 50,
            'low': [99.0] * 50, 'close': [100.5] * 50, 'volume': [10.0] * 50,
        })
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        # ETHUSDT 不完整（过期）
        old_base = datetime.now(timezone.utc) - timedelta(minutes=30)
        dates = pd.date_range(old_base - timedelta(minutes=50), periods=50, freq='1min', tz='UTC')
        df = pd.DataFrame({
            'timestamp': dates,
            'open': [100.0] * 50, 'high': [101.0] * 50,
            'low': [99.0] * 50, 'close': [100.5] * 50, 'volume': [10.0] * 50,
        })
        dm.cache.put("ETHUSDT", "1m", df, force_1m=True)

        result = dm.is_data_complete(["BTCUSDT", "ETHUSDT"])
        assert result["BTCUSDT"] is True
        assert result["ETHUSDT"] is False
        assert not all(result.values())  # 整体不完整
