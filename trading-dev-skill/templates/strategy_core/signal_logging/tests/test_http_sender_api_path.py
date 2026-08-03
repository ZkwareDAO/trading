# NOTE: IP addresses in this test are mock values, not real endpoints
#!/usr/bin/env python3
"""
测试 HTTP 信号发送器支持配置 API 路径

验证：
1. HttpSignalSender 支持自定义 api_path 参数
2. 默认 api_path 为 /api/v1/kafka/message（向后兼容）
3. 配置的 api_path 正确拼接到 URL
4. run_strategy.py 读取 signal_hub.api_path 配置并传递给 SignalLogger
"""

import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import tempfile
import yaml

from strategy_core.signal_logging.http_sender import HttpSignalSender, RetryConfig
from strategy_core.signal_logging.storage import Signal, SignalType


class TestHttpSenderApiPath:
    """测试 HttpSignalSender 支持自定义 API 路径"""

    def _make_signal(self) -> Signal:
        return Signal(
            signal_id="test_api_path_001",
            strategy_id="RBreaker_v2_1m_BTCUSDT",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            strength=0.8,
            timestamp=datetime.now(timezone.utc),
        )

    def test_default_api_path_is_v1(self):
        """默认 api_path 应为 /api/v1/kafka/message（向后兼容）"""
        sender = HttpSignalSender(base_url="http://127.0.0.1:18888")
        assert sender.api_path == "/api/v1/kafka/message"

    def test_custom_api_path_v2(self, caplog):
        """支持自定义 api_path（v2 版本）"""
        sender = HttpSignalSender(
            base_url="http://127.0.0.1:18888",
            api_path="/api/v2/signals",
        )

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"status": "success"}'
            mock_post.return_value = mock_resp

            with caplog.at_level(logging.INFO, logger="strategy_core.signal_logging.http_sender"):
                result = sender.send_signal(signal, topic="strategy_signals")

        assert result is True
        # 验证 URL 使用了自定义 api_path
        call_args = mock_post.call_args
        assert call_args is not None
        called_url = call_args[1]["url"]
        assert called_url == "http://127.0.0.1:18888/api/v2/signals"

    def test_custom_api_path_v1(self, caplog):
        """显式指定 v1 路径"""
        sender = HttpSignalSender(
            base_url="http://127.0.0.1:18888",
            api_path="/api/v1/kafka/message",
        )

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"status": "success"}'
            mock_post.return_value = mock_resp

            with caplog.at_level(logging.INFO, logger="strategy_core.signal_logging.http_sender"):
                result = sender.send_signal(signal, topic="strategy_signals")

        assert result is True
        called_url = mock_post.call_args[1]["url"]
        assert called_url == "http://127.0.0.1:18888/api/v1/kafka/message"

    def test_url_construction_with_api_path(self, caplog):
        """验证 base_url + api_path 正确拼接"""
        sender = HttpSignalSender(
            base_url="http://127.0.0.1:18888/",  # 末尾有斜杠
            api_path="/api/v2/signals",
        )

        signal = self._make_signal()

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"status": "success"}'
            mock_post.return_value = mock_resp

            result = sender.send_signal(signal, topic="strategy_signals")

        assert result is True
        called_url = mock_post.call_args[1]["url"]
        # 不应有双斜杠
        assert called_url == "http://127.0.0.1:18888/api/v2/signals"


class TestRunStrategyReadsApiPath:
    """测试 run_strategy.py 读取 signal_hub.api_path 配置"""

    def test_reads_signal_hub_api_path_from_global_config(self, tmp_path):
        """从全局配置读取 signal_hub.api_path 并传递给 SignalLogger"""
        # 创建全局配置
        global_config = {
            "signal_hub": {
                "enabled": True,
                "endpoint": "http://127.0.0.1:8891",
                "api_path": "/api/v2/signals",
            },
            "signal_logging": {
                "storage": {"path": str(tmp_path / "signals")},
                "kafka": {"enabled": False},
            },
            "strategy_engine": {
                "factory_endpoint": "http://127.0.0.1:8888",
                "strategies_dir": str(tmp_path / "strategies"),
            },
        }
        config_file = tmp_path / "settings.yaml"
        with open(config_file, "w") as f:
            yaml.dump(global_config, f)

        # 创建策略配置
        strategy_dir = tmp_path / "strategies" / "test_strategy"
        strategy_dir.mkdir(parents=True)
        strategy_config = {"test_strategy": {"enabled": True, "symbols": ["BTCUSDT"]}}
        with open(strategy_dir / "config.yaml", "w") as f:
            yaml.dump(strategy_config, f)

        # 导入并创建 runner
        from run_strategy import StrategyProcessRunner

        with patch("run_strategy.SignalLogger") as mock_logger_class:
            mock_logger = MagicMock()
            mock_logger_class.return_value = mock_logger

            runner = StrategyProcessRunner(
                strategy_name="test_strategy",
                strategy_config=strategy_config["test_strategy"],
                global_config_path=str(config_file),
            )

            # 验证 SignalLogger 被调用时传入了 http_api_path
            mock_logger_class.assert_called_once()
            call_kwargs = mock_logger_class.call_args[1]
            assert "http_api_path" in call_kwargs
            assert call_kwargs["http_api_path"] == "/api/v2/signals"

    def test_default_api_path_when_not_configured(self, tmp_path):
        """未配置 api_path 时使用默认值"""
        global_config = {
            "signal_hub": {
                "enabled": True,
                "endpoint": "http://127.0.0.1:8891",
                # 无 api_path 配置
            },
            "signal_logging": {
                "storage": {"path": str(tmp_path / "signals")},
                "kafka": {"enabled": False},
            },
            "strategy_engine": {
                "factory_endpoint": "http://127.0.0.1:8888",
                "strategies_dir": str(tmp_path / "strategies"),
            },
        }
        config_file = tmp_path / "settings.yaml"
        with open(config_file, "w") as f:
            yaml.dump(global_config, f)

        strategy_dir = tmp_path / "strategies" / "test_strategy"
        strategy_dir.mkdir(parents=True)
        strategy_config = {"test_strategy": {"enabled": True, "symbols": ["BTCUSDT"]}}
        with open(strategy_dir / "config.yaml", "w") as f:
            yaml.dump(strategy_config, f)

        from run_strategy import StrategyProcessRunner

        with patch("run_strategy.SignalLogger") as mock_logger_class:
            mock_logger = MagicMock()
            mock_logger_class.return_value = mock_logger

            runner = StrategyProcessRunner(
                strategy_name="test_strategy",
                strategy_config=strategy_config["test_strategy"],
                global_config_path=str(config_file),
            )

            mock_logger_class.assert_called_once()
            call_kwargs = mock_logger_class.call_args[1]
            # 默认值应为 None（由 HttpSignalSender 处理默认值）
            assert call_kwargs.get("http_api_path") is None
