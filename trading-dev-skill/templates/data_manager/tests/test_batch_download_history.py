#!/usr/bin/env python3
"""
测试: DataManager.batch_download_history 方法

批量下载最近 N 天（排除今天），for day in days: download_daily_data()
"""

import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from data_manager.manager import DataManager, DataManagerConfig


def _make_api_klines(count=10):
    """生成 count 条模拟 K 线数据"""
    base_ts = 1712548800000  # 2024-04-08 00:00 UTC
    result = []
    for i in range(count):
        ts = base_ts + i * 60000
        result.append([
            ts, "50000.0", "50100.0", "49900.0", "50050.0", "100.5",
            ts + 60000, "5025000.0", 1234, "50.25", "2512500.0", "0"
        ])
    return result


class TestBatchDownloadHistory:

    def _make_manager(self, tmp_path: Path) -> DataManager:
        config = DataManagerConfig(
            csv_dir=str(tmp_path / "klines"),
            klines_service_enabled=True,
            klines_service_http_url="http://127.0.0.1:17081",
        )
        dm = DataManager(config)
        dm.enable_kline_repository()
        return dm

    def _mock_download_daily(self, klines_data=None):
        """创建 download_daily_data 的 mock"""
        async def fake_download(symbol, day):
            # 模拟 CSV 文件被写入
            dm_instance._downloaded_days.append(day)
            return True

        return fake_download

    @pytest.mark.asyncio
    async def test_batch_download_history_default_30_days(self, tmp_path):
        """测试默认下载最近 30 天（排除今天）"""
        dm = self._make_manager(tmp_path)
        dm._downloaded_days = []  # 追踪调用

        today = datetime.now(timezone.utc).date()

        # mock download_daily_data
        with patch.object(dm, 'download_daily_data', return_value=True) as mock_dl:
            result = await dm.batch_download_history("BTCUSDT")

            assert len(result) == 30
            assert all(result.values())

            # 验证调用了 30 次 download_daily_data
            assert mock_dl.call_count == 30

            # 验证日期范围：从 30 天前到昨天
            calls = mock_dl.call_args_list
            called_days = [c[0][1] for c in calls]
            expected_days = [
                (today - timedelta(days=d)).strftime("%Y-%m-%d")
                for d in range(30, 0, -1)
            ]
            assert sorted(called_days) == sorted(expected_days)

    @pytest.mark.asyncio
    async def test_batch_download_history_custom_days(self, tmp_path):
        """测试自定义天数"""
        dm = self._make_manager(tmp_path)

        with patch.object(dm, 'download_daily_data', return_value=True) as mock_dl:
            result = await dm.batch_download_history("BTCUSDT", days=7)

            assert len(result) == 7
            assert mock_dl.call_count == 7

    @pytest.mark.asyncio
    async def test_batch_download_history_partial_failure(self, tmp_path):
        """测试部分日期下载失败"""
        dm = self._make_manager(tmp_path)

        call_count = 0

        async def flaky_download(symbol, day):
            nonlocal call_count
            call_count += 1
            return call_count % 3 != 0  # 每 3 次失败 1 次

        with patch.object(dm, 'download_daily_data', side_effect=flaky_download):
            result = await dm.batch_download_history("BTCUSDT", days=6)

            assert len(result) == 6
            success_count = sum(1 for v in result.values() if v)
            assert success_count == 4  # 6 天中有 4 天成功

    @pytest.mark.asyncio
    async def test_batch_download_history_excludes_today(self, tmp_path):
        """测试排除今天"""
        dm = self._make_manager(tmp_path)
        today_str = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")

        with patch.object(dm, 'download_daily_data', return_value=True) as mock_dl:
            await dm.batch_download_history("BTCUSDT", days=5)

            called_days = [c[0][1] for c in mock_dl.call_args_list]
            assert today_str not in called_days
