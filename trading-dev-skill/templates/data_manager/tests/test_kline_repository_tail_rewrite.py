#!/usr/bin/env python3
"""尾部重写快速路径测试（tail-rewrite fast path）

背景: 增量聚合产出的行必然与 CSV 尾部重叠——最后一根大周期 K 线未闭合，
每分钟都要重写。原 _try_fast_append 只处理"纯新增"，重叠时落到慢速路径
(读全量 + 合并 + 全量写)，成本由 CSV 总行数决定。

本测试驱动尾部重写: 重叠仅限尾部时，用 seek+truncate 砍掉尾部重叠行再
append，成本 O(重叠行数)。

对应 plan: .claude/plans/1m-cache-append-fast-path.plan.md (遗留项 1)
"""

import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import pytest

from data_manager.kline_repository import KlineRepository


OHLCV_COLS = ["open", "high", "low", "close", "volume"]


def _kline(ts: datetime, close: float = 100.0) -> dict:
    return {
        "timestamp": ts,
        "open": close - 1.0,
        "high": close + 1.0,
        "low": close - 2.0,
        "close": close,
        "volume": 10.0,
    }


def _klines(base: datetime, n: int, step_min: int = 60, close0: float = 100.0) -> list:
    return [
        _kline(base + timedelta(minutes=i * step_min), close0 + i)
        for i in range(n)
    ]


def _read(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df.sort_values("timestamp").reset_index(drop=True)


class TestTailRewriteFastPath:
    """尾部重叠时走 truncate+append，不读写全量"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base = datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _seed(self, repo: KlineRepository, n: int) -> Path:
        repo.save_klines_to_csv("TEST", "1h", _klines(self.base, n))
        return repo._get_file_path("TEST", "1h")

    def test_tail_rewrite_updates_overlapping_tail_rows(self):
        """尾部重叠行被新值覆盖，行数不变"""
        repo = KlineRepository(csv_dir=self.tmpdir)
        path = self._seed(repo, 100)

        # 重写最后 3 根（时间戳与已有尾部重叠），close 改为 999+
        overlap = [
            _kline(self.base + timedelta(hours=97 + i), 999.0 + i)
            for i in range(3)
        ]
        assert repo.save_klines_to_csv("TEST", "1h", overlap) is True

        df = _read(path)
        assert len(df) == 100, f"行数应不变，实际 {len(df)}"
        assert df["close"].iloc[-3:].tolist() == [999.0, 1000.0, 1001.0]
        assert df["timestamp"].is_monotonic_increasing

    def test_tail_rewrite_mixed_overlap_and_new(self):
        """尾部重叠 + 新增混合：覆盖旧尾部并追加新行"""
        repo = KlineRepository(csv_dir=self.tmpdir)
        path = self._seed(repo, 50)

        # 重写最后 2 根 + 新增 2 根
        mixed = [
            _kline(self.base + timedelta(hours=48 + i), 500.0 + i)
            for i in range(4)
        ]
        assert repo.save_klines_to_csv("TEST", "1h", mixed) is True

        df = _read(path)
        assert len(df) == 52, f"应为 52 行 (50 - 2 覆盖 + 4)，实际 {len(df)}"
        assert df["close"].iloc[-4:].tolist() == [500.0, 501.0, 502.0, 503.0]
        assert df["timestamp"].is_monotonic_increasing

    def test_tail_rewrite_result_equals_full_merge(self):
        """尾部重写结果与全量合并逐列一致"""
        base_rows = _klines(self.base, 60)
        overlap = [
            _kline(self.base + timedelta(hours=57 + i), 777.0 + i)
            for i in range(5)
        ]

        # 走优化路径
        repo_fast = KlineRepository(csv_dir=self.tmpdir)
        repo_fast.save_klines_to_csv("FAST", "1h", base_rows)
        repo_fast.save_klines_to_csv("FAST", "1h", overlap)
        got = _read(repo_fast._get_file_path("FAST", "1h"))

        # 全量合并基线
        expected = pd.DataFrame(base_rows + overlap)
        expected["timestamp"] = pd.to_datetime(expected["timestamp"], utc=True)
        expected = expected.drop_duplicates(subset=["timestamp"], keep="last")
        expected = expected.sort_values("timestamp").reset_index(drop=True)

        assert len(got) == len(expected)
        for col in ["timestamp"] + OHLCV_COLS:
            pd.testing.assert_series_equal(
                got[col].reset_index(drop=True),
                expected[col].reset_index(drop=True),
                check_names=False,
            )

    def test_deep_overlap_falls_back_to_full_merge(self):
        """重叠深入文件中部时回退全量合并（不是尾部，truncate 不适用）"""
        repo = KlineRepository(csv_dir=self.tmpdir)
        path = self._seed(repo, 200)

        # 覆盖中间段（第 50-54 根），远离尾部
        mid = [
            _kline(self.base + timedelta(hours=50 + i), 333.0 + i)
            for i in range(5)
        ]
        assert repo.save_klines_to_csv("TEST", "1h", mid) is True

        df = _read(path)
        assert len(df) == 200, f"行数应不变，实际 {len(df)}"
        rows = df[
            (df["timestamp"] >= self.base + timedelta(hours=50))
            & (df["timestamp"] <= self.base + timedelta(hours=54))
        ]
        assert rows["close"].tolist() == [333.0, 334.0, 335.0, 336.0, 337.0]
        assert df["timestamp"].is_monotonic_increasing

    def test_tail_rewrite_does_not_read_whole_file(self):
        """尾部重写不触发慢速路径的全量读"""
        repo = KlineRepository(csv_dir=self.tmpdir)
        self._seed(repo, 500)

        overlap = [
            _kline(self.base + timedelta(hours=498 + i), 888.0 + i)
            for i in range(2)
        ]

        import data_manager.kline_repository as krmod

        full_reads = []
        orig_read_csv = krmod.pd.read_csv

        def spy(path_or_buf, *a, **kw):
            # nrows=0 是读 header，不算全量读
            if "nrows" not in kw and "skiprows" not in kw:
                full_reads.append(str(path_or_buf)[:80])
            return orig_read_csv(path_or_buf, *a, **kw)

        krmod.pd.read_csv = spy
        try:
            repo.save_klines_to_csv("TEST", "1h", overlap)
        finally:
            krmod.pd.read_csv = orig_read_csv

        # _read_csv_tail 对 <10MB 文件会全量读一次做重叠检测（_try_fast_append
        # 和 _try_tail_rewrite 各一次），共 ≤2 次。慢速路径的全量合并是第三次，
        # 要被消除。关键指标：≤2，不是 3。
        assert len(full_reads) <= 2, (
            f"尾部重写不应触发慢速路径的全量读，实际读了 {len(full_reads)} 次: {full_reads}"
        )

    def test_tail_rewrite_preserves_extra_columns(self):
        """含额外列（quote_volume 等）时列顺序与值保持正确"""
        repo = KlineRepository(csv_dir=self.tmpdir)

        def wide(ts, close):
            d = _kline(ts, close)
            d.update({
                "quote_volume": close * 100,
                "trade_num": 7,
                "active_buy_volume": close / 2,
                "active_buy_quote_volume": close * 50,
            })
            return d

        seed = [wide(self.base + timedelta(hours=i), 100.0 + i) for i in range(30)]
        repo.save_klines_to_csv("TEST", "1h", seed)
        path = repo._get_file_path("TEST", "1h")
        cols_before = pd.read_csv(path, nrows=0).columns.tolist()

        overlap = [wide(self.base + timedelta(hours=28 + i), 600.0 + i) for i in range(3)]
        repo.save_klines_to_csv("TEST", "1h", overlap)

        df = pd.read_csv(path)
        assert df.columns.tolist() == cols_before
        assert len(df) == 31
        assert df["close"].iloc[-3:].tolist() == [600.0, 601.0, 602.0]
        assert df["quote_volume"].iloc[-1] == 602.0 * 100
