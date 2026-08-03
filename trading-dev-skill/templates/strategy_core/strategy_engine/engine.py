"""
Strategy Engine - 策略引擎核心实现

统一管理所有策略的生命周期，处理与 cta-factory-service 的通信
"""

import logging
# 应用 defusedxml 补丁以防止 XML 外部实体攻击 (XXE)
from defusedxml.xmlrpc import monkey_patch
monkey_patch()

# nosec B411 - defusedxml monkey_patch applied above
import xmlrpc.client  # nosec B411
from xmlrpc.client import ServerProxy  # nosec B411
from typing import Dict, Optional, Any, List
from pathlib import Path

from .registry import StrategyRegistry, StrategyStatus
from .lifecycle import LifecycleManager
from ..constants import (
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TRAILING_PROFIT_ACTIVATION,
    DEFAULT_TRAILING_PROFIT_DRAWDOWN,
)

logger = logging.getLogger(__name__)


class StrategyEngine:
    """
    策略引擎

    功能:
    - 发现并加载 strategies/ 目录下的所有策略子模块
    - 注册到 cta-factory-service
    - 统一处理启停/暂停/恢复指令
    - 分发数据更新事件到各策略
    """

    def __init__(
        self,
        factory_endpoint: str = "http://127.0.0.1:8888",
        position_proxy_url: str = "http://127.0.0.1:8889",
        strategies_dir: str = "./strategies",
        data_manager: Any = None,
        signal_logger: Any = None,
        csv_writer: Any = None
    ):
        """
        初始化策略引擎

        Args:
            factory_endpoint: cta-factory-service 的 RPC 端点
            position_proxy_url: Position 代理端点（端口 8889）
            strategies_dir: 策略子模块目录
            data_manager: 数据管理器实例
            signal_logger: 信号日志实例
            csv_writer: 信号 CSV 写入器实例
        """
        self.factory_endpoint = factory_endpoint
        self.position_proxy_url = position_proxy_url
        self.strategies_dir = Path(strategies_dir)
        self.data_manager = data_manager
        self.signal_logger = signal_logger
        self.csv_writer = csv_writer

        self.registry = StrategyRegistry()
        self.lifecycle = LifecycleManager(self.registry, self)
        self.factory_client: Optional[ServerProxy] = None
        self._connected_to_factory = False

    def connect_to_factory(self) -> bool:
        """连接到 cta-factory-service"""
        try:
            client = xmlrpc.client.ServerProxy(
                self.factory_endpoint, allow_none=True
            )
            # 测试连接
            if hasattr(client, 'health_check'):
                client.health_check()
            elif hasattr(client, 'list'):
                client.list()
            self.factory_client = client
            self._connected_to_factory = True
            logger.info(f"已连接到 cta-factory-service: {self.factory_endpoint}")
            return True
        except Exception as e:
            logger.warning(f"连接 cta-factory-service 失败：{e}")
            self._connected_to_factory = False
            return False

    def discover_strategies(self) -> List[str]:
        """
        自动发现 strategies/ 目录下的所有策略子模块

        Returns:
            策略名称列表
        """
        if not self.strategies_dir.exists():
            logger.warning(f"策略目录不存在：{self.strategies_dir}")
            return []

        strategy_names = []
        for item in self.strategies_dir.iterdir():
            if item.is_dir() and not item.name.startswith('_') and not item.name.startswith('.'):
                # 检查是否有 strategy.py 文件
                strategy_file = item / "strategy.py"
                if strategy_file.exists():
                    strategy_names.append(item.name)
                    logger.info(f"发现策略子模块：{item.name}")

        return strategy_names

    def load_strategy(
        self,
        strategy_name: str,
        config: Dict[str, Any],
        strategy_id: Optional[str] = None
    ) -> bool:
        """
        加载单个策略子模块

        Args:
            strategy_name: 策略名称（目录名）
            config: 策略配置
            strategy_id: 策略唯一 ID（可选，默认使用策略名称）

        Returns:
            是否成功加载
        """
        strategy_id = strategy_id or f"{strategy_name}_001"
        module_path = f"strategies.{strategy_name}.strategy"

        # 注册策略
        self.registry.register(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            module_path=module_path,
            config=config
        )

        # 实例化策略
        strategy_entry = self.registry.get(strategy_id)
        if strategy_entry is None:
            logger.error(f"获取策略条目失败：{strategy_id}")
            return False

        success = self.lifecycle.instantiate_strategy(
            strategy_entry,
            self.data_manager,
        )

        if success:
            logger.info(f"策略加载成功：{strategy_id}")
        else:
            # 从注册表获取错误信息
            entry = self.registry.get(strategy_id)
            error_msg = entry.error_message if entry and entry.error_message else "未知错误"
            logger.error(f"策略加载失败：{strategy_id} - {error_msg}")

        return success

    def load_all_strategies(self, configs: Dict[str, Dict[str, Any]]) -> List[str]:
        """
        加载所有已发现的策略

        Args:
            configs: 策略配置字典 {strategy_name: config}

        Returns:
            成功加载的策略 ID 列表
        """
        discovered = self.discover_strategies()
        loaded = []

        for name in discovered:
            config = configs.get(name)
            # 如果没有传入配置（None），让策略从各自的 config.yaml 文件加载
            if config is None:
                if self.load_strategy(name, {}):
                    loaded.append(name)
            elif config.get('enabled', True):
                if self.load_strategy(name, config):
                    loaded.append(name)

        logger.info(f"加载了 {len(loaded)} 个策略：{loaded}")
        return loaded

    def register_to_factory(self) -> bool:
        """
        将所有策略注册到 cta-factory-service

        Returns:
            是否成功注册
        """
        if not self._connected_to_factory:
            if not self.connect_to_factory():
                logger.warning("无法连接到 cta-factory-service，跳过注册")
                return False

        if self.factory_client is None:
            logger.error("factory_client 为 None，无法注册")
            return False

        success_count = 0
        for strategy_id, entry in self.registry.list_strategies().items():
            try:
                # 调用 factory-service 的 register RPC 方法
                # 只传一个 JSON 参数，包含所有策略信息
                result: Any = self.factory_client.register({
                    "strategy_id": strategy_id,
                    "strategy_name": entry.strategy_name,
                    "config": entry.config,
                    # 可随时新增字段
                })

                if isinstance(result, dict) and result.get("status") == "success":
                    logger.info(f"策略 {strategy_id} 注册到 factory-service 成功")
                    success_count += 1
                elif isinstance(result, dict):
                    logger.warning(f"策略 {strategy_id} 注册失败：{result.get('message', '未知错误')}")
                else:
                    logger.warning(f"策略 {strategy_id} 注册返回未知格式：{result}")
            except Exception as e:
                logger.error(f"注册策略 {strategy_id} 到 factory-service 失败：{e}")

        logger.info(f"成功注册 {success_count}/{len(self.registry.list_strategies())} 个策略到 factory-service")
        return success_count > 0

    def start_strategy(self, strategy_id: str) -> bool:
        """启动策略"""
        return self.lifecycle.start_strategy(strategy_id)

    def stop_strategy(self, strategy_id: str) -> bool:
        """停止策略"""
        return self.lifecycle.stop_strategy(strategy_id)

    def pause_strategy(self, strategy_id: str) -> bool:
        """暂停策略"""
        return self.lifecycle.pause_strategy(strategy_id)

    def resume_strategy(self, strategy_id: str) -> bool:
        """恢复策略"""
        return self.lifecycle.resume_strategy(strategy_id)

    def start_all(self) -> Dict[str, bool]:
        """启动所有策略"""
        results = {}
        for strategy_id in self.registry.list_strategies().keys():
            results[strategy_id] = self.start_strategy(strategy_id)
        return results

    def stop_all(self) -> Dict[str, bool]:
        """停止所有策略"""
        results = {}
        for strategy_id in self.registry.list_strategies().keys():
            results[strategy_id] = self.stop_strategy(strategy_id)
        return results

    def get_status(self, strategy_id: Optional[str] = None) -> Any:
        """获取策略状态"""
        if strategy_id:
            return self.lifecycle.get_strategy_status(strategy_id)
        else:
            return {
                sid: self.lifecycle.get_strategy_status(sid)
                for sid in self.registry.list_strategies().keys()
            }

    def on_kline_update(self, kline: Any):
        """
        K 线更新时分发给所有策略

        Args:
            kline: Kline 对象
        """
        kline_symbol = kline.symbol.upper() if hasattr(kline, 'symbol') else None
        for entry in self.registry.list_strategies().values():
            if entry.status == StrategyStatus.RUNNING and entry.instance:
                # 按 symbol 过滤：只分发给订阅了该 symbol 的策略
                if kline_symbol:
                    subs = getattr(entry.instance, 'subscribed_symbols', None)
                    if isinstance(subs, set):
                        # 多 symbol 策略：以 subscribed_symbols 为准
                        if kline_symbol not in subs:
                            continue
                    else:
                        # 单 symbol 策略：回退到 symbol 字段检查
                        sym = getattr(entry.instance, 'symbol', None)
                        if sym and kline_symbol != sym.upper():
                            continue
                try:
                    if hasattr(entry.instance, 'on_kline'):
                        signal = entry.instance.on_kline(kline)
                        # 如果生成信号，统一存储 CSV + Kafka
                        if signal and self.signal_logger:
                            strategy_params = self._build_strategy_params(entry)
                            self._log_signal_unified(signal, strategy_params, entry)
                except Exception as e:
                    logger.error(f"策略 {entry.strategy_id} 处理 K 线更新失败：{e}")

    def _log_signal_unified(
        self,
        signal: Any,
        strategy_params: Dict[str, Any],
        entry: Any,
    ):
        """
        统一信号存储：同时写 CSV 和 Kafka

        策略只返回 Signal 对象，引擎负责统一存储：
        1. 统一生成 CtaSignalCSV 对象（确保数据一致）
        2. SignalCsvWriter 写入 CSV
        3. SignalLogger 推送 HTTP/Kafka

        Args:
            signal: Signal 对象
            strategy_params: 完整策略参数（含 user_id 等）
            entry: StrategyEntry 实例
        """
        from strategy_core.signal_logging.csv_adapter import CtaSignalCSV

        cfg = entry.config or {}

        # 使用 signal.strategy_id 作为策略名称（完整策略实例名，如 ICT_1D_3_BNBUSDT_LIVE）
        # 用于 CSV 文件路径，与 history_positions 目录结构一致
        strategy_full_name = signal.strategy_id or entry.strategy_name or ''

        # 统一构建 CtaSignalCSV 参数
        # 从策略实例获取 trading_mode
        trading_mode = getattr(entry.instance, '_trading_mode', 'live') if entry.instance else 'live'

        # 获取调整后的资金（优先使用 metadata，否则使用配置）
        adjusted_cash = signal.metadata.get('adjusted_cash', strategy_params.get('strategy_cash', 100))

        cta_params = {
            "strategy_name": strategy_full_name,
            "strategy_version": strategy_params.get('strategy_version', cfg.get('version', 'v1')),
            "interval": strategy_params.get('strategy_internal', ''),
            "strategy_params": dict(cfg.get("params", {}) or {}),
            "strategy_cash": adjusted_cash,
            "strategy_parts": strategy_params.get('strategy_parts', 1),
            "strategy_valid_before": strategy_params.get(
                'strategy_valid_before', cfg.get('valid_before', '2030-12-31 08:00:00')
            ),
            "strategy_type": strategy_params.get('strategy_type', 'CTAFutureFactory'),
            "strategy_type_name": strategy_params.get('strategy_type_name', ''),
            "risk_strategy_type": strategy_params.get('risk_strategy_type', 'cta_intraday'),
            "user_id": strategy_params.get('user_id', 1),
            "signal_exchange": strategy_params.get('signal_exchange', 'binance'),
            "signal_order_type": strategy_params.get('signal_order_type', 1),
            "signal_slippage": strategy_params.get('signal_slippage', 0),
            "pos_type": strategy_params.get('pos_type', 2),
            "leverage": strategy_params.get('leverage', 5),
            "risk_stop_loss_pct": strategy_params.get('StopLossThreshold', DEFAULT_STOP_LOSS_PCT),
            "risk_trailing_profit_activation": strategy_params.get('TakeProfitBackThreshold', DEFAULT_TRAILING_PROFIT_ACTIVATION),
            "risk_trailing_profit_drawdown": strategy_params.get('TakeProfitBackDynamicFallPercent', DEFAULT_TRAILING_PROFIT_DRAWDOWN),
            "trading_mode": trading_mode,
        }

        # 1. 统一生成 CtaSignalCSV 对象
        try:
            cta_signal = CtaSignalCSV.from_signal(signal, **cta_params)
        except Exception as e:
            logger.error(f"信号数据生成失败 [{entry.strategy_id}]: {e}")
            return

        # 2. 写入 CSV
        csv_ok = True
        if self.csv_writer:
            try:
                csv_ok = self.csv_writer.write_cta_signal(cta_signal)
            except Exception as e:
                logger.error(f"CSV 写入失败 [{entry.strategy_id}]: {e}")
                csv_ok = False

        # 3. 推送 HTTP/Kafka（CSV 失败时跳过，避免数据不一致）
        if csv_ok:
            try:
                self.signal_logger.log_cta_signal(cta_signal)
            except Exception as e:
                logger.error(f"HTTP/Kafka 推送失败 [{entry.strategy_id}]: {e}")

    def _build_strategy_params(self, entry: Any) -> Dict[str, Any]:
        """
        构建策略参数（用于 Kafka 推送）

        从策略配置中提取 params + risk + 信号相关字段合并。

        Args:
            entry: StrategyEntry 实例

        Returns:
            策略参数字典
        """
        cfg = entry.config or {}
        params = dict(cfg.get("params", {}) or {})

        # 注入信号标识字段
        if "user_id" in cfg:
            params["user_id"] = cfg["user_id"]
        if "strategy_type" in cfg:
            params["strategy_type"] = cfg["strategy_type"]
        if "risk_strategy_type" in cfg:
            params["risk_strategy_type"] = cfg["risk_strategy_type"]
        if "pos_type" in cfg:
            params["pos_type"] = cfg["pos_type"]

        # 注入策略元数据
        if "version" in cfg:
            params["strategy_version"] = cfg["version"]
        if "valid_before" in cfg:
            params["strategy_valid_before"] = cfg["valid_before"]

        # 注入策略内部名称和主时间框架
        strategy_cfg = cfg.get('strategy', {}) or {}
        if 'name' in strategy_cfg:
            params['strategy_type_name'] = strategy_cfg['name']
        if 'timeframe' in cfg:
            params['strategy_internal'] = cfg['timeframe']
        elif 'timeframes' in cfg:
            tfs = cfg['timeframes']
            params['strategy_internal'] = tfs[0] if isinstance(tfs, list) and tfs else ''

        # 注入信号配置
        signal_cfg = cfg.get("signal", {}) or {}
        if "exchange" in signal_cfg:
            params["signal_exchange"] = signal_cfg["exchange"]
        if "order_type" in signal_cfg:
            params["signal_order_type"] = signal_cfg["order_type"]
        if "slippage" in signal_cfg:
            params["signal_slippage"] = signal_cfg["slippage"]
        if "valid_before_hours" in signal_cfg:
            params["signal_valid_before_hours"] = signal_cfg["valid_before_hours"]
        if "quantity" in signal_cfg:
            params["signal_quantity"] = signal_cfg["quantity"]

        # 注入资金配置
        capital = cfg.get("capital", {}) or {}
        if "max_cash" in capital:
            params["strategy_cash"] = capital["max_cash"]
        if "max_parts" in capital:
            params["strategy_parts"] = capital["max_parts"]
        if "leverage" in capital:
            params["leverage"] = capital["leverage"]

        # 注入风控字段（支持新旧两种格式）
        risk = cfg.get("risk", {}) or {}
        trailing = risk.get("trailing_profit", {}) or {}

        # StopLossThreshold: 新格式 fixed_stop_loss_pct > 旧格式 stop_loss_pct > 默认值
        params["StopLossThreshold"] = risk.get(
            "fixed_stop_loss_pct",
            risk.get("stop_loss_pct", DEFAULT_STOP_LOSS_PCT)
        )

        # TakeProfitBackThreshold: 新格式 activation_pct > 旧格式 trailing_profit_activation > 默认值
        params["TakeProfitBackThreshold"] = trailing.get(
            "activation_pct",
            risk.get("trailing_profit_activation", DEFAULT_TRAILING_PROFIT_ACTIVATION)
        )

        # TakeProfitBackDynamicFallPercent: 新格式 drawdown_pct > 旧格式 trailing_profit_drawdown > 默认值
        params["TakeProfitBackDynamicFallPercent"] = trailing.get(
            "drawdown_pct",
            risk.get("trailing_profit_drawdown", DEFAULT_TRAILING_PROFIT_DRAWDOWN)
        )

        return params

    def list_strategies(self) -> Dict[str, Dict]:
        """列出所有策略"""
        return {
            sid: entry.to_dict()
            for sid, entry in self.registry.list_strategies().items()
        }
