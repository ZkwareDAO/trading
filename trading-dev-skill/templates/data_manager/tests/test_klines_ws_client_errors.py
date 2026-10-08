"""
KlinesWebSocketClient 错误处理测试

单体模式：客户端直连 Binance 公共 fstream combined-stream，
streams 固定在连接 URL 中（无 subscribe/unsubscribe 消息协议），
旧 klines_service 协议用例已随通道移除，改测 Binance 消息解析与连接回退。
"""

import asyncio
from unittest.mock import patch, MagicMock, AsyncMock
from datetime import datetime, timezone

import pytest

from data_manager.klines_ws_client import KlinesWebSocketClient
from data_manager.klines_data import Kline


def _binance_kline_msg(symbol="BTCUSDT", ts_ms=1775584800000):
    """构造 Binance combined-stream kline 消息"""
    return {
        "stream": f"{symbol.lower()}@kline_1m",
        "data": {
            "e": "kline",
            "E": ts_ms + 1000,
            "s": symbol,
            "k": {
                "t": ts_ms,
                "T": ts_ms + 59999,
                "s": symbol,
                "i": "1m",
                "o": "100.0",
                "h": "105.0",
                "l": "95.0",
                "c": "102.0",
                "v": "10.0",
                "q": "10200.0",
                "n": 55,
                "V": "5.0",
                "Q": "5100.0",
                "x": True,
            },
        },
    }


class TestConnectionFailure:
    """连接失败测试"""

    def test_init_default_url(self):
        """默认 URL：Binance 公共 combined-stream"""
        client = KlinesWebSocketClient()
        assert client.ws_url == "wss://fstream.binance.com/stream"

    def test_init_custom_url(self):
        """自定义 URL 初始化"""
        client = KlinesWebSocketClient(ws_url="ws://example.com/ws")
        assert client.ws_url == "ws://example.com/ws"

    def test_init_with_symbols(self):
        """带 symbols 初始化"""
        client = KlinesWebSocketClient(symbols=["BTCUSDT"])
        assert client.symbols == ["BTCUSDT"]

    @pytest.mark.asyncio
    async def test_connect_refused(self):
        """连接被拒绝（服务器不可达）"""
        client = KlinesWebSocketClient(ws_url="ws://127.0.0.1:59999/ws/klines")
        result = await asyncio.wait_for(client.connect(), timeout=2.0)
        assert result is False
        assert client._connected is False

    @pytest.mark.asyncio
    async def test_connect_refuses_sets_not_connected(self):
        """连接失败后状态为未连接"""
        client = KlinesWebSocketClient(ws_url="ws://127.0.0.1:59999/ws/klines")
        await asyncio.wait_for(client.connect(), timeout=2.0)
        assert client._connected is False


class TestParseBinanceKline:
    """Binance combined-stream K 线解析测试"""

    def setup_method(self):
        self.client = KlinesWebSocketClient()

    def test_parse_valid_kline_message(self):
        """解析有效 Binance combined-stream kline 消息"""
        ts_ms = int(datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
        msg = _binance_kline_msg("BTCUSDT", ts_ms)

        result = self.client._parse_binance_kline(msg)
        assert isinstance(result, Kline)
        assert result.symbol == 'BTCUSDT'
        assert result.interval == '1m'
        assert result.open == 100.0
        assert result.high == 105.0
        assert result.low == 95.0
        assert result.close == 102.0
        assert result.volume == 10.0
        assert result.timestamp == datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)

    def test_parse_kline_symbol_from_stream_payload(self):
        """symbol 来自 k.s 字段"""
        ts_ms = int(datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
        msg = _binance_kline_msg("ETHUSDT", ts_ms)
        result = self.client._parse_binance_kline(msg)
        assert result.symbol == 'ETHUSDT'

    def test_parse_non_kline_event_returns_none(self):
        """非 kline 事件（aggTrade 等）返回 None"""
        msg = {'stream': 'btcusdt@aggTrade', 'data': {'e': 'aggTrade'}}
        assert self.client._parse_binance_kline(msg) is None


class TestSubscription:
    """订阅语义测试（单体模式：streams 固定在 URL，无 subscribe 协议）"""

    def test_ws_url_contains_streams(self):
        """symbols 经 URL streams 参数表达，客户端记录 symbols 仅供展示"""
        client = KlinesWebSocketClient(
            ws_url="wss://fstream.binance.com/stream?streams=btcusdt@kline_1m",
            symbols=["BTCUSDT"],
        )
        assert "btcusdt@kline_1m" in client.ws_url
        assert client.symbols == ["BTCUSDT"]

    @pytest.mark.asyncio
    async def test_reconnect_reuses_same_url_no_resubscribe(self):
        """重连复用同一 URL（streams 在 URL 中），无需重新订阅"""
        client = KlinesWebSocketClient(
            ws_url="ws://127.0.0.1:59999/ws/klines",
            max_reconnect=1,
        )
        client._running = True
        url_before = client.ws_url
        with patch.object(client, 'connect', AsyncMock(return_value=False)):
            await client._reconnect()
        assert client.ws_url == url_before


class TestConnectionCallbacks:
    """连接回调测试"""

    def test_set_on_kline_callback(self):
        """设置 K 线回调"""
        client = KlinesWebSocketClient()
        callback = MagicMock()
        client.set_on_kline_callback(callback)
        assert client._on_kline_callback == callback

    def test_set_on_reconnect_callback(self):
        """设置重连成功回调"""
        client = KlinesWebSocketClient()
        callback = MagicMock()
        client.set_on_reconnect_callback(callback)
        assert client._on_reconnect_callback == callback


class TestDisconnect:
    """断开连接测试"""

    @pytest.mark.asyncio
    async def test_disconnect_without_connect(self):
        """未连接时断开"""
        client = KlinesWebSocketClient()
        # 不应抛出异常
        await client.disconnect()
        assert client._connected is False

    @pytest.mark.asyncio
    async def test_disconnect_sets_not_connected(self):
        """断开后状态为未连接"""
        client = KlinesWebSocketClient()
        client._ws = AsyncMock()
        client._connected = True
        client._running = True

        await client.disconnect()
        assert client._connected is False
        assert client._running is False


class TestReconnect:
    """重连逻辑测试"""

    @pytest.mark.asyncio
    async def test_reconnect_not_running(self):
        """不运行时不重连"""
        client = KlinesWebSocketClient()
        client._running = False
        await client._reconnect()
        assert client._reconnect_count == 0

    @pytest.mark.asyncio
    async def test_reconnect_max_retries(self):
        """达到最大重连次数后停止"""
        client = KlinesWebSocketClient(max_reconnect=1)
        client._running = True
        client._reconnect_count = 1  # 已达到上限

        # mock connect 返回 False
        client.connect = AsyncMock(return_value=False)
        await client._reconnect()
        # 不应再增加（超过 max 直接 return）
        assert client._reconnect_count == 1

    @pytest.mark.asyncio
    async def test_reconnect_backoff_capped(self):
        """重连延迟指数退避且封顶 max_backoff"""
        client = KlinesWebSocketClient(
            reconnect_delay=1.0, max_reconnect=10, max_backoff=2.0
        )
        client._running = True
        client._reconnect_count = 9  # 下一次退避应为 1.0 * 2^9 → 封顶 2.0

        sleeps = []

        real_sleep = asyncio.sleep

        async def fake_sleep(t):
            sleeps.append(t)
            await real_sleep(0)

        client.connect = AsyncMock(return_value=False)
        with patch('data_manager.klines_ws_client.asyncio.sleep', side_effect=fake_sleep):
            await client._reconnect()
        # 第 10 次退避 = 1.0 * 2^9 = 512 → 封顶 2.0
        assert sleeps and sleeps[-1] == 2.0, f"退避未封顶: {sleeps}"
