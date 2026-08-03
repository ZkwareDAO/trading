#!/usr/bin/env python3
"""
测试 DataManager 大周期 CSV 预加载和持久化

TDD RED phase: 测试先写，实现后补
"""

import tempfile
from pathlib import Path

import pandas as pd


class TestPreloadAllBigIntervalsFromCsv:
    """测试 _preload_all_big_intervals_from_csv 方法"""

    def test_loads_big_interval_csv_into_cache(self):
        """当大周期 CSV 存在时，加载到缓存"""
        from data_manager.manager import DataManager, DataManagerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 15m CSV 文件
            interval_dir = Path(tmpdir) / "15m"
            interval_dir.mkdir(parents=True)
            csv_path = interval_dir / "BTCUSDT_15m.csv"
            df = pd.DataFrame({
                'timestamp': pd.to_datetime(['2026-04-22 00:00:00', '2026-04-22 00:15:00'], utc=True),
                'open': [50000.0, 50100.0],
                'high': [50050.0, 50150.0],
                'low': [49950.0, 50050.0],
                'close': [50020.0, 50120.0],
                'volume': [10.0, 11.0],
                'quote_volume': [500000.0, 501000.0],
                'trade_num': [100, 101],
                'active_buy_volume': [5.0, 5.5],
                'active_buy_quote_volume': [250000.0, 255000.0],
            })
            df.to_csv(csv_path, index=False)

            dm_config = DataManagerConfig(csv_dir=tmpdir, preload_1m_enabled=False)
            dm = DataManager(dm_config)
            dm.connect()

            # 注册时间框架（使 kline_repo 知道 BTCUSDT 有 15m）
            dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "15m"])

            # 调用被测方法
            dm._preload_all_big_intervals_from_csv("BTCUSDT")

            # 验证缓存中有 15m 数据
            cached = dm.cache.get("BTCUSDT", "15m")
            assert cached is not None
            assert len(cached) == 2
            assert cached['close'].iloc[-1] == 50120.0

    def test_skips_when_no_csv_exists(self):
        """当大周期 CSV 不存在时，不报错也不写入缓存"""
        from data_manager.manager import DataManager, DataManagerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            dm_config = DataManagerConfig(csv_dir=tmpdir, preload_1m_enabled=False)
            dm = DataManager(dm_config)
            dm.connect()

            dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "15m"])

            dm._preload_all_big_intervals_from_csv("BTCUSDT")

            cached = dm.cache.get("BTCUSDT", "15m")
            assert cached is None

    def test_skips_when_no_kline_repo(self):
        """kline_repo 未初始化时，方法安全返回"""
        from data_manager.manager import DataManager, DataManagerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            dm_config = DataManagerConfig(csv_dir=tmpdir, preload_1m_enabled=False)
            dm = DataManager(dm_config)
            # 不调用 connect()，kline_repo 为 None

            dm._preload_all_big_intervals_from_csv("BTCUSDT")
            # 不应抛出异常
            assert True

    def test_loads_multiple_big_intervals(self):
        """加载多个大周期 CSV（15m + 1h）"""
        from data_manager.manager import DataManager, DataManagerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            for interval in ["15m", "1h"]:
                d = base / interval
                d.mkdir(parents=True)
                df = pd.DataFrame({
                    'timestamp': pd.to_datetime(['2026-04-22 00:00:00'], utc=True),
                    'open': [50000.0],
                    'high': [50050.0],
                    'low': [49950.0],
                    'close': [50020.0],
                    'volume': [10.0],
                    'quote_volume': [500000.0],
                    'trade_num': [100],
                    'active_buy_volume': [5.0],
                    'active_buy_quote_volume': [250000.0],
                })
                df.to_csv(d / f"BTCUSDT_{interval}.csv", index=False)

            dm_config = DataManagerConfig(csv_dir=tmpdir, preload_1m_enabled=False)
            dm = DataManager(dm_config)
            dm.connect()
            dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "15m", "1h"])

            dm._preload_all_big_intervals_from_csv("BTCUSDT")

            assert dm.cache.get("BTCUSDT", "15m") is not None
            assert dm.cache.get("BTCUSDT", "1h") is not None


class TestUpdateBigIntervalsFromCachePersistence:
    """测试 _update_big_intervals_from_cache 增加 CSV 持久化"""

    def test_saves_aggregated_data_to_csv(self):
        """聚合后应将数据写入 CSV 文件"""
        from data_manager.manager import DataManager, DataManagerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            dm_config = DataManagerConfig(csv_dir=tmpdir, preload_1m_enabled=False)
            dm = DataManager(dm_config)
            dm.connect()

            # 注册 15m
            dm.register_timeframes_for_symbol("ETHUSDT", ["1m", "15m"])

            # 放入 1m 数据（足够聚合 15m）
            df_1m = pd.DataFrame({
                'timestamp': pd.date_range('2026-04-22 00:00:00', periods=15, freq='1min', tz='UTC'),
                'open': [50000.0 + i for i in range(15)],
                'high': [50010.0 + i for i in range(15)],
                'low': [49990.0 + i for i in range(15)],
                'close': [50005.0 + i for i in range(15)],
                'volume': [1.0] * 15,
                'quote_volume': [50000.0] * 15,
                'trade_num': [10] * 15,
                'active_buy_volume': [0.5] * 15,
                'active_buy_quote_volume': [25000.0] * 15,
            })
            dm.cache.put("ETHUSDT", "1m", df_1m, force_1m=True)

            # 调用聚合方法
            results = dm._update_big_intervals_from_cache("ETHUSDT")

            assert "15m" in results
            assert results["15m"] is True

            # 验证 CSV 文件已写入
            csv_path = Path(tmpdir) / "15m" / "ETHUSDT_15m.csv"
            assert csv_path.exists(), "聚合后应将数据持久化到 CSV"
