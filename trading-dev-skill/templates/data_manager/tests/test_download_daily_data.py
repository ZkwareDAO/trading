#!/usr/bin/env python3
"""
测试: DataManager.download_daily_data 方法

POST /api/v1/klines/daily 下载单日数据 → 存本地 CSV
"""

import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from data_manager.manager import DataManager, DataManagerConfig


def make_api_response():
    """模拟 POST /api/v1/klines/daily 的响应格式 (Binance 风格)"""
    return [
        [
            1712548800000,  # 0: open_time (ms)
            "50000.0",      # 1: open
            "50100.0",      # 2: high
            "49900.0",      # 3: low
            "50050.0",      # 4: close
            "100.5",        # 5: volume
            1712548860000,  # 6: close_time
            "5025000.0",    # 7: quote_volume
            1234,           # 8: count
            "50.25",        # 9: taker_buy_base
            "2512500.0",    # 10: taker_buy_quote
            "0"             # 11: ignore
        ]
    ]


class TestDownloadDailyData:
    """download_daily_data 方法测试"""

    def _make_manager(self, tmp_path: Path) -> DataManager:
        """创建测试用 DataManager"""
        config = DataManagerConfig(
            csv_dir=str(tmp_path / "klines"),
            klines_service_enabled=True,
            klines_service_http_url="http://127.0.0.1:17081",
        )
        dm = DataManager(config)
        dm.enable_kline_repository()
        return dm

    @pytest.mark.asyncio
    async def test_download_daily_data_success(self, tmp_path):
        """测试成功下载单日数据并保存 CSV"""
        dm = self._make_manager(tmp_path)

        mock_response_data = make_api_response()

        with patch("aiohttp.ClientSession") as MockSession:
            mock_post_ctx = self._make_mock_response(mock_response_data, 200)
            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_post_ctx)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            MockSession.return_value = mock_session

            result = await dm.download_daily_data("BTCUSDT", "2024-04-08")

            assert result is True

            # 验证调用了正确的 URL 和参数
            call_args = mock_session.post.call_args
            assert call_args is not None
            url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
            assert "/api/v1/klines/daily" in url

    @pytest.mark.asyncio
    async def test_download_daily_data_empty_response(self, tmp_path):
        """测试 API 返回空数据"""
        dm = self._make_manager(tmp_path)

        with patch("aiohttp.ClientSession") as MockSession:
            mock_post_ctx = self._make_mock_response([], 200)
            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_post_ctx)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            MockSession.return_value = mock_session

            result = await dm.download_daily_data("BTCUSDT", "2024-04-08")

            assert result is False

    @pytest.mark.asyncio
    async def test_download_daily_data_api_error(self, tmp_path):
        """测试 API 返回错误"""
        dm = self._make_manager(tmp_path)

        with patch("aiohttp.ClientSession") as MockSession:
            mock_post_ctx = self._make_mock_response({"error": "internal"}, 500)
            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_post_ctx)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            MockSession.return_value = mock_session

            result = await dm.download_daily_data("BTCUSDT", "2024-04-08")

            assert result is False

    @pytest.mark.asyncio
    async def test_download_daily_data_network_error(self, tmp_path):
        """测试网络异常"""
        dm = self._make_manager(tmp_path)

        with patch("aiohttp.ClientSession") as MockSession:
            MockSession.side_effect = ConnectionError("Connection refused")

            result = await dm.download_daily_data("BTCUSDT", "2024-04-08")

            assert result is False

    @pytest.mark.asyncio
    async def test_download_daily_data_saves_csv(self, tmp_path):
        """测试数据保存到 CSV"""
        dm = self._make_manager(tmp_path)

        mock_response_data = make_api_response()

        with patch("aiohttp.ClientSession") as MockSession:
            mock_post_ctx = self._make_mock_response(mock_response_data, 200)
            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_post_ctx)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            MockSession.return_value = mock_session

            await dm.download_daily_data("BTCUSDT", "2024-04-08")

            # 验证 CSV 文件已创建
            csv_path = tmp_path / "klines" / "1m" / "BTCUSDT_1m.csv"
            assert csv_path.exists()

            # 验证内容正确
            df = pd.read_csv(csv_path)
            assert len(df) == 1
            assert df.iloc[0]["open"] == 50000.0
            assert df.iloc[0]["close"] == 50050.0
            assert df.iloc[0]["volume"] == 100.5

    @pytest.mark.asyncio
    async def test_download_daily_data_merges_existing(self, tmp_path):
        """测试已存在 CSV 时合并数据（去重）"""
        dm = self._make_manager(tmp_path)

        # 先写入一条已有数据
        existing = pd.DataFrame({
            "timestamp": ["2024-04-08 00:00:00+00:00"],
            "open": [49000.0],
            "high": [49100.0],
            "low": [48900.0],
            "close": [49050.0],
            "volume": [50.0],
        })
        csv_dir = tmp_path / "klines" / "1m"
        csv_dir.mkdir(parents=True, exist_ok=True)
        existing.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)

        # API 返回新数据（时间戳不同）
        new_data = [
            [1712548860000, "50000.0", "50100.0", "49900.0", "50050.0", "100.5",
             1712548920000, "5025000.0", 1234, "50.25", "2512500.0", "0"]
        ]

        with patch("aiohttp.ClientSession") as MockSession:
            mock_post_ctx = self._make_mock_response(new_data, 200)
            mock_session = AsyncMock()
            mock_session.post = MagicMock(return_value=mock_post_ctx)
            mock_session.__aenter__ = AsyncMock(return_value=mock_session)
            mock_session.__aexit__ = AsyncMock(return_value=None)
            MockSession.return_value = mock_session

            await dm.download_daily_data("BTCUSDT", "2024-04-08")

            # 验证合并后有 2 条数据
            df = pd.read_csv(csv_dir / "BTCUSDT_1m.csv")
            assert len(df) == 2

    def _make_mock_response(self, json_data, status=200):
        """创建 mock POST/GET 响应的异步上下文管理器"""
        mock_response = AsyncMock()
        mock_response.status = status
        mock_response.json = AsyncMock(return_value=json_data)
        mock_response.text = AsyncMock(return_value=str(json_data))

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)
        return mock_ctx
