"""
KlineRepository.save_klines_to_csv 测试

覆盖:
- 保存新数据（无现有文件）
- 追加数据到已有文件
- 去重（相同 timestamp 覆盖）
- 空数据列表
- 缺少必要列
- 路径格式验证
"""

import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

import pytest

from data_manager.kline_repository import KlineRepository


def _make_klines(count=5, start_ts=None):
    """生成测试 K 线数据（字典格式，含毫秒时间戳）"""
    if start_ts is None:
        start_ts = datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc)
    klines = []
    for i in range(count):
        ts = start_ts
        if hasattr(start_ts, 'timestamp'):
            ts_ms = int(start_ts.timestamp() * 1000) + i * 60000
        else:
            ts_ms = start_ts + i * 60000
        klines.append({
            'timestamp': ts_ms,
            'open': 100.0 + i,
            'high': 105.0 + i,
            'low': 95.0 + i,
            'close': 102.0 + i,
            'volume': 10.0 + i,
        })
    return klines


class TestSaveKlinesToCsvNewData:
    """保存新数据测试"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = KlineRepository(csv_dir=self.tmpdir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_save_new_data_creates_csv(self):
        """保存新数据应创建 CSV 文件"""
        klines = _make_klines(5)
        result = self.repo.save_klines_to_csv("BTCUSDT", "1m", klines)

        assert result is True
        csv_path = Path(self.tmpdir) / "1m" / "BTCUSDT_1m.csv"
        assert csv_path.exists()

    def test_save_new_data_correct_content(self):
        """保存新数据内容正确"""
        klines = _make_klines(3)
        self.repo.save_klines_to_csv("BTCUSDT", "1m", klines)

        df = self.repo._get_dataframe("BTCUSDT", "1m")
        assert df is not None
        assert len(df) == 3
        assert all(col in df.columns for col in ['timestamp', 'open', 'high', 'low', 'close', 'volume'])

    def test_save_new_data_big_interval_path(self):
        """大周期路径格式正确"""
        klines = _make_klines(3)
        self.repo.save_klines_to_csv("ETHUSDT", "4h", klines)

        csv_path = Path(self.tmpdir) / "4h" / "ETHUSDT_4h.csv"
        assert csv_path.exists()


class TestSaveKlinesToCsvMerge:
    """合并数据测试"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = KlineRepository(csv_dir=self.tmpdir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_append_data(self):
        """追加数据应增加行数"""
        klines1 = _make_klines(3)
        self.repo.save_klines_to_csv("BTCUSDT", "1m", klines1)

        klines2 = _make_klines(3, start_ts=datetime(2026, 4, 10, 10, 10, tzinfo=timezone.utc))
        self.repo.save_klines_to_csv("BTCUSDT", "1m", klines2)

        df = self.repo._get_dataframe("BTCUSDT", "1m")
        assert len(df) == 6

    def test_dedup_same_timestamp_overwrites(self):
        """相同 timestamp 的数据应覆盖"""
        base_ts = datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc)
        klines1 = [{
            'timestamp': int(base_ts.timestamp() * 1000),
            'open': 100.0, 'high': 105.0, 'low': 95.0, 'close': 102.0, 'volume': 10.0,
        }]
        self.repo.save_klines_to_csv("BTCUSDT", "1m", klines1)

        klines2 = [{
            'timestamp': int(base_ts.timestamp() * 1000),
            'open': 200.0, 'high': 205.0, 'low': 195.0, 'close': 202.0, 'volume': 20.0,
        }]
        self.repo.save_klines_to_csv("BTCUSDT", "1m", klines2)

        df = self.repo._get_dataframe("BTCUSDT", "1m")
        assert len(df) == 1
        assert df.iloc[0]['close'] == 202.0


class TestSaveKlinesToCsvEdgeCases:
    """边界条件测试"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = KlineRepository(csv_dir=self.tmpdir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_empty_klines_returns_false(self):
        """空列表应返回 False"""
        result = self.repo.save_klines_to_csv("BTCUSDT", "1m", [])
        assert result is False

    def test_missing_required_column_returns_false(self):
        """缺少必要列应返回 False"""
        klines = [{'open': 100.0, 'high': 105.0}]  # 缺少 timestamp 等
        result = self.repo.save_klines_to_csv("BTCUSDT", "1m", klines)
        assert result is False

    def test_case_insensitive_symbol(self):
        """symbol 大小写不敏感"""
        klines = _make_klines(2)
        self.repo.save_klines_to_csv("btcusdt", "1m", klines)

        csv_path = Path(self.tmpdir) / "1m" / "BTCUSDT_1m.csv"
        assert csv_path.exists()

    def test_case_insensitive_interval(self):
        """interval 大小写不敏感"""
        klines = _make_klines(2)
        self.repo.save_klines_to_csv("BTCUSDT", "1H", klines)

        csv_path = Path(self.tmpdir) / "1h" / "BTCUSDT_1h.csv"
        assert csv_path.exists()
