#!/usr/bin/env python3
"""
测试大周期聚合的首桶截断问题

核心不变式：增量聚合结果必须与全量聚合结果一致。

背景：1m → 大周期聚合的源数据切片起点若不落在目标周期边界上，
首桶只含该桶的后半段，open/high/low/volume 全部失真。旧实现会
让这个截断桶覆盖缓存/CSV 中已有的正确值，且不再被任何路径重算。
"""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from data_manager.klines_loader import resample_ohlcv
from data_manager.manager import DataManager, DataManagerConfig


SYMBOL = "BTCUSDT"


def make_1m(start: str, end: str) -> pd.DataFrame:
    """生成单调递增的 1m 数据，便于判断 open/high 是否取自桶首"""
    ts = pd.date_range(start, end, freq="1min", tz="UTC")
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


def assert_buckets_match(truth: pd.DataFrame, actual: pd.DataFrame, label: str):
    """断言 actual 中每个桶的值都与全量聚合真值一致"""
    merged = truth.merge(actual, on="timestamp", suffixes=("_t", "_a"))
    assert not merged.empty, f"{label}: 没有可比对的桶"
    for col in ("open", "high", "low", "close", "volume"):
        bad = merged[~np.isclose(merged[f"{col}_t"], merged[f"{col}_a"])]
        assert bad.empty, (
            f"{label}: {col} 失真 {len(bad)} 桶\n"
            f"{bad[['timestamp', f'{col}_t', f'{col}_a']].to_string()}"
        )


class TestResamplePartialHead:
    """resample_ohlcv 的首桶截断处理"""

    def test_drops_truncated_head_bucket(self):
        # 源数据从 01:06 开始，4h 首桶 00:00 只含后半段
        df = make_1m("2026-01-01 01:06", "2026-01-01 13:05")
        out = resample_ohlcv(df, "4h", datetime_column="timestamp",
                             drop_partial_head=True)
        assert out["timestamp"].iloc[0] == pd.Timestamp("2026-01-01 04:00", tz="UTC")

    def test_keeps_aligned_head_bucket(self):
        # 源数据正好从桶边界开始，首桶完整，不应被丢弃
        df = make_1m("2026-01-01 04:00", "2026-01-01 13:05")
        out = resample_ohlcv(df, "4h", datetime_column="timestamp",
                             drop_partial_head=True)
        assert out["timestamp"].iloc[0] == pd.Timestamp("2026-01-01 04:00", tz="UTC")
        assert out["volume"].iloc[0] == 240.0

    def test_keeps_partial_tail_bucket(self):
        # 末尾未闭合桶是设计内的（由 get_closed_data 剔除），不能丢
        df = make_1m("2026-01-01 00:00", "2026-01-01 13:05")
        out = resample_ohlcv(df, "4h", datetime_column="timestamp",
                             drop_partial_head=True)
        assert out["timestamp"].iloc[-1] == pd.Timestamp("2026-01-01 12:00", tz="UTC")
        assert out["volume"].iloc[-1] == 66.0

    def test_interior_gap_does_not_drop_buckets(self):
        # 中间缺失分钟是正常数据 gap，不应触发丢桶
        df = make_1m("2026-01-01 00:00", "2026-01-01 13:05")
        hole = ((df["timestamp"] >= pd.Timestamp("2026-01-01 04:00", tz="UTC"))
                & (df["timestamp"] < pd.Timestamp("2026-01-01 04:30", tz="UTC")))
        df = df[~hole]
        out = resample_ohlcv(df, "4h", datetime_column="timestamp",
                             drop_partial_head=True)
        assert pd.Timestamp("2026-01-01 04:00", tz="UTC") in set(out["timestamp"])

    def test_default_preserves_legacy_behavior(self):
        df = make_1m("2026-01-01 01:06", "2026-01-01 13:05")
        out = resample_ohlcv(df, "4h", datetime_column="timestamp")
        assert out["timestamp"].iloc[0] == pd.Timestamp("2026-01-01 00:00", tz="UTC")


def _make_dm(timeframes) -> DataManager:
    dm = DataManager(config=DataManagerConfig(backtest_mode=False))
    dm.kline_repo = MagicMock()
    state = MagicMock()
    state.registered_timeframes = timeframes
    dm.kline_repo._states = {SYMBOL: state}
    return dm


class TestFullRebuildPath:
    """实盘全量兜底路径：_update_big_intervals_from_cache 的 df_agg is None 分支

    该分支在冷启动、大周期缓存为空、增量前置条件不满足时走到，随后无条件
    落盘。1m 缓存起点由 default_1m_rows_limit 裁剪决定，落在任意分钟而非
    周期边界，故这条路径与增量路径同样需要丢弃残缺首桶。
    """

    @pytest.mark.parametrize("timeframe,period_minutes", [
        ("1h", 60), ("4h", 240), ("8h", 480),
    ])
    def test_full_rebuild_drops_partial_head(self, timeframe, period_minutes):
        """缓存为空（走全量路径）时，残缺首桶不得进入缓存"""
        # 起点 03:17 不对齐任何周期边界
        full = make_1m("2026-01-01 03:17", "2026-01-03 00:00")

        dm = _make_dm(["1m", timeframe])
        dm.cache.put(SYMBOL, "1m", full, force_1m=True)
        # 不预置大周期缓存 → cached_agg 为 None → 必走全量路径
        assert dm.cache.get(SYMBOL, timeframe) is None
        dm._update_big_intervals_from_cache(SYMBOL)

        cached = dm.cache.get(SYMBOL, timeframe)
        assert cached is not None and not cached.empty
        # 首桶必须是满值，而非只含桶后半段的残缺根
        assert cached["volume"].iloc[0] == float(period_minutes), (
            f"{timeframe} 首桶 {cached['timestamp'].iloc[0]} "
            f"vol={cached['volume'].iloc[0]}，期望满值 {period_minutes}"
        )
        assert_buckets_match(
            resample_ohlcv(full, timeframe, datetime_column="timestamp"),
            cached, f"全量路径 {timeframe}")

    def test_full_rebuild_does_not_persist_partial_head(self):
        """残缺首桶不得写入 CSV —— 落盘后窗口滑过永不修复"""
        full = make_1m("2026-01-01 03:17", "2026-01-03 00:00")

        dm = _make_dm(["1m", "8h"])
        dm.cache.put(SYMBOL, "1m", full, force_1m=True)
        dm._update_big_intervals_from_cache(SYMBOL)

        # 收集实际落盘的行
        assert dm.kline_repo.save_klines_to_csv.called
        saved = dm.kline_repo.save_klines_to_csv.call_args[0][2]
        first = min(saved, key=lambda r: r["timestamp"])
        assert first["volume"] == 480.0, (
            f"落盘首桶 {first['timestamp']} vol={first['volume']}，"
            f"残缺根被写入 CSV 会覆盖已有完整根"
        )


class TestIncrementalMatchesFull:
    """实盘增量路径：_update_big_intervals_from_cache"""

    @pytest.mark.parametrize("timeframe", ["15m", "1h", "4h", "8h"])
    def test_incremental_equals_full_aggregation(self, timeframe):
        base = make_1m("2026-01-01 00:00", "2026-01-03 00:00")
        truth = resample_ohlcv(base, timeframe, datetime_column="timestamp")

        dm = _make_dm(["1m", timeframe])

        # 冷启动：先用前一天建立缓存（走全量路径）
        warm_n = int((base["timestamp"]
                      <= pd.Timestamp("2026-01-02 00:00", tz="UTC")).sum())
        dm.cache.put(SYMBOL, "1m", base.iloc[:warm_n].copy(), force_1m=True)
        dm._update_big_intervals_from_cache(SYMBOL)

        # 逐分钟推进，走增量路径
        for i in range(warm_n, len(base)):
            dm.cache.put(SYMBOL, "1m", base.iloc[:i + 1].copy(), force_1m=True)
            dm._update_big_intervals_from_cache(SYMBOL)

        assert_buckets_match(truth, dm.cache.get(SYMBOL, timeframe),
                             f"增量聚合 {timeframe}")

    def test_incremental_does_not_lose_buckets(self):
        base = make_1m("2026-01-01 00:00", "2026-01-03 00:00")
        truth = resample_ohlcv(base, "4h", datetime_column="timestamp")

        dm = _make_dm(["1m", "4h"])
        warm_n = int((base["timestamp"]
                      <= pd.Timestamp("2026-01-02 00:00", tz="UTC")).sum())
        dm.cache.put(SYMBOL, "1m", base.iloc[:warm_n].copy(), force_1m=True)
        dm._update_big_intervals_from_cache(SYMBOL)
        for i in range(warm_n, len(base)):
            dm.cache.put(SYMBOL, "1m", base.iloc[:i + 1].copy(), force_1m=True)
            dm._update_big_intervals_from_cache(SYMBOL)

        assert len(dm.cache.get(SYMBOL, "4h")) == len(truth)


class TestRestartPreloadMerge:
    """重启路径：_preload_big_intervals_to_cache"""

    def test_partial_head_does_not_overwrite_csv_value(self):
        """1m 缓存起点不对齐时，聚合结果不得覆盖 CSV 里的正确桶"""
        full = make_1m("2026-01-01 00:00", "2026-01-06 00:00")
        truth = resample_ohlcv(full, "4h", datetime_column="timestamp")

        # 1m 缓存起点是任意分钟（非 4h 边界）
        cut = pd.Timestamp("2026-01-04 02:37", tz="UTC")
        trimmed = full[full["timestamp"] >= cut].reset_index(drop=True)

        dm = _make_dm(["1m", "4h"])
        dm.cache.put(SYMBOL, "1m", trimmed, force_1m=True)
        dm.cache.put(SYMBOL, "4h", truth.copy())  # 上次运行落盘的正确历史

        dm._preload_big_intervals_to_cache(SYMBOL)

        assert_buckets_match(truth, dm.cache.get(SYMBOL, "4h"), "重启合并")

    def test_no_existing_cache_still_drops_bad_bucket(self):
        """无已有缓存时，截断桶应被丢弃而非写入错误值"""
        full = make_1m("2026-01-01 00:00", "2026-01-06 00:00")
        cut = pd.Timestamp("2026-01-04 02:37", tz="UTC")
        trimmed = full[full["timestamp"] >= cut].reset_index(drop=True)

        dm = _make_dm(["1m", "4h"])
        dm.cache.put(SYMBOL, "1m", trimmed, force_1m=True)
        dm._preload_big_intervals_to_cache(SYMBOL)

        cached = dm.cache.get(SYMBOL, "4h")
        assert cached["timestamp"].iloc[0] == pd.Timestamp("2026-01-04 04:00",
                                                           tz="UTC")
        assert_buckets_match(
            resample_ohlcv(full, "4h", datetime_column="timestamp"),
            cached, "重启无缓存")


class TestRestartMidBucket:
    """重启发生在大周期桶中途（例如 01:15 重启，聚合 2h）"""

    def test_restart_mid_bucket_keeps_growing_bucket(self):
        """01:15 重启：00:00 这根 2h 桶尚未闭合，应保留且值正确"""
        df = make_1m("2026-01-01 00:00", "2026-01-01 01:15")
        dm = _make_dm(["1m", "2h"])
        dm.cache.put(SYMBOL, "1m", df, force_1m=True)
        dm._preload_big_intervals_to_cache(SYMBOL)

        cached = dm.cache.get(SYMBOL, "2h")
        assert len(cached) == 1
        assert cached["timestamp"].iloc[0] == pd.Timestamp("2026-01-01 00:00",
                                                           tz="UTC")
        # 76 根 1m（00:00~01:15 含两端），桶未闭合但值必须是真实累计
        assert cached["volume"].iloc[0] == 76.0
        assert cached["open"].iloc[0] == df["open"].iloc[0]

    def test_unclosed_bucket_hidden_from_strategy(self):
        """未闭合桶不得被策略当作已闭合 K 线使用"""
        from strategy_core.base.core import BaseStrategyCore

        df = make_1m("2026-01-01 00:00", "2026-01-01 01:15")
        dm = _make_dm(["1m", "2h"])
        dm.cache.put(SYMBOL, "1m", df, force_1m=True)
        dm._preload_big_intervals_to_cache(SYMBOL)

        closed = BaseStrategyCore.get_closed_data(
            {"2h": dm.cache.get(SYMBOL, "2h")}, "2h", min_rows=1,
            current_time=pd.Timestamp("2026-01-01 01:16", tz="UTC"),
        )
        assert closed.empty

    def test_bucket_completes_after_ws_resume(self):
        """01:15 重启后 WS 恢复推送，未闭合桶应长到完整值"""
        full = make_1m("2026-01-01 00:00", "2026-01-01 06:00")
        truth = resample_ohlcv(full, "2h", datetime_column="timestamp")

        dm = _make_dm(["1m", "2h"])
        n0 = int((full["timestamp"]
                  <= pd.Timestamp("2026-01-01 01:15", tz="UTC")).sum())
        dm.cache.put(SYMBOL, "1m", full.iloc[:n0].copy(), force_1m=True)
        dm._preload_big_intervals_to_cache(SYMBOL)
        assert dm.cache.get(SYMBOL, "2h")["volume"].iloc[0] == 76.0

        for i in range(n0, len(full)):
            dm.cache.put(SYMBOL, "1m", full.iloc[:i + 1].copy(), force_1m=True)
            dm._update_big_intervals_from_cache(SYMBOL)

        cached = dm.cache.get(SYMBOL, "2h")
        assert cached["volume"].iloc[0] == 120.0  # 已闭合，满 2h
        assert_buckets_match(truth, cached, "WS 恢复后")

    def test_insufficient_data_yields_no_bucket(self):
        """不足一个完整桶且起点不对齐时，应为空而非写入残缺值"""
        df = make_1m("2026-01-01 01:37", "2026-01-01 01:59")
        dm = _make_dm(["1m", "2h"])
        dm.cache.put(SYMBOL, "1m", df, force_1m=True)
        dm._preload_big_intervals_to_cache(SYMBOL)

        cached = dm.cache.get(SYMBOL, "2h")
        assert cached is None or cached.empty


class TestAlignment:
    """周期边界对齐：首桶必须是满值"""

    @pytest.mark.parametrize("timeframe,expected_first", [
        ("2h", "2026-01-01 08:00"),
        ("4h", "2026-01-01 08:00"),
        ("8h", "2026-01-01 08:00"),
        ("12h", "2026-01-01 12:00"),
        ("1d", "2026-01-02 00:00"),
    ])
    def test_first_bucket_is_full(self, timeframe, expected_first):
        """源起点 07:23 时，各周期首桶都应对齐边界且为满值"""
        df = make_1m("2026-01-01 07:23", "2026-01-05 00:00")
        out = resample_ohlcv(df, timeframe, datetime_column="timestamp",
                             drop_partial_head=True)
        assert out["timestamp"].iloc[0] == pd.Timestamp(expected_first, tz="UTC")
        minutes = {"2h": 120, "4h": 240, "8h": 480, "12h": 720, "1d": 1440}
        assert out["volume"].iloc[0] == float(minutes[timeframe])


class TestBacktestLiveParity:
    """回测与实盘聚合必须产出相同结果（配置/路径分叉即回测失真）"""

    def test_live_matches_backtest(self):
        full = make_1m("2026-01-01 00:00", "2026-01-02 00:00")
        truth = resample_ohlcv(full, "2h", datetime_column="timestamp")

        live = _make_dm(["1m", "2h"])
        n0 = int((full["timestamp"]
                  <= pd.Timestamp("2026-01-01 06:00", tz="UTC")).sum())
        live.cache.put(SYMBOL, "1m", full.iloc[:n0].copy(), force_1m=True)
        live._update_big_intervals_from_cache(SYMBOL)
        for i in range(n0, len(full)):
            live.cache.put(SYMBOL, "1m", full.iloc[:i + 1].copy(), force_1m=True)
            live._update_big_intervals_from_cache(SYMBOL)
        live_df = live.cache.get(SYMBOL, "2h")

        bt = DataManager(config=DataManagerConfig(backtest_mode=True))
        bt.kline_repo = MagicMock()
        st = MagicMock(); st.registered_timeframes = ["1m", "2h"]
        bt.kline_repo._states = {SYMBOL: st}
        bt.cache.put(SYMBOL, "1m", full.copy(), force_1m=True)
        bt.set_backtest_timestamp(full["timestamp"].iloc[-1])
        bt_df = bt.get_dataframe_cached(SYMBOL, "2h", limit=5000)

        assert_buckets_match(truth, live_df, "实盘")
        assert_buckets_match(truth, bt_df, "回测")
        assert_buckets_match(live_df.rename(columns=lambda c: c), bt_df,
                             "回测 vs 实盘")


class TestInteriorGap:
    """桶内部分分钟缺失 —— drop_partial_head 检测不到，属数据完整性范畴"""

    def test_interior_gap_bucket_is_incomplete_and_undetected(self):
        """已知局限：桶起点对齐但内部缺分钟时，聚合值偏低且无告警。

        gap 补齐由 _fill_ws_gap_async 负责（异步、失败仅告警），聚合层
        无法区分"该分钟无成交"与"该分钟丢了"。此测试锁定当前行为，
        若将来引入完整性校验需同步更新。
        """
        full = make_1m("2026-01-01 00:00", "2026-01-01 06:00")
        hole = ((full["timestamp"] >= pd.Timestamp("2026-01-01 02:00", tz="UTC"))
                & (full["timestamp"] < pd.Timestamp("2026-01-01 02:30", tz="UTC")))
        out = resample_ohlcv(full[~hole], "2h", datetime_column="timestamp",
                             drop_partial_head=True)

        bucket = out[out["timestamp"] == pd.Timestamp("2026-01-01 02:00",
                                                      tz="UTC")]
        assert len(bucket) == 1
        assert bucket["volume"].iloc[0] == 90.0  # 缺 30 根，非满值 120

    def test_whole_missing_bucket_is_skipped_not_faked(self):
        """整桶缺失时不应凭空造桶"""
        full = make_1m("2026-01-01 00:00", "2026-01-01 06:00")
        hole = ((full["timestamp"] >= pd.Timestamp("2026-01-01 02:00", tz="UTC"))
                & (full["timestamp"] < pd.Timestamp("2026-01-01 04:00", tz="UTC")))
        out = resample_ohlcv(full[~hole], "2h", datetime_column="timestamp",
                             drop_partial_head=True)
        assert pd.Timestamp("2026-01-01 02:00", tz="UTC") not in set(
            out["timestamp"])

