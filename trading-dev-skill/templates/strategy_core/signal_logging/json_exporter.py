"""
Signal JSON Exporter - 信号 JSON 导出模块

从 CSV 读取信号并导出为 JSON 格式，支持内部格式和 Kafka 格式。
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List
from pathlib import Path

from .storage import Signal
from .logger import SignalStorage
from .csv_adapter import CtaSignalCSV

logger = logging.getLogger(__name__)


class SignalJsonExporter:
    """
    信号 JSON 导出器

    复用 SignalStorage 读取 CSV 信号，转换为 JSON 格式输出。
    支持两种格式：
    - internal: 扁平结构 (Signal.to_dict())
    - kafka: 嵌套结构 (CtaSignalCSV.to_json())
    """

    def __init__(self, storage: SignalStorage):
        """
        初始化导出器

        Args:
            storage: SignalStorage 实例，用于读取 CSV 信号
        """
        self.storage = storage

    def export_signals(
        self,
        strategy_id: Optional[str] = None,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        fmt: str = "internal",
    ) -> List[Dict[str, Any]]:
        """
        查询信号并返回 JSON 字典列表

        Args:
            strategy_id: 策略 ID
            symbol: 交易标的
            start_time: 开始时间
            end_time: 结束时间
            limit: 返回数量限制 (0 = 无限制)
            fmt: 输出格式 ("internal" | "kafka")

        Returns:
            JSON 字典列表
        """
        signals = self.storage.get_signals(
            strategy_id=strategy_id,
            symbol=symbol,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )

        if fmt == "kafka":
            return [self._to_kafka_format(s) for s in signals]
        return [s.to_dict() for s in signals]

    def export_to_file(
        self,
        output_path: str,
        strategy_id: Optional[str] = None,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
        fmt: str = "internal",
    ) -> int:
        """
        查询信号并写入 JSON 文件

        Args:
            output_path: 输出文件路径
            strategy_id: 策略 ID
            symbol: 交易标的
            start_time: 开始时间
            end_time: 结束时间
            limit: 返回数量限制
            fmt: 输出格式

        Returns:
            写入的信号数量
        """
        signals = self.export_signals(
            strategy_id=strategy_id,
            symbol=symbol,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
            fmt=fmt,
        )

        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(signals, f, indent=2, ensure_ascii=False)

        logger.info(f"已导出 {len(signals)} 条信号到 {output_path}")
        return len(signals)

    def export_latest(
        self,
        strategy_id: Optional[str] = None,
        limit: int = 10,
        fmt: str = "internal",
    ) -> List[Dict[str, Any]]:
        """
        快捷方法：导出最新 N 条信号

        Args:
            strategy_id: 策略 ID
            limit: 数量限制
            fmt: 输出格式

        Returns:
            JSON 字典列表
        """
        return self.export_signals(strategy_id=strategy_id, limit=limit, fmt=fmt)

    def export_all(
        self,
        strategy_id: Optional[str] = None,
        fmt: str = "internal",
    ) -> List[Dict[str, Any]]:
        """
        快捷方法：导出某策略的全部信号

        Args:
            strategy_id: 策略 ID
            fmt: 输出格式

        Returns:
            JSON 字典列表
        """
        return self.export_signals(strategy_id=strategy_id, limit=0, fmt=fmt)

    def export_statistics(
        self,
        strategy_id: str,
        period: str = "7d",
    ) -> Dict[str, Any]:
        """
        导出统计信息为 JSON

        Args:
            strategy_id: 策略 ID
            period: 统计周期 (7d, 30d, etc.)

        Returns:
            统计信息字典
        """
        return self.storage.get_statistics(strategy_id=strategy_id, period=period)

    def _to_kafka_format(self, signal: Signal, **kwargs) -> Dict[str, Any]:
        """
        将 Signal 转换为 Kafka 格式 JSON

        Args:
            signal: Signal 对象
            **kwargs: 透传给 CtaSignalCSV.from_signal 的参数 (如 user_id)

        Returns:
            Kafka 格式字典
        """
        cta_signal = CtaSignalCSV.from_signal(signal, **kwargs)
        return cta_signal.to_json()
