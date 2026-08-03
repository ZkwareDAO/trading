"""
Data Manager - 数据管理器

提供统一的本地数据接入层，从 CSV 文件加载 K 线数据
并提供技术指标计算功能
"""

from .manager import DataManager, DataManagerConfig, DataCache
from .cache import ShardCache, ShardCacheConfig
from .klines_data import Kline
from .klines_ws_client import KlinesWebSocketClient
from .kafka_consumer import KlineKafkaConsumer
from .klines_loader import (
    load_klines_data,
    resample_ohlcv,
    save_to_csv,
)

__all__ = [
    "DataManager",
    "DataManagerConfig",
    "DataCache",
    "ShardCache",
    "ShardCacheConfig",
    "Kline",
    "KlinesWebSocketClient",
    "KlineKafkaConsumer",
    "load_klines_data",
    "resample_ohlcv",
    "save_to_csv",
]
