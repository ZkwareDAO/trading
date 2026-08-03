#!/usr/bin/env python3
"""
测试: DataManager.init_today_realtime 方法

下载今天数据 + API 补齐分钟 gap + 开 WS → 存内存
"""

import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from data_manager.manager import DataManager, DataManagerConfig


class TestInitTodayRealtime:

    def _make_manager(self, tmp_path: Path) -> DataManager:
        config = DataManagerConfig(
            csv_dir=str(tmp_path / "klines"),
            klines_service_enabled=True,
            klines_service_http_url="http://127.0.0.1:17081",
            klines_service_ws_url="ws://127.0.0.1:17081/ws/klines",
        )
        dm = DataManager(config)
        dm.enable_kline_repository()
        return dm

    def _make_recent_klines(self, count=5):
        """生成最近 N 分钟的 K 线数据"""
        now = datetime.now(timezone.utc)
        result = []
        for i in range(count, 0, -1):
            ts = now - timedelta(minutes=i)
            ts_ms = int(ts.timestamp() * 1000)
            result.append({
                'timestamp': ts,
                'open': 50000.0,
                'high': 50100.0,
                'low': 49900.0,
                'close': 50050.0,
                'volume': 100.5,
                'quote_volume': 5025000.0,
                'trade_num': 1234,
                'active_buy_volume': 50.25,
                'active_buy_quote_volume': 2512500.0,
            })
        return result

    @pytest.mark.asyncio
    async def test_init_today_realtime_success(self, tmp_path):
        """测试成功初始化今天实时数据"""
        dm = self._make_manager(tmp_path)

        # mock download_daily_data
        with patch.object(dm, 'download_daily_data', return_value=True):
            # mock _load_csv 返回最近数据
            recent = self._make_recent_klines(5)
            df = pd.DataFrame(recent)

            with patch.object(dm, '_load_csv', return_value=df):
                # mock WS 启动
                with patch.object(dm, 'start_klines_service_async', return_value=True):
                    with patch.object(dm, 'subscribe_klines_async', return_value=True):
                        result = await dm.init_today_realtime("BTCUSDT")

                        assert result is True
                        # 验证缓存中有数据
                        cached = dm.cache.get_1m_data("BTCUSDT")
                        assert cached is not None
                        assert len(cached) == 5

    @pytest.mark.asyncio
    async def test_init_today_realtime_download_fails(self, tmp_path):
        """测试下载今天数据失败时仍继续"""
        dm = self._make_manager(tmp_path)

        with patch.object(dm, 'download_daily_data', return_value=False):
            recent = self._make_recent_klines(3)
            df = pd.DataFrame(recent)

            with patch.object(dm, '_load_csv', return_value=df):
                with patch.object(dm, 'start_klines_service_async', return_value=True):
                    with patch.object(dm, 'subscribe_klines_async', return_value=True):
                        # 即使下载失败，本地有数据时仍应成功
                        result = await dm.init_today_realtime("BTCUSDT")
                        assert result is True

    @pytest.mark.asyncio
    async def test_init_today_realtime_no_local_data(self, tmp_path):
        """测试本地无数据且下载失败"""
        dm = self._make_manager(tmp_path)

        with patch.object(dm, 'download_daily_data', return_value=False):
            with patch.object(dm, '_load_csv', return_value=None):
                with patch.object(dm, 'start_klines_service_async', return_value=False):
                    result = await dm.init_today_realtime("BTCUSDT")
                    assert result is False

    @pytest.mark.asyncio
    async def test_init_today_realtime_ws_fallback(self, tmp_path):
        """测试 WS 启动失败时降级"""
        dm = self._make_manager(tmp_path)

        with patch.object(dm, 'download_daily_data', return_value=True):
            recent = self._make_recent_klines(3)
            df = pd.DataFrame(recent)

            with patch.object(dm, '_load_csv', return_value=df):
                with patch.object(dm, 'start_klines_service_async', return_value=False):
                    # WS 失败时应降级，但仍然返回 True（本地数据可用）
                    result = await dm.init_today_realtime("BTCUSDT")
                    assert result is True
                    # 验证缓存中有数据
                    cached = dm.cache.get_1m_data("BTCUSDT")
                    assert cached is not None
