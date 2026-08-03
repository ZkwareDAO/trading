"""
Signal - 信号数据模型

定义交易信号的数据结构
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
import uuid


def generate_signal_id(
    strategy_type: str,
    symbol: str,
    kline_timestamp: datetime,
    signal_type: str,
) -> str:
    """
    生成确定性 signal_id

    基于 1m K线时间戳 + 策略 + 标的 + 信号类型生成唯一 ID。
    实盘和回测使用相同 K线数据时，生成的 ID 相同。

    Args:
        strategy_type: 策略类型 (如 "rbreaker")
        symbol: 交易标的 (如 "BTCUSDT")
        kline_timestamp: 1m K线的时间戳 (来自 Signal.timestamp)
        signal_type: 信号类型 (buy/sell/buy_close/sell_close)

    Returns:
        格式为 "sig_{16位hash}" 的确定性 ID
    """
    # 使用 1m K线的时间戳（毫秒）
    ts_ms = int(kline_timestamp.timestamp() * 1000)
    # 组合因子（大小写不敏感）
    key = f"{strategy_type.lower()}_{symbol.upper()}_{ts_ms}_{signal_type.lower()}"
    # 使用 SHA256 生成短 ID（16 字符）
    hash_val = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"sig_{hash_val}"


class SignalType(Enum):
    """信号类型"""
    BUY = "buy"           # 买入
    SELL = "sell"         # 卖出
    FLAT = "flat"         # 平仓
    BUY_CLOSE = "buy_close"       # 买入平仓（空头）
    SELL_CLOSE = "sell_close"     # 卖出平仓（多头）
    REVERSE_LONG = "reverse_long"  # 反手做多
    REVERSE_SHORT = "reverse_short"  # 反手做空


@dataclass
class Signal:
    """
    交易信号

    Attributes:
        signal_id: 信号唯一 ID（自动生成或手动指定）
        strategy_id: 策略 ID（完整名称，如 RBreakerv2_1m_BTCUSDT）
        strategy_type: 策略类型（如 cta_rbreaker），用于生成确定性 ID
        signal_type: 信号类型
        symbol: 交易标的
        price: 信号价格
        volume: 交易数量
        timestamp: 信号时间
        strength: 信号强度 (0-1)
        metadata: 附加元数据
    """
    strategy_id: str
    signal_type: SignalType
    symbol: str
    price: float
    timestamp: datetime = field(default_factory=datetime.now)
    signal_id: str = ""
    strategy_type: Optional[str] = None  # 用于生成确定性 ID
    volume: float = 0.0
    strength: float = 0.0
    direction: Optional[str] = None  # long/short
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """初始化后处理：自动生成 signal_id"""
        if not self.signal_id:
            if self.strategy_type:
                # 有 strategy_type 时，生成确定性 ID
                self.signal_id = generate_signal_id(
                    strategy_type=self.strategy_type,
                    symbol=self.symbol,
                    kline_timestamp=self.timestamp,
                    signal_type=self.signal_type.value,
                )
            else:
                # 向后兼容：使用随机 UUID
                self.signal_id = str(uuid.uuid4())

    @classmethod
    def buy(
        cls,
        symbol: str,
        price: float,
        strategy_id: str = "unknown",
        strategy_type: Optional[str] = None,
        volume: float = 0.0,
        strength: float = 1.0,
        timestamp: Optional[datetime] = None,
        **kwargs
    ) -> 'Signal':
        """创建买入信号"""
        return cls(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            signal_type=SignalType.BUY,
            symbol=symbol,
            price=price,
            volume=volume,
            strength=strength,
            direction="long",
            timestamp=timestamp if timestamp is not None else datetime.now(),
            metadata=kwargs
        )

    @classmethod
    def sell(
        cls,
        symbol: str,
        price: float,
        strategy_id: str = "unknown",
        strategy_type: Optional[str] = None,
        volume: float = 0.0,
        strength: float = 1.0,
        timestamp: Optional[datetime] = None,
        **kwargs
    ) -> 'Signal':
        """创建卖出信号"""
        return cls(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            signal_type=SignalType.SELL,
            symbol=symbol,
            price=price,
            volume=volume,
            strength=strength,
            direction="short",
            timestamp=timestamp if timestamp is not None else datetime.now(),
            metadata=kwargs
        )

    @classmethod
    def flat(
        cls,
        symbol: str,
        price: float,
        strategy_id: str = "unknown",
        strategy_type: Optional[str] = None,
        timestamp: Optional[datetime] = None,
        **kwargs
    ) -> 'Signal':
        """创建平仓信号"""
        return cls(
            strategy_id=strategy_id,
            strategy_type=strategy_type,
            signal_type=SignalType.FLAT,
            symbol=symbol,
            price=price,
            timestamp=timestamp if timestamp is not None else datetime.now(),
            metadata=kwargs
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "signal_id": self.signal_id,
            "strategy_id": self.strategy_id,
            "strategy_type": self.strategy_type,
            "signal_type": self.signal_type.value,
            "symbol": self.symbol,
            "price": self.price,
            "volume": self.volume,
            "direction": self.direction,
            "strength": self.strength,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Signal':
        """从字典创建 Signal"""
        ts = data.get('timestamp')
        if isinstance(ts, str):
            timestamp = datetime.fromisoformat(ts)
        else:
            timestamp = datetime.now()

        return cls(
            signal_id=data.get('signal_id', ''),
            strategy_id=data.get('strategy_id', 'unknown'),
            strategy_type=data.get('strategy_type'),
            signal_type=SignalType(data.get('signal_type', 'buy')),
            symbol=data.get('symbol', 'UNKNOWN'),
            price=float(data.get('price', 0)),
            volume=float(data.get('volume', 0)),
            strength=float(data.get('strength', 0)),
            direction=data.get('direction'),
            timestamp=timestamp,
            metadata=data.get('metadata', {})
        )

    def to_row(self) -> Dict[str, Any]:
        """转换为 CSV 行数据"""
        return {
            "signal_id": self.signal_id,
            "strategy_id": self.strategy_id,
            "strategy_type": self.strategy_type or "",
            "signal_type": self.signal_type.value,
            "symbol": self.symbol,
            "price": self.price,
            "volume": self.volume,
            "direction": self.direction or "",
            "strength": self.strength,
            "timestamp": self.timestamp.isoformat(),
            "metadata": str(self.metadata)
        }

    @classmethod
    def from_row(cls, row: Dict[str, str]) -> 'Signal':
        """从 CSV 行创建 Signal"""
        try:
            import ast
            metadata = ast.literal_eval(row.get('metadata', '{}'))
        except (ValueError, SyntaxError):
            metadata = {}

        ts_str = row.get('timestamp', datetime.now().isoformat())
        try:
            timestamp = datetime.fromisoformat(ts_str)
        except ValueError:
            timestamp = datetime.now()

        # 解析 strategy_type
        strategy_type_raw = row.get('strategy_type')
        strategy_type = strategy_type_raw if strategy_type_raw and strategy_type_raw.strip() else None

        return cls(
            signal_id=row.get('signal_id', ''),
            strategy_id=row.get('strategy_id', 'unknown'),
            strategy_type=strategy_type,
            signal_type=SignalType(row.get('signal_type', 'buy')),
            symbol=row.get('symbol', 'UNKNOWN'),
            price=float(row.get('price', 0)),
            volume=float(row.get('volume', 0)),
            strength=float(row.get('strength', 0)),
            direction=row.get('direction') or None,
            timestamp=timestamp,
            metadata=metadata
        )

    def __str__(self) -> str:
        return (
            f"Signal({self.signal_id}, {self.strategy_id}, "
            f"{self.signal_type.value} {self.symbol} @ {self.price})"
        )
