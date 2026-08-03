"""
Strategy Core - 量化交易策略核心框架
"""

from .strategy_engine import StrategyEngine
from .signal_logging import SignalLogger

__version__ = "1.0.0"
__all__ = ["StrategyEngine", "SignalLogger"]
