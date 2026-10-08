#!/usr/bin/env python3
"""K 线 CSV schema 一致性回归测试。

背景：回测聚合出的大周期 CSV 需要能直接放进实盘当历史数据用，
前提是两侧 schema 一致。此前有两个静默损坏破坏该前提：

1. resample_ohlcv 的 agg_dict 漏了 trade_num（只列了 Binance 历史
   CSV 的别名 count），聚合产物比 1m 源少一列。
2. _append_to_csv 用 header 与数据列的交集写入，于是：
   - 缺列 → 写出短行，pandas 按位置解析导致列整体左移；
   - 多列 → 静默丢弃，文件永远停在旧 schema。

标准 schema（= API 1m 下载格式 = 修复后的聚合输出）：
    timestamp,open,high,low,close,volume,
    quote_volume,trade_num,active_buy_volume,active_buy_quote_volume
"""

import pandas as pd
import pytest

from data_manager.kline_repository import KlineRepository
from data_manager.klines_loader import resample_ohlcv


STANDARD_COLS = [
    "timestamp", "open", "high", "low", "close", "volume",
    "quote_volume", "trade_num",
    "active_buy_volume", "active_buy_quote_volume",
]

# data/klines 的历史形态：只有 OHLCV
LEGACY_COLS = ["timestamp", "open", "high", "low", "close", "volume"]


def _make_1m(periods=120, start="2026-01-01 00:00", cols=STANDARD_COLS):
    """构造 1m K 线 DataFrame，只包含 cols 指定的列。"""
    ts = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    full = {
        "timestamp": ts,
        "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5,
        "volume": 1.0, "quote_volume": 10.0, "trade_num": 5,
        "active_buy_volume": 0.4, "active_buy_quote_volume": 4.0,
    }
    return pd.DataFrame({c: full[c] for c in cols})


def _rows(df):
    return df.to_dict(orient="records")


class TestResampleSchema:
    """聚合不得丢列。"""

    def test_aggregation_preserves_all_columns(self):
        df_1m = _make_1m()
        out = resample_ohlcv(df_1m, "1h", datetime_column="timestamp")
        assert list(out.columns) == STANDARD_COLS, (
            f"聚合产物列集与 1m 源不一致，丢失: "
            f"{[c for c in df_1m.columns if c not in out.columns]}"
        )

    def test_trade_num_is_summed(self):
        """trade_num 是成交笔数，必须求和而非丢弃。"""
        df_1m = _make_1m(periods=60)
        out = resample_ohlcv(df_1m, "1h", datetime_column="timestamp")
        assert out["trade_num"].iloc[0] == 60 * 5

    def test_binance_count_alias_still_works(self):
        """历史 CSV 用 count 而非 trade_num，两个别名都要支持。"""
        ts = pd.date_range("2026-01-01 00:00", periods=60, freq="1min", tz="UTC")
        df = pd.DataFrame({
            "timestamp": ts, "open": 1.0, "high": 2.0, "low": 0.5,
            "close": 1.5, "volume": 1.0, "count": 3,
        })
        out = resample_ohlcv(df, "1h", datetime_column="timestamp")
        assert "count" in out.columns
        assert out["count"].iloc[0] == 60 * 3

    @pytest.mark.parametrize("tf", ["15m", "1h", "4h", "8h"])
    def test_schema_stable_across_timeframes(self, tf):
        out = resample_ohlcv(_make_1m(periods=60 * 24), tf,
                             datetime_column="timestamp")
        assert list(out.columns) == STANDARD_COLS


class TestAppendRefusesRaggedWrite:
    """_append_to_csv 的两个方向都必须拒绝，不得静默损坏。"""

    def test_missing_columns_never_produce_ragged_csv(self, tmp_path):
        """缺列时不得写出短行（否则读回列错位）。"""
        repo = KlineRepository(csv_dir=str(tmp_path))
        path = tmp_path / "1h" / "BTCUSDT_1h.csv"

        repo.save_klines_to_csv("BTCUSDT", "1h",
                                _rows(_make_1m(3, "2026-01-01 00:00")))
        # 后续写入缺 trade_num（模拟未修复的聚合产物）
        lean = _make_1m(2, "2026-01-01 00:10",
                        cols=[c for c in STANDARD_COLS if c != "trade_num"])
        repo.save_klines_to_csv("BTCUSDT", "1h", _rows(lean))

        lines = path.read_text().strip().splitlines()
        width = len(lines[0].split(","))
        for i, line in enumerate(lines[1:], start=1):
            assert len(line.split(",")) == width, (
                f"第 {i} 行字段数 {len(line.split(','))} != header {width}，CSV 不等宽"
            )

    def test_missing_columns_do_not_shift_values(self, tmp_path):
        """列错位的核心断言：已有行的值不得被相邻列顶掉。"""
        repo = KlineRepository(csv_dir=str(tmp_path))
        path = tmp_path / "1h" / "BTCUSDT_1h.csv"

        repo.save_klines_to_csv("BTCUSDT", "1h",
                                _rows(_make_1m(3, "2026-01-01 00:00")))
        lean = _make_1m(2, "2026-01-01 00:10",
                        cols=[c for c in STANDARD_COLS if c != "trade_num"])
        repo.save_klines_to_csv("BTCUSDT", "1h", _rows(lean))

        back = pd.read_csv(path)
        # quote_volume 曾被 active_buy_volume 的值顶掉
        assert (back["quote_volume"].dropna() == 10.0).all()
        assert (back["active_buy_volume"].dropna() == 0.4).all()
        assert (back["active_buy_quote_volume"].dropna() == 4.0).all()

    def test_extra_columns_upgrade_header(self, tmp_path):
        """多列时 header 必须升级，而非静默丢弃新字段。

        这是 data/klines 从 6 列自愈到 10 列的机制。
        """
        repo = KlineRepository(csv_dir=str(tmp_path))
        path = tmp_path / "1m" / "BTCUSDT_1m.csv"
        path.parent.mkdir(parents=True)

        legacy = _make_1m(2, "2026-01-01 00:00", cols=LEGACY_COLS)
        legacy = legacy.copy()
        legacy["timestamp"] = legacy["timestamp"].dt.strftime(
            "%Y-%m-%d %H:%M:%S+00:00")
        legacy.to_csv(path, index=False)

        repo.save_klines_to_csv("BTCUSDT", "1m",
                                _rows(_make_1m(2, "2026-01-01 00:02")))

        back = pd.read_csv(path)
        assert list(back.columns) == STANDARD_COLS, "header 未升级到标准 schema"
        # 旧行 extras 为 NaN，新行有值 —— 语义正确，无错位
        assert back["quote_volume"].isna().sum() == 2
        assert (back["quote_volume"].dropna() == 10.0).all()

        lines = path.read_text().strip().splitlines()
        width = len(lines[0].split(","))
        assert all(len(l.split(",")) == width for l in lines[1:])


class TestBacktestLiveInterchange:
    """回测聚合产物与实盘历史数据可互换 —— 本次改动的目标。"""

    def test_aggregated_output_matches_api_download_schema(self):
        """聚合产物的 schema 必须等于 API 下载 1m 的 schema。

        两者一致，回测算出的大周期 CSV 才能直接当实盘历史用。
        """
        api_1m = _make_1m()          # API 下载形态
        aggregated = resample_ohlcv(api_1m, "1h", datetime_column="timestamp")
        assert list(aggregated.columns) == list(api_1m.columns)

    def test_roundtrip_through_csv_is_stable(self, tmp_path):
        """聚合 → 落盘 → 读回 → 再落盘，schema 与值都不漂移。"""
        repo = KlineRepository(csv_dir=str(tmp_path))
        path = tmp_path / "4h" / "BTCUSDT_4h.csv"

        agg = resample_ohlcv(_make_1m(60 * 24), "4h",
                             datetime_column="timestamp")
        repo.save_klines_to_csv("BTCUSDT", "4h", _rows(agg))
        first = pd.read_csv(path)

        # 实盘续写后续区间（同一 schema）
        agg2 = resample_ohlcv(_make_1m(60 * 24, "2026-01-02 00:00"), "4h",
                              datetime_column="timestamp")
        repo.save_klines_to_csv("BTCUSDT", "4h", _rows(agg2))
        second = pd.read_csv(path)

        assert list(first.columns) == STANDARD_COLS
        assert list(second.columns) == STANDARD_COLS
        assert len(second) > len(first)
        assert second["trade_num"].notna().all()
