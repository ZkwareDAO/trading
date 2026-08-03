#!/usr/bin/env python3
"""
失败信号持久化队列

职责：
- 持久化 HTTP/Kafka 发送失败的信号到本地 CSV
- 支持重试发送
- 超过最大重试次数后标记为放弃
"""

import csv
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from strategy_core.signal_logging.storage import Signal, SignalType

logger = logging.getLogger(__name__)


@dataclass
class FailedSignal:
    """失败信号数据结构"""
    signal_id: str
    strategy_id: str
    signal_type: str  # buy, sell, buy_close, sell_close
    symbol: str
    price: float
    strength: float
    timestamp: str  # ISO 格式
    topic: str
    retry_count: int = 0
    last_retry_time: Optional[str] = None
    status: str = "pending"  # pending, success, abandoned
    metadata: str = "{}"  # JSON 字符串

    @classmethod
    def from_signal(cls, signal: Signal, topic: str = "strategy_signals", metadata: Optional[Dict] = None) -> "FailedSignal":
        """从 Signal 创建 FailedSignal"""
        signal_type_map = {
            SignalType.BUY: "buy",
            SignalType.SELL: "sell",
            SignalType.BUY_CLOSE: "buy_close",
            SignalType.SELL_CLOSE: "sell_close",
        }
        return cls(
            signal_id=signal.signal_id,
            strategy_id=signal.strategy_id,
            signal_type=signal_type_map.get(signal.signal_type, "unknown"),
            symbol=signal.symbol,
            price=signal.price,
            strength=signal.strength,
            timestamp=signal.timestamp.isoformat() if isinstance(signal.timestamp, datetime) else str(signal.timestamp),
            topic=topic,
            retry_count=0,
            status="pending",
            metadata=json.dumps(metadata or {}, ensure_ascii=False),
        )

    def to_csv_row(self) -> Dict[str, str]:
        """转换为 CSV 行"""
        return {
            "signal_id": self.signal_id,
            "strategy_id": self.strategy_id,
            "signal_type": self.signal_type,
            "symbol": self.symbol,
            "price": str(self.price),
            "strength": str(self.strength),
            "timestamp": self.timestamp,
            "topic": self.topic,
            "retry_count": str(self.retry_count),
            "last_retry_time": self.last_retry_time or "",
            "status": self.status,
            "metadata": self.metadata,
        }

    @classmethod
    def from_csv_row(cls, row: Dict[str, str]) -> "FailedSignal":
        """从 CSV 行恢复"""
        return cls(
            signal_id=row.get("signal_id", ""),
            strategy_id=row.get("strategy_id", ""),
            signal_type=row.get("signal_type", ""),
            symbol=row.get("symbol", ""),
            price=float(row.get("price", 0)),
            strength=float(row.get("strength", 0)),
            timestamp=row.get("timestamp", ""),
            topic=row.get("topic", "strategy_signals"),
            retry_count=int(row.get("retry_count", 0)),
            last_retry_time=row.get("last_retry_time") or None,
            status=row.get("status", "pending"),
            metadata=row.get("metadata", "{}"),
        )


class RetryQueue:
    """
    失败信号持久化队列

    使用 CSV 文件存储失败信号，支持重试。
    """

    FIELDNAMES = [
        "signal_id", "strategy_id", "signal_type", "symbol", "price",
        "strength", "timestamp", "topic", "retry_count", "last_retry_time",
        "status", "metadata"
    ]

    def __init__(self, base_dir: str = "./data/retry_queue", max_retries: int = 5):
        """
        初始化重试队列

        Args:
            base_dir: CSV 文件存储目录
            max_retries: 最大重试次数
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.max_retries = max_retries
        logger.info(f"重试队列初始化完成：{self.base_dir}")

    def _get_csv_path(self) -> Path:
        """获取当天 CSV 文件路径"""
        today = datetime.now().strftime("%Y%m%d")
        return self.base_dir / f"{today}.csv"

    def _init_csv_file(self, csv_path: Path) -> None:
        """初始化 CSV 文件（创建表头）"""
        if not csv_path.exists():
            with open(csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writeheader()
            logger.debug(f"创建重试队列 CSV 文件：{csv_path}")

    def add_failed_signal(
        self,
        signal: Signal,
        topic: str = "strategy_signals",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        添加失败信号到队列

        Args:
            signal: 失败的信号
            topic: Kafka topic
            metadata: 额外元数据
        """
        failed = FailedSignal.from_signal(signal, topic, metadata)
        csv_path = self._get_csv_path()
        self._init_csv_file(csv_path)

        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
            writer.writerow(failed.to_csv_row())

        logger.info(f"失败信号已添加到队列：{signal.signal_id}")

    def _read_signals_by_status(self, status: str) -> List[FailedSignal]:
        """读取指定状态的信号"""
        signals = []
        for csv_file in sorted(self.base_dir.glob("*.csv")):
            try:
                with open(csv_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        signal = FailedSignal.from_csv_row(row)
                        if signal.status == status:
                            signals.append(signal)
            except Exception as e:
                logger.warning(f"读取重试队列文件失败 {csv_file}: {e}")
        return signals

    def get_pending_signals(self) -> List[FailedSignal]:
        """获取所有待重试的信号"""
        return self._read_signals_by_status("pending")

    def get_abandoned_signals(self) -> List[FailedSignal]:
        """获取已放弃的信号"""
        return self._read_signals_by_status("abandoned")

    def retry_all(self, sender) -> int:
        """
        重试所有待重试的信号

        Args:
            sender: HTTP sender 对象，需有 send_signal() 方法

        Returns:
            成功发送的信号数量
        """
        pending = self.get_pending_signals()
        if not pending:
            return 0

        success_count = 0

        for failed in pending:
            # 构建临时 Signal 对象
            signal = Signal(
                signal_id=failed.signal_id,
                strategy_id=failed.strategy_id,
                signal_type=SignalType(failed.signal_type),
                symbol=failed.symbol,
                price=failed.price,
                strength=failed.strength,
                timestamp=datetime.fromisoformat(failed.timestamp),
            )

            # 尝试发送
            try:
                metadata = json.loads(failed.metadata)
            except json.JSONDecodeError:
                metadata = {}

            success = sender.send_signal(signal, topic=failed.topic, **metadata)

            if success:
                failed.status = "success"
                self._update_signal(failed)
                success_count += 1
                logger.info(f"信号重试成功：{failed.signal_id}")
            else:
                failed.retry_count += 1
                failed.last_retry_time = datetime.now(timezone.utc).isoformat()

                if failed.retry_count >= self.max_retries:
                    failed.status = "abandoned"
                    logger.warning(f"信号重试次数超限，已放弃：{failed.signal_id}")
                else:
                    logger.warning(f"信号重试失败：{failed.signal_id}, 已重试 {failed.retry_count} 次")

                self._update_signal(failed)

        return success_count

    def _update_signal(self, updated: FailedSignal) -> None:
        """更新信号状态"""
        # 读取所有信号
        all_signals = []

        for csv_file in sorted(self.base_dir.glob("*.csv")):
            try:
                with open(csv_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        signal = FailedSignal.from_csv_row(row)
                        if signal.signal_id == updated.signal_id:
                            all_signals.append(updated)
                        else:
                            all_signals.append(signal)
            except Exception as e:
                logger.warning(f"读取重试队列文件失败 {csv_file}: {e}")

        # 重写当天文件
        csv_path = self._get_csv_path()
        self._init_csv_file(csv_path)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
            writer.writeheader()
            for signal in all_signals:
                if signal.status in ("pending", "success", "abandoned"):
                    writer.writerow(signal.to_csv_row())

    def clear_sent_signals(self) -> int:
        """清除已成功发送的信号"""
        cleared = 0

        for csv_file in self.base_dir.glob("*.csv"):
            pending = []

            try:
                with open(csv_file, "r", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        signal = FailedSignal.from_csv_row(row)
                        if signal.status != "success":
                            pending.append(signal)
                        else:
                            cleared += 1
            except Exception as e:
                logger.warning(f"读取重试队列文件失败 {csv_file}: {e}")
                continue

            # 重写文件
            with open(csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writeheader()
                for signal in pending:
                    writer.writerow(signal.to_csv_row())

        logger.info(f"已清除 {cleared} 个成功发送的信号")
        return cleared
