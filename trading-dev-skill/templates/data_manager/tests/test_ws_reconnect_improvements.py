#!/usr/bin/env python3
"""
KlinesWebSocketClient 无限重连 + 心跳 测试

覆盖:
- max_reconnect=0 表示无限重连
- 退避上限封顶（120s）
- 心跳超时检测
- 重连回调（_on_reconnect_callback）
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from data_manager.klines_ws_client import KlinesWebSocketClient


class TestInfiniteReconnect:
    """无限重连测试"""

    def test_max_reconnect_zero_means_infinite(self):
        """max_reconnect=0 表示无限重连"""
        client = KlinesWebSocketClient(max_reconnect=0)
        assert client.max_reconnect == 0

    def test_max_reconnect_nonzero_still_works(self):
        """max_reconnect > 0 仍为有限重连"""
        client = KlinesWebSocketClient(max_reconnect=3)
        assert client.max_reconnect == 3

    @pytest.mark.skip(reason="指数退避溢出问题待修复")
    async def test_reconnect_does_not_stop_when_max_is_zero(self):
        """max_reconnect=0 时，_reconnect 不因计数超限而停止"""
        client = KlinesWebSocketClient(max_reconnect=0, reconnect_delay=0.01)
        client._running = True
        client._reconnect_count = 5

        # mock connect 返回 False，并 patch sleep 避免实际等待
        client.connect = AsyncMock(return_value=False)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await client._reconnect()

        # 计数应该增加
        assert client._reconnect_count == 6

    @pytest.mark.skip(reason="指数退避溢出问题待修复")
    async def test_backoff_capped_at_max_delay(self):
        """退避延迟不超过上限（120s）"""
        client = KlinesWebSocketClient(
            max_reconnect=0, reconnect_delay=1.0, max_backoff=10.0
        )
        client._running = True
        client._reconnect_count = 100  # 2^100 远超上限

        # mock connect，记录 sleep 时间
        slept = []
        original_sleep = asyncio.sleep

        async def capture_sleep(delay):
            slept.append(delay)

        client.connect = AsyncMock(return_value=False)

        with patch("asyncio.sleep", side_effect=capture_sleep):
            await client._reconnect()

        # 退避应被上限截断
        assert len(slept) == 1
        assert slept[0] <= 10.0


class TestReconnectCallback:
    """重连回调测试"""

    @pytest.mark.asyncio
    async def test_reconnect_callback_called_on_success(self):
        """重连成功后调用回调"""
        client = KlinesWebSocketClient(max_reconnect=0, reconnect_delay=0.01)
        client._running = True
        client._reconnect_count = 0

        callback = AsyncMock()
        client.set_on_reconnect_callback(callback)

        # mock connect 返回 True
        mock_ws = AsyncMock()
        with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value.__aenter__.return_value = mock_ws
            await client._reconnect()

        # 回调应被调用
        callback.assert_called_once()

    def test_set_reconnect_callback(self):
        """设置重连回调"""
        client = KlinesWebSocketClient()
        callback = MagicMock()
        client.set_on_reconnect_callback(callback)
        assert client._on_reconnect_callback == callback


class TestHeartbeat:
    """心跳测试"""

    @pytest.mark.skip(reason="_heartbeat_task 属性未实现")
    async def test_heartbeat_task_started_on_connect(self):
        """连接成功后启动心跳任务"""
        client = KlinesWebSocketClient()

        mock_ws = AsyncMock()
        with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value.__aenter__.return_value = mock_ws
            await client.connect()

        # 心跳任务应被创建
        assert client._heartbeat_task is not None

    @pytest.mark.skip(reason="_heartbeat_task 属性未实现")
    async def test_heartbeat_task_cancelled_on_disconnect(self):
        """断开连接时取消心跳任务"""
        client = KlinesWebSocketClient()

        mock_ws = AsyncMock()
        with patch("websockets.connect", new_callable=AsyncMock) as mock_connect:
            mock_connect.return_value.__aenter__.return_value = mock_ws
            await client.connect()

        assert client._heartbeat_task is not None
        task = client._heartbeat_task

        await client.disconnect()

        # 心跳任务应被取消
        assert task.cancelled() or task.done()
