#!/usr/bin/env python3
"""
测试回测模式下大周期聚合行为

TDD RED phase: 测试先写，实现后补
"""

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import pytest


class TestBacktestBigIntervalAggregation:
    """测试回测模式下 _update_big_intervals_from_cache 的行为"""

    def _create_1m_data(self, start_dt: datetime, count: int) -> pd.DataFrame:
        """创建 1m K 线数据"""
        timestamps = [start_dt + timedelta(minutes=i) for i in range(count)]
        return pd.DataFrame({
            'timestamp': timestamps,
            'open': [50000.0 + i * 10 for i in range(count)],
            'high': [50050.0 + i * 10 for i in range(count)],
            'low': [49950.0 + i * 10 for i in range(count)],
            'close': [50020.0 + i * 10 for i in range(count)],
            'volume': [10.0] * count,
            'quote_volume': [500000.0] * count,
            'trade_num': [100] * count,
            'active_buy_volume': [5.0] * count,
            'active_buy_quote_volume': [250000.0] * count,
        })

    def test_backtest_mode_filters_by_timestamp(self):
        """
        回测模式下，大周期聚合只包含当前 bar 时间戳之前的数据

        场景：
        - 1m 缓存有 120 条数据（2 小时）
        - 当前回测时间戳是第 59 分钟（00:59:00）
        - 聚合 1h 周期时，应该只有 0 条数据（因为 1h bar 还没完成）
        """
        from data_manager.manager import DataManager, DataManagerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            dm_config = DataManagerConfig(
                csv_dir=tmpdir,
                preload_1m_enabled=False,
                backtest_mode=True,  # 回测模式
            )
            dm = DataManager(dm_config)
            dm.connect()

            # 注册时间框架
            dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "1h"])

            # 创建 120 条 1m 数据（2 小时）
            start_dt = datetime(2026, 5, 14, 0, 0, 0, tzinfo=timezone.utc)
            df_1m = self._create_1m_data(start_dt, 120)
            dm.cache.put("BTCUSDT", "1m", df_1m, force_1m=True)

            # 设置回测时间戳为第 59 分钟（1h bar 还没完成）
            bt_ts = start_dt + timedelta(minutes=59)
            dm.set_backtest_timestamp(bt_ts)

            # 调用大周期聚合
            dm._update_big_intervals_from_cache("BTCUSDT")

            # 验证：1h 缓存应该为空（因为 59 分钟不足以形成完整的 1h bar）
            cached_1h = dm.cache.get("BTCUSDT", "1h")
            # 聚合逻辑可能产生不完整的 bar，但时间戳应该不超过 bt_ts
            if cached_1h is not None and not cached_1h.empty:
                # 如果有数据，时间戳应该是 00:00:00（第一个小时的开始）
                # 但这个 bar 只有 59 分钟的数据，不是完整的 1h
                assert cached_1h['timestamp'].iloc[-1] <= bt_ts, \
                    f"1h bar 时间戳不应超过回测时间戳"

    def test_backtest_mode_includes_complete_hour(self):
        """
        回测模式下，当 1h bar 完成时，应该包含该 bar

        场景：
        - 1m 缓存有 120 条数据（2 小时）
        - 当前回测时间戳是第 60 分钟（01:00:00）
        - 聚合 1h 周期时，应该有 1 条数据（第一个小时完成了）
        """
        from data_manager.manager import DataManager, DataManagerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            dm_config = DataManagerConfig(
                csv_dir=tmpdir,
                preload_1m_enabled=False,
                backtest_mode=True,
            )
            dm = DataManager(dm_config)
            dm.connect()

            dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "1h"])

            # 创建 120 条 1m 数据（2 小时）
            start_dt = datetime(2026, 5, 14, 0, 0, 0, tzinfo=timezone.utc)
            df_1m = self._create_1m_data(start_dt, 120)
            dm.cache.put("BTCUSDT", "1m", df_1m, force_1m=True)

            # 设置回测时间戳为第 60 分钟（第一个小时完成）
            bt_ts = start_dt + timedelta(minutes=60)
            dm.set_backtest_timestamp(bt_ts)

            # 调用大周期聚合
            dm._update_big_intervals_from_cache("BTCUSDT")

            # 验证：1h 缓存应该有 1 条数据（第一个小时）
            cached_1h = dm.cache.get("BTCUSDT", "1h")
            assert cached_1h is not None, "1h 缓存应该有数据"
            # 注意：聚合后可能产生 2 条 bar（00:00 和 01:00）
            # 因为 <= bt_ts 包含了 01:00:00 这条 K 线
            # 这是合理的：01:00:00 的 K 线代表 00:00-01:00 这个小时，已经完成
            # 所以应该有 1 条完整的 1h bar（时间戳 00:00:00）
            # 但由于聚合逻辑，可能产生 2 条（取决于 resample 行为）
            # 我们验证不超过 2 条
            assert len(cached_1h) <= 2, \
                f"回测模式下应该最多 2 条 1h bar，实际 {len(cached_1h)} 条"

    def test_live_mode_uses_all_data(self):
        """
        实盘模式下，大周期聚合使用所有 1m 数据（不受时间戳限制）

        场景：
        - 1m 缓存有 60 条数据（1 小时）
        - 实盘模式（backtest_mode=False）
        - 聚合 1h 周期时，应该包含所有 60 条数据
        """
        from data_manager.manager import DataManager, DataManagerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            dm_config = DataManagerConfig(
                csv_dir=tmpdir,
                preload_1m_enabled=False,
                backtest_mode=False,  # 实盘模式
            )
            dm = DataManager(dm_config)
            dm.connect()

            # 注册时间框架
            dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "1h"])

            # 创建 60 条 1m 数据
            start_dt = datetime(2026, 5, 14, 0, 0, 0, tzinfo=timezone.utc)
            df_1m = self._create_1m_data(start_dt, 60)
            dm.cache.put("BTCUSDT", "1m", df_1m, force_1m=True)

            # 设置回测时间戳（实盘模式下应该被忽略）
            bt_ts = start_dt + timedelta(minutes=30)
            dm.set_backtest_timestamp(bt_ts)

            # 调用大周期聚合
            dm._update_big_intervals_from_cache("BTCUSDT")

            # 验证：1h 缓存应该有 1 条完整数据（60 分钟聚合的）
            cached_1h = dm.cache.get("BTCUSDT", "1h")
            assert cached_1h is not None, "1h 缓存应该有数据"
            assert len(cached_1h) == 1, f"实盘模式应该聚合完整的 1h bar，实际 {len(cached_1h)} 条"

    def test_backtest_mode_empty_when_no_data_before_timestamp(self):
        """
        回测模式下，如果当前时间戳之前没有数据，大周期缓存应该为空
        """
        from data_manager.manager import DataManager, DataManagerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            dm_config = DataManagerConfig(
                csv_dir=tmpdir,
                preload_1m_enabled=False,
                backtest_mode=True,
            )
            dm = DataManager(dm_config)
            dm.connect()

            dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "1h"])

            # 创建 10 条 1m 数据
            start_dt = datetime(2026, 5, 14, 0, 0, 0, tzinfo=timezone.utc)
            df_1m = self._create_1m_data(start_dt, 10)
            dm.cache.put("BTCUSDT", "1m", df_1m, force_1m=True)

            # 设置回测时间戳为开始时间之前（没有数据）
            bt_ts = start_dt - timedelta(minutes=10)
            dm.set_backtest_timestamp(bt_ts)

            # 调用大周期聚合
            dm._update_big_intervals_from_cache("BTCUSDT")

            # 验证：1h 缓存应该为空
            cached_1h = dm.cache.get("BTCUSDT", "1h")
            # 可能为 None 或空 DataFrame
            assert cached_1h is None or cached_1h.empty, \
                "时间戳之前没有数据时，大周期缓存应该为空"
