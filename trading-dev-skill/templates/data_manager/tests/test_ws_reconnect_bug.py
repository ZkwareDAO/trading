#!/usr/bin/env python3
"""
WebSocket 重连逻辑测试

测试 Bug: 重连失败后不再尝试后续重连
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call
from datetime import datetime, timezone

from data_manager.klines_ws_client import KlinesWebSocketClient


class TestWebSocketReconnect:
    """WebSocket 重连测试"""

    @pytest.mark.asyncio
    async def test_reconnect_retries_on_connect_failure(self):
        """
        Bug reproducer: 重连失败后应该继续尝试下一次重连

        场景:
        1. 连接成功后断线
        2. 第一次重连失败 (connect 返回 False)
        3. 应该继续尝试第二次重连 (而不是直接放弃)
        """
        client = KlinesWebSocketClient(
            max_reconnect=3,
            reconnect_delay=1.0,  # 缩短延迟方便测试
            max_backoff=2.0
        )
        client.symbols = ["BTCUSDT"]
        client._running = True

        # 记录重连尝试次数
        reconnect_attempts = []

        # Mock connect: 第一次成功，断线后前两次失败，第三次成功
        async def mock_connect():
            reconnect_attempts.append(len(reconnect_attempts) + 1)
            if len(reconnect_attempts) == 1:
                # 第一次连接成功
                client._connected = True
                client._ws = AsyncMock()
                return True
            elif len(reconnect_attempts) <= 3:
                # 重连第 1、2 次失败
                client._connected = False
                return False
            else:
                # 重连第 3 次成功
                client._connected = True
                client._ws = AsyncMock()
                return True

        with patch.object(client, 'connect', mock_connect):
            # 第一次连接成功
            result = await client.connect()
            assert result is True
            assert len(reconnect_attempts) == 1

            # 模拟断线
            client._connected = False
            client._ws = None

            # 触发重连
            await client._reconnect()

            # 关键验证: 应该尝试了 3 次重连 (max_reconnect=3)
            # Bug 修复前: 只尝试 1 次，connect 失败后直接返回
            # Bug 修复后: 应尝试 3 次，直到成功或达到上限
            assert len(reconnect_attempts) >= 2, (
                f"重连失败后应继续尝试，但只尝试了 {len(reconnect_attempts)} 次"
            )

    @pytest.mark.asyncio
    async def test_reconnect_stops_after_max_attempts(self):
        """
        测试达到最大重连次数后停止尝试

        场景:
        1. 连接成功后断线
        2. 所有重连都失败
        3. 达到 max_reconnect 后停止
        """
        client = KlinesWebSocketClient(
            max_reconnect=3,
            reconnect_delay=0.5,
            max_backoff=1.0
        )
        client._running = True

        # 使用列表避免闭包变量问题
        attempt_count = [0]

        async def mock_connect_always_fail():
            attempt_count[0] += 1
            client._connected = False
            return False

        with patch.object(client, 'connect', mock_connect_always_fail):
            await client._reconnect()

            # Bug: 当前代码只尝试 1 次，应该尝试 max_reconnect 次
            # 修复后应该正好尝试 max_reconnect 次
            assert attempt_count[0] == 3, (
                f"应该尝试 {client.max_reconnect} 次，实际尝试 {attempt_count[0]} 次"
            )

    @pytest.mark.asyncio
    async def test_reconnect_infinite_mode(self):
        """
        测试 max_reconnect=0 表示无限重连

        场景:
        1. max_reconnect=0 表示无限
        2. 前几次失败后最终成功
        """
        client = KlinesWebSocketClient(
            max_reconnect=0,  # 无限重连
            reconnect_delay=0.5,
            max_backoff=1.0
        )
        client.symbols = ["BTCUSDT"]
        client._running = True

        attempt_count = [0]

        async def mock_connect_fail_then_success():
            attempt_count[0] += 1
            if attempt_count[0] < 3:
                client._connected = False
                return False
            else:
                client._connected = True
                client._ws = AsyncMock()
                return True

        with patch.object(client, 'connect', mock_connect_fail_then_success):
            await client._reconnect()

            # 应该在第 3 次成功
            assert attempt_count[0] == 3

    @pytest.mark.asyncio
    async def test_reconnect_resets_count_on_success(self):
        """
        测试重连成功后 _reconnect_count 重置为 0

        注意: 当前实现中 connect() 成功时会重置 _reconnect_count=0
        但这个行为是在 connect() 内部完成的

        场景:
        1. 第一次连接成功，_reconnect_count=0
        2. 断线后触发 _reconnect()
        3. _reconnect 内部 _reconnect_count += 1
        4. connect() 成功后会重置 _reconnect_count=0
        """
        client = KlinesWebSocketClient(
            max_reconnect=5,
            reconnect_delay=0.5
        )
        client._running = True

        # 不使用 patch，直接调用真实的 connect
        # 需要 mock websockets.connect
        with patch('websockets.connect', new_callable=AsyncMock) as mock_ws_connect:
            mock_ws = AsyncMock()
            mock_ws_connect.return_value.__aenter__.return_value = mock_ws

            # 第一次连接
            result = await client.connect()
            assert result is True
            assert client._reconnect_count == 0

            # 模拟断线
            client._connected = False

            # 重连
            result = await client._reconnect()
            # 重连成功
            assert client._connected is True
            # connect() 成功时会重置 _reconnect_count=0
            assert client._reconnect_count == 0

    @pytest.mark.asyncio
    async def test_reconnect_stops_when_not_running(self):
        """
        测试 _running=False 时停止重连

        场景:
        1. disconnect() 设置 _running=False
        2. _reconnect() 应直接返回
        """
        client = KlinesWebSocketClient()
        client._running = False  # 已停止

        # 不应该调用 connect
        with patch.object(client, 'connect', AsyncMock(return_value=True)) as mock:
            await client._reconnect()

            mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_reconnect_subscribe_on_success(self):
        """
        测试重连成功后重新订阅 symbols
        """
        client = KlinesWebSocketClient(
            max_reconnect=3,
            reconnect_delay=0.5
        )
        client.symbols = ["BTCUSDT", "ETHUSDT"]
        client._running = True

        async def mock_connect_success():
            client._connected = True
            client._ws = AsyncMock()
            return True

        with patch.object(client, 'connect', mock_connect_success):
            with patch.object(client, 'subscribe', AsyncMock(return_value=True)) as mock_subscribe:
                await client._reconnect()

                # 重连成功后应重新订阅
                mock_subscribe.assert_called_once_with(["BTCUSDT", "ETHUSDT"])

    @pytest.mark.asyncio
    async def test_reconnect_calls_callback_on_success(self):
        """
        测试重连成功后调用回调
        """
        client = KlinesWebSocketClient(
            max_reconnect=3,
            reconnect_delay=0.5
        )
        client.symbols = ["BTCUSDT"]
        client._running = True

        reconnect_callback = AsyncMock()
        client.set_on_reconnect_callback(reconnect_callback)

        async def mock_connect_success():
            client._connected = True
            client._ws = AsyncMock()
            return True

        with patch.object(client, 'connect', mock_connect_success):
            with patch.object(client, 'subscribe', AsyncMock(return_value=True)):
                await client._reconnect()

                reconnect_callback.assert_called_once()


class TestWebSocketReconnectPrevention:
    """重入保护测试"""

    @pytest.mark.asyncio
    async def test_handle_disconnect_prevents_duplicate_reconnect(self):
        """
        Bug reproducer: _handle_disconnect 可能被多次调用导致重复重连

        场景:
        1. _receive_loop 和 _heartbeat_loop 都可能触发断线检测
        2. _handle_disconnect 应有防重入机制

        测试方法: 使用真实的 _handle_disconnect 和 _reconnect，
        mock connect() 让其耗时足够长，验证并发调用只有一次成功进入重连流程
        """
        client = KlinesWebSocketClient(
            reconnect_delay=0.5
        )
        client._connected = True
        client._running = True

        connect_calls = [0]

        async def mock_connect_slow():
            connect_calls[0] += 1
            await asyncio.sleep(0.2)  # 模拟连接耗时
            client._connected = True
            client._ws = AsyncMock()
            return True

        with patch.object(client, 'connect', mock_connect_slow):
            # 模拟并发调用 _handle_disconnect
            # 第一次进入会设置 _reconnecting=True，阻止第二次
            await asyncio.gather(
                client._handle_disconnect(),
                client._handle_disconnect(),
            )

            # 只应该调用一次 connect（防重入生效）
            assert connect_calls[0] == 1, (
                f"_handle_disconnect 应防重入，但 connect 被调用 {connect_calls[0]} 次"
            )