"""
KlineRepository 智能保存测试 (Prove-It)

验证快速路径追加与慢速路径全量合并的输出一致性，
以及 _read_csv_tail / _append_to_csv 的正确性。
"""

import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone, timedelta

import pandas as pd
import pytest

from data_manager.kline_repository import KlineRepository


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_kline(ts: datetime, open_p: float = 100.0, **overrides):
    """快速构造单条 K 线 dict"""
    return {
        "timestamp": ts,
        "open": open_p,
        "high": overrides.get("high", open_p + 5.0),
        "low": overrides.get("low", open_p - 5.0),
        "close": overrides.get("close", open_p + 2.0),
        "volume": overrides.get("volume", 10.0),
    }


def _make_klines(base_ts: datetime, n: int, gap_minutes: int = 1) -> list:
    """构造 n 条连续 K 线"""
    return [
        _make_kline(base_ts + timedelta(minutes=i * gap_minutes), open_p=100.0 + i)
        for i in range(n)
    ]


def _csv_to_sorted_rows(csv_path: Path) -> list:
    """读取 CSV 并返回按时间戳排序的行列表（用于对比）"""
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df.to_dict("records")


# ── _read_csv_tail ────────────────────────────────────────────────────────────


class TestReadCsvTail:
    """_read_csv_tail 正确性测试"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_returns_none_for_missing_file(self):
        """文件不存在返回 None"""
        repo = KlineRepository(csv_dir=self.tmpdir)
        result = repo._read_csv_tail(Path(self.tmpdir) / "nonexistent.csv")
        assert result is None

    def test_reads_tail_of_small_file(self):
        """小文件正确返回尾部 N 行"""
        repo = KlineRepository(csv_dir=self.tmpdir)
        filepath = Path(self.tmpdir) / "1m" / "TEST_1m.csv"

        base = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        repo.save_klines_to_csv("TEST", "1m", _make_klines(base, 100))

        tail = repo._read_csv_tail(filepath, nrows=10)
        assert tail is not None
        assert len(tail) == 10
        assert tail["timestamp"].max() == base + timedelta(minutes=99)

    def test_reads_tail_returns_all_when_fewer_rows(self):
        """文件行数少于请求行数时返回全部"""
        repo = KlineRepository(csv_dir=self.tmpdir)
        filepath = Path(self.tmpdir) / "1m" / "TEST_1m.csv"

        base = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        repo.save_klines_to_csv("TEST", "1m", _make_klines(base, 5))

        tail = repo._read_csv_tail(filepath, nrows=500)
        assert len(tail) == 5

    def test_large_file_seek_based_read(self):
        """> 10MB 大文件 seek 读取尾部正确"""
        repo = KlineRepository(csv_dir=self.tmpdir)
        filepath = Path(self.tmpdir) / "1m" / "LARGE_1m.csv"
        filepath.parent.mkdir(parents=True, exist_ok=True)

        base = datetime(2020, 1, 1, tzinfo=timezone.utc)
        # 生成 ~15MB 的 CSV
        rows = []
        for i in range(200000):
            ts = base + timedelta(minutes=i)
            rows.append(
                f"{ts.strftime('%Y-%m-%d %H:%M:%S+00:00')},"
                f"{100.0+i*0.01},{101.0+i*0.01},{99.0+i*0.01},{100.5+i*0.01},{10.0}"
            )
        header = "timestamp,open,high,low,close,volume\n"
        with open(filepath, "w") as f:
            f.write(header)
            f.write("\n".join(rows))
            f.write("\n")

        file_size_mb = filepath.stat().st_size / (1024 * 1024)
        assert file_size_mb > 10, f"文件不够大: {file_size_mb:.1f}MB"

        tail = repo._read_csv_tail(filepath, nrows=10)
        assert tail is not None
        assert len(tail) == 10
        expected_last = base + timedelta(minutes=199999)
        assert tail["timestamp"].max() == expected_last


# ── _append_to_csv ────────────────────────────────────────────────────────────


class TestAppendToCsv:
    """_append_to_csv 正确性测试"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_appended_rows_match_save_format(self):
        """追加的行与 _save_dataframe 格式完全一致"""
        repo = KlineRepository(csv_dir=self.tmpdir)

        base = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        repo.save_klines_to_csv("TEST", "1m", _make_klines(base, 3))

        filepath = Path(self.tmpdir) / "1m" / "TEST_1m.csv"
        before_lines = filepath.read_text().strip().split("\n")
        before_cols = before_lines[0].split(",")

        # 追加一行
        new_row = pd.DataFrame([_make_kline(base + timedelta(minutes=3))])
        new_row["timestamp"] = pd.to_datetime(new_row["timestamp"], utc=True)
        repo._append_to_csv(new_row, filepath)

        after_lines = filepath.read_text().strip().split("\n")
        after_cols = after_lines[0].split(",")

        assert before_cols == after_cols, f"列名不一致: {before_cols} vs {after_cols}"
        assert len(after_lines) == len(before_lines) + 1
        for i, line in enumerate(after_lines):
            assert len(line.split(",")) == len(before_cols), f"第 {i} 行列数不一致"

    def test_append_preserves_column_order(self):
        """追加时列顺序与已有 CSV 对齐"""
        repo = KlineRepository(csv_dir=self.tmpdir)

        base = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
        repo.save_klines_to_csv("TEST", "1m", _make_klines(base, 3))

        filepath = Path(self.tmpdir) / "1m" / "TEST_1m.csv"
        existing_cols = pd.read_csv(filepath, nrows=0).columns.tolist()

        # 用不同列顺序的 DataFrame 追加
        new_row = pd.DataFrame(
            [
                {
                    "volume": 20.0,
                    "close": 107.0,
                    "low": 104.0,
                    "high": 108.0,
                    "open": 106.0,
                    "timestamp": base + timedelta(minutes=3),
                }
            ]
        )
        new_row["timestamp"] = pd.to_datetime(new_row["timestamp"], utc=True)
        repo._append_to_csv(new_row, filepath)

        df = pd.read_csv(filepath)
        assert df.columns.tolist() == existing_cols
        assert len(df) == 4


# ── Fast Path vs Slow Path: 输出一致性 ────────────────────────────────────────


class TestFastPathOutputIdentity:
    """快速路径与慢速路径输出完全一致"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def _make_repo(self):
        return KlineRepository(csv_dir=self.tmpdir)

    def test_save_klines_fast_equals_slow(self):
        """save_klines_to_csv: 快速路径输出 = 慢速路径输出"""
        # ── 慢速路径建立基线 ──
        repo_slow = self._make_repo()
        repo_slow.save_klines_to_csv("TEST", "1m", _make_klines(self.base, 5))
        filepath_slow = Path(self.tmpdir) / "1m" / "TEST_1m.csv"
        existing = pd.read_csv(filepath_slow)
        new_data = _make_klines(self.base + timedelta(minutes=5), 3)
        df_new = pd.DataFrame(new_data)
        df_new["timestamp"] = pd.to_datetime(df_new["timestamp"], utc=True)
        existing["timestamp"] = pd.to_datetime(existing["timestamp"], utc=True)
        df_all = pd.concat([existing, df_new], ignore_index=True)
        df_all = df_all.drop_duplicates(subset=["timestamp"], keep="last")
        df_all = df_all.sort_values("timestamp").reset_index(drop=True)
        repo_slow._save_dataframe(df_all, filepath_slow)
        slow_rows = _csv_to_sorted_rows(filepath_slow)

        # ── 快速路径 ──
        fast_tmpdir = tempfile.mkdtemp()
        try:
            repo_fast = KlineRepository(csv_dir=fast_tmpdir)
            repo_fast.save_klines_to_csv("TEST", "1m", _make_klines(self.base, 5))
            repo_fast.save_klines_to_csv(
                "TEST", "1m",
                _make_klines(self.base + timedelta(minutes=5), 3),
            )
            filepath_fast = Path(fast_tmpdir) / "1m" / "TEST_1m.csv"
            fast_rows = _csv_to_sorted_rows(filepath_fast)

            # ── 断言 ──
            assert len(fast_rows) == len(slow_rows), (
                f"行数不一致: fast={len(fast_rows)} slow={len(slow_rows)}"
            )
            for i, (fr, sr) in enumerate(zip(fast_rows, slow_rows)):
                assert fr["timestamp"] == sr["timestamp"], (
                    f"第 {i} 行时间戳不一致"
                )
                for col in ["open", "high", "low", "close", "volume"]:
                    assert fr[col] == sr[col], (
                        f"第 {i} 行 {col} 不一致: {fr[col]} vs {sr[col]}"
                    )
        finally:
            shutil.rmtree(fast_tmpdir)

    def test_save_klines_overlap_triggers_slow_path(self):
        """时间戳重叠时走慢速路径（去重生效）"""
        repo = self._make_repo()
        repo.save_klines_to_csv("TEST", "1m", _make_klines(self.base, 5))
        filepath = Path(self.tmpdir) / "1m" / "TEST_1m.csv"

        # 包含重叠时间戳
        overlap_data = [
            _make_kline(self.base + timedelta(minutes=3), open_p=999.0),
            _make_kline(self.base + timedelta(minutes=5), open_p=105.0),
        ]
        repo.save_klines_to_csv("TEST", "1m", overlap_data)

        df = pd.read_csv(filepath)
        assert len(df) == 6, f"去重后应为 6 行，实际 {len(df)}"
        overlap_row = df[
            pd.to_datetime(df["timestamp"], utc=True)
            == (self.base + timedelta(minutes=3))
        ]
        assert overlap_row.iloc[0]["open"] == 999.0, "重叠行未更新为新值"

    def test_save_dataframe_fast_path(self):
        """save_dataframe_to_csv 也走快速路径"""
        repo = self._make_repo()
        repo.save_dataframe_to_csv(
            "TEST", "1m",
            pd.DataFrame(_make_klines(self.base, 5)),
        )
        filepath = Path(self.tmpdir) / "1m" / "TEST_1m.csv"

        df_new = pd.DataFrame(_make_klines(self.base + timedelta(minutes=10), 3))
        repo.save_dataframe_to_csv("TEST", "1m", df_new)

        df = pd.read_csv(filepath)
        assert len(df) == 8, f"应为 8 行，实际 {len(df)}"

    def test_save_dataframe_overlap_triggers_slow_path(self):
        """save_dataframe_to_csv 时间戳重叠走慢速路径"""
        repo = self._make_repo()
        repo.save_dataframe_to_csv(
            "TEST", "1m",
            pd.DataFrame(_make_klines(self.base, 5)),
        )
        filepath = Path(self.tmpdir) / "1m" / "TEST_1m.csv"

        df_overlap = pd.DataFrame(
            [_make_kline(self.base + timedelta(minutes=2), open_p=777.0)]
        )
        repo.save_dataframe_to_csv("TEST", "1m", df_overlap)

        df = pd.read_csv(filepath)
        assert len(df) == 5  # 去重
        overlap_row = df[
            pd.to_datetime(df["timestamp"], utc=True)
            == (self.base + timedelta(minutes=2))
        ]
        assert overlap_row.iloc[0]["open"] == 777.0

    def test_update_from_1m_incremental_append(self):
        """update_from_1m 多次增量调用正确累加数据"""
        repo = self._make_repo()
        repo.register_symbol("TEST", ["1m"])

        repo.update_from_1m("TEST", _make_klines(self.base, 3))
        repo.update_from_1m(
            "TEST", _make_klines(self.base + timedelta(minutes=3), 3)
        )
        repo.update_from_1m(
            "TEST", _make_klines(self.base + timedelta(minutes=6), 3)
        )

        filepath = Path(self.tmpdir) / "1m" / "TEST_1m.csv"
        df = pd.read_csv(filepath)
        assert len(df) == 9
        assert df["timestamp"].is_monotonic_increasing


# ── 回退安全网 ────────────────────────────────────────────────────────────────


class TestFallbackSafetyNet:
    """快速路径失败时安全回退到慢速路径"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_read_tail_returns_none_falls_back(self):
        """_read_csv_tail 返回 None 时回退到全量合并"""
        repo = KlineRepository(csv_dir=self.tmpdir)
        repo.save_klines_to_csv("TEST", "1m", _make_klines(self.base, 3))

        # 正常追加（快速路径应正常工作）
        result = repo.save_klines_to_csv(
            "TEST", "1m",
            _make_klines(self.base + timedelta(minutes=3), 2),
        )
        assert result is True

    def test_gap_fill_sorts_correctly(self):
        """中间插入历史数据（时间戳早于尾部）走慢速路径，排序正确"""
        repo = KlineRepository(csv_dir=self.tmpdir)

        # 先写"未来"数据
        future_base = self.base + timedelta(days=30)
        repo.save_klines_to_csv("TEST", "1m", _make_klines(future_base, 5))

        # 再补"过去"数据 — 时间戳全部早于已有数据
        repo.save_klines_to_csv("TEST", "1m", _make_klines(self.base, 5))

        filepath = Path(self.tmpdir) / "1m" / "TEST_1m.csv"
        df = pd.read_csv(filepath)
        assert len(df) == 10
        assert df["timestamp"].is_monotonic_increasing


# ── _aggregate_and_save fast path ─────────────────────────────────────────────


class TestAggregateAndSaveFastPath:
    """聚合保存也走快速路径"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.base = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_aggregate_no_overlap_appends(self):
        """聚合结果时间戳不重叠时走追加"""
        repo = KlineRepository(csv_dir=self.tmpdir)

        # 写入足够的 1m 数据以产生 1h 聚合
        repo.save_klines_to_csv("TEST", "1m", _make_klines(self.base, 120))

        # 第一次聚合
        repo._aggregate_and_save("TEST", "1m", "1h")
        filepath = Path(self.tmpdir) / "1h" / "TEST_1h.csv"
        df1 = pd.read_csv(filepath)
        first_count = len(df1)
        assert first_count > 0

        # 追加更多 1m 数据（完全在已有 1h 之后）
        later_base = self.base + timedelta(hours=first_count + 2)
        repo.save_klines_to_csv("TEST", "1m", _make_klines(later_base, 120))

        # 第二次聚合 — 应走快速路径
        repo._aggregate_and_save("TEST", "1m", "1h")
        df2 = pd.read_csv(filepath)
        assert len(df2) > first_count
        assert df2["timestamp"].is_monotonic_increasing
