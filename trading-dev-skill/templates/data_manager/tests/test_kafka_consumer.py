# NOTE: IP addresses in this test are mock values, not real endpoints
#!/usr/bin/env python3
"""
KlineKafkaConsumer 单元测试

测试 Kafka 消费者的核心功能:
- 连接/断开
- symbol 过滤
- 消息处理
- 异步消费循环
"""

import asyncio
import json
import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime, timezone

from data_manager.klines_data import Kline


class TestKlineKafkaConsumerInit:
    """测试 KlineKafkaConsumer 初始化"""

    def test_init_with_defaults(self):
        """测试默认参数初始化"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(
            brokers=["localhost:9092"],
            topic="test_klines",
        )

        assert consumer.brokers == ["localhost:9092"]
        assert consumer.topic == "test_klines"
        assert consumer.group_id == "cta-strategy-default"
        assert consumer.symbols == set()
        assert consumer._consumer is None
        assert consumer._connected is False
        assert consumer._running is False

    def test_init_with_custom_params(self):
        """测试自定义参数初始化"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(
            brokers=["127.0.0.1:9092", "127.0.0.1:9092"],
            topic="biance_klines",
            group_id="strategy-cta_ict_v2-BTCUSDT-4h",
            symbols={"BTCUSDT", "ETHUSDT"},
        )

        assert consumer.brokers == ["127.0.0.1:9092", "127.0.0.1:9092"]
        assert consumer.topic == "biance_klines"
        assert consumer.group_id == "strategy-cta_ict_v2-BTCUSDT-4h"
        assert consumer.symbols == {"BTCUSDT", "ETHUSDT"}


class TestKlineKafkaConsumerSymbolManagement:
    """测试 symbol 管理"""

    def test_add_symbol(self):
        """测试添加单个 symbol"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(brokers=["localhost:9092"])
        consumer.add_symbol("BTCUSDT")
        consumer.add_symbol("btcusdt")  # 测试大小写不敏感

        assert consumer.symbols == {"BTCUSDT"}
        assert consumer.subscribed_symbols == {"BTCUSDT"}

    def test_add_symbols(self):
        """测试批量添加 symbol"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(brokers=["localhost:9092"])
        consumer.add_symbols(["BTCUSDT", "ETHUSDT", "SOLUSDT"])

        assert consumer.symbols == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

    def test_remove_symbol(self):
        """测试移除 symbol"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(
            brokers=["localhost:9092"],
            symbols={"BTCUSDT", "ETHUSDT"}
        )
        consumer.remove_symbol("BTCUSDT")

        assert consumer.symbols == {"ETHUSDT"}

    def test_remove_nonexistent_symbol(self):
        """测试移除不存在的 symbol（不应报错）"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(
            brokers=["localhost:9092"],
            symbols={"BTCUSDT"}
        )
        consumer.remove_symbol("ETHUSDT")  # 不存在

        assert consumer.symbols == {"BTCUSDT"}


class TestKlineKafkaConsumerConnection:
    """测试 Kafka 连接"""

    def test_connect_success(self):
        """测试连接成功"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        # Mock kafka.KafkaConsumer (在模块级别)
        with patch('kafka.KafkaConsumer') as mock_kafka_consumer_class:
            mock_consumer = MagicMock()
            mock_kafka_consumer_class.return_value = mock_consumer

            consumer = KlineKafkaConsumer(
                brokers=["localhost:9092"],
                topic="test_klines",
                group_id="test-group",
            )

            result = consumer.connect()

            assert result is True
            assert consumer.is_connected is True
            mock_kafka_consumer_class.assert_called_once()

    def test_connect_failure(self):
        """测试连接失败"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        with patch('kafka.KafkaConsumer', side_effect=Exception("Connection refused")):
            consumer = KlineKafkaConsumer(brokers=["localhost:9092"])
            result = consumer.connect()

            assert result is False
            assert consumer.is_connected is False

    def test_connect_missing_dependency(self):
        """测试缺少 kafka-python 依赖"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(brokers=["localhost:9092"])

        with patch.dict('sys.modules', {'kafka': None}):
            with patch('builtins.__import__', side_effect=ImportError("No module named 'kafka'")):
                result = consumer.connect()

        assert result is False

    def test_disconnect(self):
        """测试断开连接"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        with patch('kafka.KafkaConsumer') as mock_kafka_consumer_class:
            mock_consumer = MagicMock()
            mock_kafka_consumer_class.return_value = mock_consumer

            consumer = KlineKafkaConsumer(brokers=["localhost:9092"])
            consumer.connect()
            consumer.disconnect()

            mock_consumer.close.assert_called_once()
            assert consumer.is_connected is False


class TestKlineKafkaConsumerMessageProcessing:
    """测试消息处理"""

    def test_process_message_with_matching_symbol(self):
        """测试处理匹配 symbol 的消息"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(
            brokers=["localhost:9092"],
            symbols={"BTCUSDT"}
        )

        callback = Mock()
        consumer.set_on_kline_callback(callback)

        # 模拟 Kafka 消息
        message_data = {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "open": "50000.0",
            "high": "50100.0",
            "low": "49900.0",
            "close": "50050.0",
            "volume": "100.5",
            "quote_volume": "5025000.0",
            "trade_num": 1234,
            "active_buy_volume": "50.25",
            "active_buy_quote_volume": "2512500.0",
            "is_final": True,
            "start_time": 1712548800000,
            "end_time": 1712548860000,
        }

        # 运行异步处理
        async def run_test():
            await consumer._process_message(message_data)

        asyncio.run(run_test())

        # 验证回调被调用
        assert callback.called
        kline = callback.call_args[0][0]
        assert isinstance(kline, Kline)
        assert kline.symbol == "BTCUSDT"
        assert kline.interval == "1m"

    def test_process_message_with_non_matching_symbol(self):
        """测试过滤不匹配 symbol 的消息"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(
            brokers=["localhost:9092"],
            symbols={"BTCUSDT"}
        )

        callback = Mock()
        consumer.set_on_kline_callback(callback)

        message_data = {
            "symbol": "ETHUSDT",  # 不在订阅列表中
            "interval": "1m",
            "open": "3000.0",
            "high": "3050.0",
            "low": "2980.0",
            "close": "3020.0",
            "volume": "50.0",
            "quote_volume": "150000.0",
            "trade_num": 500,
            "active_buy_volume": "25.0",
            "active_buy_quote_volume": "75000.0",
            "is_final": True,
            "start_time": 1712548800000,
            "end_time": 1712548860000,
        }

        async def run_test():
            await consumer._process_message(message_data)

        asyncio.run(run_test())

        # 回调不应被调用
        assert not callback.called

    def test_process_message_with_empty_symbols_filter(self):
        """测试空 symbol 过滤器（接收所有消息）"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(
            brokers=["localhost:9092"],
            symbols=set()  # 空集合 = 接收所有
        )

        callback = Mock()
        consumer.set_on_kline_callback(callback)

        message_data = {
            "symbol": "ETHUSDT",
            "interval": "1m",
            "open": "3000.0",
            "high": "3050.0",
            "low": "2980.0",
            "close": "3020.0",
            "volume": "50.0",
            "quote_volume": "150000.0",
            "trade_num": 500,
            "active_buy_volume": "25.0",
            "active_buy_quote_volume": "75000.0",
            "is_final": True,
            "start_time": 1712548800000,
            "end_time": 1712548860000,
        }

        async def run_test():
            await consumer._process_message(message_data)

        asyncio.run(run_test())

        # 空过滤器时应该接收消息
        assert callback.called

    def test_process_message_async_callback(self):
        """测试异步回调"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(
            brokers=["localhost:9092"],
            symbols={"BTCUSDT"}
        )

        async_callback = AsyncMock()
        consumer.set_on_kline_callback(async_callback)

        message_data = {
            "symbol": "BTCUSDT",
            "interval": "1m",
            "open": "50000.0",
            "high": "50100.0",
            "low": "49900.0",
            "close": "50050.0",
            "volume": "100.5",
            "quote_volume": "5025000.0",
            "trade_num": 1234,
            "active_buy_volume": "50.25",
            "active_buy_quote_volume": "2512500.0",
            "is_final": True,
            "start_time": 1712548800000,
            "end_time": 1712548860000,
        }

        async def run_test():
            await consumer._process_message(message_data)

        asyncio.run(run_test())

        async_callback.assert_called_once()


class TestKlineKafkaConsumerConsumeLoop:
    """测试消费循环"""

    def test_consume_loop_processes_messages(self):
        """测试消费循环处理消息"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        # 模拟 Kafka Consumer
        with patch('kafka.KafkaConsumer') as mock_kafka_consumer_class:
            mock_consumer = MagicMock()
            mock_kafka_consumer_class.return_value = mock_consumer

            # 模拟 poll 返回消息
            from kafka import TopicPartition
            tp = TopicPartition("test_klines", 0)

            mock_record = MagicMock()
            mock_record.value = {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "open": "50000.0",
                "high": "50100.0",
                "low": "49900.0",
                "close": "50050.0",
                "volume": "100.5",
                "quote_volume": "5025000.0",
                "trade_num": 1234,
                "active_buy_volume": "50.25",
                "active_buy_quote_volume": "2512500.0",
                "is_final": True,
                "start_time": 1712548800000,
                "end_time": 1712548860000,
            }

            mock_consumer.poll.return_value = {tp: [mock_record]}

            # 创建消费者
            consumer = KlineKafkaConsumer(
                brokers=["localhost:9092"],
                topic="test_klines",
                symbols={"BTCUSDT"}
            )
            consumer.connect()

            callback = Mock()
            consumer.set_on_kline_callback(callback)

            # 运行消费循环（限制迭代次数）
            call_count = 0

            async def limited_consume():
                nonlocal call_count
                while call_count < 3:
                    messages = consumer._consumer.poll(timeout_ms=100)
                    for tp, records in messages.items():
                        for record in records:
                            await consumer._process_message(record.value)
                    await asyncio.sleep(0)
                    call_count += 1

            asyncio.run(limited_consume())

            # 验证回调被调用
            assert callback.called

    def test_start_consume(self):
        """测试启动消费循环"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        with patch('kafka.KafkaConsumer') as mock_kafka_consumer_class:
            mock_consumer = MagicMock()
            mock_kafka_consumer_class.return_value = mock_consumer
            mock_consumer.poll.return_value = {}

            consumer = KlineKafkaConsumer(brokers=["localhost:9092"])
            consumer.connect()

            result = asyncio.run(consumer.start_consume())

            assert result is True
            assert consumer.is_running is True
            assert consumer._consume_task is not None

            # 清理
            asyncio.run(consumer.stop_consume())

    def test_stop_consume(self):
        """测试停止消费循环"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        with patch('kafka.KafkaConsumer') as mock_kafka_consumer_class:
            mock_consumer = MagicMock()
            mock_kafka_consumer_class.return_value = mock_consumer
            mock_consumer.poll.return_value = {}

            consumer = KlineKafkaConsumer(brokers=["localhost:9092"])
            consumer.connect()
            asyncio.run(consumer.start_consume())

            # 停止
            asyncio.run(consumer.stop_consume())

            assert consumer.is_running is False
            assert consumer._consume_task is None


class TestKlineKafkaConsumerErrorHandling:
    """测试错误处理"""

    def test_process_message_with_invalid_data(self):
        """测试处理无效消息"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(
            brokers=["localhost:9092"],
            symbols={"BTCUSDT"}
        )

        callback = Mock()
        consumer.set_on_kline_callback(callback)

        # 缺少必要字段的消息
        invalid_message = {
            "symbol": "BTCUSDT",
            # 缺少 interval, open, close 等
        }

        async def run_test():
            await consumer._process_message(invalid_message)

        # 不应抛出异常
        asyncio.run(run_test())

    def test_consume_loop_handles_exception(self):
        """测试消费循环异常处理"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        with patch('kafka.KafkaConsumer') as mock_kafka_consumer_class:
            mock_consumer = MagicMock()
            mock_kafka_consumer_class.return_value = mock_consumer

            # poll 抛出异常
            mock_consumer.poll.side_effect = Exception("Kafka error")

            consumer = KlineKafkaConsumer(brokers=["localhost:9092"])
            consumer.connect()

            # 运行一次循环，不应崩溃
            call_count = 0

            async def limited_consume():
                nonlocal call_count
                while call_count < 2:
                    try:
                        messages = consumer._consumer.poll(timeout_ms=100)
                    except Exception:
                        pass
                    await asyncio.sleep(0.01)
                    call_count += 1

            asyncio.run(limited_consume())

            assert call_count == 2  # 循环继续运行


class TestKlineKafkaConsumerProperties:
    """测试属性方法"""

    def test_is_connected(self):
        """测试 is_connected 属性"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        with patch('kafka.KafkaConsumer') as mock_kafka_consumer_class:
            mock_consumer = MagicMock()
            mock_kafka_consumer_class.return_value = mock_consumer

            consumer = KlineKafkaConsumer(brokers=["localhost:9092"])

            assert consumer.is_connected is False

            consumer.connect()
            assert consumer.is_connected is True

            consumer.disconnect()
            assert consumer.is_connected is False

    def test_is_running(self):
        """测试 is_running 属性"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(brokers=["localhost:9092"])

        assert consumer.is_running is False

        consumer._running = True
        assert consumer.is_running is True

    def test_subscribed_symbols(self):
        """测试 subscribed_symbols 属性返回副本"""
        from data_manager.kafka_consumer import KlineKafkaConsumer

        consumer = KlineKafkaConsumer(
            brokers=["localhost:9092"],
            symbols={"BTCUSDT", "ETHUSDT"}
        )

        symbols = consumer.subscribed_symbols
        symbols.add("SOLUSDT")  # 修改副本

        # 原始集合不应改变
        assert "SOLUSDT" not in consumer.symbols