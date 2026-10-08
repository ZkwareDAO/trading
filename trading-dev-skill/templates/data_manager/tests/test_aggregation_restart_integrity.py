#!/usr/bin/env python3
"""
测试进程重启后大周期聚合的时间段完整性

核心不变式：**任何**落进 CSV / 缓存的大周期桶，其 OHLCV 必须等于用
完整 1m 数据全量聚合得到的真值。不允许出现"看起来有这根，但值是残缺的"。

背景（实测确认的 bug）：
进程被杀时，最后一根 1m 往往是**未闭合**状态就落了盘 —— WS 缓冲区满
10 条即 save_klines_to_csv，不检查 is_final。重启后三处 gap 补齐都用
`latest_ts + 1min` 作起点，正好跳过这根残缺根，于是它永久残留：

    04:15 残缺根 (volume=0.3, 真值 1.0)
      → 04:00-07:59 的 4h 桶 volume = 239.3，真值 240.0
      → 08:00 聚合写入 4h CSV，此后不再被任何路径重算

drop_partial_head 挡不住这个 —— 它处理的是残缺**首**桶（源数据起点不对齐），
而这里是桶**中间**某根的值本身残缺。get_closed_data 也挡不住 —— 它只丢弃
最后一根，而失真的是已闭合的历史桶。

修复：gap 起点改为 latest_ts 本身（不 +1min），让 API 的完整值按
timestamp keep="last" 覆盖残缺值。
"""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from data_manager.klines_data import Kline
from data_manager.klines_loader import resample_ohlcv
from data_manager.manager import DataManager, DataManagerConfig


SYMBOL = "BTCUSDT"

# 与 1m CSV / Kline 一致的列集合
OHLCV_COLS = ("open", "high", "low", "close", "volume")


# ============================================================
# 数据构造
# ============================================================


def make_1m_range(start: str, periods: int, volume: float = 1.0) -> pd.DataFrame:
    """生成连续 1m 数据。价格带正弦波动，确保 high/low 落在桶中间而非端点，
    这样残缺根才能真正影响 high/low —— 单调序列会让 high 恒在桶尾，
    掩盖掉 max 聚合的失真。
    """
    ts = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    idx = np.arange(periods, dtype=float)
    base = 100.0 + np.sin(idx / 7.0) * 5.0
    return pd.DataFrame({
        "timestamp": ts,
        "open": base,
        "high": base + 0.5,
        "low": base - 0.5,
        "close": base + 0.1,
        "volume": np.full(periods, volume),
        "quote_volume": np.full(periods, volume * 100.0),
        "trade_num": np.full(periods, 10, dtype=int),
        "active_buy_volume": np.full(periods, volume / 2),
        "active_buy_quote_volume": np.full(periods, volume * 50.0),
    })


def truncate_last_bar(df: pd.DataFrame, factor: float = 0.3) -> pd.DataFrame:
    """把最后一根改成"未闭合"状态：volume 只累积了一部分，
    high/low 还没走到最终区间。模拟进程被杀那一刻的 WS 快照。
    """
    out = df.copy()
    last = out.index[-1]
    out.loc[last, "volume"] = out.loc[last, "volume"] * factor
    out.loc[last, "quote_volume"] = out.loc[last, "quote_volume"] * factor
    out.loc[last, "active_buy_volume"] = out.loc[last, "active_buy_volume"] * factor
    out.loc[last, "active_buy_quote_volume"] = (
        out.loc[last, "active_buy_quote_volume"] * factor
    )
    # 未闭合时 high/low 尚未探到边界，向 open 收缩
    out.loc[last, "high"] = out.loc[last, "open"]
    out.loc[last, "low"] = out.loc[last, "open"]
    return out


def to_api_rows(df: pd.DataFrame) -> list:
    """DataFrame → Binance klines API 的 12 元素数组格式"""
    rows = []
    for _, r in df.iterrows():
        ts_ms = int(pd.Timestamp(r["timestamp"]).timestamp() * 1000)
        rows.append([
            ts_ms,
            str(r["open"]), str(r["high"]), str(r["low"]), str(r["close"]),
            str(r["volume"]),
            ts_ms + 59_999,
            str(r["quote_volume"]),
            int(r["trade_num"]),
            str(r["active_buy_volume"]),
            str(r["active_buy_quote_volume"]),
            "0",
        ])
    return rows


def assert_all_buckets_exact(
    truth: pd.DataFrame, actual: pd.DataFrame, label: str
):
    """断言 actual 中每一个与 truth 同名的桶，OHLCV 完全一致。

    只比对交集：actual 可以少几根（窗口裁剪、drop_partial_head），
    但**凡是存在的根，值必须精确**。这正是 bug 的形态 —— 根数对得上，值是错的。
    """
    merged = truth.merge(actual, on="timestamp", suffixes=("_t", "_a"))
    assert not merged.empty, f"{label}: 没有可比对的桶"
    for col in OHLCV_COLS:
        if f"{col}_t" not in merged.columns:
            continue
        bad = merged[~np.isclose(merged[f"{col}_t"], merged[f"{col}_a"])]
        assert bad.empty, (
            f"{label}: {col} 失真 {len(bad)}/{len(merged)} 桶\n"
            f"{bad[['timestamp', f'{col}_t', f'{col}_a']].to_string()}"
        )


def make_manager(tmp_path: Path) -> DataManager:
    config = DataManagerConfig(
        csv_dir=str(tmp_path / "klines"),
        realtime_enabled=False,
    )
    dm = DataManager(config)
    dm.enable_kline_repository()
    # sync_to_latest 的「无数据 / >1天」分支现走 download_range（真实网络）。
    # 测试数据全部由 mock 的 _fetch_from_binance_public 提供，故这里把大缺口
    # 补齐全量路由回同一条 mock 接缝（分页取回 + 原子合并），语义与生产路径
    # 的 fapi 兜底一致；需要断言「不应走大缺口」的用例可自行 patch 成 boom。
    async def fake_large_gap_fill(symbol, start_dt, end_dt):
        rows = await dm._fetch_gap_range(symbol, start_dt, end_dt)
        if rows:
            dm._merge_api_data_to_cache(symbol, rows)
        return bool(rows)

    dm._fill_large_gap_via_download_range = fake_large_gap_fill

    # scan_and_fill_holes 生产环境归档优先（fetch_range_rows 走 requests 真实
    # 网络）；测试数据同样由 mock 的 _fetch_from_binance_public 提供，直接
    # 路由回 fapi 分页接缝。
    async def fake_hole_rows(symbol, last_ts, new_ts):
        return await dm._fetch_gap_range(symbol, last_ts, new_ts)

    dm._fetch_hole_rows_archive_first = fake_hole_rows
    return dm


# ============================================================
# 1. gap 补齐起点：必须含最后一根
# ============================================================


class TestGapStartIncludesLastBar:
    """三处 gap 补齐的起点都必须 <= 缓存/CSV 最后一根，否则残缺根永不重取"""

    @pytest.mark.asyncio
    async def test_sync_to_latest_refetches_last_bar(self, tmp_path):
        dm = make_manager(tmp_path)
        # 缓存末根 = 30 分钟前，且是残缺的
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = now - timedelta(minutes=90)
        df = truncate_last_bar(make_1m_range(start.isoformat(), 60))
        last_ts = df["timestamp"].iloc[-1]
        dm.cache.put(SYMBOL, "1m", df, force_1m=True)

        captured = {}

        async def fake_fetch(symbol, day=None, start_time_ms=None, **kw):
            captured["start_ms"] = start_time_ms
            return []

        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch):
            await dm.sync_to_latest(SYMBOL)

        assert "start_ms" in captured, "未触发 gap 补齐"
        requested = pd.Timestamp(captured["start_ms"], unit="ms", tz="UTC")
        assert requested <= last_ts, (
            f"gap 起点 {requested} 晚于末根 {last_ts}，"
            f"残缺的末根不会被重新拉取"
        )

    @pytest.mark.asyncio
    async def test_init_today_realtime_refetches_last_bar(self, tmp_path):
        dm = make_manager(tmp_path)
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = now - timedelta(minutes=90)
        df = truncate_last_bar(make_1m_range(start.isoformat(), 60))
        last_ts = df["timestamp"].iloc[-1]

        captured = {}

        async def fake_fetch(symbol, day=None, start_time_ms=None, **kw):
            captured["start_ms"] = start_time_ms
            return []

        with patch.object(dm, "download_daily_data", return_value=True), \
             patch.object(dm, "_load_csv", return_value=df), \
             patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch), \
             patch.object(dm, "start_realtime_async", return_value=True), \
             patch.object(dm, "subscribe_klines_async", return_value=True):
            await dm.init_today_realtime(SYMBOL)

        assert "start_ms" in captured, "未触发 gap 补齐"
        requested = pd.Timestamp(captured["start_ms"], unit="ms", tz="UTC")
        assert requested <= last_ts, (
            f"gap 起点 {requested} 晚于末根 {last_ts}"
        )

    def test_fill_ws_gap_refetches_last_bar(self, tmp_path):
        dm = make_manager(tmp_path)
        last_ts = datetime(2026, 1, 10, 4, 15, tzinfo=timezone.utc)
        new_ts = datetime(2026, 1, 10, 4, 30, tzinfo=timezone.utc)

        captured = {}

        async def fake_fetch(symbol, day=None, start_time_ms=None,
                             end_time_ms=None, **kw):
            captured["start_ms"] = start_time_ms
            return []

        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch):
            dm._fill_ws_gap_async(SYMBOL, last_ts, new_ts)

        assert "start_ms" in captured, "未触发 gap 补齐"
        requested = pd.Timestamp(captured["start_ms"], unit="ms", tz="UTC")
        assert requested <= pd.Timestamp(last_ts), (
            f"WS gap 起点 {requested} 晚于末根 {last_ts}"
        )


# ============================================================
# 2. 端到端：崩溃 → 重启 → 补齐 → 聚合，桶值必须等于真值
# ============================================================


class TestRestartAggregationIntegrity:
    """用户场景：4:15 停止，4:30 启动，8:00 时 4h 桶必须完整"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("interval", ["1h", "4h", "8h", "1d"])
    async def test_crash_midbar_restart_yields_exact_buckets(
        self, tmp_path, interval
    ):
        """崩溃时残缺的那根 1m，重启补齐后必须被完整值覆盖，
        使大周期每个桶都等于真值。
        """
        dm = make_manager(tmp_path)
        dm.kline_repo.register_symbol(SYMBOL, ["1m", interval])

        # 完整真值：2 天 1m 数据
        total = 2 * 24 * 60
        truth_1m = make_1m_range("2026-01-10 00:00", total)
        truth_agg = resample_ohlcv(
            truth_1m, interval, datetime_column="timestamp"
        )

        # 崩溃点：第 1 天 04:15（含），最后一根残缺
        crash_idx = 4 * 60 + 16  # 00:00..04:15 共 256 根
        pre_crash = truncate_last_bar(truth_1m.iloc[:crash_idx].copy())
        crash_ts = pre_crash["timestamp"].iloc[-1]
        assert crash_ts == pd.Timestamp("2026-01-10 04:15", tz="UTC")

        # 落盘残缺数据（模拟 WS 缓冲区在崩溃前刷盘）
        dm.kline_repo.save_klines_to_csv(
            SYMBOL, "1m", pre_crash.to_dict(orient="records")
        )

        # ---- 重启 @ 04:30 ----
        reloaded = dm._load_csv(SYMBOL, "1m")
        assert reloaded is not None and not reloaded.empty
        assert reloaded["timestamp"].iloc[-1] == crash_ts
        # 确认落盘的确实是残缺值（否则这个测试没有在测东西）
        assert not np.isclose(
            reloaded["volume"].iloc[-1], truth_1m["volume"].iloc[crash_idx - 1]
        ), "前置条件不成立：落盘的末根不是残缺的"
        dm.cache.put(SYMBOL, "1m", reloaded, force_1m=True)

        # gap 补齐：API 按请求的起点返回完整数据，直到 04:30
        restart_idx = 4 * 60 + 31

        async def fake_fetch(symbol, day=None, start_time_ms=None, **kw):
            start = pd.Timestamp(start_time_ms, unit="ms", tz="UTC")
            window = truth_1m[
                (truth_1m["timestamp"] >= start)
                & (truth_1m["timestamp"] < truth_1m["timestamp"].iloc[restart_idx])
            ]
            return to_api_rows(window)

        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch):
            await dm.sync_to_latest(SYMBOL)

        # 残缺根必须已被完整值覆盖
        cached = dm.cache.get_1m_data(SYMBOL)
        row = cached[cached["timestamp"] == crash_ts]
        assert not row.empty, f"{crash_ts} 这根丢了"
        expected_vol = truth_1m["volume"].iloc[crash_idx - 1]
        assert np.isclose(row["volume"].iloc[0], expected_vol), (
            f"崩溃点 {crash_ts} 的 volume 仍是残缺值 "
            f"{row['volume'].iloc[0]}，应为 {expected_vol}"
        )

        # ---- 继续喂完剩余数据，模拟运行到第 2 天 ----
        rest = truth_1m.iloc[restart_idx:]
        combined = pd.concat([cached, rest], ignore_index=True)
        combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        dm.cache.put(SYMBOL, "1m", combined, force_1m=True)

        # 1m 序列本身必须与真值逐行一致
        assert len(combined) == total, f"1m 行数 {len(combined)} != {total}"
        assert_all_buckets_exact(truth_1m, combined, f"{interval}/1m源")

        # ---- 聚合，每个桶必须等于真值 ----
        dm._update_big_intervals_from_cache(SYMBOL)
        agg = dm.cache.get(SYMBOL, interval)
        assert agg is not None and not agg.empty, f"{interval} 聚合为空"
        assert_all_buckets_exact(truth_agg, agg, f"{interval}/缓存")

        # CSV 落盘的同样要精确
        csv_df = dm._load_csv(SYMBOL, interval)
        assert csv_df is not None and not csv_df.empty, f"{interval} CSV 为空"
        assert_all_buckets_exact(truth_agg, csv_df, f"{interval}/CSV")

    @pytest.mark.asyncio
    async def test_crash_bucket_covers_full_period(self, tmp_path):
        """针对用户提问：4:15 崩溃，8:00 时 04:00-07:59 那个 4h 桶
        必须由完整的 240 根 1m 构成。
        """
        dm = make_manager(tmp_path)
        dm.kline_repo.register_symbol(SYMBOL, ["1m", "4h"])

        truth_1m = make_1m_range("2026-01-10 00:00", 12 * 60)
        crash_idx = 4 * 60 + 16
        pre_crash = truncate_last_bar(truth_1m.iloc[:crash_idx].copy())
        dm.kline_repo.save_klines_to_csv(
            SYMBOL, "1m", pre_crash.to_dict(orient="records")
        )

        reloaded = dm._load_csv(SYMBOL, "1m")
        dm.cache.put(SYMBOL, "1m", reloaded, force_1m=True)

        restart_idx = 4 * 60 + 31

        async def fake_fetch(symbol, day=None, start_time_ms=None, **kw):
            start = pd.Timestamp(start_time_ms, unit="ms", tz="UTC")
            window = truth_1m[
                (truth_1m["timestamp"] >= start)
                & (truth_1m["timestamp"] < truth_1m["timestamp"].iloc[restart_idx])
            ]
            return to_api_rows(window)

        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch):
            await dm.sync_to_latest(SYMBOL)

        cached = dm.cache.get_1m_data(SYMBOL)
        combined = pd.concat([cached, truth_1m.iloc[restart_idx:]],
                             ignore_index=True)
        combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        dm.cache.put(SYMBOL, "1m", combined, force_1m=True)
        dm._update_big_intervals_from_cache(SYMBOL)

        agg = dm.cache.get(SYMBOL, "4h")
        bucket = agg[agg["timestamp"] == pd.Timestamp("2026-01-10 04:00", tz="UTC")]
        assert not bucket.empty, "04:00 的 4h 桶不存在"

        src = truth_1m[
            (truth_1m["timestamp"] >= pd.Timestamp("2026-01-10 04:00", tz="UTC"))
            & (truth_1m["timestamp"] < pd.Timestamp("2026-01-10 08:00", tz="UTC"))
        ]
        assert len(src) == 240
        assert np.isclose(bucket["volume"].iloc[0], src["volume"].sum()), (
            f"4h[04:00] volume={bucket['volume'].iloc[0]}，"
            f"应为 {src['volume'].sum()}（240 根之和）"
        )
        assert np.isclose(bucket["high"].iloc[0], src["high"].max())
        assert np.isclose(bucket["low"].iloc[0], src["low"].min())
        assert np.isclose(bucket["open"].iloc[0], src["open"].iloc[0])
        assert np.isclose(bucket["close"].iloc[0], src["close"].iloc[-1])


# ============================================================
# 3. WS 断连中途 gap：桶值同样必须精确
# ============================================================


class TestWsGapAggregationIntegrity:

    def test_ws_gap_refill_restores_exact_buckets(self, tmp_path):
        """WS 断连期间缓存末根残缺，_fill_ws_gap_async 补齐后
        大周期桶必须回到真值。
        """
        dm = make_manager(tmp_path)
        dm.kline_repo.register_symbol(SYMBOL, ["1m", "1h"])

        truth_1m = make_1m_range("2026-01-10 00:00", 6 * 60)
        truth_agg = resample_ohlcv(truth_1m, "1h", datetime_column="timestamp")

        # 断连点：02:20，末根残缺
        break_idx = 2 * 60 + 21
        pre = truncate_last_bar(truth_1m.iloc[:break_idx].copy())
        dm.cache.put(SYMBOL, "1m", pre, force_1m=True)
        last_ts = pre["timestamp"].iloc[-1].to_pydatetime()

        # 恢复点：02:40
        resume_idx = 2 * 60 + 41
        new_ts = truth_1m["timestamp"].iloc[resume_idx].to_pydatetime()

        async def fake_fetch(symbol, day=None, start_time_ms=None,
                             end_time_ms=None, **kw):
            start = pd.Timestamp(start_time_ms, unit="ms", tz="UTC")
            end = pd.Timestamp(end_time_ms, unit="ms", tz="UTC")
            window = truth_1m[
                (truth_1m["timestamp"] >= start) & (truth_1m["timestamp"] < end)
            ]
            return to_api_rows(window)

        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch):
            dm._fill_ws_gap_async(SYMBOL, last_ts, new_ts)

        cached = dm.cache.get_1m_data(SYMBOL)
        row = cached[cached["timestamp"] == pd.Timestamp(last_ts)]
        assert np.isclose(
            row["volume"].iloc[0], truth_1m["volume"].iloc[break_idx - 1]
        ), "断连点残缺根未被覆盖"

        # 补完剩余，聚合校验
        combined = pd.concat([cached, truth_1m.iloc[resume_idx:]],
                             ignore_index=True)
        combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        dm.cache.put(SYMBOL, "1m", combined, force_1m=True)
        dm._update_big_intervals_from_cache(SYMBOL)

        agg = dm.cache.get(SYMBOL, "1h")
        assert_all_buckets_exact(truth_agg, agg, "WS-gap/1h")


# ============================================================
# 4. 反复重启：不能累积失真
# ============================================================


class TestRepeatedRestarts:

    @pytest.mark.asyncio
    async def test_multiple_crashes_do_not_accumulate_distortion(self, tmp_path):
        """连续 3 次崩溃-重启，每次都在桶中间。最终所有桶仍等于真值。"""
        dm = make_manager(tmp_path)
        dm.kline_repo.register_symbol(SYMBOL, ["1m", "4h"])

        truth_1m = make_1m_range("2026-01-10 00:00", 24 * 60)
        truth_agg = resample_ohlcv(truth_1m, "4h", datetime_column="timestamp")

        # 崩溃点落在不同 4h 桶的中间
        crash_points = [4 * 60 + 16, 9 * 60 + 37, 14 * 60 + 5]
        cursor = 0

        for crash_idx in crash_points:
            segment = truth_1m.iloc[cursor:crash_idx].copy()
            segment = truncate_last_bar(segment)
            dm.kline_repo.save_klines_to_csv(
                SYMBOL, "1m", segment.to_dict(orient="records")
            )

            # 重启：从 CSV 读回 + gap 补齐
            reloaded = dm._load_csv(SYMBOL, "1m")
            dm.cache.put(SYMBOL, "1m", reloaded, force_1m=True)

            async def fake_fetch(symbol, day=None, start_time_ms=None,
                                 _idx=crash_idx, **kw):
                start = pd.Timestamp(start_time_ms, unit="ms", tz="UTC")
                end = truth_1m["timestamp"].iloc[_idx]
                window = truth_1m[
                    (truth_1m["timestamp"] >= start)
                    & (truth_1m["timestamp"] < end)
                ]
                return to_api_rows(window)

            with patch.object(dm, "_fetch_from_binance_public",
                              side_effect=fake_fetch):
                await dm.sync_to_latest(SYMBOL)

            dm._update_big_intervals_from_cache(SYMBOL)
            cursor = crash_idx

        # 跑完剩余数据
        tail = truth_1m.iloc[cursor:]
        cached = dm.cache.get_1m_data(SYMBOL)
        combined = pd.concat([cached, tail], ignore_index=True)
        combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        dm.cache.put(SYMBOL, "1m", combined, force_1m=True)
        dm.kline_repo.save_klines_to_csv(
            SYMBOL, "1m", tail.to_dict(orient="records")
        )
        dm._update_big_intervals_from_cache(SYMBOL)

        assert len(combined) == 24 * 60

        agg = dm.cache.get(SYMBOL, "4h")
        assert_all_buckets_exact(truth_agg, agg, "多次重启/缓存")

        csv_df = dm._load_csv(SYMBOL, "4h")
        assert_all_buckets_exact(truth_agg, csv_df, "多次重启/CSV")


# ============================================================
# 4b. 真实配置形态与边界条件
# ============================================================


class TestRealWorldScenarios:
    """覆盖线上实际使用的多周期组合与容易漏掉的边界"""

    @pytest.mark.asyncio
    async def test_multi_timeframe_simultaneously(self, tmp_path):
        """线上 sar_snt3_v3 同时注册 8h（信号）+ 1h（SAR 跟踪）。
        一次崩溃必须让**两个**周期都回到真值 —— 它们共享同一份残缺的
        1m 源，任一失真都会让信号与跟踪脱节。
        """
        dm = make_manager(tmp_path)
        dm.kline_repo.register_symbol(SYMBOL, ["1m", "1h", "8h"])

        truth_1m = make_1m_range("2026-01-10 00:00", 2 * 24 * 60)
        truth = {
            tf: resample_ohlcv(truth_1m, tf, datetime_column="timestamp")
            for tf in ("1h", "8h")
        }

        crash_idx = 4 * 60 + 16
        pre = truncate_last_bar(truth_1m.iloc[:crash_idx].copy())
        dm.kline_repo.save_klines_to_csv(
            SYMBOL, "1m", pre.to_dict(orient="records")
        )
        dm.cache.put(SYMBOL, "1m", dm._load_csv(SYMBOL, "1m"), force_1m=True)

        restart_idx = 4 * 60 + 31

        async def fake_fetch(symbol, day=None, start_time_ms=None, **kw):
            start = pd.Timestamp(start_time_ms, unit="ms", tz="UTC")
            end = truth_1m["timestamp"].iloc[restart_idx]
            return to_api_rows(truth_1m[
                (truth_1m["timestamp"] >= start) & (truth_1m["timestamp"] < end)
            ])

        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch):
            await dm.sync_to_latest(SYMBOL)

        cached = dm.cache.get_1m_data(SYMBOL)
        combined = pd.concat([cached, truth_1m.iloc[restart_idx:]],
                             ignore_index=True)
        combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        dm.cache.put(SYMBOL, "1m", combined, force_1m=True)
        dm._update_big_intervals_from_cache(SYMBOL)

        for tf in ("1h", "8h"):
            agg = dm.cache.get(SYMBOL, tf)
            assert agg is not None and not agg.empty, f"{tf} 聚合为空"
            assert_all_buckets_exact(truth[tf], agg, f"多周期/{tf}")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("crash_min,label", [
        (4 * 60, "正好落在 4h 边界"),
        (4 * 60 + 1, "边界后 1 分钟"),
        (8 * 60 - 1, "桶内最后一分钟"),
        (2 * 60 + 30, "桶正中"),
    ])
    async def test_crash_at_various_offsets(self, tmp_path, crash_min, label):
        """崩溃点相对周期边界的位置不应影响最终完整性。
        边界处最易出错：残缺根可能是某个桶的唯一一根。
        """
        dm = make_manager(tmp_path)
        dm.kline_repo.register_symbol(SYMBOL, ["1m", "4h"])

        truth_1m = make_1m_range("2026-01-10 00:00", 16 * 60)
        truth_agg = resample_ohlcv(truth_1m, "4h", datetime_column="timestamp")

        crash_idx = crash_min + 1
        pre = truncate_last_bar(truth_1m.iloc[:crash_idx].copy())
        dm.kline_repo.save_klines_to_csv(
            SYMBOL, "1m", pre.to_dict(orient="records")
        )
        dm.cache.put(SYMBOL, "1m", dm._load_csv(SYMBOL, "1m"), force_1m=True)

        restart_idx = crash_idx + 15

        async def fake_fetch(symbol, day=None, start_time_ms=None, **kw):
            start = pd.Timestamp(start_time_ms, unit="ms", tz="UTC")
            end = truth_1m["timestamp"].iloc[restart_idx]
            return to_api_rows(truth_1m[
                (truth_1m["timestamp"] >= start) & (truth_1m["timestamp"] < end)
            ])

        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch):
            await dm.sync_to_latest(SYMBOL)

        cached = dm.cache.get_1m_data(SYMBOL)
        combined = pd.concat([cached, truth_1m.iloc[restart_idx:]],
                             ignore_index=True)
        combined = combined.drop_duplicates(subset=["timestamp"], keep="last")
        combined = combined.sort_values("timestamp").reset_index(drop=True)
        dm.cache.put(SYMBOL, "1m", combined, force_1m=True)

        assert len(combined) == 16 * 60, f"{label}: 1m 行数 {len(combined)}"
        assert_all_buckets_exact(truth_1m, combined, f"{label}/1m")

        dm._update_big_intervals_from_cache(SYMBOL)
        assert_all_buckets_exact(
            truth_agg, dm.cache.get(SYMBOL, "4h"), f"{label}/4h"
        )

    def test_incremental_after_trim_keeps_buckets_exact(self, tmp_path):
        """缓存裁剪把 1m 起点切到桶中间后，增量聚合不得用残缺首桶
        覆盖 CSV 里完整的同名桶。这是 drop_partial_head 的职责，
        与 gap 修复正交，一并回归。
        """
        dm = make_manager(tmp_path)
        dm.kline_repo.register_symbol(SYMBOL, ["1m", "4h"])

        truth_1m = make_1m_range("2026-01-10 00:00", 24 * 60)
        truth_agg = resample_ohlcv(truth_1m, "4h", datetime_column="timestamp")

        # 先用完整数据建立 4h 缓存与 CSV
        dm.cache.put(SYMBOL, "1m", truth_1m, force_1m=True)
        dm._update_big_intervals_from_cache(SYMBOL)
        assert_all_buckets_exact(truth_agg, dm.cache.get(SYMBOL, "4h"), "裁剪前")

        # 模拟裁剪：1m 起点落在 4h 桶中间（10:37）
        trimmed = truth_1m.iloc[10 * 60 + 37:].reset_index(drop=True)
        dm.cache.put(SYMBOL, "1m", trimmed, force_1m=True)
        dm._update_big_intervals_from_cache(SYMBOL)

        # 缓存与 CSV 中凡是存在的桶都必须仍等于真值
        assert_all_buckets_exact(
            truth_agg, dm.cache.get(SYMBOL, "4h"), "裁剪后/缓存"
        )
        assert_all_buckets_exact(
            truth_agg, dm._load_csv(SYMBOL, "4h"), "裁剪后/CSV"
        )

    @pytest.mark.asyncio
    async def test_no_gap_leaves_data_intact(self, tmp_path):
        """无 gap（正常运行）时，起点改动不得造成重复行或数据回退。
        latest_ts 被重新拉取，去重必须保证行数不变。
        """
        dm = make_manager(tmp_path)
        dm.kline_repo.register_symbol(SYMBOL, ["1m", "4h"])

        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        start = now - timedelta(minutes=300)
        df = make_1m_range(start.isoformat(), 300)
        dm.cache.put(SYMBOL, "1m", df, force_1m=True)
        before = len(df)
        last_ts = df["timestamp"].iloc[-1]

        async def fake_fetch(symbol, day=None, start_time_ms=None, **kw):
            start_ts = pd.Timestamp(start_time_ms, unit="ms", tz="UTC")
            return to_api_rows(df[df["timestamp"] >= start_ts])

        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch):
            await dm.sync_to_latest(SYMBOL)

        after = dm.cache.get_1m_data(SYMBOL)
        assert len(after) == before, (
            f"重复拉取造成行数变化：{before} → {len(after)}"
        )
        assert after["timestamp"].is_unique, "存在重复时间戳"
        assert after["timestamp"].iloc[-1] == last_ts, "末根时间戳回退"
        assert after["timestamp"].is_monotonic_increasing, "时间戳非单调"

    @pytest.mark.asyncio
    async def test_short_gap_branch_end_to_end(self, tmp_path):
        """用户提问的原场景，走 sync_to_latest 的 **gap <= 1 天** 分支。

        必须用"距今 15 分钟"这样的相对时间构造数据 —— 固定历史日期会让
        gap_days > 1，从而路由到 batch_download_history + init_today_realtime
        的**全量下载**分支，绕开这里要验的增量 gap 逻辑。上面那些 e2e 用例
        正是走了全量分支（实测：只回退 sync_to_latest 的 +1min 时它们全绿）。
        """
        dm = make_manager(tmp_path)
        dm.kline_repo.register_symbol(SYMBOL, ["1m", "4h"])

        # 对齐到 4h 边界，让崩溃点落在桶中间且距今 < 1 天
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        bucket_start = now.replace(
            hour=(now.hour // 4) * 4, minute=0
        ) - timedelta(hours=4)
        span = int((now - bucket_start).total_seconds() // 60) + 1
        truth_1m = make_1m_range(bucket_start.isoformat(), span)
        truth_agg = resample_ohlcv(truth_1m, "4h", datetime_column="timestamp")

        # 崩溃在 15 分钟前，末根残缺
        crash_idx = span - 15
        pre = truncate_last_bar(truth_1m.iloc[:crash_idx].copy())
        crash_ts = pre["timestamp"].iloc[-1]
        dm.kline_repo.save_klines_to_csv(
            SYMBOL, "1m", pre.to_dict(orient="records")
        )
        dm.cache.put(SYMBOL, "1m", dm._load_csv(SYMBOL, "1m"), force_1m=True)

        called = {}

        async def fake_fetch(symbol, day=None, start_time_ms=None, **kw):
            called["hit"] = True
            start_ts = pd.Timestamp(start_time_ms, unit="ms", tz="UTC")
            return to_api_rows(truth_1m[truth_1m["timestamp"] >= start_ts])

        # 若走了全量分支，这两个会被调用 → 断言失败，暴露测试没测到点上
        async def boom_batch(*a, **kw):
            raise AssertionError("走到了全量下载分支，未覆盖 gap<=1天 逻辑")

        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch), \
             patch.object(dm, "batch_download_history", side_effect=boom_batch):
            await dm.sync_to_latest(SYMBOL)

        assert called.get("hit"), "gap 补齐未触发"

        # 残缺根已被完整值覆盖
        cached = dm.cache.get_1m_data(SYMBOL)
        row = cached[cached["timestamp"] == crash_ts]
        assert not row.empty, f"{crash_ts} 丢失"
        assert np.isclose(
            row["volume"].iloc[0], truth_1m["volume"].iloc[crash_idx - 1]
        ), f"崩溃点 {crash_ts} 的 volume 仍残缺：{row['volume'].iloc[0]}"

        assert len(cached) == span, f"1m 行数 {len(cached)} != {span}"
        assert_all_buckets_exact(truth_1m, cached, "短gap/1m")

        dm._update_big_intervals_from_cache(SYMBOL)
        assert_all_buckets_exact(
            truth_agg, dm.cache.get(SYMBOL, "4h"), "短gap/4h缓存"
        )
        assert_all_buckets_exact(
            truth_agg, dm._load_csv(SYMBOL, "4h"), "短gap/4hCSV"
        )


# ============================================================
# 4c. K 线不完整的其他形态
# ============================================================


class TestIncompleteKlineForms:
    """"不完整"不止"末根残缺"一种形态，各自的失败模式不同。

    实测三种形态在 resample_ohlcv 里的行为（/tmp 探测脚本已验证）：

    | 形态           | 行为                                    | 可检测性 |
    |----------------|-----------------------------------------|----------|
    | 末根残缺       | 桶值失真（volume 偏低）                 | 无感知   |
    | 桶内挖洞       | 桶照样生成，volume 按实到根数求和       | 无感知   |
    | 整桶缺失       | dropna() 静默丢弃该桶，序列出现时间跳跃 | 桶数变少 |
    | 输入乱序       | 安全 —— pandas resample 内部按 index 排序 | 不适用  |

    关键：前三种**都不报错**。桶内挖洞尤其危险 —— 时间戳序列看不出任何
    异常（桶还在、时间连续），只有 volume 悄悄偏低。所以这里的断言必须
    落在"桶内实际根数"上，而不能只看桶存在与否。
    """

    def test_bucket_with_hole_is_detectable_by_row_count(self):
        """桶内挖洞：桶照样生成且时间戳连续，只有 volume 偏低。

        锚定这个"静默"行为本身 —— 若哪天 resample 改成对缺口报错/补 NaN，
        本测试会失败，提醒重新评估依赖它的调用方。
        """
        full = make_1m_range("2026-01-10 00:00", 240)
        truth = resample_ohlcv(full, "4h", datetime_column="timestamp")

        holed = full.drop(full.index[100:130]).reset_index(drop=True)
        out = resample_ohlcv(holed, "4h", datetime_column="timestamp")

        # 桶数不变、时间戳不变 —— 从结构上完全看不出缺了 30 根
        assert len(out) == len(truth) == 1
        assert out["timestamp"].iloc[0] == truth["timestamp"].iloc[0]
        # 但 volume 少了正好 30 根的量
        assert np.isclose(
            out["volume"].iloc[0], truth["volume"].iloc[0] - 30.0
        ), "挖洞后 volume 未按实到根数求和，聚合语义已变"

    def test_missing_whole_bucket_creates_time_jump(self):
        """整桶缺失：dropna() 把该桶整根丢掉，序列出现时间跳跃。

        这是唯一"可从结构察觉"的形态 —— 调用方若假设桶时间戳连续递增
        且步长恒定，会在这里踩空。
        """
        a = make_1m_range("2026-01-10 00:00", 240)          # 00:00-03:59
        c = make_1m_range("2026-01-10 08:00", 240)          # 08:00-11:59
        gapped = pd.concat([a, c], ignore_index=True)

        out = resample_ohlcv(gapped, "4h", datetime_column="timestamp")
        stamps = list(out["timestamp"])

        assert len(out) == 2, f"应只剩 2 个桶，实际 {len(out)}"
        assert stamps[0] == pd.Timestamp("2026-01-10 00:00", tz="UTC")
        # 04:00 桶被静默丢弃，而非补成 NaN 或 0
        assert pd.Timestamp("2026-01-10 04:00", tz="UTC") not in stamps
        assert stamps[1] == pd.Timestamp("2026-01-10 08:00", tz="UTC")
        # 相邻桶间隔 8h 而非 4h —— 时间跳跃
        assert (stamps[1] - stamps[0]) == pd.Timedelta(hours=8)

    def test_out_of_order_input_is_safe(self):
        """输入乱序不影响聚合：pandas resample 按 DatetimeIndex 分桶排序。

        WS 重放 / gap 补齐会产生乱序拼接，这条锚定它是安全的，
        免得后续为"防乱序"加多余的排序逻辑。
        """
        n = 240
        ts = pd.date_range("2026-01-10 00:00", periods=n, freq="1min", tz="UTC")
        r = np.arange(n, dtype=float)
        df = pd.DataFrame({
            "timestamp": ts, "open": 100 + r, "high": 100 + r,
            "low": 100 + r, "close": 100 + r,
            "volume": 1.0, "quote_volume": 100.0,
        })
        truth = resample_ohlcv(df, "4h", datetime_column="timestamp")
        shuffled = df.sample(frac=1, random_state=1).reset_index(drop=True)
        out = resample_ohlcv(shuffled, "4h", datetime_column="timestamp")

        for col in ("open", "high", "low", "close", "volume"):
            assert np.isclose(out[col].iloc[0], truth[col].iloc[0]), (
                f"乱序输入导致 {col} 失真"
            )

    @pytest.mark.asyncio
    async def test_mid_hole_is_invisible_to_ws_gap_detection(self):
        """**已知缺陷**：中部的洞永远不会被 WS gap 检测发现。

        `_on_kline_received` 的连续性检查只比较「缓存末根」与「新推送」：

            diff = new_ts - existing['timestamp'].iloc[-1]
            if diff > 90: _fill_ws_gap_async(...)

        它能发现「末尾断档」，发现不了「中部空洞」—— 只要末根紧接新推送，
        diff 就是 60 秒，检查通过，洞被无限期保留。而聚合又不报错
        （见 test_bucket_with_hole_is_detectable_by_row_count），于是
        4h 桶带着偏低的 volume 一路喂给策略。

        本测试锚定这个**当前行为**，不是宣称它正确。若日后加了全序列
        连续性校验，本测试会失败 —— 那时应改为断言洞被检出并补齐。
        """
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        dm = make_manager(tmp)
        dm.kline_repo.register_symbol(SYMBOL, ["1m", "4h"])

        # 固定时间（与本文件其他用例的 2026-01-10 基准一致）。
        # 原先用 datetime.now()：240 根窗口相对 resample 的 4h 网格位置随挂钟
        # 漂移，洞（第 100-130 根）有时落在保留桶、有时落在被 drop_partial_head
        # 丢掉的残缺首桶里，本测试便在每个 4h 边界前约 15 分钟（如
        # 07:44-07:58 UTC）假失败。此处固定为 03:59，洞稳定落在 00:00 桶内。
        now = datetime(2026, 1, 10, 3, 59, tzinfo=timezone.utc)
        full = make_1m_range((now - timedelta(minutes=239)).isoformat(), 240)
        holed = full.drop(full.index[100:130]).reset_index(drop=True)
        dm.cache.put(SYMBOL, "1m", holed, force_1m=True)

        # WS 推下一根，时间紧接缓存末根（diff = 60s，连续性检查通过）
        nxt = now + timedelta(minutes=1)
        kline = Kline(
            symbol=SYMBOL, interval="1m", timestamp=nxt,
            open=100.0, high=100.5, low=99.5, close=100.1,
            volume=1.0, quote_volume=100.0, trade_num=10,
            active_buy_volume=0.5, active_buy_quote_volume=50.0,
            is_final=True,
        )

        # _on_kline_received 有「滞后 >5 分钟跳过」的实时保护
        # （manager.py），固定时间必须配套固定时间源，否则这根 K 线会被拒。
        with patch.object(dm, "_fill_ws_gap_async") as spy, \
                patch.object(dm, "_utcnow", return_value=nxt):
            dm._on_kline_received(kline)

        assert spy.call_count == 0, (
            "中部空洞竟然触发了 gap 补齐 —— 说明已加入全序列连续性校验，"
            "本测试应改为断言洞被检出并补齐"
        )

        # 洞仍在，且聚合不报错、桶照样生成
        cached = dm.cache.get_1m_data(SYMBOL)
        assert len(cached) == 211, f"缓存行数 {len(cached)}，洞已被意外填补"
        agg = dm.cache.get(SYMBOL, "4h")
        assert agg is not None and not agg.empty
        # volume 明显低于该桶应有的根数 —— 静默失真。
        # 真值对齐 agg 实际保留的那个桶（不能用 floor("h")+4h 猜边界，
        # floor("h") 是按小时取整而非按 4h 网格）。
        bucket_start = agg["timestamp"].iloc[0]
        bucket_truth = full[
            (full["timestamp"] >= bucket_start)
            & (full["timestamp"] < bucket_start + pd.Timedelta(hours=4))
        ]
        assert agg["volume"].iloc[0] < len(bucket_truth), (
            f"首桶 volume 未偏低，前置条件已变："
            f"桶起点={bucket_start}, vol={agg['volume'].iloc[0]}, "
            f"该桶应有 {len(bucket_truth)} 根"
        )

    def test_explicit_gap_range_is_refilled(self):
        """给定明确的洞边界时，_fill_ws_gap_async 能把该区间补满。

        这验证的是补齐**能力**（区间内的行被真正插入，而非仅靠
        keep="last" 覆盖末根）。注意它不代表洞会被自动发现 ——
        发现能力的缺失见 test_mid_hole_is_invisible_to_ws_gap_detection。
        """
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        dm = make_manager(tmp)
        dm.kline_repo.register_symbol(SYMBOL, ["1m", "4h"])

        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        full = make_1m_range((now - timedelta(minutes=239)).isoformat(), 240)

        hole_lo, hole_hi = 100, 130
        holed = full.drop(full.index[hole_lo:hole_hi]).reset_index(drop=True)
        dm.cache.put(SYMBOL, "1m", holed, force_1m=True)
        assert len(holed) == 210, "前置条件：洞确实存在"

        async def fake_fetch(symbol, day=None, start_time_ms=None,
                             end_time_ms=None, **kw):
            start = pd.Timestamp(start_time_ms, unit="ms", tz="UTC")
            w = full[full["timestamp"] >= start]
            if end_time_ms is not None:
                end = pd.Timestamp(end_time_ms, unit="ms", tz="UTC")
                w = w[w["timestamp"] < end]
            return to_api_rows(w)

        # 洞的真实边界：last=洞前最后一根，new=洞后第一根
        last_ts = full["timestamp"].iloc[hole_lo - 1].to_pydatetime()
        new_ts = full["timestamp"].iloc[hole_hi].to_pydatetime()

        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch):
            dm._fill_ws_gap_async(SYMBOL, last_ts, new_ts)

        cached = dm.cache.get_1m_data(SYMBOL)
        assert len(cached) == 240, (
            f"补齐后 {len(cached)} 行 != 240，洞未填满"
        )
        assert cached["timestamp"].is_unique
        assert cached["timestamp"].is_monotonic_increasing
        assert_all_buckets_exact(full, cached, "洞补齐/1m")

        dm._update_big_intervals_from_cache(SYMBOL)
        truth_agg = resample_ohlcv(full, "4h", datetime_column="timestamp")
        assert_all_buckets_exact(
            truth_agg, dm.cache.get(SYMBOL, "4h"), "洞补齐/4h"
        )


# ============================================================
# 4d. 定时扫描补洞（方案 C）
# ============================================================


class TestHoleScanAndFill:
    """`find_holes` + `scan_and_fill_holes`：补上 WS 路径的发现盲区。

    设计取舍（方案 C）：不在 `_on_kline_received` 热路径做全序列扫描
    （每根 K 线扫几十万行缓存代价过高），改由定时维护任务承担。
    代价是洞最多存在一个维护周期（默认 5 分钟）。
    """

    def _mk(self, tmp_path):
        dm = make_manager(tmp_path)
        dm.kline_repo.register_symbol(SYMBOL, ["1m", "4h"])
        return dm

    # ---------- find_holes ----------

    def test_no_holes_on_contiguous_data(self, tmp_path):
        dm = self._mk(tmp_path)
        dm.cache.put(SYMBOL, "1m", make_1m_range("2026-01-10 00:00", 240),
                     force_1m=True)
        assert dm.find_holes(SYMBOL) == []

    def test_finds_single_hole_with_correct_bounds(self, tmp_path):
        """区间语义必须是 [洞前最后一根, 洞后第一根)，与 _fill_gap_range 对齐"""
        dm = self._mk(tmp_path)
        full = make_1m_range("2026-01-10 00:00", 240)
        holed = full.drop(full.index[100:130]).reset_index(drop=True)
        dm.cache.put(SYMBOL, "1m", holed, force_1m=True)

        holes = dm.find_holes(SYMBOL)
        assert len(holes) == 1
        lo, hi = holes[0]
        assert pd.Timestamp(lo) == full["timestamp"].iloc[99]
        assert pd.Timestamp(hi) == full["timestamp"].iloc[130]

    def test_finds_multiple_holes(self, tmp_path):
        dm = self._mk(tmp_path)
        full = make_1m_range("2026-01-10 00:00", 240)
        drop = list(range(30, 45)) + list(range(100, 110)) + list(range(200, 220))
        dm.cache.put(SYMBOL, "1m",
                     full.drop(full.index[drop]).reset_index(drop=True),
                     force_1m=True)
        assert len(dm.find_holes(SYMBOL)) == 3

    def test_single_minute_hole_is_detected(self, tmp_path):
        """只缺 1 根也必须检出 —— 间隔 120s > 90s 阈值"""
        dm = self._mk(tmp_path)
        full = make_1m_range("2026-01-10 00:00", 240)
        dm.cache.put(SYMBOL, "1m",
                     full.drop(full.index[[100]]).reset_index(drop=True),
                     force_1m=True)
        assert len(dm.find_holes(SYMBOL)) == 1

    @pytest.mark.parametrize("df_desc,builder", [
        ("空缓存", lambda: None),
        ("单行", lambda: make_1m_range("2026-01-10 00:00", 1)),
        ("两行连续", lambda: make_1m_range("2026-01-10 00:00", 2)),
    ])
    def test_degenerate_inputs_return_empty(self, tmp_path, df_desc, builder):
        """退化输入不得抛异常 —— 定时任务里抛异常会污染日志且可能中断循环"""
        dm = self._mk(tmp_path)
        df = builder()
        if df is not None:
            dm.cache.put(SYMBOL, "1m", df, force_1m=True)
        assert dm.find_holes(SYMBOL) == [], df_desc

    def test_max_holes_truncates(self, tmp_path):
        """洞过多时截断并告警，而非无上限逐个补（数据源有系统性问题）"""
        dm = self._mk(tmp_path)
        full = make_1m_range("2026-01-10 00:00", 240)
        # 每隔一根删一根 → 制造大量洞
        drop = list(range(10, 200, 2))
        dm.cache.put(SYMBOL, "1m",
                     full.drop(full.index[drop]).reset_index(drop=True),
                     force_1m=True)
        holes = dm.find_holes(SYMBOL, max_holes=5)
        assert len(holes) == 5

    # ---------- scan_and_fill_holes ----------

    @pytest.mark.asyncio
    async def test_fills_all_holes_and_restores_buckets(self, tmp_path):
        """端到端：多个洞全部补满，1m 与 4h 都回到真值"""
        dm = self._mk(tmp_path)
        full = make_1m_range("2026-01-10 00:00", 240)
        truth_agg = resample_ohlcv(full, "4h", datetime_column="timestamp")

        drop = list(range(50, 70)) + list(range(150, 165))
        holed = full.drop(full.index[drop]).reset_index(drop=True)
        dm.cache.put(SYMBOL, "1m", holed, force_1m=True)

        async def fake_fetch(symbol, day=None, start_time_ms=None,
                             end_time_ms=None, **kw):
            s = pd.Timestamp(start_time_ms, unit="ms", tz="UTC")
            w = full[full["timestamp"] >= s]
            if end_time_ms is not None:
                w = w[w["timestamp"] < pd.Timestamp(end_time_ms, unit="ms",
                                                    tz="UTC")]
            return to_api_rows(w)

        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch):
            filled = await dm.scan_and_fill_holes(SYMBOL)

        assert filled > 0
        after = dm.cache.get_1m_data(SYMBOL)
        assert len(after) == 240, f"补齐后 {len(after)} 行 != 240"
        assert after["timestamp"].is_unique
        assert after["timestamp"].is_monotonic_increasing
        assert dm.find_holes(SYMBOL) == [], "补齐后仍有洞"
        assert_all_buckets_exact(full, after, "扫描补洞/1m")
        assert_all_buckets_exact(
            truth_agg, dm.cache.get(SYMBOL, "4h"), "扫描补洞/4h"
        )

    @pytest.mark.asyncio
    async def test_noop_when_no_holes(self, tmp_path):
        """无洞时不得发起任何 API 请求"""
        dm = self._mk(tmp_path)
        dm.cache.put(SYMBOL, "1m", make_1m_range("2026-01-10 00:00", 240),
                     force_1m=True)
        with patch.object(dm, "_fetch_from_binance_public") as spy:
            filled = await dm.scan_and_fill_holes(SYMBOL)
        assert filled == 0
        assert spy.call_count == 0

    @pytest.mark.asyncio
    async def test_api_failure_leaves_data_intact(self, tmp_path):
        """API 全部失败时数据不得损坏或重复 —— 洞还在，但不能更糟"""
        dm = self._mk(tmp_path)
        full = make_1m_range("2026-01-10 00:00", 240)
        holed = full.drop(full.index[100:130]).reset_index(drop=True)
        dm.cache.put(SYMBOL, "1m", holed, force_1m=True)
        before = len(holed)

        with patch.object(dm, "_fetch_from_binance_public", return_value=[]):
            filled = await dm.scan_and_fill_holes(SYMBOL)

        assert filled == 0
        after = dm.cache.get_1m_data(SYMBOL)
        assert len(after) == before
        assert after["timestamp"].is_unique
        assert after["timestamp"].is_monotonic_increasing

    @pytest.mark.asyncio
    async def test_api_exception_is_contained(self, tmp_path):
        """API 抛异常不得逃出 scan_and_fill_holes（否则中断定时循环）"""
        dm = self._mk(tmp_path)
        full = make_1m_range("2026-01-10 00:00", 240)
        dm.cache.put(SYMBOL, "1m",
                     full.drop(full.index[100:130]).reset_index(drop=True),
                     force_1m=True)

        async def boom(*a, **kw):
            raise RuntimeError("network down")

        with patch.object(dm, "_fetch_from_binance_public", side_effect=boom):
            filled = await dm.scan_and_fill_holes(SYMBOL)
        assert filled == 0

    @pytest.mark.asyncio
    async def test_idempotent_across_runs(self, tmp_path):
        """连跑两次：第二次应无洞可补，且不产生重复行"""
        dm = self._mk(tmp_path)
        full = make_1m_range("2026-01-10 00:00", 240)
        dm.cache.put(SYMBOL, "1m",
                     full.drop(full.index[100:130]).reset_index(drop=True),
                     force_1m=True)

        async def fake_fetch(symbol, day=None, start_time_ms=None,
                             end_time_ms=None, **kw):
            s = pd.Timestamp(start_time_ms, unit="ms", tz="UTC")
            w = full[full["timestamp"] >= s]
            if end_time_ms is not None:
                w = w[w["timestamp"] < pd.Timestamp(end_time_ms, unit="ms",
                                                    tz="UTC")]
            return to_api_rows(w)

        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch):
            await dm.scan_and_fill_holes(SYMBOL)
            second = await dm.scan_and_fill_holes(SYMBOL)

        assert second == 0, "第二轮仍在补齐，说明不幂等"
        after = dm.cache.get_1m_data(SYMBOL)
        assert len(after) == 240
        assert after["timestamp"].is_unique

    # ---------- 接线 ----------

    @pytest.mark.asyncio
    async def test_periodic_loop_calls_scan(self, tmp_path):
        """接线：定时维护任务必须真的调用 scan_and_fill_holes。

        方法本身能用不代表被接上了 —— 参照 _resolve_history_days 的教训
        （方法级测试全绿但调用点已断）。
        """
        dm = self._mk(tmp_path)
        dm.config.persistence_interval_minutes = 0  # 立即触发
        dm.cache.put(SYMBOL, "1m", make_1m_range("2026-01-10 00:00", 10),
                     force_1m=True)

        calls = []

        async def spy(symbol):
            calls.append(symbol)
            return 0

        with patch.object(dm, "scan_and_fill_holes", side_effect=spy), \
             patch.object(dm, "_flush_all_cache_to_csv", return_value={}), \
             patch.object(dm, "manage_memory_cache"):
            task = dm.start_periodic_persistence()
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert SYMBOL in calls, "定时任务未调用 scan_and_fill_holes"

    @pytest.mark.asyncio
    async def test_backtest_mode_skips_scan(self, tmp_path):
        """回测模式不得触发补洞 —— 数据已预加载，且不应发网络请求"""
        dm = self._mk(tmp_path)
        dm.config.backtest_mode = True
        dm.config.persistence_interval_minutes = 0
        dm.cache.put(SYMBOL, "1m", make_1m_range("2026-01-10 00:00", 10),
                     force_1m=True)

        with patch.object(dm, "scan_and_fill_holes") as spy, \
             patch.object(dm, "_flush_all_cache_to_csv", return_value={}), \
             patch.object(dm, "manage_memory_cache"):
            task = dm.start_periodic_persistence()
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        assert spy.call_count == 0, "回测模式仍触发了补洞"


# ============================================================
# 4e. 补洞与策略读取的并发安全
# ============================================================


class TestConcurrentReadDuringRefill:
    """定时补洞与策略取数并发时，策略读到的数据必须完整。

    并发模型（已核对）：
    - 策略计算链路是**纯同步**的：`strategy.py` 里没有一个 `async def`，
      `engine.on_kline_update` 也是同步函数。所以策略一旦开始取数，
      在拿完所有周期之前不会被事件循环打断 —— 不存在"取 8h 时被切走，
      回来再取 1h"的撕裂。
    - 但 `scan_and_fill_holes` 每次 API 调用之间有 await，事件循环会在
      此切到 WS 回调 / 策略。所以**补齐侧**必须保证每次让出控制权时，
      缓存都处于自洽状态。
    - `KlineCache` 有 per-symbol RLock，且 `get_1m_data` 返回 `.copy()`，
      单次 put/get 本身是原子的。

    因此风险不在锁，而在**写入次数**：逐洞写缓存会让策略看到部分补齐的
    中间态。实测未修前 1m 行数序列为 180→200→220→240（三个洞逐个补）。
    修法是"全部取回后单次合并"。
    """

    def _setup(self, tmp_path, drop_ranges, total=240, tf="4h"):
        dm = make_manager(tmp_path)
        dm.kline_repo.register_symbol(SYMBOL, ["1m", tf])
        full = make_1m_range("2026-01-10 00:00", total)
        drop = [i for r in drop_ranges for i in r]
        holed = full.drop(full.index[drop]).reset_index(drop=True)
        dm.cache.put(SYMBOL, "1m", holed, force_1m=True)
        dm._update_big_intervals_from_cache(SYMBOL)
        return dm, full, holed

    def _fetcher(self, full, observer):
        """每次 API 调用前后各让出一次控制权，模拟策略在补齐中途读取"""
        async def fake(symbol, day=None, start_time_ms=None,
                       end_time_ms=None, **kw):
            observer()
            await asyncio.sleep(0)
            observer()
            s = pd.Timestamp(start_time_ms, unit="ms", tz="UTC")
            w = full[full["timestamp"] >= s]
            if end_time_ms is not None:
                w = w[w["timestamp"] < pd.Timestamp(end_time_ms, unit="ms",
                                                    tz="UTC")]
            return to_api_rows(w)
        return fake

    @pytest.mark.asyncio
    async def test_no_partial_state_visible_with_multiple_holes(self, tmp_path):
        """多洞补齐过程中，策略只能看到「补齐前」或「补齐后」两种状态。

        这是本类的核心断言。未修前会观察到 4 种 1m 行数。
        """
        dm, full, holed = self._setup(
            tmp_path, [range(30, 50), range(100, 120), range(180, 200)]
        )
        before_rows = len(holed)

        seen_rows, seen_vol = [], []

        def observe():
            d1 = dm.get_dataframe_cached(SYMBOL, "1m", limit=100000)
            d4 = dm.get_dataframe_cached(SYMBOL, "4h", limit=200)
            seen_rows.append(len(d1))
            seen_vol.append(float(d4["volume"].iloc[0]))

        observe()  # 补齐前
        with patch.object(dm, "_fetch_from_binance_public",
                          side_effect=self._fetcher(full, observe)):
            await dm.scan_and_fill_holes(SYMBOL)
        observe()  # 补齐后

        # 至少要真的在补齐中途观察过若干次，否则测试是空的
        assert len(seen_rows) >= 4, f"观察次数不足：{len(seen_rows)}"

        distinct_rows = sorted(set(seen_rows))
        assert distinct_rows == [before_rows, 240], (
            f"策略观察到 {len(distinct_rows)} 种 1m 行数 {distinct_rows}，"
            f"存在部分补齐的中间态（应只有 {before_rows} 和 240）"
        )
        assert len(set(seen_vol)) <= 2, (
            f"策略观察到 {len(set(seen_vol))} 种 4h volume {sorted(set(seen_vol))}，"
            f"大周期出现中间态"
        )

    @pytest.mark.asyncio
    async def test_every_observed_snapshot_is_self_consistent(self, tmp_path):
        """更强的断言：策略每次读到的快照，其 1m 与大周期必须**互相自洽**。

        即：用当次读到的 1m 重新聚合，结果应与当次读到的 4h 一致。
        若补齐侧在 1m 已更新但大周期未重算时让出控制权，这里会失败。
        """
        dm, full, _ = self._setup(
            tmp_path, [range(40, 60), range(140, 160)]
        )
        violations = []

        def observe():
            d1 = dm.get_dataframe_cached(SYMBOL, "1m", limit=100000)
            d4 = dm.get_dataframe_cached(SYMBOL, "4h", limit=200)
            if d1 is None or d4 is None or d1.empty or d4.empty:
                return
            recomputed = resample_ohlcv(
                d1, "4h", datetime_column="timestamp", drop_partial_head=True,
            )
            merged = recomputed.merge(d4, on="timestamp", suffixes=("_r", "_c"))
            if merged.empty:
                return
            bad = merged[~np.isclose(merged["volume_r"], merged["volume_c"])]
            if not bad.empty:
                violations.append(
                    f"1m({len(d1)}行) 重算与缓存 4h 不一致 {len(bad)} 桶"
                )

        observe()
        with patch.object(dm, "_fetch_from_binance_public",
                          side_effect=self._fetcher(full, observe)):
            await dm.scan_and_fill_holes(SYMBOL)
        observe()

        assert not violations, (
            "策略读到了 1m 与大周期不自洽的快照：\n" + "\n".join(violations)
        )

    @pytest.mark.asyncio
    async def test_reader_never_sees_empty_or_shrunk_data(self, tmp_path):
        """补齐过程中数据量只能增不能减，且不得出现空/None。

        `_merge_api_data_to_cache` 用 concat+dedup，理论上只增不减；
        这条钉住它，防止日后误改成"先清空再写入"。
        """
        dm, full, holed = self._setup(
            tmp_path, [range(30, 50), range(100, 120), range(180, 200)]
        )
        counts = []

        def observe():
            d1 = dm.get_dataframe_cached(SYMBOL, "1m", limit=100000)
            assert d1 is not None and not d1.empty, "补齐中途读到空数据"
            assert d1["timestamp"].is_unique, "补齐中途读到重复时间戳"
            assert d1["timestamp"].is_monotonic_increasing, "补齐中途读到乱序"
            counts.append(len(d1))

        observe()
        with patch.object(dm, "_fetch_from_binance_public",
                          side_effect=self._fetcher(full, observe)):
            await dm.scan_and_fill_holes(SYMBOL)
        observe()

        assert counts == sorted(counts), f"数据量出现回退：{counts}"
        assert counts[0] == len(holed) and counts[-1] == 240

    @pytest.mark.asyncio
    async def test_ws_push_during_refill_is_not_lost(self, tmp_path):
        """补齐让出控制权时到达的 WS 推送不得被覆盖丢失。

        补齐用 concat+dedup(keep="last") 合并，而 WS 推送的时间戳晚于
        所有洞，两者不冲突 —— 但若补齐改成"用快照整体覆盖缓存"，
        这期间的 WS 数据就会丢。这条钉住该行为。
        """
        dm, full, _ = self._setup(tmp_path, [range(40, 60)], total=240)

        ws_ts = pd.Timestamp("2026-01-10 04:00", tz="UTC")
        pushed = {"done": False}

        def push_ws():
            if pushed["done"]:
                return
            pushed["done"] = True
            kline = Kline(
                symbol=SYMBOL, interval="1m",
                timestamp=ws_ts.to_pydatetime(),
                open=100.0, high=100.5, low=99.5, close=100.1,
                volume=7.0, quote_volume=700.0, trade_num=10,
                active_buy_volume=0.5, active_buy_quote_volume=50.0,
                is_final=True,
            )
            # 直接写缓存，绕开 _on_kline_received 的时间戳滞后校验
            existing = dm.cache.get_1m_data(SYMBOL)
            row = pd.DataFrame([{
                "timestamp": ws_ts, "open": 100.0, "high": 100.5, "low": 99.5,
                "close": 100.1, "volume": 7.0, "quote_volume": 700.0,
                "trade_num": 10, "active_buy_volume": 0.5,
                "active_buy_quote_volume": 50.0,
            }])
            combined = pd.concat([existing, row], ignore_index=True)
            combined = combined.drop_duplicates(subset=["timestamp"],
                                                keep="last")
            combined = combined.sort_values("timestamp").reset_index(drop=True)
            dm.cache.put(SYMBOL, "1m", combined, force_1m=True)

        with patch.object(dm, "_fetch_from_binance_public",
                          side_effect=self._fetcher(full, push_ws)):
            await dm.scan_and_fill_holes(SYMBOL)

        after = dm.cache.get_1m_data(SYMBOL)
        row = after[after["timestamp"] == ws_ts]
        assert not row.empty, f"补齐期间到达的 WS 数据 @{ws_ts} 丢失了"
        assert np.isclose(row["volume"].iloc[0], 7.0), (
            f"WS 数据被补齐覆盖：volume={row['volume'].iloc[0]}，应为 7.0"
        )

    def test_get_dataframe_cached_returns_copy(self, tmp_path):
        """`get_dataframe_cached`（策略实际使用的入口）必须返回副本。

        注意 `DataCache.get_1m_data` 返回的是**裸引用**（无锁、无 copy）——
        隔离由上层 `get_dataframe_cached` 的 `.copy()` 提供。策略若绕过它
        直连 `cache.get_1m_data`，改动会污染全局缓存。这条钉住策略入口的
        隔离性；下面 test_raw_cache_returns_reference 记录底层的裸引用行为。
        """
        dm = make_manager(tmp_path)
        dm.cache.put(SYMBOL, "1m", make_1m_range("2026-01-10 00:00", 100),
                     force_1m=True)

        a = dm.get_dataframe_cached(SYMBOL, "1m", limit=100000)
        a.loc[0, "volume"] = 999.0
        b = dm.get_dataframe_cached(SYMBOL, "1m", limit=100000)
        assert not np.isclose(b["volume"].iloc[0], 999.0), (
            "改动 get_dataframe_cached 返回值污染了缓存 —— 未返回副本"
        )

    def test_raw_cache_returns_reference(self, tmp_path):
        """**已知特性**：`DataCache.get_1m_data` 返回裸引用，不是副本。

        `DataCache`（manager.py 内）没有任何锁，`get_1m_data` 直接
        `return self._1m_cache.get(sym)`。`data_manager/cache.py::ShardCache`
        是带 RLock 且返回 `.copy()` 的另一个类，但它**当前是死代码**
        （只在 __init__ 导出，无实际使用者）—— 不要把两者搞混。

        当前之所以安全：策略计算链路纯同步 + WS 回调也在事件循环上
        （`_call_callback` 是 await），不存在真正的多线程并发；且策略
        统一走 `get_dataframe_cached`（有 .copy()）。

        本测试锚定现状，不是宣称它理想。若日后给 DataCache 加了锁/copy，
        这里会失败 —— 那时应改为断言返回副本。
        """
        dm = make_manager(tmp_path)
        dm.cache.put(SYMBOL, "1m", make_1m_range("2026-01-10 00:00", 100),
                     force_1m=True)
        a = dm.cache.get_1m_data(SYMBOL)
        b = dm.cache.get_1m_data(SYMBOL)
        assert a is b, (
            "DataCache.get_1m_data 已改为返回副本 —— 请更新本测试与"
            "test_get_dataframe_cached_returns_copy 的注释说明"
        )

    def test_ws_callback_runs_on_event_loop_not_thread(self):
        """WS 回调在事件循环上执行（`_call_callback` 是 async），
        不是独立线程 —— 这是"无锁也安全"的前提。

        若日后改成在线程里回调，DataCache 的无锁裸引用就会变成真实的
        数据竞争，本测试会失败以提醒补锁。
        """
        import inspect
        from data_manager.klines_ws_client import KlinesWebSocketClient
        assert inspect.iscoroutinefunction(
            KlinesWebSocketClient._call_callback
        ), (
            "WS 回调不再是协程 —— 可能已改为线程模型，"
            "DataCache 的无锁裸引用需要重新评估"
        )


# ============================================================
# 5. 周期解析：增量切片行数的正确性
# ============================================================


class TestIntervalParsing:
    """_parse_interval_to_minutes 决定增量聚合的切片宽度 tail_rows =
    period_minutes * 3。解析错误会让切片远小于一个周期，
    增量桶只含少数几分钟的数据却覆盖 CSV 里完整的同名桶。
    """

    @pytest.mark.parametrize("interval,expected", [
        ("1m", 1), ("5m", 5), ("15m", 15), ("30m", 30),
        ("1h", 60), ("4h", 240), ("8h", 480), ("12h", 720),
        ("1d", 1440), ("3d", 4320),
        ("1w", 10080),
    ])
    def test_parse_interval_to_minutes(self, tmp_path, interval, expected):
        dm = make_manager(tmp_path)
        assert dm._parse_interval_to_minutes(interval) == expected

    @pytest.mark.parametrize("bad", ["", "abc", "xh", "1y", "h"])
    def test_unparseable_returns_zero_not_one(self, tmp_path, bad):
        """无法解析必须返回 0：调用方按 `period_minutes > 0` 决定是否走
        增量路径，返回 0 才能安全退化到全量聚合。返回 1 会让
        tail_rows=3，增量桶只含 3 分钟数据。
        """
        dm = make_manager(tmp_path)
        assert dm._parse_interval_to_minutes(bad) == 0

    def test_manager_matches_repository(self, tmp_path):
        """两套解析器必须一致，否则同一周期在缓存路径和 CSV 路径
        算出不同的窗口宽度。
        """
        dm = make_manager(tmp_path)
        for tf in ["1m", "5m", "15m", "1h", "4h", "8h", "1d", "3d", "1w"]:
            assert (
                dm._parse_interval_to_minutes(tf)
                == dm.kline_repo._get_interval_minutes(tf)
            ), f"{tf}: manager 与 repository 解析不一致"


class TestAggregationStartTime:
    """_get_aggregation_start_time 必须往回退一个**完整**周期，
    否则源窗口不足，首桶残缺。
    """

    @pytest.mark.parametrize("interval,last,expect", [
        ("1h", "2026-01-10 05:00", "2026-01-10 04:00"),
        ("4h", "2026-01-10 04:00", "2026-01-10 00:00"),
        ("8h", "2026-01-10 16:00", "2026-01-10 08:00"),
        ("1d", "2026-01-10 00:00", "2026-01-09 00:00"),
        # 3d 曾被当成 1d（_get_interval_hours 无条件返回 24），只退 1 天
        ("3d", "2026-01-10 00:00", "2026-01-07 00:00"),
        ("1w", "2026-01-05 00:00", "2025-12-29 00:00"),
    ])
    def test_walks_back_one_full_period(self, tmp_path, interval, last, expect):
        dm = make_manager(tmp_path)
        last_dt = pd.Timestamp(last, tz="UTC").to_pydatetime()
        with patch.object(dm.kline_repo, "_get_last_kline_time",
                          return_value=last_dt):
            got = dm.kline_repo._get_aggregation_start_time(SYMBOL, interval)
        assert pd.Timestamp(got) == pd.Timestamp(expect, tz="UTC"), (
            f"{interval}: 起点 {got}，应为 {expect}"
        )

    @pytest.mark.parametrize("interval,hours", [
        ("1h", 1), ("4h", 4), ("8h", 8), ("12h", 12),
        ("1d", 24), ("3d", 72), ("1w", 168), ("2w", 336),
    ])
    def test_interval_hours_keeps_multiplier(self, tmp_path, interval, hours):
        dm = make_manager(tmp_path)
        assert dm.kline_repo._get_interval_hours(interval) == hours
