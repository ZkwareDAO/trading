"""
OpenViking 交易数据同步模块

将 CTA 策略系统的交易数据同步到 OpenViking 上下文数据库。

配置文件: config/openviking_sync.yaml

支持的数据类型:
- 信号 (signals)
- 回测结果 (backtest)
- 持仓状态 (positions)
- 历史仓位 (history_positions)
- 自定义源 (通过配置添加)

使用方式:
    # CLI
    python -m strategy_core.openviking_sync sync --today
    python -m strategy_core.openviking_sync sync --today --source signals,positions
    python -m strategy_core.openviking_sync list-syncers
    python -m strategy_core.openviking_sync status

    # 编程方式
    from strategy_core.openviking_sync import TradingDataSyncService

    service = TradingDataSyncService.from_config_file()
    result = service.sync_daily()
"""

from .ov_client import OpenVikingClient, OpenVikingConfig, OpenVikingError
from .base_sync import BaseSyncer, SyncResult
from .sync_service import TradingDataSyncService, SyncConfig, DailySyncResult
from .universal_syncer import UniversalSyncer, UniversalSyncResult
from .formatter import SignalFormatter, CsvFormatter

__all__ = [
    # 客户端
    "OpenVikingClient",
    "OpenVikingConfig",
    "OpenVikingError",
    # 基类
    "BaseSyncer",
    "SyncResult",
    # 同步服务
    "TradingDataSyncService",
    "SyncConfig",
    "DailySyncResult",
    # 统一同步器
    "UniversalSyncer",
    "UniversalSyncResult",
    # 格式化器
    "SignalFormatter",
    "CsvFormatter",
]