"""
策略注册表

管理已注册策略的元数据和实例
"""

import logging
import threading
from typing import Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class StrategyStatus(Enum):
    """策略状态枚举"""
    PENDING = "pending"       # 待启动
    RUNNING = "running"       # 运行中
    PAUSED = "paused"         # 已暂停
    STOPPED = "stopped"       # 已停止
    ERROR = "error"           # 错误状态


@dataclass
class StrategyEntry:
    """策略注册条目"""
    strategy_id: str
    strategy_name: str
    module_path: str
    config: Dict[str, Any]
    status: StrategyStatus = StrategyStatus.PENDING
    instance: Any = None  # 策略实例
    created_at: datetime = field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    stopped_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "module_path": self.module_path,
            "config": self.config,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
            "error_message": self.error_message,
            "metadata": self.metadata
        }


class StrategyRegistry:
    """
    策略注册表

    管理所有已注册策略的元数据和实例
    """

    def __init__(self) -> None:
        self._entries: Dict[str, StrategyEntry] = {}
        self._lock = threading.Lock()

    def register(
        self,
        strategy_id: str,
        strategy_name: str,
        module_path: str,
        config: Dict[str, Any]
    ) -> StrategyEntry:
        """
        注册策略

        Args:
            strategy_id: 策略唯一 ID
            strategy_name: 策略名称
            module_path: 策略模块路径
            config: 策略配置

        Returns:
            策略条目
        """
        if strategy_id in self._entries:
            logger.warning(f"策略 {strategy_id} 已存在，将更新注册信息")

        entry = StrategyEntry(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            module_path=module_path,
            config=config
        )
        with self._lock:
            self._entries[strategy_id] = entry
        logger.info(f"策略已注册：{strategy_id} ({strategy_name})")
        return entry

    def unregister(self, strategy_id: str) -> bool:
        """
        注销策略

        Args:
            strategy_id: 策略 ID

        Returns:
            是否成功注销
        """
        with self._lock:
            if strategy_id in self._entries:
                del self._entries[strategy_id]
                logger.info(f"策略已注销：{strategy_id}")
                return True
        logger.warning(f"策略不存在，无法注销：{strategy_id}")
        return False

    def get(self, strategy_id: str) -> Optional[StrategyEntry]:
        """获取策略条目"""
        with self._lock:
            return self._entries.get(strategy_id)

    def get_instance(self, strategy_id: str) -> Any:
        """获取策略实例"""
        with self._lock:
            entry = self._entries.get(strategy_id)
            return entry.instance if entry else None

    def set_instance(self, strategy_id: str, instance: Any):
        """设置策略实例"""
        with self._lock:
            entry = self._entries.get(strategy_id)
            if entry:
                entry.instance = instance
            else:
                logger.warning(f"策略不存在，无法设置实例：{strategy_id}")

    def update_status(
        self,
        strategy_id: str,
        status: StrategyStatus,
        error_message: Optional[str] = None
    ):
        """更新策略状态"""
        with self._lock:
            entry = self._entries.get(strategy_id)
            if entry:
                entry.status = status
                entry.error_message = error_message
                if status == StrategyStatus.RUNNING:
                    entry.started_at = datetime.now()
                elif status in (StrategyStatus.STOPPED, StrategyStatus.ERROR):
                    entry.stopped_at = datetime.now()

    def list_strategies(self) -> Dict[str, StrategyEntry]:
        """列出所有策略"""
        with self._lock:
            return dict(self._entries)

    def get_running_strategies(self) -> Dict[str, StrategyEntry]:
        """获取所有运行中的策略"""
        with self._lock:
            return {
                k: v for k, v in self._entries.items()
                if v.status == StrategyStatus.RUNNING
            }

    def count(self) -> int:
        """获取注册策略数量"""
        with self._lock:
            return len(self._entries)

    def clear(self):
        """清空注册表"""
        with self._lock:
            self._entries.clear()
        logger.info("策略注册表已清空")
