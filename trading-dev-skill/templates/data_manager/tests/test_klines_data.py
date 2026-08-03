#!/usr/bin/env python3
"""
Kline 数据类测试

测试共享的 Kline 数据类的解析和序列化功能。
"""

from datetime import datetime, timezone
from data_manager.klines_data import Kline


class TestKlineCreation:
    """测试 Kline 创建"""

    def test_default_values(self):
        """测试默认值初始化"""
        ts = datetime(2024, 4, 8, 0, 0, tzinfo=timezone.utc)
        kline = Kline(symbol="BTCUSDT", interval="1m", timestamp=ts)

        assert kline.symbol == "BTCUSDT"
        assert kline.interval == "1m"
        assert kline.timestamp == ts
        assert kline.open == 0.0
        assert kline.high == 0.0
        assert kline.low == 0.0
        assert kline.close == 0.0
        assert kline.volume == 0.0
        assert kline.quote_volume == 0.0
        assert kline.trade_num == 0
        assert kline.is_final is True

    def test_custom_values(self):
        """测试自定义值初始化"""
        ts = datetime(2024, 4, 8, 12, 0, tzinfo=timezone.utc)
        kline = Kline(
            symbol="ETHUSDT", interval="15m", timestamp=ts,
            open=3000.0, high=3050.0, low=2980.0, close=3020.0,
            volume=100.5, quote_volume=302000.0, trade_num=500,
            active_buy_volume=60.0, active_buy_quote_volume=180000.0,
            is_final=False
        )

        assert kline.symbol == "ETHUSDT"
        assert kline.interval == "15m"
        assert kline.open == 3000.0
        assert kline.high == 3050.0
        assert kline.low == 2980.0
        assert kline.close == 3020.0
        assert kline.volume == 100.5
        assert kline.quote_volume == 302000.0
        assert kline.trade_num == 500
        assert kline.active_buy_volume == 60.0
        assert kline.active_buy_quote_volume == 180000.0
        assert kline.is_final is False


class TestKlineFromBinanceFormat:
    """测试从 Binance API 格式解析"""

    def test_parse_binance_kline(self):
        """测试解析 Binance K 线数据"""
        data = [
            1712548800000,   # open_time (毫秒)
            "50000.0",       # open
            "50100.0",       # high
            "49900.0",       # low
            "50050.0",       # close
            "100.5",         # volume
            1712548860000,   # close_time
            "5025000.0",     # quote_volume
            1234,            # count
            "50.25",         # taker_buy_base
            "2512500.0",     # taker_buy_quote
            "0"              # ignore
        ]

        kline = Kline.from_binance_format(data, "BTCUSDT", "1m")

        assert kline.symbol == "BTCUSDT"
        assert kline.interval == "1m"
        assert kline.open == 50000.0
        assert kline.high == 50100.0
        assert kline.low == 49900.0
        assert kline.close == 50050.0
        assert kline.volume == 100.5
        assert kline.quote_volume == 5025000.0
        assert kline.trade_num == 1234
        assert kline.active_buy_volume == 50.25
        assert kline.active_buy_quote_volume == 2512500.0
        assert kline.is_final is True

        expected_ts = datetime.fromtimestamp(1712548800000 / 1000, tz=timezone.utc)
        assert kline.timestamp == expected_ts

    def test_parse_binance_kline_string_timestamp(self):
        """测试解析字符串时间戳"""
        data = [
            "1712548800000",  # open_time as string
            "50000.0", "50100.0", "49900.0", "50050.0",
            "100.5", 1712548860000, "5025000.0",
            1234, "50.25", "2512500.0", "0"
        ]

        kline = Kline.from_binance_format(data, "ETHUSDT", "15m")

        assert kline.symbol == "ETHUSDT"
        assert kline.interval == "15m"
        assert kline.open == 50000.0


class TestKlineFromDict:
    """测试从字典解析"""

    def test_from_dict_millisecond_timestamp(self):
        """测试毫秒时间戳解析"""
        data = {
            'symbol': 'BTCUSDT',
            'interval': '1m',
            'timestamp': 1712548800000,
            'open': 50000.0,
            'high': 50100.0,
            'low': 49900.0,
            'close': 50050.0,
            'volume': 100.5,
            'quote_volume': 5025000.0,
            'trade_num': 1234,
            'active_buy_volume': 50.25,
            'active_buy_quote_volume': 2512500.0,
            'is_final': False
        }

        kline = Kline.from_dict(data)

        assert kline.symbol == "BTCUSDT"
        assert kline.interval == "1m"
        assert kline.open == 50000.0
        assert kline.is_final is False

    def test_from_dict_second_timestamp(self):
        """测试秒时间戳解析"""
        data = {
            'symbol': 'ETHUSDT',
            'interval': '15m',
            'timestamp': 1712548800,  # 秒
            'open': 3000.0,
            'high': 3050.0,
            'low': 2980.0,
            'close': 3020.0,
            'volume': 100.5,
            'quote_volume': 302000.0,
            'trade_num': 500,
            'active_buy_volume': 60.0,
            'active_buy_quote_volume': 180000.0,
            'is_final': True
        }

        kline = Kline.from_dict(data)

        expected_ts = datetime.fromtimestamp(1712548800, tz=timezone.utc)
        assert kline.timestamp == expected_ts

    def test_from_dict_iso_string_timestamp(self):
        """测试 ISO 字符串时间戳解析"""
        data = {
            'symbol': 'BTCUSDT',
            'interval': '1h',
            'timestamp': '2024-04-08T12:00:00+00:00',
            'open': 50000.0, 'high': 50100.0, 'low': 49900.0, 'close': 50050.0,
            'volume': 100.5, 'quote_volume': 5025000.0, 'trade_num': 1234,
            'active_buy_volume': 50.25, 'active_buy_quote_volume': 2512500.0,
        }

        kline = Kline.from_dict(data)

        assert kline.symbol == "BTCUSDT"
        assert kline.interval == "1h"

    def test_from_dict_z_timestamp(self):
        """测试 Z 后缀时间戳"""
        data = {
            'timestamp': '2024-04-08T12:00:00Z',
            'open': 50000.0, 'high': 50100.0, 'low': 49900.0, 'close': 50050.0,
            'volume': 100.5, 'quote_volume': 5025000.0, 'trade_num': 1234,
            'active_buy_volume': 50.25, 'active_buy_quote_volume': 2512500.0,
        }

        kline = Kline.from_dict(data)

        assert kline.timestamp.tzinfo == timezone.utc

    def test_from_dict_start_time_fallback(self):
        """测试 start_time 字段回退"""
        data = {
            'start_time': 1712548800000,
            'symbol': 'BTCUSDT',
            'open': 50000.0, 'high': 50100.0, 'low': 49900.0, 'close': 50050.0,
            'volume': 100.5, 'quote_volume': 5025000.0, 'trade_num': 1234,
            'active_buy_volume': 50.25, 'active_buy_quote_volume': 2512500.0,
        }

        kline = Kline.from_dict(data)

        expected_ts = datetime.fromtimestamp(1712548800000 / 1000, tz=timezone.utc)
        assert kline.timestamp == expected_ts

    def test_from_dict_websocket_format_start_time_takes_priority(self):
        """
        WebSocket 推送数据中 timestamp 为零值，start_time 才是有效值。
        start_time 应优先于无效的 timestamp 被使用。

        实际 WebSocket 推送格式:
        {
            "symbol": "BTCUSDT",
            "timestamp": "0001-01-01T00:00:00Z",  // 无效
            "start_time": 1775805720000,            // 有效毫秒时间戳
            ...
        }
        """
        data = {
            'symbol': 'BTCUSDT',
            'interval': '1m',
            'timestamp': '0001-01-01T00:00:00Z',
            'start_time': 1775805720000,
            'open': '71712.00',
            'high': '71726.40',
            'low': '71711.20',
            'close': '71711.20',
            'volume': '34.082',
            'is_final': True,
            'quote_volume': '2444255.35410',
            'trade_num': 975,
            'active_buy_volume': '20.222',
            'active_buy_quote_volume': '1450253.97240',
        }

        kline = Kline.from_dict(data)

        # 应使用 start_time 解析，而不是无效的 "0001-01-01T00:00:00Z"
        expected_ts = datetime.fromtimestamp(1775805720000 / 1000, tz=timezone.utc)
        assert kline.timestamp == expected_ts, \
            f"时间戳应为 {expected_ts.isoformat()}，实际为 {kline.timestamp.isoformat()}"
        assert kline.close == 71711.20
        assert kline.symbol == "BTCUSDT"

    def test_from_dict_defaults(self):
        """测试缺失字段的默认值"""
        data = {}
        kline = Kline.from_dict(data)

        assert kline.symbol == ""
        assert kline.interval == "1m"
        assert kline.open == 0.0
        assert kline.is_final is True


class TestKlineToDict:
    """测试转换为字典"""

    def test_to_dict(self):
        """测试 to_dict 序列化"""
        ts = datetime(2024, 4, 8, 12, 0, tzinfo=timezone.utc)
        kline = Kline(
            symbol="BTCUSDT", interval="1m", timestamp=ts,
            open=50000.0, high=50100.0, low=49900.0, close=50050.0,
            volume=100.5, quote_volume=5025000.0, trade_num=1234,
            active_buy_volume=50.25, active_buy_quote_volume=2512500.0,
            is_final=True
        )

        result = kline.to_dict()

        assert result['symbol'] == "BTCUSDT"
        assert result['interval'] == "1m"
        assert result['timestamp'] == 1712577600000  # 毫秒
        assert result['open'] == 50000.0
        assert result['high'] == 50100.0
        assert result['low'] == 49900.0
        assert result['close'] == 50050.0
        assert result['volume'] == 100.5
        assert result['quote_volume'] == 5025000.0
        assert result['trade_num'] == 1234
        assert result['active_buy_volume'] == 50.25
        assert result['active_buy_quote_volume'] == 2512500.0
        assert result['is_final'] is True


class TestKlineRepr:
    """测试字符串表示"""

    def test_repr(self):
        """测试 __repr__"""
        ts = datetime(2024, 4, 8, 12, 0, tzinfo=timezone.utc)
        kline = Kline(
            symbol="BTCUSDT", interval="1m", timestamp=ts,
            open=50000.0, high=50100.0, low=49900.0, close=50050.0,
            volume=100.5
        )

        repr_str = repr(kline)

        assert "BTCUSDT" in repr_str
        assert "1m" in repr_str
        assert "50000.0" in repr_str
        assert "2024-04-08" in repr_str
