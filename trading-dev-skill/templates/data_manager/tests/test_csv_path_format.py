#!/usr/bin/env python3
"""
测试 CSV 路径格式固定为 {csv_dir}/{symbol}/{interval}/{symbol}_{interval}.csv

覆盖:
- _get_file_path 返回固定格式路径
- 不再回退旧路径
"""

import tempfile
import shutil
from pathlib import Path

from data_manager.manager import DataManager, DataManagerConfig
from data_manager.kline_repository import KlineRepository


class TestManagerCsvPathFormat:
    """测试 DataManager._get_file_path() 路径格式"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        config = DataManagerConfig(
            csv_dir=self.tmpdir,
            preload_1m_enabled=False,
            klines_service_enabled=False,
        )
        self.dm = DataManager(config)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_path_format_is_interval_symbol(self):
        """路径格式为 {csv_dir}/{interval}/{SYMBOL}_{interval}.csv"""
        path = self.dm._get_file_path("BTCUSDT", "1m")
        assert path == Path(f"{self.tmpdir}/1m/BTCUSDT_1m.csv")

    def test_path_format_uppercase_symbol(self):
        """symbol 自动转大写"""
        path = self.dm._get_file_path("btcusdt", "1h")
        assert path == Path(f"{self.tmpdir}/1h/BTCUSDT_1h.csv")

    def test_path_format_various_intervals(self):
        """各种时间周期路径正确"""
        for interval in ["1m", "5m", "15m", "1h", "4h", "1d"]:
            path = self.dm._get_file_path("ETHUSDT", interval)
            assert path == Path(f"{self.tmpdir}/{interval}/ETHUSDT_{interval}.csv")

    def test_path_does_not_fallback_to_old_format(self):
        """不再回退到旧路径格式"""
        # 创建旧格式路径的文件
        old_path = Path(self.tmpdir) / "BTCUSDT" / "1m" / "BTCUSDT_1m.csv"
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_text("timestamp,open,high,low,close,volume\n")

        # 仍然返回新路径（即使文件不存在）
        new_path = self.dm._get_file_path("BTCUSDT", "1m")
        assert new_path == Path(f"{self.tmpdir}/1m/BTCUSDT_1m.csv")
        # 不应返回旧路径
        assert new_path != old_path


class TestKlineRepositoryCsvPathFormat:
    """测试 KlineRepository._get_file_path() 路径格式"""

    def test_path_format_is_timeframe_symbol(self):
        """路径格式为 {csv_dir}/{timeframe}/{SYMBOL}_{timeframe}.csv"""
        tmpdir = tempfile.mkdtemp()
        repo = KlineRepository(tmpdir)
        path = repo._get_file_path("BTCUSDT", "1m")
        assert path == Path(f"{tmpdir}/1m/BTCUSDT_1m.csv")
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_path_does_not_fallback_to_old_format(self):
        """不再回退到旧路径格式"""
        tmpdir = tempfile.mkdtemp()
        repo = KlineRepository(tmpdir)

        # 创建旧格式路径的文件
        old_path = Path(tmpdir) / "BTCUSDT" / "1m" / "BTCUSDT_1m.csv"
        old_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.write_text("timestamp,open,high,low,close,volume\n")

        # 仍然返回新路径
        new_path = repo._get_file_path("BTCUSDT", "1m")
        assert new_path == Path(f"{tmpdir}/1m/BTCUSDT_1m.csv")
        assert new_path != old_path

        shutil.rmtree(tmpdir, ignore_errors=True)
