#!/usr/bin/env python3
"""
测试 SignalLogger 的 JSON 本地备份和 HTTP 发送功能
"""

import json
import tempfile
import shutil
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.logger import SignalLogger, SignalStorage


def _make_signal() -> Signal:
    return Signal(
        signal_id="test-signal-001",
        strategy_id="Dolphinv2_15m_SOLUSDT",
        signal_type=SignalType.BUY,
        symbol="SOLUSDT",
        price=88.5,
        strength=0.8,
        direction="long",
        timestamp=datetime(2026, 5, 8, 1, 43, 0, tzinfo=timezone.utc),
        metadata={"adx": 25.0, "reason": "breakout"},
    )


class TestJsonLocalBackup:
    """测试 JSON 本地备份功能"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.storage = MagicMock(spec=SignalStorage)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_logger(self, json_backup_dir: str | None = None, kafka_producer=None):
        return SignalLogger(
            storage=self.storage,
            kafka_producer=kafka_producer,
            json_backup_dir=json_backup_dir,
        )

    def test_json_backup_creates_file(self):
        """启用 JSON 备份时，应在指定目录创建文件"""
        logger = self._make_logger(json_backup_dir=self.tmpdir)
        signal = _make_signal()

        logger.log_signal(signal, strategy_params={"threshold": 0.005})

        # 查找创建的 JSON 文件
        json_files = list(Path(self.tmpdir).rglob("*.json"))
        assert len(json_files) == 1
        assert "test-signal-001" in json_files[0].name

        # 验证内容
        with open(json_files[0]) as f:
            data = json.load(f)
        assert data["symbol"] == "SOLUSDT"
        assert data["signal"]["side"] == 1  # buy
        assert data["signal"]["trigger_price"] == 88.5

    def test_json_backup_disabled(self):
        """未启用 JSON 备份时，不应创建文件"""
        logger = self._make_logger(json_backup_dir=None)
        signal = _make_signal()

        logger.log_signal(signal)

        json_files = list(Path(self.tmpdir).rglob("*.json"))
        assert len(json_files) == 0

    def test_json_backup_does_not_block_on_failure(self):
        """JSON 备份失败不应阻断 Kafka 推送"""
        logger = self._make_logger(json_backup_dir="/nonexistent/invalid/path")
        signal = _make_signal()

        kafka_mock = MagicMock()
        kafka_mock.is_available.return_value = True
        logger.kafka_producer = kafka_mock

        # 不应抛出异常
        result = logger.log_signal(signal)

        # Kafka 推送应正常执行
        kafka_mock.send_signal.assert_called_once()

    def test_json_backup_with_strategy_subdir(self):
        """JSON 文件应存储在 data/signals/{strategy_name}/ 下"""
        logger = self._make_logger(json_backup_dir=self.tmpdir)
        signal = _make_signal()

        logger.log_signal(signal, strategy_name="Dolphinv2_15m_SOLUSDT",
                          strategy_params={"threshold": 0.005})

        # 文件应在策略子目录下
        json_files = list(Path(self.tmpdir).rglob("*.json"))
        assert len(json_files) == 1
        # 路径应包含策略名称
        assert "Dolphinv2_15m_SOLUSDT" in str(json_files[0])


class TestHttpSignalSender:
    """测试 HTTP 信号发送器"""

    def test_send_signal_posts_to_endpoint(self):
        """HTTP 发送器应向指定端点 POST 数据"""
        from strategy_core.signal_logging.http_sender import HttpSignalSender

        signal = _make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)

            sender = HttpSignalSender(base_url="http://127.0.0.1:8888")
            result = sender.send_signal(signal, topic="signal-topic")

            assert result is True
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args.kwargs["url"] == "http://127.0.0.1:8888/api/v1/kafka/message"
            body = json.loads(call_args.kwargs["data"])
            assert body["topic"] == "signal-topic"
            assert "message" in body

    def test_send_signal_returns_false_on_failure(self):
        """HTTP 请求失败应返回 False"""
        from strategy_core.signal_logging.http_sender import HttpSignalSender

        signal = _make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_post.side_effect = Exception("connection refused")

            sender = HttpSignalSender(base_url="http://127.0.0.1:8888")
            result = sender.send_signal(signal, topic="signal-topic")

            assert result is False

    def test_send_signal_returns_false_on_non_2xx(self):
        """HTTP 返回非 2xx 状态码应返回 False"""
        from strategy_core.signal_logging.http_sender import HttpSignalSender

        signal = _make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=500)

            sender = HttpSignalSender(base_url="http://127.0.0.1:8888")
            result = sender.send_signal(signal, topic="signal-topic")

            assert result is False


class TestSignalLoggerHttpIntegration:
    """测试 SignalLogger 的 HTTP 发送集成"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.storage = MagicMock(spec=SignalStorage)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_log_signal_uses_http(self):
        """当配置 http_endpoint 时，log_signal 应通过 HTTP 发送"""
        from strategy_core.signal_logging.http_sender import HttpSignalSender

        with patch.object(HttpSignalSender, "send_signal", return_value=True) as mock_send:
            logger = SignalLogger(
                storage=self.storage,
                http_endpoint="http://127.0.0.1:8888",
                json_backup_dir=self.tmpdir,
            )
            signal = _make_signal()
            logger.log_signal(signal, strategy_name="TestStrategy",
                              strategy_params={"threshold": 0.005})

            mock_send.assert_called_once()

    def test_log_signal_fallback_to_kafka_when_http_fails(self):
        """HTTP 失败时应降级到 Kafka"""
        from strategy_core.signal_logging.http_sender import HttpSignalSender

        kafka_mock = MagicMock()
        kafka_mock.is_available.return_value = True

        with patch.object(HttpSignalSender, "send_signal", return_value=False) as mock_http:
            logger = SignalLogger(
                storage=self.storage,
                http_endpoint="http://127.0.0.1:8888",
                json_backup_dir=self.tmpdir,
                kafka_producer=kafka_mock,
            )
            signal = _make_signal()
            logger.log_signal(signal, strategy_name="TestStrategy",
                              strategy_params={"threshold": 0.005})

            mock_http.assert_called_once()
            kafka_mock.send_signal.assert_called_once()
