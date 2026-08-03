"""
同步服务总控

配置驱动的统一同步服务。
所有同步源通过 UniversalSyncer 实现，无需编写同步器类。
"""

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Set

import yaml

from .ov_client import OpenVikingClient, OpenVikingConfig
from .base_sync import SyncResult
from .universal_syncer import UniversalSyncer

logger = logging.getLogger(__name__)


def _expand_env_vars(value: str) -> str:
    """展开字符串中的环境变量 ${VAR_NAME}"""
    if not isinstance(value, str):
        return value
    return os.path.expandvars(value)


def _resolve_config_path(config_path: Optional[str]) -> Optional[str]:
    """
    解析配置文件路径，按优先级返回有效路径

    Args:
        config_path: 用户指定的配置路径

    Returns:
        有效的配置文件路径，如果都无效则返回 None
    """
    # 优先使用用户指定的配置文件
    if config_path:
        path = Path(config_path)
        if path.exists():
            logger.info(f"Using config file: {config_path}")
            return str(path)
        logger.warning(f"Config file not found: {config_path}, falling back to default")

    # 尝试默认配置文件
    default_path = Path("./config/openviking_sync.yaml")
    if default_path.exists():
        logger.info("Using openviking_sync.yaml")
        return str(default_path)

    return None


@dataclass
class SyncConfig:
    """同步配置"""
    enabled: bool = True
    dedup_file: str = "./data/.ov_synced_records"
    max_retries: int = 3
    retry_delay: float = 5.0
    sources: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class DailySyncResult:
    """每日同步结果"""
    date: str
    results: List[SyncResult] = field(default_factory=list)

    @property
    def total_success(self) -> int:
        """成功总数"""
        return sum(1 for r in self.results if r.success)

    @property
    def total_failed(self) -> int:
        """失败总数"""
        return sum(1 for r in self.results if not r.success)


class TradingDataSyncService:
    """交易数据同步服务"""

    def __init__(
        self,
        config: SyncConfig,
        ov_config: OpenVikingConfig,
    ):
        """
        初始化同步服务

        Args:
            config: 同步配置
            ov_config: OpenViking 配置
        """
        self.config = config
        self.ov_config = ov_config
        self.ov_client = OpenVikingClient(ov_config)
        self.syncers: Dict[str, UniversalSyncer] = {}
        self._synced_records: Set[str] = self._load_synced_records()
        self._account: str = ov_config.account

        # 注册同步器
        self._register_syncers()

    def _register_syncers(self):
        """从配置注册所有同步器"""
        for name, source_config in self.config.sources.items():
            if not source_config.get("enabled", True):
                continue

            try:
                syncer = UniversalSyncer(
                    source_name=name,
                    config=source_config,
                    ov_client=self.ov_client,
                )
                self.syncers[name] = syncer
                logger.info(f"Registered syncer: {name}")
            except Exception as e:
                logger.warning(f"Failed to register syncer {name}: {e}")

    @classmethod
    def from_config_file(
        cls,
        config_path: str = "./config/openviking_sync.yaml"
    ) -> 'TradingDataSyncService':
        """
        从配置文件创建服务实例

        Args:
            config_path: 配置文件路径

        Returns:
            服务实例
        """
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        return cls.from_config(config)

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> 'TradingDataSyncService':
        """
        从配置字典创建服务实例

        Args:
            config: 配置字典

        Returns:
            服务实例
        """
        # 解析服务器配置
        server = config.get("server", {})
        account = config.get("account", {})

        ov_config = OpenVikingConfig(
            server_url=server.get("url", "http://localhost:1933"),
            cli_path=server.get("cli_path", "ov"),
            timeout=server.get("timeout", 60.0),
            enabled=True,
            account=account.get("name", ""),
            api_key=_expand_env_vars(account.get("api_key", "")),
            root_api_key=_expand_env_vars(account.get("root_api_key", "")),
            auto_create_account=account.get("auto_create", True),
        )

        # 解析同步配置
        dedup = config.get("dedup", {})
        sync_config = SyncConfig(
            enabled=config.get("enabled", True),
            dedup_file=dedup.get("file", "./data/.ov_synced_records"),
            sources=config.get("sources", {}),
        )

        return cls(sync_config, ov_config)

    @classmethod
    def from_settings(cls, settings: Dict[str, Any], config_path: Optional[str] = None) -> 'TradingDataSyncService':
        """
        从 settings.yaml 配置创建服务实例（向后兼容）

        Args:
            settings: settings.yaml 解析后的字典（仅当 config_path 无效时使用）
            config_path: 配置文件路径，优先使用

        Returns:
            服务实例
        """
        # 优先使用指定的配置文件
        actual_config = _resolve_config_path(config_path)
        if actual_config:
            return cls.from_config_file(actual_config)

        # 向后兼容：从 settings.yaml 解析
        logger.info("Using settings.yaml (deprecated, migrate to openviking_sync.yaml)")

        ov_sync_config = settings.get("openviking_sync", {})
        ov_config = settings.get("openviking", {})

        # 构建新格式配置
        config = {
            "server": ov_config.get("server", {}),
            "account": ov_config.get("account", {}),
            "dedup": ov_sync_config.get("dedup", {}),
            "sources": ov_sync_config.get("sources", {}),
        }

        # 合并 custom_sources 到 sources
        custom_sources = ov_sync_config.get("custom_sources", {})
        config["sources"].update(custom_sources)

        return cls.from_config(config)

    def sync_daily(
        self,
        date: Optional[datetime] = None,
        strategy_names: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
    ) -> DailySyncResult:
        """
        同步指定日期的全部数据

        Args:
            date: 日期，默认今天
            strategy_names: 策略列表，默认全部
            sources: 同步源列表，默认全部

        Returns:
            每日同步结果汇总
        """
        if date is None:
            date = datetime.now()

        # 确保账户存在
        self.ov_client.ensure_account()

        all_results: List[SyncResult] = []

        # 确定要运行的同步器
        if sources:
            active_syncers = {k: v for k, v in self.syncers.items() if k in sources}
        else:
            active_syncers = self.syncers.copy()

        # 执行同步
        for syncer_name, syncer in active_syncers.items():
            try:
                results = syncer.sync_daily(date, strategy_names, account=self._account)
                all_results.extend(results)
            except Exception as e:
                logger.error(f"Syncer {syncer_name} failed: {e}")

        result = DailySyncResult(
            date=date.strftime("%Y%m%d"),
            results=all_results,
        )

        # 标记已同步
        self._mark_synced(result)

        return result

    def sync_range(
        self,
        start: datetime,
        end: datetime,
        strategy_names: Optional[List[str]] = None,
        sources: Optional[List[str]] = None,
    ) -> List[DailySyncResult]:
        """
        同步日期范围

        Args:
            start: 开始日期
            end: 结束日期
            strategy_names: 策略列表
            sources: 同步源列表

        Returns:
            每日同步结果列表
        """
        results = []
        current = start

        while current <= end:
            result = self.sync_daily(current, strategy_names, sources)
            results.append(result)
            current += timedelta(days=1)

        return results

    def sync_all_pending(self) -> List[DailySyncResult]:
        """
        同步所有未同步数据

        扫描数据目录，找出未同步的日期

        Returns:
            同步结果列表
        """
        results = []

        for syncer_name, syncer in self.syncers.items():
            for pending in self._find_pending_items(syncer_name, syncer):
                result = self.sync_daily(pending['date'], [pending['strategy']])
                results.append(result)

        return results

    def _find_pending_items(self, syncer_name: str, syncer: UniversalSyncer) -> List[Dict]:
        """
        查找同步器中待同步的项目

        Args:
            syncer_name: 同步器名称
            syncer: 同步器实例

        Returns:
            待同步项列表 [{'date': datetime, 'strategy': str}]
        """
        pending = []

        for base_path in syncer.paths:
            if not base_path.exists():
                continue

            for strategy_dir in base_path.iterdir():
                if not strategy_dir.is_dir():
                    continue

                for file in strategy_dir.glob("*.csv"):
                    date_str = file.stem
                    sync_key = f"{syncer_name}:{strategy_dir.name}:{date_str}"

                    if sync_key in self._synced_records:
                        continue

                    try:
                        date = datetime.strptime(date_str, "%Y%m%d")
                        pending.append({'date': date, 'strategy': strategy_dir.name})
                    except ValueError:
                        logger.warning(f"Invalid date format in file: {file}")

        return pending

    def _load_synced_records(self) -> Set[str]:
        """
        加载已同步记录

        Returns:
            已同步记录集合
        """
        dedup_file = Path(self.config.dedup_file)
        if not dedup_file.exists():
            return set()

        try:
            with open(dedup_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data.get("synced", []))
        except Exception:
            return set()

    def _mark_synced(self, result: DailySyncResult):
        """
        标记已同步

        Args:
            result: 同步结果
        """
        for r in result.results:
            if r.success:
                key = r.uri  # 使用 URI 作为唯一标识
                self._synced_records.add(key)

        self._save_synced_records()

    def _save_synced_records(self):
        """保存已同步记录到文件"""
        dedup_file = Path(self.config.dedup_file)
        dedup_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(dedup_file, "w", encoding="utf-8") as f:
                json.dump({"synced": list(self._synced_records)}, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save synced records: {e}")

    def list_syncers(self) -> List[str]:
        """
        列出已注册的同步器

        Returns:
            同步器名称列表
        """
        return list(self.syncers.keys())

    def _is_synced(self, uri: str) -> bool:
        """
        检查是否已同步

        Args:
            uri: 资源 URI

        Returns:
            是否已同步
        """
        return uri in self._synced_records

    def _generate_daily_uri(self, date: datetime) -> str:
        """
        生成当日根目录 URI

        Args:
            date: 日期

        Returns:
            根 URI
        """
        return OpenVikingClient.generate_daily_uri(date, self._account)
