#!/usr/bin/env python3
"""
测试 1m 内存缓存裁剪的接线与安全性

背景：manage_memory_cache 此前从未被任何生产代码调用（只存在于文档
和测试中），导致 1m 缓存无界增长、cache_1m_max_rows/max_age_days
两个配置项形同虚设。裁剪窗口也曾硬编码 2 天，与配置项不一致。

裁剪必须满足：
1. 由定时维护循环自动触发
2. 落盘先于裁剪，不丢未持久化数据
3. 不破坏已建立的大周期缓存（大周期由 1m 聚合而来）
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from data_manager.manager import DataManager, DataManagerConfig


SYMBOL = "BTCUSDT"


def make_1m_ending_now(days: float) -> pd.DataFrame:
    """生成截止到当前时刻的 1m 数据（裁剪按 now 计算，必须用真实时间）"""
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    ts = pd.date_range(now - timedelta(days=days), now, freq="1min")
    rng = np.arange(len(ts), dtype=float)
    return pd.DataFrame({
        "timestamp": ts,
        "open": 100.0 + rng * 0.01,
        "high": 100.0 + rng * 0.01,
        "low": 100.0 + rng * 0.01,
        "close": 100.0 + rng * 0.01,
        "volume": 1.0,
        "quote_volume": 1.0,
    })


def make_dm(tmp_path, timeframe="1d", **cfg) -> DataManager:
    dm = DataManager(config=DataManagerConfig(
        csv_dir=str(tmp_path / "klines"),
        realtime_enabled=False,
        backtest_mode=False,
        **cfg,
    ))
    dm.kline_repo = MagicMock()
    state = MagicMock()
    state.registered_timeframes = ["1m", timeframe]
    dm.kline_repo._states = {SYMBOL: state}
    return dm


class TestTrimPreservesBigIntervals:
    """裁剪 1m 不得破坏大周期缓存"""

    @pytest.mark.parametrize("timeframe", ["4h", "1d"])
    def test_big_interval_cache_survives_trim(self, tmp_path, timeframe):
        dm = make_dm(tmp_path, timeframe, cache_1m_max_age_days=90)
        dm.cache.put(SYMBOL, "1m", make_1m_ending_now(120), force_1m=True)
        dm._preload_big_intervals_to_cache(SYMBOL)

        before_1m = len(dm.cache.get_1m_data(SYMBOL))
        before_big = len(dm.cache.get(SYMBOL, timeframe))
        assert before_big > 0

        dm.manage_memory_cache(SYMBOL)

        # 1m 确实被裁剪，大周期桶数不减
        assert len(dm.cache.get_1m_data(SYMBOL)) < before_1m
        assert len(dm.cache.get(SYMBOL, timeframe)) == before_big

    @pytest.mark.parametrize("timeframe", ["4h", "1d"])
    def test_aggregation_after_trim_keeps_history(self, tmp_path, timeframe):
        """裁剪后继续聚合，历史桶不得被截断掉"""
        dm = make_dm(tmp_path, timeframe, cache_1m_max_age_days=90)
        dm.cache.put(SYMBOL, "1m", make_1m_ending_now(120), force_1m=True)
        dm._preload_big_intervals_to_cache(SYMBOL)
        before_big = len(dm.cache.get(SYMBOL, timeframe))

        dm.manage_memory_cache(SYMBOL)
        dm._update_big_intervals_from_cache(SYMBOL)

        assert len(dm.cache.get(SYMBOL, timeframe)) == before_big


class TestRowLimitFollowsConfig:
    """行数上限必须来自配置"""

    def test_row_limit_applied(self, tmp_path):
        dm = make_dm(tmp_path, cache_1m_max_rows=500,
                     cache_1m_max_age_days=90)
        dm.cache.put(SYMBOL, "1m", make_1m_ending_now(2), force_1m=True)
        dm.manage_memory_cache(SYMBOL)
        assert len(dm.cache.get_1m_data(SYMBOL)) == 500

    def test_generous_limit_keeps_all(self, tmp_path):
        df = make_1m_ending_now(1)
        dm = make_dm(tmp_path, cache_1m_max_rows=10_000_000,
                     cache_1m_max_age_days=90)
        dm.cache.put(SYMBOL, "1m", df, force_1m=True)
        dm.manage_memory_cache(SYMBOL)
        assert len(dm.cache.get_1m_data(SYMBOL)) == len(df)


class TestMaintenanceLoopWiring:
    """定时维护循环必须真的调用裁剪"""

    @pytest.mark.asyncio
    async def test_loop_invokes_trim_for_each_symbol(self, tmp_path):
        dm = make_dm(tmp_path)
        dm.config.persistence_interval_minutes = 0
        dm.cache.put(SYMBOL, "1m", make_1m_ending_now(0.1), force_1m=True)
        dm.cache.put("ETHUSDT", "1m", make_1m_ending_now(0.1), force_1m=True)

        trimmed = []
        with patch.object(dm, "_flush_all_cache_to_csv", return_value={}), \
                patch.object(dm, "manage_memory_cache",
                             side_effect=trimmed.append):
            task = dm.start_periodic_persistence()
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert SYMBOL in trimmed
        assert "ETHUSDT" in trimmed

    @pytest.mark.asyncio
    async def test_flush_runs_before_trim(self, tmp_path):
        """落盘必须先于裁剪，否则被淘汰的数据永久丢失"""
        dm = make_dm(tmp_path)
        dm.config.persistence_interval_minutes = 0
        dm.cache.put(SYMBOL, "1m", make_1m_ending_now(0.1), force_1m=True)

        order = []
        with patch.object(dm, "_flush_all_cache_to_csv",
                          side_effect=lambda: order.append("flush") or {}), \
                patch.object(dm, "manage_memory_cache",
                             side_effect=lambda s: order.append("trim")):
            task = dm.start_periodic_persistence()
            await asyncio.sleep(0.3)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert order[:2] == ["flush", "trim"]

    @pytest.mark.asyncio
    async def test_trim_failure_does_not_kill_loop(self, tmp_path):
        """单个 symbol 裁剪失败不得终止维护循环"""
        dm = make_dm(tmp_path)
        dm.config.persistence_interval_minutes = 0
        dm.cache.put(SYMBOL, "1m", make_1m_ending_now(0.1), force_1m=True)

        flushes = []
        with patch.object(dm, "_flush_all_cache_to_csv",
                          side_effect=lambda: flushes.append(1) or {}), \
                patch.object(dm, "manage_memory_cache",
                             side_effect=RuntimeError("boom")):
            task = dm.start_periodic_persistence()
            await asyncio.sleep(0.3)
            still_running = not task.done()
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert still_running
        assert len(flushes) >= 2  # 循环继续转
