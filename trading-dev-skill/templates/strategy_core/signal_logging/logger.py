"""
Signal Logging - 信号日志

负责信号的持久化存储和查询
"""

import json
import logging
import csv
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections import defaultdict

from .storage import Signal, SignalType
from .csv_adapter import CtaSignalCSV

logger = logging.getLogger(__name__)


class SignalStorage:
    """
    信号存储器

    使用 CSV 文件存储信号数据
    文件组织：./data/signals/{strategy_id}/{date}.csv
    """

    # CSV 文件列名
    FIELDNAMES = [
        "signal_id", "strategy_id", "signal_type", "symbol", "price",
        "volume", "direction", "strength", "timestamp", "metadata"
    ]

    def __init__(self, base_dir: str = "./data/signals"):
        """
        初始化信号存储器

        Args:
            base_dir: 信号数据根目录
        """
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"信号存储目录初始化完成：{self.base_dir}")

    def _get_file_path(self, strategy_id: str, date: datetime) -> Path:
        """
        获取指定策略和日期的 CSV 文件路径

        Args:
            strategy_id: 策略 ID
            date: 日期

        Returns:
            CSV 文件路径
        """
        # 使用 UTC 日期作为文件名，确保与 K 线时间一致
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        date_str = date.astimezone(timezone.utc).strftime("%Y%m%d")
        strategy_dir = self.base_dir / strategy_id
        strategy_dir.mkdir(parents=True, exist_ok=True)
        return strategy_dir / f"{date_str}.csv"

    def _file_exists(self, strategy_id: str, date: datetime) -> bool:
        """检查指定策略和日期的 CSV 文件是否存在"""
        return self._get_file_path(strategy_id, date).exists()

    def _init_csv_file(self, strategy_id: str, date: datetime):
        """
        初始化 CSV 文件（创建表头）

        Args:
            strategy_id: 策略 ID
            date: 日期
        """
        file_path = self._get_file_path(strategy_id, date)
        if not file_path.exists():
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writeheader()
            logger.debug(f"创建信号 CSV 文件：{file_path}")

    def save(self, signal: Signal) -> bool:
        """
        保存信号到 CSV 文件

        Args:
            signal: Signal 对象

        Returns:
            是否保存成功
        """
        try:
            # 获取信号日期的文件路径
            file_path = self._get_file_path(signal.strategy_id, signal.timestamp)

            # 确保文件已初始化
            self._init_csv_file(signal.strategy_id, signal.timestamp)

            # 追加写入信号
            with open(file_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writerow(signal.to_row())

            logger.debug(f"信号已保存：{signal.signal_id} -> {file_path}")
            return True

        except Exception as e:
            logger.error(f"保存信号失败：{e}")
            return False

    def save_batch(self, signals: List[Signal]) -> int:
        """
        批量保存信号

        Args:
            signals: Signal 对象列表

        Returns:
            成功保存的信号数量
        """
        # 按策略和日期分组
        grouped = defaultdict(list)
        for signal in signals:
            key = (signal.strategy_id, signal.timestamp.date())
            grouped[key].append(signal)

        count = 0
        try:
            for (strategy_id, date), signal_list in grouped.items():
                file_path = self._get_file_path(strategy_id, datetime.combine(date, datetime.min.time()))
                self._init_csv_file(strategy_id, datetime.combine(date, datetime.min.time()))

                with open(file_path, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                    for signal in signal_list:
                        writer.writerow(signal.to_row())
                        count += 1

            return count

        except Exception as e:
            logger.error(f"批量保存信号失败：{e}")
            return count

    def get_signals(
        self,
        strategy_id: Optional[str] = None,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Signal]:
        """
        查询信号

        Args:
            strategy_id: 策略 ID
            symbol: 交易标的
            start_time: 开始时间
            end_time: 结束时间
            limit: 返回数量限制

        Returns:
            Signal 对象列表
        """
        signals = []

        # 确定要读取的日期范围
        if start_time is None:
            start_time = datetime.now(timezone.utc) - timedelta(days=365)
        if end_time is None:
            end_time = datetime.now(timezone.utc)

        current_date = start_time.date()
        end_date = end_time.date()

        # 确定要读取的策略
        strategies_to_read = []
        if strategy_id:
            strategies_to_read = [strategy_id]
        else:
            # 读取所有策略目录
            if self.base_dir.exists():
                strategies_to_read = [
                    d.name for d in self.base_dir.iterdir()
                    if d.is_dir() and not d.name.startswith('_')
                ]

        # 遍历每个策略和日期读取 CSV 文件
        for strat_id in strategies_to_read:
            strategy_dir = self.base_dir / strat_id
            if not strategy_dir.exists():
                continue

            while current_date <= end_date:
                file_path = strategy_dir / f"{current_date.strftime('%Y%m%d')}.csv"

                if file_path.exists():
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            reader = csv.DictReader(f)
                            for row in reader:
                                signal = Signal.from_row(row)

                                # 过滤条件
                                if symbol and signal.symbol != symbol:
                                    continue
                                if signal.timestamp < start_time or signal.timestamp > end_time:
                                    continue

                                signals.append(signal)
                    except Exception as e:
                        logger.warning(f"读取 CSV 文件失败 {file_path}: {e}")

                current_date += timedelta(days=1)

            current_date = start_time.date()

        # 按时间倒序排序并限制数量
        signals.sort(key=lambda s: s.timestamp, reverse=True)
        return signals[:limit] if limit > 0 else signals

    def get_statistics(
        self,
        strategy_id: str,
        period: str = "7d"
    ) -> Dict[str, Any]:
        """
        获取信号统计

        Args:
            strategy_id: 策略 ID
            period: 统计周期 (7d, 30d, etc.)

        Returns:
            统计信息字典
        """
        # 解析周期
        days = int(period.replace('d', ''))
        start_time = datetime.now(timezone.utc) - timedelta(days=days)

        signals = self.get_signals(
            strategy_id=strategy_id,
            start_time=start_time,
            limit=10000
        )

        if not signals:
            return {
                "total": 0,
                "buy_count": 0,
                "sell_count": 0,
                "flat_count": 0,
                "avg_strength": 0,
                "avg_price": 0
            }

        buy_count = sum(1 for s in signals if s.signal_type == SignalType.BUY)
        sell_count = sum(1 for s in signals if s.signal_type == SignalType.SELL)
        flat_count = sum(1 for s in signals if s.signal_type == SignalType.FLAT)

        return {
            "total": len(signals),
            "buy_count": buy_count,
            "sell_count": sell_count,
            "flat_count": flat_count,
            "avg_strength": sum(s.strength for s in signals) / len(signals),
            "avg_price": sum(s.price for s in signals) / len(signals),
            "period": period
        }

    def delete_old_signals(self, retention_days: int = 90) -> int:
        """
        删除过期信号文件

        Args:
            retention_days: 保留天数

        Returns:
            删除的文件数量
        """
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        deleted_count = 0

        if not self.base_dir.exists():
            return 0

        # 遍历所有策略目录
        for strategy_dir in self.base_dir.iterdir():
            if not strategy_dir.is_dir():
                continue

            # 遍历所有 CSV 文件
            for csv_file in strategy_dir.glob("*.csv"):
                try:
                    # 从文件名提取日期
                    date_str = csv_file.stem  # 例如 "20240101"
                    file_date = datetime.strptime(date_str, "%Y%m%d")

                    if file_date < cutoff_date:
                        csv_file.unlink()
                        deleted_count += 1
                        logger.info(f"删除过期信号文件：{csv_file}")

                except ValueError as e:
                    logger.warning(f"无法解析文件名日期：{csv_file.name}, {e}")
                except Exception as e:
                    logger.error(f"删除文件失败 {csv_file}: {e}")

        return deleted_count

    def clear(self, strategy_id: Optional[str] = None):
        """
        清空信号

        Args:
            strategy_id: 如果指定，只清空该策略的信号
        """
        try:
            if strategy_id:
                # 清空指定策略的信号
                strategy_dir = self.base_dir / strategy_id
                if strategy_dir.exists():
                    for csv_file in strategy_dir.glob("*.csv"):
                        csv_file.unlink()
                    logger.info(f"清空策略 {strategy_id} 的信号文件")
            else:
                # 清空所有信号
                if self.base_dir.exists():
                    for strategy_dir in self.base_dir.iterdir():
                        if strategy_dir.is_dir():
                            for csv_file in strategy_dir.glob("*.csv"):
                                csv_file.unlink()
                    logger.info("清空所有信号文件")

        except Exception as e:
            logger.error(f"清空信号失败：{e}")

    def get_signal_files(self, strategy_id: Optional[str] = None) -> List[Path]:
        """
        获取信号文件列表

        Args:
            strategy_id: 策略 ID，如果指定只返回该策略的文件

        Returns:
            CSV 文件路径列表
        """
        files = []

        if strategy_id:
            strategy_dir = self.base_dir / strategy_id
            if strategy_dir.exists():
                files = sorted(strategy_dir.glob("*.csv"))
        else:
            for strategy_dir in self.base_dir.iterdir():
                if strategy_dir.is_dir():
                    files.extend(sorted(strategy_dir.glob("*.csv")))

        return files


class SignalLogger:
    """
    信号日志器

    封装 SignalStorage，提供便捷的信号记录接口。
    可选集成 Kafka Producer / HTTP Sender 用于实时推送信号。
    可选启用 JSON 本地备份。
    """

    def __init__(
        self,
        storage: SignalStorage,
        kafka_producer=None,
        http_endpoint: Optional[str] = None,
        http_api_path: Optional[str] = None,
        json_backup_dir: Optional[str] = None,
        kafka_topic: Optional[str] = None,
    ):
        """
        初始化信号日志器

        Args:
            storage: SignalStorage 实例
            kafka_producer: 可选的 KafkaSignalProducer 实例
            http_endpoint: 可选的 HTTP 端点 (如 http://127.0.0.1:8888)
            http_api_path: 可选的 API 路径 (如 /api/v2/signals，默认 /api/v1/kafka/message)
            json_backup_dir: 可选的 JSON 本地备份目录
            kafka_topic: Kafka topic 名称（用于 HTTP 发送）
        """
        self.storage = storage
        self.kafka_producer = kafka_producer
        self.json_backup_dir = json_backup_dir
        self.kafka_topic = kafka_topic

        # 初始化 HTTP 发送器（延迟导入避免 requests 依赖问题）
        self._http_sender = None
        if http_endpoint:
            from .http_sender import HttpSignalSender
            self._http_sender = HttpSignalSender(
                base_url=http_endpoint,
                api_path=http_api_path,
            )

    def _write_json_backup(self, signal: Signal, strategy_name: str = "", **params):
        """将信号写入本地 JSON 文件（失败不阻断）"""
        if not self.json_backup_dir:
            return
        try:
            cta = CtaSignalCSV.from_signal(signal, strategy_name=strategy_name, **params)
            data = cta.to_json()

            # 路径: {json_backup_dir}/{strategy_name}/{timestamp}-{signal_id}.json
            ts_str = signal.timestamp.strftime("%Y%m%d_%H%M%S")
            if strategy_name:
                base = Path(self.json_backup_dir) / strategy_name
            else:
                base = Path(self.json_backup_dir)
            base.mkdir(parents=True, exist_ok=True)

            filename = f"{ts_str}-{signal.signal_id}.json"
            file_path = base / filename

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            logger.debug(f"JSON 备份已保存: {file_path}")

        except Exception as e:
            logger.warning(f"JSON 备份失败: {signal.signal_id}, 错误: {e}")

    def log_signal(
        self,
        signal: Signal,
        strategy_name: str = "",
        strategy_params: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        推送信号：优先 HTTP → 降级 Kafka → 始终 CSV（由引擎处理）
        同时可选写入 JSON 本地备份。

        Args:
            signal: Signal 对象
            strategy_name: 策略名称（用于 JSON 备份子目录）
            strategy_params: 可选的策略配置参数

        Returns:
            是否至少通过一种方式成功推送
        """
        # 1. JSON 本地备份（始终尝试，失败不阻断）
        self._write_json_backup(signal, strategy_name, **(strategy_params or {}))

        # 2. HTTP 发送（如果启用）
        if self._http_sender:
            try:
                # 使用配置的 kafka_topic，或从 strategy_params 获取，或默认值
                topic = self.kafka_topic or (strategy_params or {}).get("topic", "strategy_signals")
                # 传递时去掉 topic 避免重复
                http_params = {k: v for k, v in (strategy_params or {}).items() if k != "topic"}
                http_ok = self._http_sender.send_signal(
                    signal, topic=topic, **http_params,
                )
                if http_ok:
                    return True
                logger.warning(f"HTTP 发送失败，降级到 Kafka: {signal.signal_id}")
            except Exception as e:
                logger.warning(f"HTTP 发送异常，降级到 Kafka: {signal.signal_id}, 错误: {e}")

        # 3. Kafka 推送（降级路径）
        if self.kafka_producer and self.kafka_producer.is_available():
            try:
                params = strategy_params or {}
                self.kafka_producer.send_signal(signal, **params)
                return True
            except Exception as e:
                logger.warning(f"Kafka 推送失败: {signal.signal_id}, 错误: {e}")
                return False

        return True

    def log_cta_signal(self, cta_signal, topic: Optional[str] = None) -> bool:
        """
        统一发送 CtaSignalCSV 对象

        Args:
            cta_signal: 已生成的 CtaSignalCSV 对象
            topic: Kafka topic（可选，默认使用配置的 kafka_topic）

        Returns:
            是否发送成功
        """
        # 1. HTTP 发送（如果启用）
        if self._http_sender:
            try:
                send_topic = topic or self.kafka_topic or "strategy_signals"
                http_ok = self._http_sender.send_cta_signal(cta_signal, topic=send_topic)
                if http_ok:
                    return True
                logger.warning(f"HTTP 发送失败，降级到 Kafka: {cta_signal.signal_id}")
            except Exception as e:
                logger.warning(f"HTTP 发送异常，降级到 Kafka: {cta_signal.signal_id}, 错误: {e}")

        # 2. Kafka 推送（降级路径）
        if self.kafka_producer and self.kafka_producer.is_available():
            try:
                return self.kafka_producer.send_cta_signal(cta_signal)
            except Exception as e:
                logger.warning(f"Kafka 推送失败: {cta_signal.signal_id}, 错误: {e}")
                return False

        return True

    def get_signals(
        self,
        strategy_id: Optional[str] = None,
        symbol: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100
    ) -> List[Signal]:
        """查询信号"""
        return self.storage.get_signals(strategy_id, symbol, start_time, end_time, limit)

    def get_statistics(self, strategy_id: str, period: str = "7d") -> Dict[str, Any]:
        """获取统计信息"""
        return self.storage.get_statistics(strategy_id, period)
