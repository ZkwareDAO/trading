#!/usr/bin/env python3
"""
DataManager 新方法测试：load_history, sync_to_latest, cache_recent_data, fetch_klines_range
"""

import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pandas as pd
import pytest

from data_manager.manager import DataManager, DataManagerConfig


def make_api_klines(n: int, start_ms: int = 1713500000000) -> list:
    """模拟 klines_service API 返回的 Binance 格式数据"""
    klines = []
    for i in range(n):
        ts = start_ms + i * 60_000  # 每分钟
        klines.append([
            ts,           # open_time ms
            "100.0",      # open
            "101.0",      # high
            "99.0",       # low
            "100.5",      # close
            "1000.0",     # volume
            ts + 60_000,  # close_time
            "100500.0",   # quote_volume
            50,           # trade_num
            "500.0",      # active_buy_volume
            "50250.0",    # active_buy_quote_volume
        ])
    return klines


def make_df_from_api(api_data: list) -> pd.DataFrame:
    """将 API 数据转为 DataFrame"""
    rows = []
    for k in api_data:
        rows.append({
            'timestamp': k[0],
            'open': float(k[1]),
            'high': float(k[2]),
            'low': float(k[3]),
            'close': float(k[4]),
            'volume': float(k[5]),
            'quote_volume': float(k[7]),
            'trade_num': int(k[8]),
            'active_buy_volume': float(k[9]),
            'active_buy_quote_volume': float(k[10]),
        })
    df = pd.DataFrame(rows)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    return df


@pytest.fixture
def dm(tmp_path):
    """创建 DataManager 实例，使用临时目录"""
    config = DataManagerConfig(
        csv_dir=str(tmp_path / "klines"),
        klines_service_enabled=True,
        klines_service_http_url="http://test:17081",
        auto_sync_on_connect=False,  # 关闭自动同步，避免测试中连 API
    )
    dm = DataManager(config)
    # 启用 kline_repo（_load_csv 依赖）
    dm.enable_kline_repository()
    return dm


class TestLoadHistory:
    """load_history 测试"""

    def test_load_history_from_csv(self, dm):
        """从 CSV 加载历史数据"""
        # 创建 CSV 文件
        csv_dir = dm.csv_dir / "1m"
        csv_dir.mkdir(parents=True, exist_ok=True)
        df = make_df_from_api(make_api_klines(50))
        df.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)

        result = dm.load_history("BTCUSDT")
        assert result is not None
        assert len(result) == 50
        assert 'timestamp' in result.columns
        assert 'close' in result.columns

    def test_load_history_nonexistent(self, dm):
        """不存在的 CSV 返回 None"""
        result = dm.load_history("NONEXIST")
        assert result is None

    def test_load_history_case_insensitive(self, dm):
        """symbol 大小写不敏感"""
        csv_dir = dm.csv_dir / "1m"
        csv_dir.mkdir(parents=True, exist_ok=True)
        df = make_df_from_api(make_api_klines(10))
        df.to_csv(csv_dir / "ETHUSDT_1m.csv", index=False)

        result = dm.load_history("ethusdt")
        assert result is not None
        assert len(result) == 10


class TestFetchKlinesRange:
    """fetch_klines_range 测试"""

    @pytest.mark.asyncio
    async def test_fetch_klines_range_success(self, dm):
        """成功从 API 拉取时间范围数据"""
        start_ms = 1713500000000
        end_ms = 1713500000000 + 60_000 * 10  # 10 分钟后

        with patch.object(dm, '_fetch_klines_from_api', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = make_api_klines(10, start_ms)

            result = await dm.fetch_klines_range("BTCUSDT", "1m", start_ms, end_ms)
            assert result is not None
            assert len(result) == 10

            # 验证调用参数
            mock_fetch.assert_called_once()
            call_args, call_kwargs = mock_fetch.call_args
            assert call_args[0] == "BTCUSDT"
            assert call_args[1] == "1m"

    @pytest.mark.asyncio
    async def test_fetch_klines_range_api_failure(self, dm):
        """API 调用失败返回 None"""
        with patch.object(dm, '_fetch_klines_from_api', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = None

            result = await dm.fetch_klines_range("BTCUSDT", "1m", 1713500000000, 1713500100000)
            assert result is None


class TestSyncToLatest:
    """sync_to_latest 测试"""

    @pytest.mark.asyncio
    async def test_sync_to_latest_no_existing_data(self, dm):
        """无本地数据时，下载完整历史"""
        with patch.object(dm, 'batch_download_history', new_callable=AsyncMock) as mock_batch:
            mock_batch.return_value = {"2026-04-19": True}
            with patch.object(dm, 'init_today_realtime', new_callable=AsyncMock) as mock_today:
                mock_today.return_value = True

                result = await dm.sync_to_latest("BTCUSDT", max_history_days=1)
                # 无数据时会调用 batch_download_history + init_today_realtime
                mock_batch.assert_called_once()
                mock_today.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_to_latest_recent_data(self, dm):
        """本地数据距今 < 1 天，只补齐 gap"""
        # 放入已有缓存
        now = datetime.now(timezone.utc)
        df = make_df_from_api(make_api_klines(10, int((now - timedelta(hours=2)).timestamp() * 1000)))
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        with patch.object(dm, '_fetch_klines_from_api', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = make_api_klines(5, int((now - timedelta(minutes=5)).timestamp() * 1000))

            result = await dm.sync_to_latest("BTCUSDT", max_history_days=1)
            # 数据距今 < 1 天，只调用 API 补齐 gap
            mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_sync_to_latest_old_data_needs_full_sync(self, dm):
        """本地数据距今 > 1 天，全量补齐"""
        old_time = datetime.now(timezone.utc) - timedelta(days=5)
        df = make_df_from_api(make_api_klines(5, int(old_time.timestamp() * 1000)))
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        with patch.object(dm, 'batch_download_history', new_callable=AsyncMock) as mock_batch:
            mock_batch.return_value = {}
            with patch.object(dm, 'init_today_realtime', new_callable=AsyncMock) as mock_today:
                mock_today.return_value = True

                result = await dm.sync_to_latest("BTCUSDT", max_history_days=5)
                mock_batch.assert_called_once()


class TestCacheRecentData:
    """cache_recent_data 测试"""

    def test_cache_recent_data_basic(self, dm):
        """缓存多个 symbols 的近 7 天数据"""
        csv_dir = dm.csv_dir / "1m"
        csv_dir.mkdir(parents=True, exist_ok=True)

        # 创建两个 symbol 的 CSV
        now = datetime.now(timezone.utc)
        df_btc = make_df_from_api(make_api_klines(100, int((now - timedelta(days=3)).timestamp() * 1000)))
        df_eth = make_df_from_api(make_api_klines(80, int((now - timedelta(days=2)).timestamp() * 1000)))

        df_btc.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)
        df_eth.to_csv(csv_dir / "ETHUSDT_1m.csv", index=False)

        success = dm.cache_recent_data(["BTCUSDT", "ETHUSDT"], days=7)

        assert "BTCUSDT" in success
        assert "ETHUSDT" in success
        assert success["BTCUSDT"] is True
        assert success["ETHUSDT"] is True

        # 验证缓存中有数据
        assert dm.cache.get_1m_data("BTCUSDT") is not None
        assert dm.cache.get_1m_data("ETHUSDT") is not None

    def test_cache_recent_data_empty_symbols(self, dm):
        """空 symbols 列表返回空字典"""
        result = dm.cache_recent_data([], days=7)
        assert result == {}


class TestGetIndicators:
    """get_indicators 测试"""

    def test_get_indicators_adx(self, dm):
        """获取 ADX 指标"""
        csv_dir = dm.csv_dir / "1m"
        csv_dir.mkdir(parents=True, exist_ok=True)
        # 需要足够数据计算 ADX，且价格要有趋势变化
        now = datetime.now(timezone.utc)
        start_ms = int((now - timedelta(hours=1)).timestamp() * 1000)
        api_data = []
        base = 100.0
        for i in range(60):
            ts = start_ms + i * 60_000
            trend = i * 0.3  # 上升趋势
            high_val = base + trend + 1.0
            low_val = base + trend - 1.0
            close_val = base + trend
            api_data.append([
                ts, str(close_val - 0.1), str(high_val), str(low_val),
                str(close_val), "1000.0", ts + 60_000, "100500.0",
                50, "500.0", "50250.0",
            ])
        df = make_df_from_api(api_data)
        df.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        result = dm.get_indicators("BTCUSDT", "1m", "adx")
        assert result is not None
        assert len(result) > 0
        assert "adx" in result.columns

    def test_get_indicators_rsi(self, dm):
        """获取 RSI 指标"""
        now = datetime.now(timezone.utc)
        api_data = make_api_klines(50, int((now - timedelta(hours=1)).timestamp() * 1000))
        df = make_df_from_api(api_data)
        dm.cache.put("BTCUSDT", "1m", df, force_1m=True)

        result = dm.get_indicators("BTCUSDT", "1m", "rsi", params={"period": 14})
        assert result is not None
        assert len(result) > 0

    def test_get_indicators_no_data(self, dm):
        """无数据时返回空 DataFrame"""
        result = dm.get_indicators("NONEXIST", "1m", "adx")
        assert result is not None
        assert result.empty

    def test_get_available_indicators(self, dm):
        """获取可用指标列表"""
        indicators = dm.get_available_indicators()
        assert "adx" in indicators
        assert "rsi" in indicators
        assert "macd" in indicators
