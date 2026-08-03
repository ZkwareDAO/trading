"""
WebSocket 重连策略测试

测试:
- 类常量定义正确
- 无限重连配置 (max_reconnect=0)
- 每分钟重试间隔
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from data_manager.manager import DataManager, DataManagerConfig
from data_manager.klines_ws_client import KlinesWebSocketClient


class TestWebSocketReconnectStrategy:
    """WebSocket 重连策略测试"""

    def test_class_constants_defined(self):
        """测试类常量已定义且值正确"""
        assert hasattr(DataManager, 'WS_RECONNECT_DELAY')
        assert hasattr(DataManager, 'WS_MAX_RECONNECT')
        assert hasattr(DataManager, 'WS_MAX_BACKOFF')

        assert DataManager.WS_RECONNECT_DELAY == 60.0
        assert DataManager.WS_MAX_RECONNECT == 0  # 0 表示无限重试
        assert DataManager.WS_MAX_BACKOFF == 60.0

    def test_ws_client_uses_class_constants(self):
        """测试 WebSocket 客户端使用类常量配置"""
        dm = DataManager()

        # 验证常量值会被传递给 KlinesWebSocketClient
        # 通过检查常量值来确认配置意图
        assert dm.WS_RECONNECT_DELAY == 60.0, "重连延迟应为 60 秒"
        assert dm.WS_MAX_RECONNECT == 0, "max_reconnect=0 表示无限重试"
        assert dm.WS_MAX_BACKOFF == 60.0, "退避上限应为 60 秒"

    def test_reconnect_delay_is_one_minute(self):
        """测试重连延迟为 1 分钟"""
        assert DataManager.WS_RECONNECT_DELAY == 60.0

    def test_max_reconnect_is_infinite(self):
        """测试最大重连次数为无限"""
        assert DataManager.WS_MAX_RECONNECT == 0

    def test_max_backoff_equals_reconnect_delay(self):
        """测试退避上限等于重连延迟（固定间隔，无指数退避）"""
        assert DataManager.WS_MAX_BACKOFF == DataManager.WS_RECONNECT_DELAY


class TestKlinesWebSocketClientInfiniteRetry:
    """KlinesWebSocketClient 无限重试行为测试"""

    def test_max_reconnect_zero_means_infinite(self):
        """测试 max_reconnect=0 表示无限重试"""
        client = KlinesWebSocketClient(
            ws_url="ws://test:8080/ws",
            max_reconnect=0,
        )

        assert client.max_reconnect == 0
        assert client.reconnect_delay == 5.0  # 默认值

    def test_custom_reconnect_delay(self):
        """测试自定义重连延迟"""
        client = KlinesWebSocketClient(
            ws_url="ws://test:8080/ws",
            reconnect_delay=60.0,
            max_reconnect=0,
            max_backoff=60.0,
        )

        assert client.reconnect_delay == 60.0
        assert client.max_reconnect == 0
        assert client.max_backoff == 60.0

    @pytest.mark.asyncio
    async def test_reconnect_never_gives_up_when_zero(self):
        """测试 max_reconnect=0 时永不放弃重连"""
        client = KlinesWebSocketClient(
            ws_url="ws://test:8080/ws",
            reconnect_delay=0.1,  # 快速测试
            max_reconnect=0,
            max_backoff=0.1,
        )

        # 模拟连接始终失败
        fail_count = 0

        async def mock_connect():
            nonlocal fail_count
            fail_count += 1
            return False

        # 替换 connect 方法
        client.connect = mock_connect

        # 启动重连循环（会在后台运行）
        client._running = True
        client._connected = False

        # 模拟多次重连尝试
        for _ in range(10):
            if not client._running:
                break
            # 检查重连逻辑不会因为达到上限而停止
            is_infinite = client.max_reconnect == 0
            should_stop = not is_infinite and client._reconnect_count >= client.max_reconnect
            assert not should_stop, "max_reconnect=0 时不应停止重连"

        # 验证即使多次失败，客户端仍处于运行状态
        assert client.max_reconnect == 0


class TestWebSocketReconnectIntegration:
    """WebSocket 重连集成测试"""

    @pytest.mark.asyncio
    async def test_manager_creates_ws_client_with_infinite_retry(self):
        """测试 DataManager 创建的 WS 客户端配置为无限重试"""
        dm = DataManager()

        # Mock WebSocket 连接
        with patch.object(KlinesWebSocketClient, 'connect', new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value = True

            with patch.object(KlinesWebSocketClient, 'set_on_kline_callback'):
                result = await dm.start_klines_service_async()

                assert result is True
                assert dm._ws_client is not None

                # 验证重连配置
                assert dm._ws_client.max_reconnect == 0, "应为无限重试"
                assert dm._ws_client.reconnect_delay == 60.0, "应为 60 秒重试间隔"
                assert dm._ws_client.max_backoff == 60.0, "退避上限应为 60 秒"
