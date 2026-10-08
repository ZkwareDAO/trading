"""
Signal Logging - 信号日志模块

负责信号的持久化、查询和统计

单体模式信号出口：存储（CSV）后由本进程直连交易所下单
（direct_trading，见 config/settings.yaml）。
历史上还有 signal_hub HTTP 推送 / Kafka 直推通道，均已移除。
"""

from .logger import SignalLogger, SignalStorage
from .storage import Signal, SignalType
from .csv_adapter import SignalCsvWriter, CtaSignalCSV
from .signal_params import build_signal_params
from .binance_trader import (
    BinanceApiError,
    BinanceCredentialsError,
    BinanceTrader,
    BinanceTraderConfig,
)

__all__ = [
    "SignalLogger",
    "SignalStorage",
    "Signal",
    "SignalType",
    "SignalCsvWriter",
    "CtaSignalCSV",
    "build_signal_params",
    "BinanceTrader",
    "BinanceTraderConfig",
    "BinanceCredentialsError",
    "BinanceApiError",
]
