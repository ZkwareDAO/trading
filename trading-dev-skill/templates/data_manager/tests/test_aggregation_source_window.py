#!/usr/bin/env python3
"""
测试聚合的源数据窗口推导：_get_last_kline_time 与 _resolve_source_limit

两个不变式：

1. `_get_last_kline_time` 必须返回 CSV **末**根的时间。返回首根会让
   `_get_aggregation_start_time` 算出的 start_ts 早于全部源数据，
   `df_source["timestamp"] >= start_ts` 的增量过滤退化成空操作。

2. 读取行数必须覆盖到 start_ts。写死的公式（如 max(1000, 周期分钟*4)）与
   start_ts 互不协商，策略停跑数天后重启时只读到尾部若干行，
   中间缺失的大周期 K 线永远补不回 —— CSV 留永久空洞（末根写上了，中间补不回）。
"""

import pandas as pd
import pytest

from data_manager.kline_repository import KlineRepository


SYMBOL = "BTCUSDT"


def _write_csv(repo: KlineRepository, timeframe: str, ts) -> None:
    """按仓库的路径约定写一份 CSV"""
    df = pd.DataFrame({
        "timestamp": ts,
        "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0,
    })
    path = repo._get_file_path(SYMBOL, timeframe)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


class TestLastKlineTime:
    """_get_last_kline_time 必须读末行"""

    @pytest.mark.parametrize("timeframe,freq", [("1h", "1h"), ("8h", "8h")])
    def test_reads_tail_not_head(self, tmp_path, timeframe, freq):
        repo = KlineRepository(csv_dir=str(tmp_path))
        ts = pd.date_range("2026-01-01", periods=100, freq=freq, tz="UTC")
        _write_csv(repo, timeframe, ts)

        got = repo._get_last_kline_time(SYMBOL, timeframe)
        assert got == ts[-1], f"应返回末根 {ts[-1]}，实得 {got}（读到了首根？）"

    def test_single_row_csv(self, tmp_path):
        """只有一行数据时首尾同根，不应因回扫逻辑出错"""
        repo = KlineRepository(csv_dir=str(tmp_path))
        ts = pd.date_range("2026-01-01", periods=1, freq="1h", tz="UTC")
        _write_csv(repo, "1h", ts)
        assert repo._get_last_kline_time(SYMBOL, "1h") == ts[-1]

    def test_missing_file_returns_none(self, tmp_path):
        repo = KlineRepository(csv_dir=str(tmp_path))
        assert repo._get_last_kline_time(SYMBOL, "1h") is None

    def test_header_only_csv_returns_none(self, tmp_path):
        """只有表头没有数据行时不能把表头当时间戳解析"""
        repo = KlineRepository(csv_dir=str(tmp_path))
        path = repo._get_file_path(SYMBOL, "1h")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("timestamp,open,high,low,close,volume\n")
        assert repo._get_last_kline_time(SYMBOL, "1h") is None

    def test_trailing_newline_tolerated(self, tmp_path):
        """文件末尾多个空行时仍应取到最后一条数据行"""
        repo = KlineRepository(csv_dir=str(tmp_path))
        ts = pd.date_range("2026-01-01", periods=10, freq="1h", tz="UTC")
        _write_csv(repo, "1h", ts)
        path = repo._get_file_path(SYMBOL, "1h")
        path.write_text(path.read_text() + "\n\n")
        assert repo._get_last_kline_time(SYMBOL, "1h") == ts[-1]

    def test_large_file_reads_tail(self, tmp_path):
        """大文件（远超回扫探测窗口）也必须拿到末行"""
        repo = KlineRepository(csv_dir=str(tmp_path))
        ts = pd.date_range("2020-01-01", periods=50000, freq="1min", tz="UTC")
        _write_csv(repo, "1m", ts)
        assert repo._get_last_kline_time(SYMBOL, "1m") == ts[-1]


class TestReadLastLine:
    """_read_last_line 的字节回扫"""

    def test_line_longer_than_probe_window(self, tmp_path):
        """单行长度超过初始 probe_bytes 时，回扫窗口需加倍直到取到完整行"""
        path = tmp_path / "wide.csv"
        wide = "x" * 9000
        path.write_text(f"header\nfirst,{wide}\nlast,{wide}\n")

        line = KlineRepository._read_last_line(path, probe_bytes=64)
        assert line.startswith("last,")

    def test_empty_file_returns_none(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("")
        assert KlineRepository._read_last_line(path) is None

    def test_no_trailing_newline(self, tmp_path):
        path = tmp_path / "nonl.csv"
        path.write_text("a\nb\nc")
        assert KlineRepository._read_last_line(path) == "c"


class TestResolveSourceLimit:
    """_resolve_source_limit：读取行数必须覆盖 start_ts 且有界"""

    def test_covers_multi_day_downtime(self, tmp_path):
        """停跑 3 天后重启，8h 周期的读取行数必须覆盖整个停跑区间。

        写死公式 max(1000, 8*60*4)=1920 行 ≈ 32 小时，覆盖不到 3 天，
        中间的 8h K 线会在 CSV 里留下永久空洞。
        """
        repo = KlineRepository(csv_dir=str(tmp_path))
        start_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=3)

        limit = repo._resolve_source_limit("1m", start_ts, 480)

        need = 3 * 24 * 60  # 3 天的 1m 行数
        assert limit >= need, f"limit={limit} 覆盖不到 {need} 行（3 天）"

    def test_bounded_by_window(self, tmp_path):
        """停跑极久时不能退化成全量扫描"""
        repo = KlineRepository(csv_dir=str(tmp_path))
        start_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=3650)

        limit = repo._resolve_source_limit("1m", start_ts, 480)

        cap = max(repo.MAX_SOURCE_WINDOW_DAYS * 24 * 60, 480 * 3) + 1
        assert limit <= cap, f"limit={limit} 超出有界窗口 {cap}"

    def test_cold_start_uses_cold_start_limit(self, tmp_path):
        """目标 CSV 为空（start_ts=None）时用冷启动行数"""
        repo = KlineRepository(csv_dir=str(tmp_path))
        assert (repo._resolve_source_limit("1m", None, 480)
                == repo.COLD_START_SOURCE_LIMIT)

    def test_respects_min_limit(self, tmp_path):
        """目标 CSV 刚更新过（start_ts 很近）时仍读到足够上下文"""
        repo = KlineRepository(csv_dir=str(tmp_path))
        start_ts = pd.Timestamp.now(tz="UTC") - pd.Timedelta(minutes=1)
        assert (repo._resolve_source_limit("1m", start_ts, 60)
                >= repo.MIN_SOURCE_LIMIT)

    def test_future_start_ts_does_not_go_negative(self, tmp_path):
        """时钟漂移让 start_ts 落在未来时，行数不得为负"""
        repo = KlineRepository(csv_dir=str(tmp_path))
        start_ts = pd.Timestamp.now(tz="UTC") + pd.Timedelta(days=1)
        assert repo._resolve_source_limit("1m", start_ts, 60) >= repo.MIN_SOURCE_LIMIT

    def test_naive_start_ts_accepted(self, tmp_path):
        """不带时区的 start_ts 也应能处理（视为 UTC）"""
        repo = KlineRepository(csv_dir=str(tmp_path))
        naive = (pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=2)).tz_localize(None)
        limit = repo._resolve_source_limit("1m", naive, 480)
        assert limit >= 2 * 24 * 60


class TestIntervalMinutes:
    """_get_interval_minutes 的周期换算"""

    @pytest.mark.parametrize("tf,expected", [
        ("1m", 1), ("15m", 15), ("1h", 60), ("8h", 480),
        ("1d", 1440), ("1w", 10080),
    ])
    def test_parses_known_timeframes(self, tmp_path, tf, expected):
        repo = KlineRepository(csv_dir=str(tmp_path))
        assert repo._get_interval_minutes(tf) == expected

    @pytest.mark.parametrize("tf", ["", "abc", "xh", "1y"])
    def test_unparseable_returns_zero(self, tmp_path, tf):
        repo = KlineRepository(csv_dir=str(tmp_path))
        assert repo._get_interval_minutes(tf) == 0


class TestAggregateAndSaveWindow:
    """端到端：停跑后重启不得在大周期 CSV 留空洞"""

    def test_no_hole_after_downtime(self, tmp_path):
        """1m 连续但 8h CSV 落后 3 天时，聚合应补齐中间所有 8h 根"""
        repo = KlineRepository(csv_dir=str(tmp_path))
        repo.register_symbol(SYMBOL, ["1m", "8h"])

        now = pd.Timestamp.now(tz="UTC").floor("h")
        start = now - pd.Timedelta(days=4)
        ts_1m = pd.date_range(start, now, freq="1min", tz="UTC")
        _write_csv(repo, "1m", ts_1m)

        # 8h CSV 只到 3 天前 —— 模拟策略停跑
        stale_end = now - pd.Timedelta(days=3)
        ts_8h = pd.date_range(start.floor("8h"), stale_end, freq="8h", tz="UTC")
        _write_csv(repo, "8h", ts_8h)

        assert repo._aggregate_and_save(SYMBOL, "1m", "8h")

        out = pd.read_csv(repo._get_file_path(SYMBOL, "8h"))
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True)

        # 从旧末根到当前，每个 8h 边界都应存在，中间不得有空洞
        expected = pd.date_range(ts_8h[-1], now.floor("8h"), freq="8h", tz="UTC")
        missing = sorted(set(expected) - set(out["timestamp"]))
        assert not missing, f"8h CSV 存在空洞：{missing[:5]}"
