#!/usr/bin/env python3
"""
测试: DataManager.download_daily_data 方法

单体模式：直接调 Binance fapi GET /fapi/v1/klines（startTime~endTime 当天范围）→ 存本地 CSV。
旧 klines_service 的 POST /api/v1/klines/daily 协议已随单体化移除，
mock 打在 _binance_public_request（统一代理/超时/错误处理的出口）上。
"""

import pytest
import pandas as pd
from pathlib import Path
from unittest.mock import AsyncMock, patch

from data_manager.manager import DataManager, DataManagerConfig


def make_api_response():
    """模拟 GET /fapi/v1/klines 的响应格式 (Binance 12 元素数组)"""
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
            realtime_enabled=True,
        )
        dm = DataManager(config)
        dm.enable_kline_repository()
        return dm

    @pytest.mark.asyncio
    async def test_download_daily_data_success(self, tmp_path):
        """测试成功下载单日数据并保存 CSV"""
        dm = self._make_manager(tmp_path)

        with patch.object(dm, '_binance_public_request', new_callable=AsyncMock) as mock_req:
            mock_req.return_value = make_api_response()

            result = await dm.download_daily_data("BTCUSDT", "2024-04-08")

            assert result is True

            # 验证调用了 Binance fapi GET klines 且带当天时间范围
            mock_req.assert_called_once()
            call_args = mock_req.call_args
            url = call_args[0][1]
            assert "/fapi/v1/klines" in url
            params = call_args[0][2]
            assert params["symbol"] == "BTCUSDT"
            assert params["interval"] == "1m"
            assert params["startTime"] == 1712534400000  # 2024-04-08 00:00 本地(+08:00) → 前一天 16:00 UTC

    @pytest.mark.asyncio
    async def test_download_daily_data_request_failure_returns_false(self, tmp_path):
        """请求失败/返回空（_binance_public_request 返回 None）时如实返回 False

        网络异常与 5xx 在生产代码内已被 _binance_public_request 吞为 None，
        本用例覆盖"取不到数据 → False"这一对外契约。
        """
        dm = self._make_manager(tmp_path)

        with patch.object(dm, '_binance_public_request', new_callable=AsyncMock) as mock_req:
            mock_req.return_value = None
            result = await dm.download_daily_data("BTCUSDT", "2024-04-08")
            assert result is False

    @pytest.mark.asyncio
    async def test_download_daily_data_empty_response(self, tmp_path):
        """测试 API 返回空列表"""
        dm = self._make_manager(tmp_path)

        with patch.object(dm, '_binance_public_request', new_callable=AsyncMock) as mock_req:
            mock_req.return_value = []
            result = await dm.download_daily_data("BTCUSDT", "2024-04-08")
            assert result is False

    @pytest.mark.asyncio
    async def test_download_daily_data_saves_csv(self, tmp_path):
        """测试数据保存到 CSV"""
        dm = self._make_manager(tmp_path)

        with patch.object(dm, '_binance_public_request', new_callable=AsyncMock) as mock_req:
            mock_req.return_value = make_api_response()
            await dm.download_daily_data("BTCUSDT", "2024-04-08")

            # 验证 CSV 文件已创建（kline_repo 的 1m 子目录约定）
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

        # API 返回新数据（时间戳不同：2024-04-08 00:01 UTC）
        new_data = [
            [1712548860000, "50000.0", "50100.0", "49900.0", "50050.0", "100.5",
             1712548920000, "5025000.0", 1234, "50.25", "2512500.0", "0"]
        ]

        with patch.object(dm, '_binance_public_request', new_callable=AsyncMock) as mock_req:
            mock_req.return_value = new_data
            await dm.download_daily_data("BTCUSDT", "2024-04-08")

            # 验证合并后有 2 条数据
            df = pd.read_csv(csv_dir / "BTCUSDT_1m.csv")
            assert len(df) == 2
