"""技术指标模块"""

from typing import Dict, Type

from .base import BaseIndicator
from .obv import OBVIndicator
from .adx import ADXIndicator
from .atr import ATRIndicator
from .fvg import FVGIndicator
from .rsi import RSIndicator
from .macd import MACDIndicator
from .bollinger import BollingerBandsIndicator
from .swing import SwingIndicator

# 指标注册表
INDICATOR_REGISTRY: Dict[str, Type[BaseIndicator]] = {
    "OBV": OBVIndicator,
    "ADX": ADXIndicator,
    "ATR": ATRIndicator,
    "FVG": FVGIndicator,
    "RSI": RSIndicator,
    "MACD": MACDIndicator,
    "BB": BollingerBandsIndicator,
    "Swing": SwingIndicator,
}


def get_indicator(name: str, **params) -> BaseIndicator:
    """获取指标实例"""
    if name not in INDICATOR_REGISTRY:
        raise ValueError(f"未知指标: {name}, 可用: {list(INDICATOR_REGISTRY.keys())}")
    return INDICATOR_REGISTRY[name](**params)


def list_indicators() -> list:
    """列出所有可用指标"""
    return list(INDICATOR_REGISTRY.keys())


__all__ = [
    "BaseIndicator",
    "OBVIndicator",
    "ADXIndicator",
    "ATRIndicator",
    "FVGIndicator",
    "RSIndicator",
    "MACDIndicator",
    "BollingerBandsIndicator",
    "INDICATOR_REGISTRY",
    "get_indicator",
    "list_indicators",
]