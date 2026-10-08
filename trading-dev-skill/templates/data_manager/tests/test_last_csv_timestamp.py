#!/usr/bin/env python3
"""DataManager._get_last_csv_timestamp 回归测试。

背景：该方法曾用 `pd.read_csv(csv_path, nrows=5)` 配 `.iloc[-1]` 取
"最后一条"时间戳，但 nrows 取的是**前** 5 行，实际拿到第 5 根 K 线
（最早的数据）。connect_and_sync 据此计算 missing_days，会把"数据
只差 1 分钟"误判成缺失数天，触发无谓的历史重下。

缓存命中时走前置分支（返回正确值），所以该 bug 只在冷启动
（CSV 尚未加载到缓存）暴露 —— 正是 connect_and_sync 的首次调用路径。
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from data_manager.manager import DataManager, DataManagerConfig


HEADER_6 = "timestamp,open,high,low,close,volume"
HEADER_10 = (
    "timestamp,open,high,low,close,volume,"
    "quote_volume,trade_num,active_buy_volume,active_buy_quote_volume"
)


@pytest.fixture
def dm(tmp_path):
    manager = DataManager(DataManagerConfig(csv_dir=str(tmp_path)))
    manager.connect()
    return manager


def _write_csv(tmp_path, text, symbol="BTCUSDT"):
    path = tmp_path / "1m" / f"{symbol}_1m.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _write_series(tmp_path, periods=3000, end=None, header=HEADER_6):
    """写出一段连续 1m K 线，返回 (path, 真实末根时间戳)。"""
    end = end or datetime.now(timezone.utc).replace(second=0, microsecond=0)
    ts = pd.date_range(end=end, periods=periods, freq="1min", tz="UTC")
    ncols = len(header.split(",")) - 1
    lines = [header]
    for t in ts:
        vals = ",".join(["1.0"] * ncols)
        lines.append(f"{t.strftime('%Y-%m-%d %H:%M:%S+00:00')},{vals}")
    path = _write_csv(tmp_path, "\n".join(lines) + "\n")
    return path, ts[-1]


class TestReadsLastRowNotFirst:
    """核心回归：必须读文件尾部。"""

    def test_returns_last_row_not_fifth(self, dm, tmp_path):
        _, last_ts = _write_series(tmp_path, periods=3000)
        got = dm._get_last_csv_timestamp("BTCUSDT")
        assert got == last_ts.to_pydatetime(), (
            "应返回 CSV 末行时间戳；读到前 5 行的 bug 会返回最早的数据"
        )

    def test_does_not_report_stale_gap(self, dm, tmp_path):
        """数据只差 1 分钟时，不得算出跨天的 missing_days。

        这是该 bug 的实际危害：connect_and_sync 会无谓重下数天历史。
        """
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        _write_series(tmp_path, periods=3000, end=now - timedelta(minutes=1))

        got = dm._get_last_csv_timestamp("BTCUSDT")
        gap_seconds = (now - got).total_seconds()
        missing_days = int(gap_seconds / 86400) + 1

        assert missing_days == 1, f"数据仅差 1 分钟却算出 {missing_days} 天缺口"

    def test_cache_hit_path_still_correct(self, dm, tmp_path):
        """缓存命中时走前置分支，也必须返回末根。"""
        _, last_ts = _write_series(tmp_path, periods=100)
        df = dm._load_csv("BTCUSDT", "1m")
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)
        assert dm._get_last_csv_timestamp("BTCUSDT") == last_ts.to_pydatetime()

    def test_cache_and_csv_paths_agree(self, dm, tmp_path):
        """两条路径（缓存 / 尾读）结果必须一致。"""
        _write_series(tmp_path, periods=500)
        from_csv = dm._get_last_csv_timestamp("BTCUSDT")

        df = dm._load_csv("BTCUSDT", "1m")
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)
        from_cache = dm._get_last_csv_timestamp("BTCUSDT")

        assert from_csv == from_cache

    def test_large_file_reads_tail(self, dm, tmp_path):
        """大文件也要拿到真正的末行（尾读不依赖全量解析）。"""
        _, last_ts = _write_series(tmp_path, periods=60 * 24 * 30)
        assert dm._get_last_csv_timestamp("BTCUSDT") == last_ts.to_pydatetime()

    def test_supports_10_column_schema(self, dm, tmp_path):
        """标准 10 列 schema 下同样正确（timestamp 仍是首列）。"""
        _, last_ts = _write_series(tmp_path, periods=200, header=HEADER_10)
        assert dm._get_last_csv_timestamp("BTCUSDT") == last_ts.to_pydatetime()


class TestDegenerateInputs:
    """异常输入一律返回 None，绝不返回错误的时间戳。"""

    def test_missing_file(self, dm):
        assert dm._get_last_csv_timestamp("NOSUCH") is None

    def test_empty_file(self, dm, tmp_path):
        _write_csv(tmp_path, "")
        assert dm._get_last_csv_timestamp("BTCUSDT") is None

    def test_header_only(self, dm, tmp_path):
        _write_csv(tmp_path, HEADER_6 + "\n")
        assert dm._get_last_csv_timestamp("BTCUSDT") is None

    def test_single_data_row(self, dm, tmp_path):
        _write_csv(tmp_path,
                   f"{HEADER_6}\n2026-01-01 00:00:00+00:00,1,2,0.5,1.5,1\n")
        got = dm._get_last_csv_timestamp("BTCUSDT")
        assert got == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_no_trailing_newline(self, dm, tmp_path):
        _write_csv(tmp_path,
                   f"{HEADER_6}\n2026-01-01 00:00:00+00:00,1,2,0.5,1.5,1")
        got = dm._get_last_csv_timestamp("BTCUSDT")
        assert got == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_trailing_blank_lines(self, dm, tmp_path):
        _write_csv(tmp_path,
                   f"{HEADER_6}\n2026-01-01 00:05:00+00:00,1,2,0.5,1.5,1\n\n\n")
        got = dm._get_last_csv_timestamp("BTCUSDT")
        assert got == datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc)

    def test_no_timestamp_column(self, dm, tmp_path):
        _write_csv(tmp_path, "a,b\n1,2\n")
        assert dm._get_last_csv_timestamp("BTCUSDT") is None

    def test_timestamp_not_first_column(self, dm, tmp_path):
        """timestamp 非首列时拒绝尾读，避免把 open 当时间戳解析。"""
        _write_csv(tmp_path,
                   "open,timestamp\n1.0,2026-01-01 00:00:00+00:00\n")
        assert dm._get_last_csv_timestamp("BTCUSDT") is None

    def test_corrupt_last_timestamp(self, dm, tmp_path):
        _write_csv(tmp_path, f"{HEADER_6}\nGARBAGE,1,2,0.5,1.5,1\n")
        assert dm._get_last_csv_timestamp("BTCUSDT") is None

    def test_returns_tz_aware(self, dm, tmp_path):
        """返回值必须带 UTC tzinfo（调用方直接与 now(utc) 相减）。"""
        _write_series(tmp_path, periods=10)
        got = dm._get_last_csv_timestamp("BTCUSDT")
        assert got is not None and got.tzinfo is not None
