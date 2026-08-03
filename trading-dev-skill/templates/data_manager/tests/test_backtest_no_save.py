"""Tests for backtest mode K-line storage behavior."""

import sys
from pathlib import Path
from datetime import datetime, timezone
import tempfile

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


class TestBacktestModeNoSave:
    """Test that backtest mode does not save K-lines to CSV."""

    def test_on_kline_received_no_save_in_backtest_mode(self):
        """回测模式下 _on_kline_received 不保存大周期 CSV"""
        from data_manager import DataManager, DataManagerConfig, Kline
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建回测模式 DataManager
            dm_config = DataManagerConfig(
                csv_dir=tmpdir,
                backtest_mode=True,
                preload_1m_enabled=False,
                klines_service_enabled=False,
            )
            dm = DataManager(dm_config)
            dm.connect()

            # 准备 1m 数据到缓存
            now = datetime.now(timezone.utc)
            df_1m = pd.DataFrame({
                'timestamp': pd.date_range(now - pd.Timedelta(hours=5), periods=300, freq='1min'),
                'open': [100.0] * 300,
                'high': [105.0] * 300,
                'low': [95.0] * 300,
                'close': [102.0] * 300,
                'volume': [1000.0] * 300,
            })
            dm.cache.put("BTCUSDT", "1m", df_1m, force_1m=True)

            # 注册大周期
            dm.register_timeframes("BTCUSDT", ["4h"])

            # 模拟回测时 _on_kline_received 被调用
            kline = Kline(
                symbol="BTCUSDT",
                interval="1m",
                timestamp=now,
                open=100.0,
                high=105.0,
                low=95.0,
                close=102.0,
                volume=1000.0,
            )
            dm._on_kline_received(kline)

            # 验证：缓存有数据
            cached_4h = dm.cache.get("BTCUSDT", "4h")
            assert cached_4h is not None, "缓存应有 4h 数据"

            # 验证：CSV 文件不应存在（回测模式不保存）
            csv_path = Path(tmpdir) / "4h" / "BTCUSDT_4h.csv"
            assert not csv_path.exists(), f"回测模式不应保存 CSV 文件: {csv_path}"

    def test_on_kline_received_saves_in_normal_mode(self):
        """正常模式下 _on_kline_received 保存大周期 CSV"""
        from data_manager import DataManager, DataManagerConfig, Kline
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建正常模式 DataManager
            dm_config = DataManagerConfig(
                csv_dir=tmpdir,
                backtest_mode=False,  # 正常模式
                preload_1m_enabled=False,
                klines_service_enabled=False,
            )
            dm = DataManager(dm_config)
            dm.connect()

            # 准备 1m 数据到缓存
            now = datetime.now(timezone.utc)
            df_1m = pd.DataFrame({
                'timestamp': pd.date_range(now - pd.Timedelta(hours=5), periods=300, freq='1min'),
                'open': [100.0] * 300,
                'high': [105.0] * 300,
                'low': [95.0] * 300,
                'close': [102.0] * 300,
                'volume': [1000.0] * 300,
            })
            dm.cache.put("BTCUSDT", "1m", df_1m, force_1m=True)

            # 注册大周期
            dm.register_timeframes("BTCUSDT", ["4h"])

            # 模拟 _on_kline_received 被调用
            kline = Kline(
                symbol="BTCUSDT",
                interval="1m",
                timestamp=now,
                open=100.0,
                high=105.0,
                low=95.0,
                close=102.0,
                volume=1000.0,
            )
            dm._on_kline_received(kline)

            # 验证：缓存有数据
            cached_4h = dm.cache.get("BTCUSDT", "4h")
            assert cached_4h is not None, "缓存应有 4h 数据"

            # 验证：CSV 文件应被创建（正常模式保存）
            csv_path = Path(tmpdir) / "4h" / "BTCUSDT_4h.csv"
            assert csv_path.exists(), "正常模式应保存 CSV 文件"
