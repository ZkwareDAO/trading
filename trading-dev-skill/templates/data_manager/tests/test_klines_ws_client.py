#!/usr/bin/env python3
"""
Klines WebSocket 客户端测试

单体模式：客户端直连 Binance 公共 fstream combined-stream，
streams 固定在连接 URL 中（无 subscribe/unsubscribe 消息协议），
旧 klines_service 协议（subscribe 消息 / _parse_kline_data）的用例
已随通道移除，改测 _parse_binance_kline / _message_handler。
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from data_manager.klines_ws_client import KlinesWebSocketClient, Kline


def _binance_kline_msg(symbol="BTCUSDT", ts_ms=1712548800000):
    """构造 Binance combined-stream kline 消息"""
    return {
        "stream": f"{symbol.lower()}@kline_1m",
        "data": {
            "e": "kline",
            "E": ts_ms + 1000,
            "s": symbol,
            "k": {
                "t": ts_ms,          # open_time
                "T": ts_ms + 59999,  # close_time
                "s": symbol,
                "i": "1m",
                "o": "50000.00",
                "h": "50100.00",
                "l": "49900.00",
                "c": "50050.00",
                "v": "100.50",
                "q": "5025000.00",
                "n": 1234,
                "V": "50.25",
                "Q": "2512500.00",
                "x": True,
            },
        },
    }


class TestKlinesWebSocketClient:
    """WebSocket 客户端测试"""

    def test_init_default_values(self):
        """测试默认初始化（单体模式：直连 Binance 公共 combined-stream）"""
        client = KlinesWebSocketClient()

        assert client.ws_url == "wss://fstream.binance.com/stream"
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

    def test_parse_binance_kline(self):
        """测试解析 Binance combined-stream kline 消息"""
        client = KlinesWebSocketClient()

        msg = _binance_kline_msg()

        kline = client._parse_binance_kline(msg)

        assert isinstance(kline, Kline)
        assert kline.symbol == "BTCUSDT"
        assert kline.interval == "1m"
        assert kline.open == 50000.00
        assert kline.high == 50100.00
        assert kline.low == 49900.00
        assert kline.close == 50050.00
        assert kline.volume == 100.50
        assert kline.timestamp == datetime.fromtimestamp(1712548800, tz=timezone.utc)
        assert kline.is_final is True

    def test_parse_binance_kline_non_kline_event(self):
        """非 kline 事件（如 aggTrade）返回 None"""
        client = KlinesWebSocketClient()

        msg = {"stream": "btcusdt@aggTrade", "data": {"e": "aggTrade"}}

        assert client._parse_binance_kline(msg) is None

    @pytest.mark.asyncio
    async def test_message_handler_calls_callback(self):
        """测试消息处理器调用回调"""
        client = KlinesWebSocketClient()
        callback = AsyncMock()
        client.set_on_kline_callback(callback)

        await client._message_handler(_binance_kline_msg())

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
            "stream": "btcusdt@aggTrade",
            "data": {"e": "aggTrade"},
        }

        await client._message_handler(ws_message)

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_handler_no_callback(self):
        """测试无回调时不报错"""
        client = KlinesWebSocketClient()
        # 未设置回调

        # 不应抛出异常
        await client._message_handler(_binance_kline_msg())


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
