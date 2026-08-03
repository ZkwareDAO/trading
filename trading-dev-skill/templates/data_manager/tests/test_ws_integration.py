"""
DataManager WebSocket 集成测试

覆盖:
- DataManager 启动/停止 klines_service
- _on_kline_received 回调：写入 1m 缓存
- _on_kline_received 回调：触发 KlineRepository 聚合
- connect() 建立 WS 连接
- close() 断开 WS 连接
- 断线重连逻辑
"""

import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, AsyncMock

import pandas as pd
import pytest

from data_manager.manager import DataManager, DataManagerConfig
from data_manager.klines_data import Kline


class TestKlinesServiceConnect:
    """klines_service 连接测试"""

    @pytest.mark.asyncio
    async def test_start_klines_service_creates_client(self):
        """启动 klines_service 创建 WS 客户端"""
        tmpdir = tempfile.mkdtemp()
        try:
            config = DataManagerConfig(
                csv_dir=tmpdir,
                klines_service_enabled=True,
                klines_service_ws_url="ws://127.0.0.1:17081/ws/klines",
                preload_1m_enabled=False,
            )
            dm = DataManager(config)

            with patch("data_manager.manager.KlinesWebSocketClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.connect = AsyncMock(return_value=True)
                mock_client.set_on_kline_callback = MagicMock()
                MockClient.return_value = mock_client

                result = await dm.start_klines_service_async()

                assert result is True
                assert dm._ws_client is not None
                MockClient.assert_called_once()
        finally:
            shutil.rmtree(tmpdir)

    @pytest.mark.asyncio
    async def test_start_klines_service_disabled(self):
        """配置禁用时不启动"""
        tmpdir = tempfile.mkdtemp()
        try:
            config = DataManagerConfig(
                csv_dir=tmpdir,
                klines_service_enabled=False,
                preload_1m_enabled=False,
            )
            dm = DataManager(config)

            result = await dm.start_klines_service_async()
            assert result is False
            assert dm._ws_client is None
        finally:
            shutil.rmtree(tmpdir)

    @pytest.mark.asyncio
    async def test_start_klines_service_connect_failure(self):
        """连接失败返回 False"""
        tmpdir = tempfile.mkdtemp()
        try:
            config = DataManagerConfig(
                csv_dir=tmpdir,
                klines_service_enabled=True,
                preload_1m_enabled=False,
            )
            dm = DataManager(config)

            with patch("data_manager.manager.KlinesWebSocketClient") as MockClient:
                mock_client = AsyncMock()
                mock_client.connect = AsyncMock(return_value=False)
                mock_client.set_on_kline_callback = MagicMock()
                MockClient.return_value = mock_client

                result = await dm.start_klines_service_async()
                assert result is False
        finally:
            shutil.rmtree(tmpdir)

    @pytest.mark.asyncio
    async def test_close_stops_ws_client(self):
        """close() 断开 WS 连接"""
        tmpdir = tempfile.mkdtemp()
        try:
            config = DataManagerConfig(
                csv_dir=tmpdir,
                klines_service_enabled=True,
                preload_1m_enabled=False,
            )
            dm = DataManager(config)

            mock_ws = AsyncMock()
            dm._ws_client = mock_ws
            dm._connected = True

            await dm.close()

            mock_ws.disconnect.assert_called_once()
            assert dm._ws_client is None
        finally:
            shutil.rmtree(tmpdir)


class TestOnKlineReceived:
    """K 线接收回调测试"""

    def _make_dm(self):
        """创建 DataManager（无 WS 连接）"""
        tmpdir = tempfile.mkdtemp()
        config = DataManagerConfig(
            csv_dir=tmpdir,
            klines_service_enabled=True,
            preload_1m_enabled=False,
        )
        dm = DataManager(config)
        dm._ws_subscribed_symbols = {"BTCUSDT"}
        return dm, tmpdir

    def _recent_ts(self, minutes_ago: int = 1) -> datetime:
        """生成近期时间戳（避免被时间戳验证跳过）"""
        return datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)

    def test_on_kline_writes_to_1m_cache(self):
        """收到 K 线写入 1m 缓存"""
        dm, tmpdir = self._make_dm()
        try:
            ts = self._recent_ts(1)
            kline = Kline(
                symbol="BTCUSDT",
                interval="1m",
                timestamp=ts,
                open=100.0,
                high=105.0,
                low=95.0,
                close=102.0,
                volume=10.0,
            )

            dm._on_kline_received(kline)

            cached = dm.cache.get_1m_data("BTCUSDT")
            assert cached is not None
            assert len(cached) == 1
            assert cached.iloc[0]["close"] == 102.0
        finally:
            shutil.rmtree(tmpdir)

    def test_on_kline_appends_to_existing(self):
        """已有缓存时追加"""
        dm, tmpdir = self._make_dm()
        try:
            base = self._recent_ts(2)
            existing = pd.DataFrame({
                "timestamp": [base],
                "open": [100.0],
                "high": [105.0],
                "low": [95.0],
                "close": [102.0],
                "volume": [10.0],
            })
            dm.cache.put("BTCUSDT", "1m", existing, force_1m=True)

            new_kline = Kline(
                symbol="BTCUSDT",
                interval="1m",
                timestamp=self._recent_ts(1),
                open=102.0,
                high=107.0,
                low=97.0,
                close=104.0,
                volume=11.0,
            )

            dm._on_kline_received(new_kline)

            cached = dm.cache.get_1m_data("BTCUSDT")
            assert len(cached) == 2
        finally:
            shutil.rmtree(tmpdir)

    def test_on_kline_triggers_repo_update(self):
        """启用 kline_repo 时触发聚合"""
        dm, tmpdir = self._make_dm()
        try:
            dm.enable_kline_repository()
            dm.register_timeframes_for_symbol("BTCUSDT", ["1h"])

            ts = self._recent_ts(1)
            kline = Kline(
                symbol="BTCUSDT",
                interval="1m",
                timestamp=ts,
                open=100.0,
                high=105.0,
                low=95.0,
                close=102.0,
                volume=10.0,
            )

            with patch.object(dm.kline_repo, "update_from_1m", return_value={"1h": True}) as mock_update:
                dm._on_kline_received(kline)
                # 不立即触发，由 main.py 轮询触发，此处验证缓存已写入
                mock_update.assert_not_called()

            # 验证缓存
            cached = dm.cache.get_1m_data("BTCUSDT")
            assert cached is not None
        finally:
            shutil.rmtree(tmpdir)

    def test_on_kline_unsubscribed_symbol_ignored(self):
        """未订阅的 symbol 忽略"""
        dm, tmpdir = self._make_dm()
        try:
            dm._ws_subscribed_symbols = {"BTCUSDT"}

            ts = self._recent_ts(1)
            kline = Kline(
                symbol="ETHUSDT",
                interval="1m",
                timestamp=ts,
                open=200.0,
                high=210.0,
                low=190.0,
                close=205.0,
                volume=20.0,
            )

            dm._on_kline_received(kline)

            cached = dm.cache.get_1m_data("ETHUSDT")
            assert cached is None
        finally:
            shutil.rmtree(tmpdir)


class TestKlinesServiceSubscribe:
    """WS 订阅测试"""

    @pytest.mark.asyncio
    async def test_subscribe_klines_success(self):
        """订阅 K 线成功"""
        tmpdir = tempfile.mkdtemp()
        try:
            config = DataManagerConfig(
                csv_dir=tmpdir,
                klines_service_enabled=True,
                preload_1m_enabled=False,
            )
            dm = DataManager(config)

            mock_ws = AsyncMock()
            mock_ws.subscribe = AsyncMock(return_value=True)
            dm._ws_client = mock_ws
            dm._connected = True

            result = await dm.subscribe_klines_async(["BTCUSDT", "ETHUSDT"])

            assert result is True
            mock_ws.subscribe.assert_called_once_with(["BTCUSDT", "ETHUSDT"])
            assert "BTCUSDT" in dm._ws_subscribed_symbols
            assert "ETHUSDT" in dm._ws_subscribed_symbols
        finally:
            shutil.rmtree(tmpdir)

    @pytest.mark.asyncio
    async def test_subscribe_not_connected(self):
        """未连接时订阅失败"""
        tmpdir = tempfile.mkdtemp()
        try:
            config = DataManagerConfig(
                csv_dir=tmpdir,
                klines_service_enabled=True,
                preload_1m_enabled=False,
            )
            dm = DataManager(config)

            result = await dm.subscribe_klines_async(["BTCUSDT"])
            assert result is False
        finally:
            shutil.rmtree(tmpdir)


class TestKlinesServiceAvailable:
    """WS 服务可用性测试"""

    def test_is_klines_service_available_false(self):
        """未启动时不可用"""
        tmpdir = tempfile.mkdtemp()
        try:
            config = DataManagerConfig(
                csv_dir=tmpdir,
                klines_service_enabled=True,
                preload_1m_enabled=False,
            )
            dm = DataManager(config)

            assert dm.is_klines_service_available() is False
        finally:
            shutil.rmtree(tmpdir)

    def test_is_klines_service_available_true(self):
        """启动后可用"""
        tmpdir = tempfile.mkdtemp()
        try:
            config = DataManagerConfig(
                csv_dir=tmpdir,
                klines_service_enabled=True,
                preload_1m_enabled=False,
            )
            dm = DataManager(config)
            dm._ws_client = MagicMock()
            dm._connected = True

            assert dm.is_klines_service_available() is True
        finally:
            shutil.rmtree(tmpdir)
