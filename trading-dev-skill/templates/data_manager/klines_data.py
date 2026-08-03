#!/usr/bin/env python3
"""
K 线数据共享模块

提供统一的 Kline 数据类和解析方法，供 HTTP 客户端、WebSocket 客户端
和 DataManager 共享使用。
"""

from datetime import datetime, timezone
from typing import List, Dict, Any

import pandas as pd


class Kline:
    """
    K 线数据类

    Attributes:
        symbol: 交易对
        interval: K 线周期
        timestamp: 时间戳
        open: 开盘价
        high: 最高价
        low: 最低价
        close: 收盘价
        volume: 成交量
        quote_volume: 成交额
        trade_num: 成交笔数
        active_buy_volume: 主动买入成交量
        active_buy_quote_volume: 主动买入成交额
        is_final: 是否完成
    """
    __slots__ = [
        'symbol', 'interval', 'timestamp', 'open', 'high', 'low',
        'close', 'volume', 'quote_volume', 'trade_num',
        'active_buy_volume', 'active_buy_quote_volume', 'is_final'
    ]

    def __init__(
        self,
        symbol: str,
        interval: str,
        timestamp: datetime,
        open: float = 0.0,
        high: float = 0.0,
        low: float = 0.0,
        close: float = 0.0,
        volume: float = 0.0,
        quote_volume: float = 0.0,
        trade_num: int = 0,
        active_buy_volume: float = 0.0,
        active_buy_quote_volume: float = 0.0,
        is_final: bool = True
    ):
        self.symbol = symbol
        self.interval = interval
        self.timestamp = timestamp
        self.open = open
        self.high = high
        self.low = low
        self.close = close
        self.volume = volume
        self.quote_volume = quote_volume
        self.trade_num = trade_num
        self.active_buy_volume = active_buy_volume
        self.active_buy_quote_volume = active_buy_quote_volume
        self.is_final = is_final

    @classmethod
    def from_binance_format(cls, data: List, symbol: str, interval: str) -> 'Kline':
        """
        从 Binance API 格式创建 Kline 对象

        Binance API 格式：
        [
            1712548800000,  # 0: open_time (毫秒)
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
        """
        open_time = data[0]
        if isinstance(open_time, (int, float)):
            timestamp = datetime.fromtimestamp(open_time / 1000, tz=timezone.utc)
        elif isinstance(open_time, str):
            timestamp = datetime.fromtimestamp(int(open_time) / 1000, tz=timezone.utc)
        else:
            timestamp = datetime.now(tz=timezone.utc)

        return cls(
            symbol=symbol,
            interval=interval,
            timestamp=timestamp,
            open=float(data[1]),
            high=float(data[2]),
            low=float(data[3]),
            close=float(data[4]),
            volume=float(data[5]),
            quote_volume=float(data[7]),
            trade_num=int(data[8]),
            active_buy_volume=float(data[9]),
            active_buy_quote_volume=float(data[10]),
            is_final=True
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Kline':
        """从字典创建 Kline 对象"""
        import math

        ts = data.get('start_time') or data.get('timestamp')

        if isinstance(ts, (int, float)):
            if ts > 1e12:
                timestamp = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
            else:
                timestamp = datetime.fromtimestamp(ts, tz=timezone.utc)
        elif isinstance(ts, str):
            ts_clean = ts.replace('+00:00', '').replace('Z', '').strip()
            timestamp = datetime.fromisoformat(ts_clean)
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        elif isinstance(ts, pd.Timestamp):
            timestamp = ts.to_pydatetime()
        elif isinstance(ts, datetime):
            timestamp = ts
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)

        def _safe_float(val, default=0.0) -> float:
            if val is None:
                return default
            f = float(val)
            return f if math.isfinite(f) else default

        def _safe_int(val, default=0) -> int:
            if val is None:
                return default
            f = float(val)
            return int(f) if math.isfinite(f) else default

        return cls(
            symbol=data.get('symbol', ''),
            interval=data.get('interval', '1m'),
            timestamp=timestamp,
            open=_safe_float(data.get('open', 0.0)),
            high=_safe_float(data.get('high', 0.0)),
            low=_safe_float(data.get('low', 0.0)),
            close=_safe_float(data.get('close', 0.0)),
            volume=_safe_float(data.get('volume', 0.0)),
            quote_volume=_safe_float(data.get('quote_volume', 0.0)),
            trade_num=_safe_int(data.get('trade_num', 0)),
            active_buy_volume=_safe_float(data.get('active_buy_volume', 0.0)),
            active_buy_quote_volume=_safe_float(data.get('active_buy_quote_volume', 0.0)),
            is_final=bool(data.get('is_final', True))
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'symbol': self.symbol,
            'interval': self.interval,
            'timestamp': self.timestamp.timestamp() * 1000,
            'open': self.open,
            'high': self.high,
            'low': self.low,
            'close': self.close,
            'volume': self.volume,
            'quote_volume': self.quote_volume,
            'trade_num': self.trade_num,
            'active_buy_volume': self.active_buy_volume,
            'active_buy_quote_volume': self.active_buy_quote_volume,
            'is_final': self.is_final
        }

    def __repr__(self) -> str:
        return (
            f"Kline({self.symbol}, {self.interval}, "
            f"O={self.open}, H={self.high}, L={self.low}, C={self.close}, "
            f"@{self.timestamp.isoformat()})"
        )
