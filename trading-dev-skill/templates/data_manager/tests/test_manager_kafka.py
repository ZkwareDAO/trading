# NOTE: IP addresses in this test are mock values, not real endpoints
#!/usr/bin/env python3
"""
DataManager Kafka 集成测试

测试 DataManager 的 Kafka 相关功能:
- init_kafka_consumer
- subscribe_klines_async (Kafka 模式)
- get_realtime_status
- stop_realtime
"""

import asyncio
import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from pathlib import Path

from data_manager import DataManager, DataManagerConfig


class TestDataManagerKafkaConfig:
    """测试 DataManagerConfig 的 Kafka 配置"""

    def test_default_kafka_disabled(self):
        """测试默认 Kafka 禁用"""
        config = DataManagerConfig()
        assert config.kafka_enabled is False
        assert config.kafka_brokers == []
        assert config.kafka_topic == "biance_klines"
        assert config.kafka_group_id is None

    def test_kafka_enabled_config(self):
        """测试启用 Kafka 配置"""
        config = DataManagerConfig(
            kafka_enabled=True,
            kafka_brokers=["127.0.0.1:9092"],
            kafka_topic="test_klines",
            kafka_group_id="test-group",
        )
        assert config.kafka_enabled is True
        assert config.kafka_brokers == ["127.0.0.1:9092"]
        assert config.kafka_topic == "test_klines"
        assert config.kafka_group_id == "test-group"

    def test_kafka_brokers_default_empty(self):
        """测试 kafka_brokers 默认为空列表"""
        config = DataManagerConfig()
        assert config.kafka_brokers == []
        assert isinstance(config.kafka_brokers, list)


class TestDataManagerKafkaInit:
    """测试 DataManager 的 Kafka 初始化"""

    def test_data_manager_with_kafka_config(self):
        """测试 DataManager 使用 Kafka 配置初始化"""
        config = DataManagerConfig(
            csv_dir="./data/test_klines",
            kafka_enabled=True,
            kafka_brokers=["localhost:9092"],
            kafka_topic="test_klines",
        )
        dm = DataManager(config)

        assert dm.config.kafka_enabled is True
        assert dm._kafka_consumer is None
        assert dm._kafka_enabled is False

    def test_data_manager_realtime_status_none(self):
        """测试无实时数据源时的状态"""
        config = DataManagerConfig(csv_dir="./data/test_klines")
        dm = DataManager(config)

        status = dm.get_realtime_status()

        assert status["mode"] == "none"
        assert status["connected"] is False


class TestDataManagerInitKafkaConsumer:
    """测试 init_kafka_consumer 方法"""

    def test_init_kafka_consumer_no_brokers(self):
        """测试无 brokers 时跳过初始化"""
        config = DataManagerConfig(
            csv_dir="./data/test_klines",
            kafka_enabled=True,
            kafka_brokers=[],
        )
        dm = DataManager(config)

        result = asyncio.run(dm.init_kafka_consumer())

        assert result is False
        assert dm._kafka_consumer is None

    @patch('data_manager.kafka_consumer.KlineKafkaConsumer')
    def test_init_kafka_consumer_success(self, mock_consumer_class):
        """测试成功初始化 Kafka 消费者"""
        mock_consumer = MagicMock()
        mock_consumer.is_connected = False
        mock_consumer.connect.return_value = True
        mock_consumer.start_consume = AsyncMock(return_value=True)
        mock_consumer_class.return_value = mock_consumer

        config = DataManagerConfig(
            csv_dir="./data/test_klines",
            kafka_enabled=True,
            kafka_brokers=["localhost:9092"],
            kafka_topic="test_klines",
            kafka_group_id="test-group",
        )
        dm = DataManager(config)

        result = asyncio.run(dm.init_kafka_consumer())

        assert result is True
        assert dm._kafka_enabled is True
        mock_consumer_class.assert_called_once_with(
            brokers=["localhost:9092"],
            topic="test_klines",
            group_id="test-group",
        )

    @patch('data_manager.kafka_consumer.KlineKafkaConsumer')
    def test_init_kafka_consumer_already_connected(self, mock_consumer_class):
        """测试已连接时跳过重复初始化"""
        mock_consumer = MagicMock()
        mock_consumer.is_connected = True
        mock_consumer_class.return_value = mock_consumer

        config = DataManagerConfig(
            csv_dir="./data/test_klines",
            kafka_brokers=["localhost:9092"],
        )
        dm = DataManager(config)
        dm._kafka_consumer = mock_consumer

        result = asyncio.run(dm.init_kafka_consumer())

        assert result is True
        # 不应创建新的 consumer
        mock_consumer_class.assert_not_called()

    @patch('data_manager.kafka_consumer.KlineKafkaConsumer')
    def test_init_kafka_consumer_connect_failure(self, mock_consumer_class):
        """测试连接失败"""
        mock_consumer = MagicMock()
        mock_consumer.is_connected = False
        mock_consumer.connect.return_value = False
        mock_consumer_class.return_value = mock_consumer

        config = DataManagerConfig(
            csv_dir="./data/test_klines",
            kafka_brokers=["localhost:9092"],
        )
        dm = DataManager(config)

        result = asyncio.run(dm.init_kafka_consumer())

        assert result is False
        assert dm._kafka_enabled is False


class TestDataManagerSubscribeKlinesKafka:
    """测试 Kafka 模式的订阅"""

    def test_subscribe_klines_kafka_mode(self):
        """测试 Kafka 模式订阅"""
        config = DataManagerConfig(
            csv_dir="./data/test_klines",
            kafka_enabled=True,
        )
        dm = DataManager(config)

        # 模拟已启用的 Kafka 消费者
        mock_consumer = MagicMock()
        mock_consumer.add_symbols = Mock()
        dm._kafka_consumer = mock_consumer
        dm._kafka_enabled = True

        result = asyncio.run(dm.subscribe_klines_async(["BTCUSDT", "ETHUSDT"]))

        assert result is True
        mock_consumer.add_symbols.assert_called_once_with(["BTCUSDT", "ETHUSDT"])

    def test_subscribe_klines_no_data_source(self):
        """测试无数据源时订阅失败"""
        config = DataManagerConfig(csv_dir="./data/test_klines")
        dm = DataManager(config)

        result = asyncio.run(dm.subscribe_klines_async(["BTCUSDT"]))

        assert result is False


class TestDataManagerStopRealtime:
    """测试停止实时数据服务"""

    def test_stop_realtime_kafka(self):
        """测试停止 Kafka"""
        config = DataManagerConfig(csv_dir="./data/test_klines")
        dm = DataManager(config)

        mock_consumer = MagicMock()
        mock_consumer.disconnect = Mock()
        dm._kafka_consumer = mock_consumer
        dm._kafka_enabled = True
        dm._connected = True

        asyncio.run(dm.stop_realtime())

        mock_consumer.disconnect.assert_called_once()
        assert dm._kafka_consumer is None
        assert dm._kafka_enabled is False
        assert dm._connected is False


class TestDataManagerGetRealtimeStatus:
    """测试获取实时数据状态"""

    def test_get_realtime_status_kafka(self):
        """测试获取 Kafka 状态"""
        config = DataManagerConfig(csv_dir="./data/test_klines")
        dm = DataManager(config)

        mock_consumer = MagicMock()
        mock_consumer.is_connected = True
        mock_consumer.is_running = True
        mock_consumer.subscribed_symbols = {"BTCUSDT", "ETHUSDT"}
        mock_consumer.brokers = ["localhost:9092"]
        mock_consumer.topic = "test_klines"
        mock_consumer.group_id = "test-group"
        dm._kafka_consumer = mock_consumer
        dm._kafka_enabled = True

        status = dm.get_realtime_status()

        assert status["mode"] == "kafka"
        assert status["connected"] is True
        assert status["running"] is True
        assert "BTCUSDT" in status["subscribed_symbols"]
        assert status["brokers"] == ["localhost:9092"]
        assert status["topic"] == "test_klines"

    def test_get_realtime_status_websocket(self):
        """测试获取 WebSocket 状态"""
        config = DataManagerConfig(csv_dir="./data/test_klines")
        dm = DataManager(config)

        mock_ws = MagicMock()
        mock_ws._connected = True
        dm._ws_client = mock_ws
        dm._ws_subscribed_symbols = {"BTCUSDT"}

        status = dm.get_realtime_status()

        assert status["mode"] == "websocket"
        assert status["connected"] is True
        assert "BTCUSDT" in status["subscribed_symbols"]


class TestDataManagerStartKlinesService:
    """测试 start_klines_service_async 方法"""

    @patch('data_manager.kafka_consumer.KlineKafkaConsumer')
    def test_start_klines_service_prefers_kafka(self, mock_consumer_class):
        """测试优先使用 Kafka"""
        mock_consumer = MagicMock()
        mock_consumer.is_connected = False
        mock_consumer.connect.return_value = True
        mock_consumer.start_consume = AsyncMock(return_value=True)
        mock_consumer_class.return_value = mock_consumer

        config = DataManagerConfig(
            csv_dir="./data/test_klines",
            kafka_enabled=True,
            kafka_brokers=["localhost:9092"],
        )
        dm = DataManager(config)

        result = asyncio.run(dm.start_klines_service_async())

        assert result is True
        assert dm._kafka_enabled is True

    def test_start_klines_service_kafka_disabled(self):
        """测试 Kafka 禁用时回退到 WebSocket"""
        config = DataManagerConfig(
            csv_dir="./data/test_klines",
            kafka_enabled=False,
            klines_service_enabled=False,
        )
        dm = DataManager(config)

        result = asyncio.run(dm.start_klines_service_async())

        assert result is False
