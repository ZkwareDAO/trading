#!/usr/bin/env python3
"""WS 回调链路快速路径测试（1m 缓存追加 + 大周期增量聚合）

用户旅程:
1. 策略需要大周期缓存保留 CSV 完整历史，请求 200 根 1d 时不被内存 1m 窗口截断
2. 运维需要 WS 回调足够快，多 symbol 推送不积压
3. 开发者需要增量聚合结果与全量聚合一致，优化不改变数据语义

对应 plan: .claude/plans/1m-cache-append-fast-path.plan.md
"""

import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import pytest

from data_manager.manager import DataManager, DataManagerConfig


# ── helpers ──────────────────────────────────────────────────────────────────

OHLCV_COLS = ["open", "high", "low", "close", "volume"]


def make_1m_df(start: datetime, n: int) -> pd.DataFrame:
    """构造 n 行连续 1m K 线 DataFrame（含所有可选列）"""
    return pd.DataFrame({
        "timestamp": pd.date_range(start, periods=n, freq="1min", tz="UTC"),
        "open": [100.0 + i * 0.1 for i in range(n)],
        "high": [101.0 + i * 0.1 for i in range(n)],
        "low": [99.0 + i * 0.1 for i in range(n)],
        "close": [100.5 + i * 0.1 for i in range(n)],
        "volume": [1000.0] * n,
        "quote_volume": [100000.0] * n,
        "trade_num": [10] * n,
        "active_buy_volume": [500.0] * n,
        "active_buy_quote_volume": [50000.0] * n,
    })


def make_big_df(start: datetime, n: int, freq: str) -> pd.DataFrame:
    """构造 n 行大周期 K 线（模拟从 CSV 加载的历史）"""
    return pd.DataFrame({
        "timestamp": pd.date_range(start, periods=n, freq=freq, tz="UTC"),
        "open": [200.0] * n,
        "high": [201.0] * n,
        "low": [199.0] * n,
        "close": [200.5] * n,
        "volume": [2000.0] * n,
        "quote_volume": [200000.0] * n,
        "trade_num": [20] * n,
        "active_buy_volume": [1000.0] * n,
        "active_buy_quote_volume": [100000.0] * n,
    })


@pytest.fixture
def tmpdir_path():
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d, ignore_errors=True)


def make_dm(tmpdir: str, backtest_mode: bool = False) -> DataManager:
    cfg = DataManagerConfig(
        csv_dir=tmpdir,
        preload_1m_enabled=False,
        backtest_mode=backtest_mode,
    )
    dm = DataManager(cfg)
    dm.connect()
    return dm


# ══════════════════════════════════════════════════════════════════════════════
# 1m 缓存追加
# ══════════════════════════════════════════════════════════════════════════════


class TestCacheAppendFastPath:
    """1m 缓存追加：快速路径与慢速路径输出一致"""

    def test_cache_append_fast_path_equals_slow_path(self, tmpdir_path):
        """时间戳单调递增时，快速路径输出与全量 concat+dedup+sort 完全一致"""
        base = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
        existing = make_1m_df(base, 100)
        new_row = make_1m_df(base + timedelta(minutes=100), 1)

        # 慢速路径（当前实现语义）
        slow = pd.concat([existing, new_row], ignore_index=True)
        slow = slow.drop_duplicates(subset=["timestamp"], keep="last")
        slow = slow.sort_values("timestamp").reset_index(drop=True)

        # 快速路径（时间戳单调 → 只 concat）
        assert new_row["timestamp"].iloc[0] > existing["timestamp"].iloc[-1]
        fast = pd.concat([existing, new_row], ignore_index=True)

        assert len(fast) == len(slow)
        for col in ["timestamp"] + OHLCV_COLS:
            pd.testing.assert_series_equal(
                fast[col].reset_index(drop=True),
                slow[col].reset_index(drop=True),
                check_names=False,
            )

    def test_cache_append_overlap_dedups_keeping_new(self, tmpdir_path):
        """时间戳重叠时走慢速路径，去重后行数不变且值取新"""
        base = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
        existing = make_1m_df(base, 10)

        overlap = make_1m_df(base + timedelta(minutes=5), 1)
        overlap.loc[0, "close"] = 999.0

        # 重叠 → 不满足快速路径前置条件
        assert not (overlap["timestamp"].iloc[0] > existing["timestamp"].iloc[-1])

        merged = pd.concat([existing, overlap], ignore_index=True)
        merged = merged.drop_duplicates(subset=["timestamp"], keep="last")
        merged = merged.sort_values("timestamp").reset_index(drop=True)

        assert len(merged) == 10
        row = merged[merged["timestamp"] == base + timedelta(minutes=5)]
        assert row.iloc[0]["close"] == 999.0

    def test_cache_append_out_of_order_sorts(self, tmpdir_path):
        """乱序推送（新 K 线早于缓存末尾）排序正确"""
        base = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        existing = make_1m_df(base, 10)
        early = make_1m_df(base - timedelta(hours=1), 5)

        merged = pd.concat([existing, early], ignore_index=True)
        merged = merged.drop_duplicates(subset=["timestamp"], keep="last")
        merged = merged.sort_values("timestamp").reset_index(drop=True)

        assert len(merged) == 15
        assert merged["timestamp"].is_monotonic_increasing

    def test_cache_append_empty_cache_first_write(self, tmpdir_path):
        """空缓存首次写入"""
        dm = make_dm(tmpdir_path)
        base = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
        df = make_1m_df(base, 5)

        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)
        got = dm.cache.get_1m_data("BTCUSDT")

        assert got is not None
        assert len(got) == 5

    def test_put_1m_trims_to_limit_keeping_newest(self, tmpdir_path):
        """超 default_1m_rows_limit 时裁剪为最新 N 行，末行是最新 K 线"""
        from data_manager.cache import ShardCache, ShardCacheConfig

        cache = ShardCache(ShardCacheConfig(default_1m_rows_limit=100))
        base = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
        df = make_1m_df(base, 250)

        cache.put_1m_data("BTCUSDT", df)
        got = cache.get_1m_data("BTCUSDT")

        assert len(got) == 100
        assert got["timestamp"].iloc[-1] == df["timestamp"].iloc[-1]
        assert got["timestamp"].iloc[0] == df["timestamp"].iloc[150]


# ══════════════════════════════════════════════════════════════════════════════
# 大周期增量聚合
# ══════════════════════════════════════════════════════════════════════════════


class TestIncrementalAggregation:
    """增量聚合结果与全量聚合一致"""

    @pytest.mark.parametrize("interval,period_minutes,freq", [
        ("1h", 60, "1h"),
        ("4h", 240, "4h"),
        ("8h", 480, "8h"),
    ])
    def test_incremental_matches_full_aggregation(
        self, tmpdir_path, interval, period_minutes, freq
    ):
        """增量聚合（尾部 3 周期）与全量聚合的重叠段逐列一致"""
        dm = make_dm(tmpdir_path)
        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        df_1m = make_1m_df(base, period_minutes * 20)

        full = dm.aggregate_1m_to_interval(df_1m, interval)

        tail_rows = period_minutes * 3
        df_tail = df_1m.iloc[-tail_rows:]
        inc = dm.aggregate_1m_to_interval(df_tail, interval)

        assert not inc.empty
        # 增量结果拼回全量的前半段，应完全等于全量
        keep = full[full["timestamp"] < inc["timestamp"].iloc[0]]
        merged = pd.concat([keep, inc], ignore_index=True)

        assert len(merged) == len(full)
        for col in ["timestamp"] + OHLCV_COLS:
            pd.testing.assert_series_equal(
                merged[col].reset_index(drop=True),
                full[col].reset_index(drop=True),
                check_names=False,
            )

    def test_empty_big_cache_uses_full_aggregation(self, tmpdir_path):
        """大周期缓存为空时走全量路径"""
        dm = make_dm(tmpdir_path)
        dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "1h"])

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        df_1m = make_1m_df(base, 180)
        dm.cache.put("BTCUSDT", "1m", df_1m, force_1m=True)

        assert dm.cache.get("BTCUSDT", "1h") is None

        results = dm._update_big_intervals_from_cache("BTCUSDT")
        assert results.get("1h") is True

        cached = dm.cache.get("BTCUSDT", "1h")
        full = dm.aggregate_1m_to_interval(df_1m, "1h")
        assert len(cached) == len(full)

    def test_backtest_mode_uses_full_aggregation(self, tmpdir_path):
        """回测模式走全量路径（数据窗口随 backtest_timestamp 变化）"""
        dm = make_dm(tmpdir_path, backtest_mode=True)
        dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "1h"])

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
        df_1m = make_1m_df(base, 180)
        dm.cache.put("BTCUSDT", "1m", df_1m, force_1m=True)
        dm.set_backtest_timestamp(base + timedelta(minutes=179))

        # 预置一段大周期缓存
        dm.cache.put("BTCUSDT", "1h", make_big_df(base, 3, "1h"))

        results = dm._update_big_intervals_from_cache("BTCUSDT")
        assert results.get("1h") is True

        cached = dm.cache.get("BTCUSDT", "1h")
        # 回测走全量：结果应等于按 bt_ts 过滤后的全量聚合
        expected = dm.aggregate_1m_to_interval(df_1m, "1h")
        assert len(cached) == len(expected)

    def test_crossing_period_boundary_creates_new_bar(self, tmpdir_path):
        """跨周期边界推送（03:59 → 04:00）生成新的大周期 K 线"""
        dm = make_dm(tmpdir_path)
        dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "4h"])

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

        # 先推到 03:59（1 根未闭合 4h）
        dm.cache.put("BTCUSDT", "1m", make_1m_df(base, 240), force_1m=True)
        dm._update_big_intervals_from_cache("BTCUSDT")
        before = dm.cache.get("BTCUSDT", "4h")
        n_before = len(before)

        # 再推到 04:00（应产生第 2 根 4h）
        dm.cache.put("BTCUSDT", "1m", make_1m_df(base, 241), force_1m=True)
        dm._update_big_intervals_from_cache("BTCUSDT")
        after = dm.cache.get("BTCUSDT", "4h")

        assert len(after) == n_before + 1
        assert after["timestamp"].iloc[-1] == base + timedelta(hours=4)
        assert after["timestamp"].is_monotonic_increasing


# ══════════════════════════════════════════════════════════════════════════════
# 历史保留（本次修复的 bug）
# ══════════════════════════════════════════════════════════════════════════════


class TestBigIntervalHistoryPreserved:
    """大周期缓存不被内存 1m 窗口截断

    现存 bug: _update_big_intervals_from_cache 用「内存 1m 聚合结果」
    整体覆盖缓存，而 _preload_all_big_intervals_from_csv 加载的是
    CSV 完整历史 → 每根 1m K 线丢失历史。
    """

    def test_csv_history_not_truncated_by_1m_window(self, tmpdir_path):
        """CSV 历史 1h 缓存不被内存 1m 窗口截断（改动前应 FAIL）"""
        dm = make_dm(tmpdir_path)
        dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "1h"])

        # CSV 历史：从 2024-01-01 起 1000 根 1h
        csv_start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        csv_1h = make_big_df(csv_start, 1000, "1h")
        dm.cache.put("BTCUSDT", "1h", csv_1h)

        # 内存 1m 只覆盖尾部 300 分钟（远晚于 CSV 起点）
        mem_start = csv_start + timedelta(hours=1000)
        df_1m = make_1m_df(mem_start, 300)
        dm.cache.put("BTCUSDT", "1m", df_1m, force_1m=True)

        dm._update_big_intervals_from_cache("BTCUSDT")
        cached = dm.cache.get("BTCUSDT", "1h")

        # 历史起点必须保留
        assert cached["timestamp"].iloc[0] == csv_start, (
            f"1h 缓存起点被截断: 期望 {csv_start}, 实际 {cached['timestamp'].iloc[0]}"
        )
        # 行数应约等于 CSV 历史 + 新增，而非仅内存 1m 聚合出的 5 根
        assert len(cached) >= 1000, (
            f"1h 缓存被截断为 {len(cached)} 行（CSV 历史有 1000 行）"
        )
        assert cached["timestamp"].is_monotonic_increasing

    def test_falls_back_to_full_when_inc_start_not_after_cache_start(self, tmpdir_path):
        """增量起点 <= 缓存起点时回退全量，不产生空 keep 导致的静默截断"""
        dm = make_dm(tmpdir_path)
        dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "1h"])

        base = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)

        # 缓存起点晚于 1m 数据起点 → 增量起点不会晚于缓存起点
        dm.cache.put("BTCUSDT", "1h", make_big_df(base + timedelta(hours=10), 3, "1h"))
        df_1m = make_1m_df(base, 180)
        dm.cache.put("BTCUSDT", "1m", df_1m, force_1m=True)

        results = dm._update_big_intervals_from_cache("BTCUSDT")
        assert results.get("1h") is True

        cached = dm.cache.get("BTCUSDT", "1h")
        # 回退全量：结果等于全量聚合，不是空 keep + 少量增量
        full = dm.aggregate_1m_to_interval(df_1m, "1h")
        assert len(cached) == len(full)

    def test_repeated_calls_never_shrink_cache(self, tmpdir_path):
        """连续调用 10 次，大周期缓存行数单调不减"""
        dm = make_dm(tmpdir_path)
        dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "1h"])

        csv_start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        dm.cache.put("BTCUSDT", "1h", make_big_df(csv_start, 500, "1h"))

        mem_start = csv_start + timedelta(hours=500)
        counts = []
        for i in range(10):
            dm.cache.put(
                "BTCUSDT", "1m", make_1m_df(mem_start, 180 + i), force_1m=True
            )
            dm._update_big_intervals_from_cache("BTCUSDT")
            cached = dm.cache.get("BTCUSDT", "1h")
            counts.append(len(cached))

        assert counts == sorted(counts), f"缓存行数出现回退: {counts}"
        assert counts[0] >= 500, f"首次调用即截断: {counts[0]} < 500"


# ══════════════════════════════════════════════════════════════════════════════
# CSV 写入行数
# ══════════════════════════════════════════════════════════════════════════════


class TestCsvWriteIsIncremental:
    """写 CSV 只含增量行，不是全量"""

    def test_csv_write_only_contains_incremental_rows(self, tmpdir_path, monkeypatch):
        """增量路径下 save_klines_to_csv 收到的行数远小于缓存总行数"""
        dm = make_dm(tmpdir_path)
        dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "1h"])

        csv_start = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)
        dm.cache.put("BTCUSDT", "1h", make_big_df(csv_start, 500, "1h"))

        mem_start = csv_start + timedelta(hours=500)
        dm.cache.put("BTCUSDT", "1m", make_1m_df(mem_start, 300), force_1m=True)

        captured = []
        orig = dm.kline_repo.save_klines_to_csv

        def spy(symbol, interval, klines):
            captured.append((interval, len(klines)))
            return orig(symbol, interval, klines)

        monkeypatch.setattr(dm.kline_repo, "save_klines_to_csv", spy)

        dm._update_big_intervals_from_cache("BTCUSDT")

        h1 = [n for iv, n in captured if iv == "1h"]
        assert h1, "应写入 1h CSV"
        cached = dm.cache.get("BTCUSDT", "1h")
        assert h1[0] < len(cached) / 10, (
            f"写 CSV 行数 {h1[0]} 接近缓存总数 {len(cached)}，未走增量"
        )
