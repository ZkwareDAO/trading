#!/usr/bin/env python3
"""周线（1w）锚定与 label 语义回归测试。

背景：pandas 的 W 系列频率有两处默认值与交易所约定不符，
resample_ohlcv 此前直接透传 "1w" 导致：

1. 默认 "W" == "W-SUN"，桶边界落在周日；Binance 周线 open_time 是
   周一 00:00 UTC（已用 fapi/v1/klines?symbol=BTCUSDT&interval=1w 核对）。
2. W 系列的 label/closed 默认在区间【右】端，与 tick 类频率（h/min）
   相反。后果是写进 CSV 的 timestamp 不是 open_time，且
   drop_partial_head 的 `source_start > first_bucket` 判据失效——
   首桶标签比源起点还晚，残缺周永远检测不出来。

1d/3d 无此问题：D 系列 label 本就在左端，故本文件只覆盖 W。
"""

import warnings

import pandas as pd
import pytest

from data_manager.klines_loader import resample_ohlcv


MINUTES_PER_WEEK = 7 * 24 * 60

# Binance 真实周线 open_time，全部为周一
BINANCE_WEEKLY_OPENS = [
    "2026-07-20", "2026-07-27", "2026-08-03", "2026-08-10", "2026-08-17",
]


def _make_1m(start, periods):
    ts = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0,
    })


class TestWeeklyAnchor:
    """周线必须锚定周一 00:00 UTC。"""

    def test_bucket_starts_on_monday(self):
        out = resample_ohlcv(_make_1m("2026-08-17 00:00", MINUTES_PER_WEEK * 2),
                             "1w", datetime_column="timestamp")
        for ts in out["timestamp"]:
            assert ts.day_name() == "Monday", f"{ts} 不是周一"

    def test_matches_binance_open_times(self):
        """与 Binance 实际返回的周线 open_time 逐个对齐。"""
        out = resample_ohlcv(_make_1m("2026-07-20 00:00", MINUTES_PER_WEEK * 5),
                             "1w", datetime_column="timestamp")
        got = [ts.strftime("%Y-%m-%d") for ts in out["timestamp"]]
        assert got == BINANCE_WEEKLY_OPENS

    def test_label_is_open_time_not_close_time(self):
        """label 必须是区间起点（open_time），不是右端。

        源恰好一周，若 label 在右端会得到 08-24 而非 08-17。
        """
        out = resample_ohlcv(_make_1m("2026-08-17 00:00", MINUTES_PER_WEEK),
                             "1w", datetime_column="timestamp")
        assert len(out) == 1
        assert out["timestamp"].iloc[0] == pd.Timestamp("2026-08-17", tz="UTC")

    def test_closed_left_boundary(self):
        """桶含 [起点, 起点+7d)，第 10081 分钟应落入下一桶。"""
        out = resample_ohlcv(_make_1m("2026-08-17 00:00", MINUTES_PER_WEEK + 1),
                             "1w", datetime_column="timestamp")
        assert len(out) == 2
        assert out["volume"].iloc[0] == MINUTES_PER_WEEK
        assert out["volume"].iloc[1] == 1

    def test_aligned_source_yields_full_weeks(self):
        out = resample_ohlcv(_make_1m("2026-08-17 00:00", MINUTES_PER_WEEK * 2),
                             "1w", datetime_column="timestamp")
        assert (out["volume"] == MINUTES_PER_WEEK).all()


class TestWeeklyPartialHead:
    """残缺首周必须能被 drop_partial_head 检出——这是修 label 的主要动因。"""

    def test_partial_week_detected_and_dropped(self):
        # 2026-01-07 是周三，首周残缺（仅 5 天 = 7200 分钟）
        out = resample_ohlcv(_make_1m("2026-01-07 00:00", MINUTES_PER_WEEK * 3),
                             "1w", datetime_column="timestamp",
                             drop_partial_head=True)
        assert not out.empty
        assert out["volume"].iloc[0] == MINUTES_PER_WEEK, (
            "残缺首周未被丢弃；label 在右端时该判据会失效"
        )
        assert out["timestamp"].iloc[0].day_name() == "Monday"

    def test_partial_week_kept_when_flag_off(self):
        out = resample_ohlcv(_make_1m("2026-01-07 00:00", MINUTES_PER_WEEK * 3),
                             "1w", datetime_column="timestamp",
                             drop_partial_head=False)
        assert out["volume"].iloc[0] < MINUTES_PER_WEEK

    def test_aligned_source_keeps_first_week(self):
        """源已对齐周一时，drop_partial_head 不应误删首周。"""
        out = resample_ohlcv(_make_1m("2026-08-17 00:00", MINUTES_PER_WEEK * 2),
                             "1w", datetime_column="timestamp",
                             drop_partial_head=True)
        assert len(out) == 2
        assert out["timestamp"].iloc[0] == pd.Timestamp("2026-08-17", tz="UTC")

    def test_idempotent(self):
        """重复聚合同一输入结果恒定（数据管道的正确性属性）。"""
        df = _make_1m("2026-01-07 00:00", MINUTES_PER_WEEK * 3)
        runs = [
            resample_ohlcv(df, "1w", datetime_column="timestamp",
                           drop_partial_head=True)["volume"].tolist()
            for _ in range(4)
        ]
        assert all(r == runs[0] for r in runs)


class TestWeeklySchemaAndWarnings:
    def test_schema_matches_standard(self):
        """周线聚合同样保留全部字段（含 trade_num）。"""
        ts = pd.date_range("2026-08-17", periods=MINUTES_PER_WEEK,
                           freq="1min", tz="UTC")
        df = pd.DataFrame({
            "timestamp": ts, "open": 1.0, "high": 2.0, "low": 0.5,
            "close": 1.5, "volume": 1.0, "quote_volume": 10.0, "trade_num": 5,
            "active_buy_volume": 0.4, "active_buy_quote_volume": 4.0,
        })
        out = resample_ohlcv(df, "1w", datetime_column="timestamp")
        assert list(out.columns) == list(df.columns)
        assert out["trade_num"].iloc[0] == MINUTES_PER_WEEK * 5

    @pytest.mark.parametrize("tf", ["4h", "1d", "1w"])
    def test_no_origin_runtime_warning(self, tf):
        """不得再触发 pandas 的 origin-not-tick-like RuntimeWarning。

        origin="epoch" 对 2h..12h 是 no-op（能整除 24h，与 start_day 重合），
        对 D/W 则会告警，故已移除。
        """
        df = _make_1m("2026-08-17 00:00", MINUTES_PER_WEEK * 2)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            resample_ohlcv(df, tf, datetime_column="timestamp")
        assert not [w for w in caught if "origin" in str(w.message)]

    def test_multi_week_frequency(self):
        """2w 等倍数周期也走同一锚定逻辑。"""
        out = resample_ohlcv(_make_1m("2026-08-17 00:00", MINUTES_PER_WEEK * 4),
                             "2w", datetime_column="timestamp")
        assert len(out) == 2
        assert all(ts.day_name() == "Monday" for ts in out["timestamp"])


class TestNonWeeklyUnaffected:
    """移除 origin="epoch" 后，非周线周期结果必须完全不变。"""

    @pytest.mark.parametrize(
        "start",
        ["2026-01-01 00:00", "2026-01-01 07:23", "2026-03-05 13:47",
         "2025-12-30 21:05"],
    )
    @pytest.mark.parametrize("tf", ["2h", "4h", "6h", "8h", "12h", "1h", "15m"])
    def test_hour_intervals_align_to_utc_grid(self, start, tf):
        """小时级周期仍对齐 UTC 网格（桶起点能被周期整除）。"""
        out = resample_ohlcv(_make_1m(start, 60 * 24 * 8), tf,
                             datetime_column="timestamp")
        minutes = (int(tf[:-1]) * 60) if tf.endswith("h") else int(tf[:-1])
        for ts in out["timestamp"]:
            offset = (ts.hour * 60 + ts.minute) % minutes
            assert offset == 0, f"{ts} 未对齐 {tf} 网格"

    def test_daily_label_is_left_edge(self):
        out = resample_ohlcv(_make_1m("2026-01-07 07:23", 60 * 24 * 5), "1d",
                             datetime_column="timestamp")
        first = out["timestamp"].iloc[0]
        assert (first.hour, first.minute) == (0, 0)
        assert first == pd.Timestamp("2026-01-07", tz="UTC")
