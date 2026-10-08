#!/usr/bin/env python3
"""
大缺口补齐测试：sync_to_latest 走 download_range、_fetch_gap_range 走 fetch_klines 分页

download_range / fetch_klines 的内部逻辑（归档分块、翻页、重试）由
scripts/tests/test_download_data.py 覆盖，此处只测 data_manager 侧的接线：
调用是否发生、参数是否正确、缓存是否重载、失败是否不阻断。
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest

from data_manager.manager import DataManager, DataManagerConfig


def make_api_klines(n: int, start_ms: int) -> list:
    """模拟 Binance 格式 K 线数组（12 列取前 11 项）"""
    return [
        [
            start_ms + i * 60_000,  # open_time ms
            "100.0", "101.0", "99.0", "100.5", "1000.0",
            start_ms + (i + 1) * 60_000,  # close_time
            "100500.0", 50, "500.0", "50250.0",
        ]
        for i in range(n)
    ]


def make_df(start_ms: int, n: int) -> pd.DataFrame:
    rows = [
        {
            "timestamp": pd.to_datetime(start_ms + i * 60_000, unit="ms", utc=True),
            "open": 100.0, "high": 101.0, "low": 99.0,
            "close": 100.5, "volume": 1000.0,
        }
        for i in range(n)
    ]
    return pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)


@pytest.fixture
def dm(tmp_path):
    config = DataManagerConfig(
        csv_dir=str(tmp_path / "klines"),
        realtime_enabled=True,
        auto_sync_on_connect=False,
    )
    dm = DataManager(config)
    dm.enable_kline_repository()
    return dm


class TestFillLargeGapViaDownloadRange:
    """_fill_large_gap_via_download_range 辅助方法"""

    @pytest.mark.asyncio
    async def test_calls_download_range_and_reloads_cache(self, dm, tmp_path):
        """转调 download_range（to_thread），成功后从 CSV 重载缓存"""
        csv_dir = tmp_path / "klines" / "1m"
        csv_dir.mkdir(parents=True)
        # download_range 的副作用：合并后的 CSV 落盘
        df = make_df(int(datetime(2026, 8, 1, tzinfo=timezone.utc).timestamp() * 1000), 10)
        df.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)

        start = datetime(2026, 8, 1, tzinfo=timezone.utc)
        end = datetime(2026, 8, 5, tzinfo=timezone.utc)

        with patch("data_manager.manager.download_range") as mock_dl:
            mock_dl.return_value = csv_dir / "BTCUSDT_1m.csv"
            ok = await dm._fill_large_gap_via_download_range("BTCUSDT", start, end)

        assert ok is True
        mock_dl.assert_called_once()
        # 参数：symbol, interval, start, end, csv_dir, proxies
        args = mock_dl.call_args[0]
        assert args[0] == "BTCUSDT"
        assert args[1] == "1m"
        assert args[2] == start
        assert args[3] == end
        assert args[4] == str(dm.csv_dir)
        # 缓存已从 CSV 重载
        cached = dm.cache.get_1m_data("BTCUSDT")
        assert cached is not None and len(cached) == 10

    @pytest.mark.asyncio
    async def test_returns_false_when_no_data(self, dm):
        """download_range 返回 None（无数据）时视为失败"""
        with patch("data_manager.manager.download_range") as mock_dl:
            mock_dl.return_value = None
            ok = await dm._fill_large_gap_via_download_range(
                "BTCUSDT",
                datetime(2026, 8, 1, tzinfo=timezone.utc),
                datetime(2026, 8, 5, tzinfo=timezone.utc),
            )
        assert ok is False

    @pytest.mark.asyncio
    async def test_returns_false_on_runtime_error(self, dm):
        """download_range 抛 RuntimeError（网络失败）时不向上传播"""
        with patch("data_manager.manager.download_range") as mock_dl:
            mock_dl.side_effect = RuntimeError("请求异常")
            ok = await dm._fill_large_gap_via_download_range(
                "BTCUSDT",
                datetime(2026, 8, 1, tzinfo=timezone.utc),
                datetime(2026, 8, 5, tzinfo=timezone.utc),
            )
        assert ok is False


class TestSyncToLatestLargeGap:
    """sync_to_latest 大缺口分支接线"""

    @pytest.mark.asyncio
    async def test_no_data_branch_calls_large_gap_fill(self, dm):
        """无本地数据 → _fill_large_gap_via_download_range + init_today_realtime"""
        with patch.object(
            dm, "_fill_large_gap_via_download_range", new_callable=AsyncMock
        ) as mock_large:
            mock_large.return_value = True
            with patch.object(dm, "init_today_realtime", new_callable=AsyncMock) as mock_today:
                mock_today.return_value = True
                await dm.sync_to_latest("BTCUSDT", max_history_days=30)

        mock_large.assert_called_once()
        # 起点 = now - max_history_days
        start_arg = mock_large.call_args[0][1]
        assert (
            datetime.now(timezone.utc) - start_arg
        ).total_seconds() <= 30 * 86400 + 5
        mock_today.assert_called_once()

    @pytest.mark.asyncio
    async def test_large_gap_branch_calls_large_gap_fill(self, dm):
        """缓存末根距今 > 1 天 → _fill_large_gap_via_download_range，起点=末根"""
        old_time = datetime.now(timezone.utc) - timedelta(days=5)
        df = make_df(int(old_time.timestamp() * 1000), 5)
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        with patch.object(
            dm, "_fill_large_gap_via_download_range", new_callable=AsyncMock
        ) as mock_large:
            mock_large.return_value = True
            with patch.object(dm, "init_today_realtime", new_callable=AsyncMock) as mock_today:
                mock_today.return_value = True
                await dm.sync_to_latest("BTCUSDT", max_history_days=30)

        mock_large.assert_called_once()
        # 起点是缓存末根本身（残缺末根需被完整值覆盖）
        start_arg = mock_large.call_args[0][1]
        expected = (old_time + timedelta(minutes=4)).replace(microsecond=0)
        assert start_arg.replace(microsecond=0) == expected

    @pytest.mark.asyncio
    async def test_large_gap_failure_does_not_block(self, dm):
        """大缺口补齐失败仍继续 init_today_realtime（warning 不阻断）"""
        with patch.object(
            dm, "_fill_large_gap_via_download_range", new_callable=AsyncMock
        ) as mock_large:
            mock_large.return_value = False
            with patch.object(dm, "init_today_realtime", new_callable=AsyncMock) as mock_today:
                mock_today.return_value = True
                result = await dm.sync_to_latest("BTCUSDT", max_history_days=30)

        assert result is True
        mock_today.assert_called_once()


class TestFetchGapRangePaged:
    """_fetch_gap_range 分页拉取（内部翻页循环复用 _fetch_from_binance_public）"""

    @pytest.mark.asyncio
    async def test_pages_until_range_covered(self, dm):
        """区间超过单次 1500 条上限时翻页，最终拼出完整区间数据"""
        last_ts = datetime(2026, 8, 1, 0, 0, tzinfo=timezone.utc)
        new_ts = datetime(2026, 8, 3, 0, 0, tzinfo=timezone.utc)
        # 真值：区间内全部分钟；每页最多 1500 条
        n_total = int((new_ts - last_ts).total_seconds() // 60)

        async def fake_fetch(symbol, day=None, start_time_ms=None,
                             end_time_ms=None, **kw):
            remaining = int((end_time_ms - start_time_ms) // 60_000)
            return make_api_klines(min(1500, remaining), start_time_ms)

        last_ts_ms = int(last_ts.timestamp() * 1000)
        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch):
            data = await dm._fetch_gap_range("BTCUSDT", last_ts, new_ts)

        assert len(data) == n_total
        # 起点含 last_ts 本身，时间戳唯一且有序
        opens = [int(r[0]) for r in data]
        assert opens[0] == last_ts_ms
        assert opens == sorted(set(opens))

    @pytest.mark.asyncio
    async def test_empty_result_returns_empty_list(self, dm):
        """API 返回空 → []，不抛异常"""
        async def fake_fetch(*a, **kw):
            return []
        with patch.object(dm, "_fetch_from_binance_public", side_effect=fake_fetch):
            data = await dm._fetch_gap_range(
                "BTCUSDT",
                datetime(2026, 8, 1, tzinfo=timezone.utc),
                datetime(2026, 8, 2, tzinfo=timezone.utc),
            )
        assert data == []

    @pytest.mark.asyncio
    async def test_exception_returns_empty_list(self, dm):
        """API 抛异常 → warning + []（不阻断补洞流程）"""
        async def boom(*a, **kw):
            raise RuntimeError("网络失败")
        with patch.object(dm, "_fetch_from_binance_public", side_effect=boom):
            data = await dm._fetch_gap_range(
                "BTCUSDT",
                datetime(2026, 8, 1, tzinfo=timezone.utc),
                datetime(2026, 8, 2, tzinfo=timezone.utc),
            )
        assert data == []

    @pytest.mark.asyncio
    async def test_scan_and_fill_holes_merges_archive_rows(self, dm):
        """scan_and_fill_holes 全链路：归档取回后一次性原子合并"""
        hole_start = datetime(2026, 8, 10, 0, 0, tzinfo=timezone.utc)
        hole_end = datetime(2026, 8, 12, 0, 0, tzinfo=timezone.utc)
        # 构造带中部空洞的缓存：洞前 5 根 + 洞后 5 根
        before = make_df(int(hole_start.timestamp() * 1000) - 5 * 60_000, 5)
        after = make_df(int(hole_end.timestamp() * 1000), 5)
        dm.cache.put("BTCUSDT", "1m", pd.concat([before, after], ignore_index=True), force_1m=True)

        with patch("data_manager.manager.fetch_range_rows") as mock_archive:
            mock_archive.return_value = make_api_klines(
                2880, int(hole_start.timestamp() * 1000)
            )
            n = await dm.scan_and_fill_holes("BTCUSDT")

        # 归档一次拉完全部 2880 根（旧 fapi 实现每轮维护只推进 1500）
        assert n == 2880
        mock_archive.assert_called_once()
        cached = dm.cache.get_1m_data("BTCUSDT")
        assert len(cached) == 2890
        # 洞已闭合：相邻间隔无 >90 秒断点
        diffs = cached["timestamp"].diff().dt.total_seconds()
        assert (diffs.dropna() <= 90).all()

    @pytest.mark.asyncio
    async def test_archive_empty_falls_back_to_fapi(self, dm):
        """归档链路返回空时，退回 fapi 分页补齐"""
        with patch("data_manager.manager.fetch_range_rows", return_value=[]), \
             patch.object(dm, "_fetch_gap_range", new_callable=AsyncMock) as mock_fapi:
            mock_fapi.return_value = make_api_klines(10, 1754784000000)
            rows = await dm._fetch_hole_rows_archive_first(
                "BTCUSDT",
                datetime(2026, 8, 10, tzinfo=timezone.utc),
                datetime(2026, 8, 11, tzinfo=timezone.utc),
            )
        assert len(rows) == 10
        mock_fapi.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_archive_exception_falls_back_to_fapi(self, dm):
        """归档链路抛异常时，退回 fapi 分页补齐（不向上传播）"""
        with patch("data_manager.manager.fetch_range_rows",
                   side_effect=RuntimeError("归档失败")), \
             patch.object(dm, "_fetch_gap_range", new_callable=AsyncMock) as mock_fapi:
            mock_fapi.return_value = []
            rows = await dm._fetch_hole_rows_archive_first(
                "BTCUSDT",
                datetime(2026, 8, 10, tzinfo=timezone.utc),
                datetime(2026, 8, 11, tzinfo=timezone.utc),
            )
        assert rows == []
        mock_fapi.assert_awaited_once()
