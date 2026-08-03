"""
同步器基类

定义同步器的通用接口和结果类型。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Dict, Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .ov_client import OpenVikingClient


@dataclass
class SyncResult:
    """同步结果基类"""
    success: bool = False
    source_type: str = ""  # signal, backtest, position, history_position, custom
    source_name: str = ""  # 配置中的 key
    uri: str = ""
    items_count: int = 0
    error: Optional[str] = None


class BaseSyncer(ABC):
    """同步器基类"""

    def __init__(
        self,
        source_name: str,
        config: Dict[str, Any],
        ov_client: "OpenVikingClient",
    ):
        """
        初始化同步器

        Args:
            source_name: 同步源名称（配置中的 key）
            config: 同步源配置
            ov_client: OpenViking 客户端
        """
        self.source_name = source_name
        self.config = config
        self.ov_client = ov_client

    @abstractmethod
    def sync_daily(
        self,
        date: datetime,
        strategy_names: Optional[List[str]] = None,
        account: str = "",
    ) -> List[SyncResult]:
        """
        同步指定日期的数据

        Args:
            date: 日期
            strategy_names: 策略名称列表，为 None 时同步所有
            account: 账户名

        Returns:
            同步结果列表
        """
        pass

    @abstractmethod
    def discover_sources(self, date: datetime) -> List[str]:
        """
        发现可同步的数据源

        Args:
            date: 日期

        Returns:
            数据源标识列表（如策略名称、文件名等）
        """
        pass

    def _generate_uri_prefix(self, date: datetime, account: str = "") -> str:
        """
        生成 URI 前缀

        格式: viking://resources/{account}/trading_data/{year}/{month}/{day}/

        Args:
            date: 日期
            account: 账户名

        Returns:
            URI 前缀
        """
        from .ov_client import OpenVikingClient
        return OpenVikingClient.generate_daily_uri(date, account)
