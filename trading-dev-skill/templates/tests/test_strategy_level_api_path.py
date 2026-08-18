#!/usr/bin/env python3
"""
测试策略级别 API 路径配置

验证：
1. 策略配置 signal.api_path 覆盖全局配置
2. 策略未配置时使用全局 signal_hub.api_path
3. 两者都未配置时使用默认值 /api/v1/kafka/message
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


class TestStrategyLevelApiPath:
    """测试策略级别 API 路径配置优先级"""

    def test_strategy_api_path_overrides_global(self, tmp_path):
        """策略配置 signal.api_path 覆盖全局配置"""
        global_config = {
            "signal_hub": {
                "enabled": True,
                "endpoint": "http://203.0.113.100:8891",
                "api_path": "/api/v1/kafka/message",  # 全局 v1
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

        # 策略配置使用 v2
        strategy_dir = tmp_path / "strategies" / "test_strategy"
        strategy_dir.mkdir(parents=True)
        strategy_config = {
            "test_strategy": {
                "enabled": True,
                "symbols": ["BTCUSDT"],
                "signal": {
                    "api_path": "/api/v2/signals",  # 策略级别 v2
                },
            }
        }
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

            # 验证使用策略级别的 api_path
            mock_logger_class.assert_called_once()
            call_kwargs = mock_logger_class.call_args[1]
            assert call_kwargs["http_api_path"] == "/api/v2/signals"

    def test_fallback_to_global_api_path(self, tmp_path):
        """策略未配置 api_path 时使用全局配置"""
        global_config = {
            "signal_hub": {
                "enabled": True,
                "endpoint": "http://203.0.113.100:8891",
                "api_path": "/api/v1/kafka/message",  # 全局 v1
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

        # 策略配置无 api_path
        strategy_dir = tmp_path / "strategies" / "test_strategy"
        strategy_dir.mkdir(parents=True)
        strategy_config = {
            "test_strategy": {
                "enabled": True,
                "symbols": ["BTCUSDT"],
                "signal": {
                    "exchange": "binance",
                },
            }
        }
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

            # 验证使用全局 api_path
            mock_logger_class.assert_called_once()
            call_kwargs = mock_logger_class.call_args[1]
            assert call_kwargs["http_api_path"] == "/api/v1/kafka/message"

    def test_fallback_to_default_when_both_missing(self, tmp_path):
        """策略和全局都未配置时使用默认值（None，由 HttpSignalSender 处理）"""
        global_config = {
            "signal_hub": {
                "enabled": True,
                "endpoint": "http://203.0.113.100:8891",
                # 无 api_path
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

        # 策略配置无 signal 节点
        strategy_dir = tmp_path / "strategies" / "test_strategy"
        strategy_dir.mkdir(parents=True)
        strategy_config = {
            "test_strategy": {
                "enabled": True,
                "symbols": ["BTCUSDT"],
            }
        }
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

            # 验证 http_api_path 为 None（默认值由 HttpSignalSender 处理）
            mock_logger_class.assert_called_once()
            call_kwargs = mock_logger_class.call_args[1]
            assert call_kwargs.get("http_api_path") is None

    def test_strategy_signal_section_missing(self, tmp_path):
        """策略配置无 signal 节点时使用全局配置"""
        global_config = {
            "signal_hub": {
                "enabled": True,
                "endpoint": "http://203.0.113.100:8891",
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

        strategy_dir = tmp_path / "strategies" / "test_strategy"
        strategy_dir.mkdir(parents=True)
        strategy_config = {
            "test_strategy": {
                "enabled": True,
                "symbols": ["BTCUSDT"],
                # 无 signal 节点
            }
        }
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

            # 验证使用全局 api_path
            mock_logger_class.assert_called_once()
            call_kwargs = mock_logger_class.call_args[1]
            assert call_kwargs["http_api_path"] == "/api/v2/signals"