#!/usr/bin/env python3
"""
测试 _preload_big_intervals_to_cache 合并逻辑

验证：
1. 大周期 CSV 数据不会被 1m 聚合覆盖
2. 聚合数据与已有缓存合并
3. 去重并保持时间顺序
"""

import pandas as pd
import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from data_manager.manager import DataManager, DataManagerConfig
from data_manager.cache import ShardCache
from data_manager.kline_repository import KlineRepository


def make_1m_df(days: int = 7) -> pd.DataFrame:
    """生成 N 天的 1m 数据"""
    rows = []
    start = datetime(2026, 6, 20, tzinfo=timezone.utc)
    for i in range(days * 1440):  # 每天 1440 分钟
        ts = start + timedelta(minutes=i)
        rows.append({
            'timestamp': ts,
            'open': 100.0 + i * 0.01,
            'high': 101.0 + i * 0.01,
            'low': 99.0 + i * 0.01,
            'close': 100.5 + i * 0.01,
            'volume': 1000.0,
            'quote_volume': 100500.0,
            'trade_num': 50,
        })
    return pd.DataFrame(rows)


def make_1d_df(days: int = 100) -> pd.DataFrame:
    """生成 N 天的 1d 数据（模拟完整历史）"""
    rows = []
    start = datetime(2023, 9, 5, tzinfo=timezone.utc)
    for i in range(days):
        ts = start + timedelta(days=i)
        rows.append({
            'timestamp': ts,
            'open': 100.0 + i,
            'high': 101.0 + i,
            'low': 99.0 + i,
            'close': 100.5 + i,
            'volume': 10000.0,
            'quote_volume': 1005000.0,
            'trade_num': 500,
        })
    return pd.DataFrame(rows)


class TestPreloadBigIntervalsMerge:
    """测试大周期缓存合并逻辑"""

    def test_should_merge_not_overwrite_existing_cache(self, tmp_path: Path):
        """
        场景：
        - 1d CSV 有 100 天完整历史数据
        - 1m CSV 只有 7 天数据
        - _preload_big_intervals_to_cache 应该合并，而不是覆盖

        预期：
        - 缓存最终包含 100 天数据（CSV 历史 + 1m 聚合补充最新）
        - 不丢失 CSV 中的历史数据
        """
        # Setup: 创建 DataManager
        csv_dir = tmp_path / "data"
        csv_dir.mkdir(parents=True)

        dm = DataManager(
            config=DataManagerConfig(
                csv_dir=str(csv_dir),
                backtest_mode=False,
            )
        )

        # Mock kline_repo 和 cache
        dm.kline_repo = MagicMock(spec=KlineRepository)
        dm.kline_repo._states = {}

        # 注册 symbol 和 timeframes
        from data_manager.kline_repository import SymbolState
        state = SymbolState(symbol="BNBUSDT")
        state.registered_timeframes = {"1m", "1d"}
        dm.kline_repo._states["BNBUSDT"] = state

        # 准备数据
        df_1m = make_1m_df(days=7)  # 只有 7 天 1m 数据
        df_1d_csv = make_1d_df(days=100)  # 100 天完整 1d 历史

        # 模拟缓存已有 1d CSV 数据（100 天）
        dm.cache.put("BNBUSDT", "1m", df_1m)
        dm.cache.put("BNBUSDT", "1d", df_1d_csv)

        # 验证初始状态
        initial_1d = dm.cache.get("BNBUSDT", "1d")
        assert len(initial_1d) == 100, f"初始 1d 缓存应有 100 条，实际 {len(initial_1d)}"
        initial_start = initial_1d['timestamp'].iloc[0]
        initial_end = initial_1d['timestamp'].iloc[-1]

        # 执行：调用 _preload_big_intervals_to_cache
        # 这会用 7 天的 1m 数据聚合出约 7 根 1d K线
        dm._preload_big_intervals_to_cache("BNBUSDT")

        # 验证：缓存不应被覆盖
        final_1d = dm.cache.get("BNBUSDT", "1d")

        # 关键断言：数据量不应减少
        assert len(final_1d) >= 100, (
            f"大周期缓存被覆盖！预期 >= 100 条，实际 {len(final_1d)} 条"
        )

        # 验证历史数据仍然存在
        final_start = final_1d['timestamp'].iloc[0]
        assert final_start.date() == initial_start.date(), (
            f"历史数据起始时间被改变：{final_start} != {initial_start}"
        )

        # 验证数据按时间排序
        timestamps = final_1d['timestamp'].tolist()
        assert timestamps == sorted(timestamps), "数据未按时间排序"

        # 验证无重复
        assert len(final_1d) == len(final_1d.drop_duplicates(subset=['timestamp'])), (
            "存在重复的时间戳"
        )

    def test_should_add_new_data_from_aggregation(self, tmp_path: Path):
        """
        场景：
        - 1d CSV 数据较旧（截止到昨天）
        - 1m 数据包含今天最新数据

        预期：
        - 聚合后的今天数据应该被合并到缓存
        """
        csv_dir = tmp_path / "data"
        csv_dir.mkdir(parents=True)

        dm = DataManager(
            config=DataManagerConfig(
                csv_dir=str(csv_dir),
                backtest_mode=False,
            )
        )

        dm.kline_repo = MagicMock(spec=KlineRepository)
        dm.kline_repo._states = {}

        from data_manager.kline_repository import SymbolState
        state = SymbolState(symbol="BNBUSDT")
        state.registered_timeframes = {"1m", "1d"}
        dm.kline_repo._states["BNBUSDT"] = state

        # 1d CSV: 截止到昨天
        today = datetime(2026, 6, 26, tzinfo=timezone.utc)
        df_1d_csv = make_1d_df(days=42)
        df_1d_csv['timestamp'] = pd.date_range(
            end=today - timedelta(days=1), periods=42, freq='D', tz='UTC'
        )

        # 1m: 包含今天数据
        df_1m = make_1m_df(days=2)
        df_1m['timestamp'] = pd.date_range(
            end=today + timedelta(hours=23, minutes=59), periods=2*1440, freq='min', tz='UTC'
        )

        dm.cache.put("BNBUSDT", "1m", df_1m)
        dm.cache.put("BNBUSDT", "1d", df_1d_csv)

        initial_count = len(dm.cache.get("BNBUSDT", "1d"))

        # 执行
        dm._preload_big_intervals_to_cache("BNBUSDT")

        # 验证：应该新增今天的数据
        final_1d = dm.cache.get("BNBUSDT", "1d")
        assert len(final_1d) > initial_count, (
            f"应该新增聚合数据，但数量未变化：{len(final_1d)} vs {initial_count}"
        )

        # 验证最新数据日期
        latest_ts = final_1d['timestamp'].iloc[-1]
        assert latest_ts.date() >= today.date(), (
            f"最新数据应该包含今天，实际最新：{latest_ts}"
        )

    def test_should_deduplicate_same_timestamp(self, tmp_path: Path):
        """
        场景：
        - 缓存已有某天的数据
        - 聚合也产生了同一天的数据（更新）

        预期：
        - 合并后去重，保留最新值
        """
        csv_dir = tmp_path / "data"
        csv_dir.mkdir(parents=True)

        dm = DataManager(
            config=DataManagerConfig(
                csv_dir=str(csv_dir),
                backtest_mode=False,
            )
        )

        dm.kline_repo = MagicMock(spec=KlineRepository)
        dm.kline_repo._states = {}

        from data_manager.kline_repository import SymbolState
        state = SymbolState(symbol="BNBUSDT")
        state.registered_timeframes = {"1m", "1d"}
        dm.kline_repo._states["BNBUSDT"] = state

        # 构造重叠场景
        today = datetime(2026, 6, 26, tzinfo=timezone.utc)

        # 1d 缓存：包含今天（未闭合）
        df_1d_cached = pd.DataFrame([
            {'timestamp': today, 'open': 100.0, 'high': 101.0, 'low': 99.0, 'close': 100.5, 'volume': 1000.0, 'quote_volume': 100500.0, 'trade_num': 50},
        ])

        # 1m 数据：同一分钟的更新
        df_1m = pd.DataFrame([
            {'timestamp': today, 'open': 100.0, 'high': 102.0, 'low': 98.0, 'close': 101.0, 'volume': 2000.0, 'quote_volume': 201000.0, 'trade_num': 100},
        ])

        dm.cache.put("BNBUSDT", "1m", df_1m)
        dm.cache.put("BNBUSDT", "1d", df_1d_cached)

        # 执行
        dm._preload_big_intervals_to_cache("BNBUSDT")

        # 验证：应该只有 1 条，去重
        final_1d = dm.cache.get("BNBUSDT", "1d")
        assert len(final_1d) == 1, f"应该去重为 1 条，实际 {len(final_1d)}"

        # 验证：保留最新值（聚合的值）
        assert final_1d['close'].iloc[0] == 101.0, "应该保留聚合后的最新值"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])