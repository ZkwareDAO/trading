"""
Lifecycle Manager - 策略生命周期管理

管理策略的启动、停止、暂停、恢复等生命周期操作
"""

import logging
import importlib
from typing import Optional, Any, Dict

from .registry import StrategyRegistry, StrategyEntry, StrategyStatus

logger = logging.getLogger(__name__)


class LifecycleManager:
    """
    策略生命周期管理器

    负责策略实例的创建、初始化、启动、停止、暂停、恢复等操作
    """

    def __init__(self, registry: StrategyRegistry, engine: Any = None):
        """
        初始化生命周期管理器

        Args:
            registry: 策略注册表实例
            engine: 策略引擎实例（用于获取 factory_client）
        """
        self.registry = registry
        self.engine = engine

    def load_strategy_module(self, module_path: str, strategy_name: str) -> Optional[Any]:
        """
        动态加载策略模块

        Args:
            module_path: 模块路径（如 strategies.cta_ict.strategy）
            strategy_name: 策略名称

        Returns:
            策略类，如果加载失败返回 None
        """
        try:
            module = importlib.import_module(module_path)
            strategy_class = getattr(module, 'Strategy', None)

            if strategy_class is None:
                logger.error(f"策略类 'Strategy' 未在模块 {module_path} 中找到")
                return None

            return strategy_class

        except ImportError as e:
            logger.error(f"导入策略模块失败 {module_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"加载策略模块失败 {module_path}: {e}")
            return None

    def _create_factory_client(self) -> Optional[Any]:
        """
        创建 FactoryClient 实例用于远程仓位查询

        Returns:
            FactoryClient 实例，或 None（如果 engine 未配置）
        """
        if not self.engine:
            return None

        from strategy_core.factory_client import FactoryClient
        return FactoryClient(
            factory_endpoint=self.engine.factory_endpoint,
            position_proxy_url=self.engine.position_proxy_url,
        )

    def instantiate_strategy(
        self,
        entry: StrategyEntry,
        data_manager: Any,
        strategy_name: Optional[str] = None,
        trading_mode: str = "live",
    ) -> bool:
        """
        实例化策略

        Args:
            entry: 策略条目
            data_manager: 数据管理器实例
            strategy_name: 外部传入的标准化策略名称（可选）
            trading_mode: 运行模式 (live / paper_trading / smoking)

        Returns:
            是否成功实例化
        """
        try:
            # 加载策略类
            strategy_class = self.load_strategy_module(
                entry.module_path,
                entry.strategy_name
            )

            if strategy_class is None:
                self.registry.update_status(
                    entry.strategy_id,
                    StrategyStatus.ERROR,
                    f"无法加载策略类：{entry.module_path}"
                )
                return False

            # 实例化策略（信号存储由引擎统一处理）
            factory_client = self._create_factory_client()

            # 从配置中读取 user_id（用于远程仓位查询）
            user_id = entry.config.get("user_id", "")

            strategy = strategy_class(
                data_manager=data_manager,
                config=entry.config,
                strategy_name=strategy_name,
                trading_mode=trading_mode,
                factory_client=factory_client,
                user_id=user_id,
            )

            # 保存实例
            self.registry.set_instance(entry.strategy_id, strategy)
            logger.info(f"策略实例化成功：{entry.strategy_id} (mode={trading_mode})")
            return True

        except Exception as e:
            error_msg = f"实例化策略失败 {entry.strategy_id}: {e}"
            logger.error(error_msg)
            self.registry.update_status(
                entry.strategy_id,
                StrategyStatus.ERROR,
                error_msg
            )
            return False

    def start_strategy(self, strategy_id: str) -> bool:
        """
        启动策略

        Args:
            strategy_id: 策略 ID

        Returns:
            是否成功启动
        """
        entry = self.registry.get(strategy_id)
        if not entry:
            logger.error(f"策略不存在：{strategy_id}")
            return False

        if entry.status == StrategyStatus.RUNNING:
            logger.warning(f"策略已在运行：{strategy_id}")
            return True

        try:
            # 如果实例不存在，先实例化
            if entry.instance is None:
                logger.error(f"策略未实例化，无法启动：{strategy_id}")
                return False

            # 调用策略的 on_start 方法
            entry.instance.on_start()

            # 更新状态
            self.registry.update_status(strategy_id, StrategyStatus.RUNNING)
            logger.info(f"策略已启动：{strategy_id}")
            return True

        except Exception as e:
            error_msg = f"启动策略失败 {strategy_id}: {e}"
            logger.error(error_msg)
            self.registry.update_status(strategy_id, StrategyStatus.ERROR, error_msg)
            return False

    def stop_strategy(self, strategy_id: str) -> bool:
        """
        停止策略

        Args:
            strategy_id: 策略 ID

        Returns:
            是否成功停止
        """
        entry = self.registry.get(strategy_id)
        if not entry:
            logger.error(f"策略不存在：{strategy_id}")
            return False

        if entry.status == StrategyStatus.STOPPED:
            logger.info(f"策略已停止：{strategy_id}")
            return True

        try:
            # 调用策略的 on_stop 方法
            if entry.instance:
                entry.instance.on_stop()

            # 更新状态
            self.registry.update_status(strategy_id, StrategyStatus.STOPPED)
            logger.info(f"策略已停止：{strategy_id}")
            return True

        except Exception as e:
            error_msg = f"停止策略失败 {strategy_id}: {e}"
            logger.error(error_msg)
            self.registry.update_status(strategy_id, StrategyStatus.ERROR, error_msg)
            return False

    def pause_strategy(self, strategy_id: str) -> bool:
        """
        暂停策略

        Args:
            strategy_id: 策略 ID

        Returns:
            是否成功暂停
        """
        entry = self.registry.get(strategy_id)
        if not entry:
            logger.error(f"策略不存在：{strategy_id}")
            return False

        if entry.status != StrategyStatus.RUNNING:
            logger.warning(f"策略不在运行状态，无法暂停：{strategy_id}")
            return False

        try:
            # 调用策略的 on_pause 方法（如果实现）
            if entry.instance and hasattr(entry.instance, 'on_pause'):
                entry.instance.on_pause()

            # 更新状态
            self.registry.update_status(strategy_id, StrategyStatus.PAUSED)
            logger.info(f"策略已暂停：{strategy_id}")
            return True

        except Exception as e:
            error_msg = f"暂停策略失败 {strategy_id}: {e}"
            logger.error(error_msg)
            self.registry.update_status(strategy_id, StrategyStatus.ERROR, error_msg)
            return False

    def resume_strategy(self, strategy_id: str) -> bool:
        """
        恢复策略

        Args:
            strategy_id: 策略 ID

        Returns:
            是否成功恢复
        """
        entry = self.registry.get(strategy_id)
        if not entry:
            logger.error(f"策略不存在：{strategy_id}")
            return False

        if entry.status != StrategyStatus.PAUSED:
            logger.warning(f"策略不在暂停状态，无法恢复：{strategy_id}")
            return False

        try:
            # 调用策略的 on_resume 方法（如果实现）
            if entry.instance and hasattr(entry.instance, 'on_resume'):
                entry.instance.on_resume()

            # 更新状态
            self.registry.update_status(strategy_id, StrategyStatus.RUNNING)
            logger.info(f"策略已恢复：{strategy_id}")
            return True

        except Exception as e:
            error_msg = f"恢复策略失败 {strategy_id}: {e}"
            logger.error(error_msg)
            self.registry.update_status(strategy_id, StrategyStatus.ERROR, error_msg)
            return False

    def get_strategy_status(self, strategy_id: str) -> Optional[Dict]:
        """
        获取策略状态

        Args:
            strategy_id: 策略 ID

        Returns:
            策略状态信息
        """
        entry = self.registry.get(strategy_id)
        if not entry:
            return None

        status_info = entry.to_dict()

        # 如果策略实例存在，获取详细状态
        if entry.instance and hasattr(entry.instance, 'get_status'):
            try:
                status_info['detailed_status'] = entry.instance.get_status()
            except Exception as e:
                logger.warning(f"获取策略详细状态失败 {strategy_id}: {e}")

        return status_info
