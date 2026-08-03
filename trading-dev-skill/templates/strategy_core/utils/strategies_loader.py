"""
策略配置加载器 - 简化配置管理

功能：
- 加载 strategies.yaml 配置文件
- 从 zktrading 配置自动读取 interval/version
- 自动生成 config_path
- 支持 overrides 参数覆盖
- 支持 symbol 级别 trading_mode 覆盖
- 实盘/回测共用

配置格式（简化版）:
    strategies:
      cta_ict_v3:
        trading_mode: "live"
        config_dir: "config/zktrading"
        symbols:
          - BTCUSDT
          - name: SOLUSDT
            trading_mode: "paper_trading"

使用示例：
    loader = StrategiesLoader("config/strategies.yaml")
    loader.load()

    # 获取所有策略实例
    instances = loader.expand_strategies()

    # 过滤
    live_instances = loader.filter(trading_mode="live")

    # 查询
    instance = loader.get_strategy_by_name_symbol("cta_ict_v3", "BTCUSDT")
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from pathlib import Path
import yaml
import copy
import re
import logging

logger = logging.getLogger(__name__)


# 字段验证正则表达式
VALID_STRATEGY_NAME_PATTERN = re.compile(r'^[a-z_][a-z0-9_]*$')
VALID_SYMBOL_PATTERN = re.compile(r'^[A-Z][A-Z0-9]*$')


@dataclass
class StrategyInstance:
    """展开后的策略实例

    每个 StrategyInstance 对应一个独立的策略运行实例。

    Attributes:
        name: 策略目录名（如 cta_ict_v3）
        symbol: 交易对（如 BTCUSDT）
        interval: 主周期（如 4h）
        version: 版本号（如 v2）
        enabled: 是否启用
        trading_mode: 运行模式（live / paper_trading / smoking）
        config_path: 策略参数配置文件路径（自动生成）
        overrides: 回测时的参数覆盖
    """
    name: str
    symbol: str
    interval: str
    version: str
    enabled: bool
    trading_mode: str
    config_path: str
    overrides: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        """验证实例字段

        Raises:
            ValueError: 字段验证失败
        """
        if not StrategiesLoader.is_valid_strategy_name(self.name):
            raise ValueError(f"Invalid strategy name: {self.name}")

        if not StrategiesLoader.is_valid_symbol(self.symbol):
            raise ValueError(f"Invalid symbol: {self.symbol}")

        if not StrategiesLoader.is_valid_config_path(self.config_path):
            raise ValueError(f"Invalid config_path: {self.config_path}")


class StrategiesLoader:
    """策略配置加载器

    功能：
    1. 加载 strategies.yaml 配置文件
    2. 展开策略为独立实例
    3. 支持过滤和查询
    4. 输入验证防止命令注入

    使用示例：
        loader = StrategiesLoader("config/strategies.yaml")
        loader.load()

        # 展开所有策略实例
        instances = loader.expand_strategies()

        # 过滤启用的实盘策略
        live_instances = loader.filter(enabled_only=True, trading_mode="live")
    """

    # 默认配置（用于缺失字段时的回退值）
    DEFAULT_CONFIG = {
        "interval": "4h",
        "version": "2",  # 与 zktrading 配置格式一致，不含 v 前缀
        "trading_mode": "live",
        "enabled": True,
        "config_dir": "config/zktrading",
    }

    def __init__(self, config_path: str = "config/strategies.yaml"):
        """初始化加载器

        Args:
            config_path: 配置文件路径
        """
        self.config_path = Path(config_path)
        self._strategies: Dict[str, Dict[str, Any]] = {}
        self._instance_map: Optional[Dict[tuple, StrategyInstance]] = None
        self._expanded_instances: Optional[List[StrategyInstance]] = None

    @staticmethod
    def is_valid_strategy_name(name: str) -> bool:
        """验证策略名称

        只允许小写字母、数字、下划线，且必须以字母或下划线开头。
        """
        return bool(name and VALID_STRATEGY_NAME_PATTERN.match(name))

    @staticmethod
    def is_valid_symbol(symbol: str) -> bool:
        """验证交易对

        只允许大写字母、数字，且必须以字母开头。
        """
        return bool(symbol and VALID_SYMBOL_PATTERN.match(symbol))

    @staticmethod
    def is_valid_config_path(path: str) -> bool:
        """验证配置路径

        防止路径遍历攻击（如 ../../../etc/passwd）。
        """
        if not path:
            return False
        # 检查路径遍历（包括 URL 编码）
        return ".." not in path and "%2e%2e" not in path.lower()

    def load(self) -> "StrategiesLoader":
        """加载配置文件

        Returns:
            self（支持链式调用）

        Raises:
            FileNotFoundError: 配置文件不存在
        """
        if not self.config_path.exists():
            raise FileNotFoundError(f"配置文件不存在: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw_config = yaml.safe_load(f) or {}

        # 只解析 strategies 字段（简化配置格式）
        self._strategies = raw_config.get("strategies", {})

        # 清除缓存
        self._instance_map = None
        self._expanded_instances = None

        return self

    def _validate_strategy_config(self, name: str, config: dict) -> None:
        """验证策略配置完整性

        检查必需字段，缺失时记录警告。

        Args:
            name: 策略名称
            config: 策略配置
        """
        recommended_fields = ["trading_mode"]
        missing = [f for f in recommended_fields if f not in config]
        if missing:
            logger.warning(
                f"策略 '{name}' 缺少推荐字段: {missing}，将使用默认值"
            )

    def _load_interval_version_from_zktrading(
        self,
        config_path: str,
        strategy_name: str,
        symbol: str
    ) -> tuple:
        """从 zktrading 配置文件读取 interval 和 version

        Args:
            config_path: zktrading 配置文件路径
            strategy_name: 策略名称
            symbol: 交易对

        Returns:
            (interval, version) 元组
        """
        defaults = self.DEFAULT_CONFIG

        try:
            full_path = Path(config_path)
            if not full_path.exists():
                logger.debug(f"zktrading 配置文件不存在: {config_path}, 使用默认值")
                return defaults["interval"], defaults["version"]

            with open(full_path, "r", encoding="utf-8") as f:
                zktrading_config = yaml.safe_load(f) or {}

            strategy_config = zktrading_config.get(strategy_name, {})

            # interval 从 timeframes[0] 读取
            timeframes = strategy_config.get("timeframes", [])
            interval = str(timeframes[0]) if timeframes else defaults["interval"]

            # version 直接读取
            version = str(strategy_config.get("version", defaults["version"]))

            return interval, version

        except Exception as e:
            logger.warning(f"读取 zktrading 配置失败: {config_path}, 错误: {e}")
            return defaults["interval"], defaults["version"]

    def expand_strategies(self) -> List[StrategyInstance]:
        """展开策略配置为实例列表

        每个策略的 symbols 列表中的每个 symbol 生成一个 StrategyInstance。
        结果会被缓存，避免重复计算。

        symbols 支持两种格式：
        1. 字符串格式：[BTCUSDT, ETHUSDT]
        2. 对象格式：[{name: BTCUSDT, trading_mode: "paper_trading"}]

        interval/version 来源：
        - 从 zktrading/{strategy}/{symbol}.yaml 的 timeframes[0] 和 version 读取
        - 如果 zktrading 配置缺失，使用默认值（"4h" 和 "v2")

        Returns:
            策略实例列表
        """
        # 返回缓存结果
        if self._expanded_instances is not None:
            return self._expanded_instances

        instances = []
        defaults = self.DEFAULT_CONFIG  # 提取到局部变量，避免重复访问

        for strategy_name, strategy_config in self._strategies.items():
            # 验证配置完整性
            self._validate_strategy_config(strategy_name, strategy_config)

            # 获取策略级配置，缺失字段使用默认值
            config_dir = strategy_config.get("config_dir", defaults["config_dir"])
            overrides = copy.deepcopy(strategy_config.get("overrides", {}))
            enabled = strategy_config.get("enabled", defaults["enabled"])
            trading_mode = strategy_config.get("trading_mode", defaults["trading_mode"])

            # 展开 symbols
            for symbol_item in strategy_config.get("symbols", []):
                symbol, symbol_trading_mode = self._parse_symbol_item(symbol_item)

                # symbol 级 trading_mode 覆盖策略级
                final_trading_mode = symbol_trading_mode or trading_mode

                config_path = str(Path(config_dir) / strategy_name / f"{symbol}.yaml")

                # interval/version 从 zktrading 配置文件读取
                interval, version = self._load_interval_version_from_zktrading(
                    config_path, strategy_name, symbol
                )

                instance = StrategyInstance(
                    name=strategy_name,
                    symbol=symbol,
                    interval=interval,
                    version=version,
                    enabled=enabled,
                    trading_mode=final_trading_mode,
                    config_path=config_path,
                    overrides=overrides,
                )
                instances.append(instance)

        # 缓存结果
        self._expanded_instances = instances
        return instances

    def _parse_symbol_item(self, item: Any) -> tuple:
        """解析 symbol 项

        支持两种格式：
        - 字符串：直接返回 symbol 名称
        - 字典：提取 name 和 trading_mode

        Returns:
            (symbol_name, trading_mode) 元组
        """
        if isinstance(item, str):
            return item, None
        if isinstance(item, dict):
            name = item.get("name")
            if not name:
                raise ValueError(f"Symbol object missing 'name' field: {item}")
            return name, item.get("trading_mode")
        raise ValueError(f"Invalid symbol format: {item}. Expected str or dict.")

    def filter(self,
               enabled_only: bool = True,
               trading_mode: Optional[str] = None) -> List[StrategyInstance]:
        """过滤策略实例

        Args:
            enabled_only: 仅返回启用的策略
            trading_mode: 按运行模式过滤

        Returns:
            过滤后的策略实例列表
        """
        instances = self.expand_strategies()

        if enabled_only:
            instances = [i for i in instances if i.enabled]

        if trading_mode:
            instances = [i for i in instances if i.trading_mode == trading_mode]

        return instances

    def get_strategy_by_name_symbol(self, name: str, symbol: str) -> Optional[StrategyInstance]:
        """按名称和交易对获取策略实例

        使用缓存优化查询性能。

        Args:
            name: 策略名称
            symbol: 交易对

        Returns:
            策略实例，未找到返回 None
        """
        # 构建缓存
        if self._instance_map is None:
            self._instance_map = {
                (i.name, i.symbol): i for i in self.expand_strategies()
            }

        return self._instance_map.get((name, symbol))
