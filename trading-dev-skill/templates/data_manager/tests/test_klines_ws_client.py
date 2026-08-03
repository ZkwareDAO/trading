#!/usr/bin/env python3
"""
Klines WebSocket 客户端测试
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from data_manager.klines_ws_client import KlinesWebSocketClient, Kline


class TestKlinesWebSocketClient:
    """WebSocket 客户端测试"""

    def test_init_default_values(self):
        """测试默认初始化"""
        client = KlinesWebSocketClient()

        assert client.ws_url == "ws://127.0.0.1:17081/ws/klines"
        assert client.symbols == []
        assert client.reconnect_delay == 5.0
        assert client.max_reconnect == 5
        assert client._connected is False
        assert client._on_kline_callback is None

    def test_init_custom_values(self):
        """测试自定义参数初始化"""
        client = KlinesWebSocketClient(
            ws_url="ws://localhost:8080/ws",
            symbols=["BTCUSDT", "ETHUSDT"],
            reconnect_delay=10.0,
            max_reconnect=3
        )

        assert client.ws_url == "ws://localhost:8080/ws"
        assert client.symbols == ["BTCUSDT", "ETHUSDT"]
        assert client.reconnect_delay == 10.0
        assert client.max_reconnect == 3

    def test_set_on_kline_callback(self):
        """测试设置回调"""
        client = KlinesWebSocketClient()
        callback = MagicMock()

        client.set_on_kline_callback(callback)

        assert client._on_kline_callback is callback

    @pytest.mark.asyncio
    async def test_connect_success(self):
        """测试连接成功"""
        client = KlinesWebSocketClient()

        with patch('websockets.connect', new_callable=AsyncMock) as mock_connect:
            mock_ws = AsyncMock()
            mock_connect.return_value.__aenter__.return_value = mock_ws

            result = await client.connect()

            assert result is True
            assert client._connected is True
            assert client._ws is not None

    @pytest.mark.asyncio
    async def test_connect_failure(self):
        """测试连接失败"""
        client = KlinesWebSocketClient()

        with patch('websockets.connect', side_effect=Exception("Connection refused")):
            result = await client.connect()

            assert result is False
            assert client._connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """测试断开连接"""
        client = KlinesWebSocketClient()
        client._connected = True
        mock_ws = AsyncMock()
        client._ws = mock_ws

        await client.disconnect()

        assert client._connected is False
        mock_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscribe_sends_message(self):
        """测试订阅发送消息"""
        client = KlinesWebSocketClient()
        client._connected = True
        client._ws = AsyncMock()

        await client.subscribe(["BTCUSDT", "ETHUSDT"])

        expected_message = '{"action": "subscribe", "symbols": ["BTCUSDT", "ETHUSDT"]}'
        client._ws.send.assert_called_once_with(expected_message)

    @pytest.mark.asyncio
    async def test_subscribe_when_not_connected(self):
        """测试未连接时订阅"""
        client = KlinesWebSocketClient()
        client._connected = False

        with pytest.raises(RuntimeError, match="Not connected"):
            await client.subscribe(["BTCUSDT"])

    @pytest.mark.asyncio
    async def test_subscribe_deduplicates_symbols(self):
        """测试订阅时去重 symbols - 防止重连时累积重复"""
        client = KlinesWebSocketClient()
        client._connected = True
        client._ws = AsyncMock()
        client.symbols = ["BTCUSDT", "ETHUSDT"]  # 已有订阅

        # 再次订阅相同 symbols
        await client.subscribe(["BTCUSDT", "ETHUSDT", "SOLUSDT"])

        # symbols 列表应该去重，不应有重复
        assert client.symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        assert len(client.symbols) == 3  # 只有 3 个，不是 5 个

    @pytest.mark.asyncio
    async def test_subscribe_multiple_times_no_duplication(self):
        """测试多次订阅同一 symbols 不累积重复"""
        client = KlinesWebSocketClient()
        client._connected = True
        client._ws = AsyncMock()

        # 模拟重连场景：多次订阅同一列表
        for _ in range(10):
            await client.subscribe(["BTCUSDT", "ETHUSDT"])

        # 重复订阅 10 次，symbols 列表应该只有 2 个元素
        assert client.symbols == ["BTCUSDT", "ETHUSDT"]
        assert len(client.symbols) == 2

    @pytest.mark.asyncio
    async def test_unsubscribe_sends_message(self):
        """测试取消订阅发送消息"""
        client = KlinesWebSocketClient()
        client._connected = True
        client._ws = AsyncMock()

        await client.unsubscribe(["BTCUSDT"])

        expected_message = '{"action": "unsubscribe", "symbols": ["BTCUSDT"]}'
        client._ws.send.assert_called_once_with(expected_message)

    def test_parse_kline_data(self):
        """测试解析 K 线数据"""
        client = KlinesWebSocketClient()

        ws_message = {
            "type": "kline",
            "symbol": "BTCUSDT",
            "data": {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "open": "50000.00",
                "high": "50100.00",
                "low": "49900.00",
                "close": "50050.00",
                "volume": "100.50",
                "is_final": True,
                "start_time": 1712548800000,
                "end_time": 1712548859999,
                "quote_volume": "5025000.00",
                "trade_num": 1234,
                "active_buy_volume": "50.25",
                "active_buy_quote_volume": "2512500.00"
            }
        }

        kline = client._parse_kline_data(ws_message)

        assert isinstance(kline, Kline)
        assert kline.symbol == "BTCUSDT"
        assert kline.interval == "1m"
        assert kline.open == 50000.00
        assert kline.high == 50100.00
        assert kline.low == 49900.00
        assert kline.close == 50050.00
        assert kline.volume == 100.50
        assert kline.timestamp == datetime.fromtimestamp(1712548800, tz=timezone.utc)

    def test_parse_kline_data_missing_fields(self):
        """测试解析缺失字段的 K 线数据"""
        client = KlinesWebSocketClient()

        ws_message = {
            "type": "kline",
            "symbol": "BTCUSDT",
            "data": {
                "open": "50000.00",
                "close": "50050.00",
                "start_time": 1712548800000
            }
        }

        kline = client._parse_kline_data(ws_message)

        assert kline.symbol == "BTCUSDT"  # 从外层获取
        assert kline.open == 50000.00
        assert kline.close == 50050.00
        assert kline.high == 0.0  # 默认值
        assert kline.low == 0.0  # 默认值
        assert kline.volume == 0.0  # 默认值

    @pytest.mark.asyncio
    async def test_message_handler_calls_callback(self):
        """测试消息处理器调用回调"""
        client = KlinesWebSocketClient()
        callback = AsyncMock()
        client.set_on_kline_callback(callback)

        ws_message = {
            "type": "kline",
            "symbol": "BTCUSDT",
            "data": {
                "open": "50000.00",
                "close": "50050.00",
                "start_time": 1712548800000
            }
        }

        await client._message_handler(ws_message)

        callback.assert_called_once()
        arg = callback.call_args[0][0]
        assert isinstance(arg, Kline)
        assert arg.symbol == "BTCUSDT"

    @pytest.mark.asyncio
    async def test_message_handler_ignores_non_kline(self):
        """测试消息处理器忽略非 K 线消息"""
        client = KlinesWebSocketClient()
        callback = AsyncMock()
        client.set_on_kline_callback(callback)

        ws_message = {
            "type": "ping",
            "data": {}
        }

        await client._message_handler(ws_message)

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_handler_no_callback(self):
        """测试无回调时不报错"""
        client = KlinesWebSocketClient()
        # 未设置回调

        ws_message = {
            "type": "kline",
            "symbol": "BTCUSDT",
            "data": {
                "open": "50000.00",
                "close": "50050.00",
                "start_time": 1712548800000
            }
        }

        # 不应抛出异常
        await client._message_handler(ws_message)


class TestKline:
    """Kline 数据类测试"""

    def test_from_dict_basic(self):
        """测试从字典创建"""
        data = {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "open": 50000.0,
            "high": 50100.0,
            "low": 49900.0,
            "close": 50050.0,
            "volume": 100.5,
            "timestamp": 1712548800000
        }

        kline = Kline.from_dict(data)

        assert kline.symbol == "BTCUSDT"
        assert kline.interval == "1m"
        assert kline.open == 50000.0
        assert kline.close == 50050.0

    def test_from_dict_string_timestamp(self):
        """测试字符串时间戳"""
        data = {
            "symbol": "BTCUSDT",
            "open": 50000.0,
            "close": 50050.0,
            "timestamp": "2024-04-08T10:00:00+00:00"
        }

        kline = Kline.from_dict(data)

        assert isinstance(kline.timestamp, datetime)
        assert kline.timestamp.tzinfo is not None

    def test_to_dict(self):
        """测试转换为字典"""
        kline = Kline(
            symbol="BTCUSDT",
            interval="1m",
            timestamp=datetime(2024, 4, 8, 10, 0, tzinfo=timezone.utc),
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.5
        )

        result = kline.to_dict()

        assert result["symbol"] == "BTCUSDT"
        assert result["interval"] == "1m"
        assert result["open"] == 50000.0
        assert result["close"] == 50050.0

    def test_repr(self):
        """测试字符串表示"""
        kline = Kline(
            symbol="BTCUSDT",
            interval="1m",
            timestamp=datetime(2024, 4, 8, 10, 0, tzinfo=timezone.utc),
            open=50000.0,
            high=50100.0,
            low=49900.0,
            close=50050.0,
            volume=100.5
        )

        repr_str = repr(kline)

        assert "BTCUSDT" in repr_str
        assert "50050.0" in repr_str
