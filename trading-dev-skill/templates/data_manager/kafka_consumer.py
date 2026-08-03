#!/usr/bin/env python3
"""
Kline Kafka 消费者模块

从 Kafka topic 订阅 K 线数据，按 symbol 过滤
"""

import asyncio
import json
import logging
from typing import Optional, Callable, List, Set, Dict, Any

from data_manager.klines_data import Kline

logger = logging.getLogger(__name__)


class KlineKafkaConsumer:
    """
    Kafka K线消费者

    功能:
    - 订阅 Kafka topic
    - 按 symbol 过滤消息
    - 支持动态添加/移除 symbol
    - 异步消费循环
    """

    def __init__(
        self,
        brokers: List[str],
        topic: str = "biance_klines",
        group_id: Optional[str] = None,
        symbols: Optional[Set[str]] = None,
    ):
        """
        初始化 Kafka 消费者

        Args:
            brokers: Kafka broker 地址列表
            topic: Kafka topic 名称
            group_id: Consumer Group ID (建议使用策略 ID)
            symbols: 初始订阅的 symbol 集合
        """
        self.brokers = brokers
        self.topic = topic
        self.group_id = group_id or "cta-strategy-default"
        self.symbols: Set[str] = symbols.copy() if symbols else set()

        self._consumer = None
        self._running = False
        self._connected = False
        self._on_kline_callback: Optional[Callable] = None
        self._consume_task: Optional[asyncio.Task] = None

    def set_on_kline_callback(self, callback: Callable):
        """设置 K 线数据回调"""
        self._on_kline_callback = callback

    def add_symbol(self, symbol: str):
        """添加订阅的 symbol"""
        self.symbols.add(symbol.upper())

    def remove_symbol(self, symbol: str):
        """移除订阅的 symbol"""
        self.symbols.discard(symbol.upper())

    def add_symbols(self, symbols: List[str]):
        """批量添加 symbol"""
        for s in symbols:
            self.symbols.add(s.upper())

    @property
    def subscribed_symbols(self) -> Set[str]:
        """返回当前订阅的 symbol 集合（副本）"""
        return self.symbols.copy()

    def connect(self) -> bool:
        """
        连接 Kafka

        Returns:
            是否连接成功
        """
        try:
            from kafka import KafkaConsumer

            self._consumer = KafkaConsumer(
                self.topic,
                bootstrap_servers=self.brokers,
                group_id=self.group_id,
                auto_offset_reset='latest',
                enable_auto_commit=True,
                auto_commit_interval_ms=1000,
                value_deserializer=lambda m: json.loads(m.decode('utf-8')),
                key_deserializer=lambda m: m.decode('utf-8') if m else None,
                consumer_timeout_ms=100,  # 非阻塞 poll
            )
            self._connected = True
            logger.info(
                f"Kafka 连接成功: brokers={self.brokers}, "
                f"topic={self.topic}, group_id={self.group_id}"
            )
            return True

        except ImportError:
            logger.error("kafka-python 未安装，请运行: pip install kafka-python")
            return False
        except Exception as e:
            logger.error(f"Kafka 连接失败: {e}")
            self._connected = False
            return False

    def disconnect(self):
        """断开 Kafka 连接"""
        self._running = False

        if self._consume_task:
            self._consume_task.cancel()
            self._consume_task = None

        if self._consumer:
            self._consumer.close()
            self._consumer = None

        self._connected = False
        logger.info("Kafka 已断开")

    async def start_consume(self):
        """启动异步消费循环"""
        if not self._connected:
            logger.warning("Kafka 未连接，无法启动消费")
            return False

        self._running = True
        self._consume_task = asyncio.create_task(self._consume_loop())
        logger.info("Kafka 消费循环已启动")
        return True

    async def stop_consume(self):
        """停止消费循环"""
        self._running = False
        if self._consume_task:
            self._consume_task.cancel()
            try:
                await self._consume_task
            except asyncio.CancelledError:
                pass
            self._consume_task = None

    async def _consume_loop(self):
        """
        消费循环（异步）

        使用 poll + asyncio.sleep 实现异步兼容
        """
        consecutive_errors = 0
        max_consecutive_errors = 10

        while self._running:
            try:
                # poll 是同步调用，timeout_ms 控制阻塞时间
                messages = self._consumer.poll(timeout_ms=100)

                for topic_partition, records in messages.items():
                    for record in records:
                        await self._process_message(record.value)

                consecutive_errors = 0  # 重置错误计数
                # 让出控制权，避免阻塞事件循环
                await asyncio.sleep(0)

            except Exception as e:
                consecutive_errors += 1
                logger.error(f"Kafka 消费异常 ({consecutive_errors}/{max_consecutive_errors}): {e}")

                if consecutive_errors >= max_consecutive_errors:
                    logger.critical("Kafka 连续错误过多，停止消费")
                    self._running = False
                    break

                # 指数退避，最大 30 秒
                backoff = min(1 * (2 ** (consecutive_errors - 1)), 30)
                await asyncio.sleep(backoff)

    async def _process_message(self, data: Dict[str, Any]):
        """
        处理单条消息

        Args:
            data: K 线数据字典
        """
        try:
            # 按 symbol 过滤
            symbol = data.get('symbol', '')
            if self.symbols and symbol.upper() not in self.symbols:
                return

            # 转换为 Kline 对象并调用回调
            kline = Kline.from_dict(data)
            if self._on_kline_callback:
                await self._call_callback(kline)

        except Exception as e:
            logger.error(f"处理 K 线消息失败: {e}")

    async def _call_callback(self, kline: Kline):
        """调用回调（支持同步和异步）"""
        if asyncio.iscoroutinefunction(self._on_kline_callback):
            await self._on_kline_callback(kline)
        else:
            self._on_kline_callback(kline)

    @property
    def is_connected(self) -> bool:
        """是否已连接"""
        return self._connected and self._consumer is not None

    @property
    def is_running(self) -> bool:
        """是否正在消费"""
        return self._running
