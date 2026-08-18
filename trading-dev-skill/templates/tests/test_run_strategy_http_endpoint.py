#!/usr/bin/env python3
"""
测试 run_strategy.py 中 SignalLogger 使用配置的 signal_hub.endpoint

验证：
1. StrategyProcessRunner 从全局配置读取 signal_hub.endpoint
2. 传递给 SignalLogger 的 http_endpoint 参数
3. signal_hub.enabled=False 时不传递 http_endpoint
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


class TestSignalLoggerUsesConfiguredEndpoint:
    """测试 SignalLogger 使用配置中的 signal_hub.endpoint"""

    def test_reads_signal_hub_endpoint_from_global_config(self, tmp_path):
        """从全局配置读取 signal_hub.endpoint 并传递给 SignalLogger"""
        # 创建全局配置
        global_config = {
            "signal_hub": {
                "enabled": True,
                "endpoint": "http://203.0.113.100:8891",
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

            # 验证 SignalLogger 被调用时传入了 http_endpoint
            mock_logger_class.assert_called_once()
            call_kwargs = mock_logger_class.call_args[1]
            assert "http_endpoint" in call_kwargs
            assert call_kwargs["http_endpoint"] == "http://203.0.113.100:8891"

    def test_no_http_endpoint_when_signal_hub_disabled(self, tmp_path):
        """signal_hub.enabled=False 时不传递 http_endpoint"""
        # 创建全局配置
        global_config = {
            "signal_hub": {
                "enabled": False,
                "endpoint": "http://203.0.113.100:8891",
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

            # 验证 SignalLogger 被调用时没有传入 http_endpoint
            mock_logger_class.assert_called_once()
            call_kwargs = mock_logger_class.call_args[1]
            assert call_kwargs.get("http_endpoint") is None

    def test_no_http_endpoint_when_signal_hub_missing(self, tmp_path):
        """signal_hub 配置缺失时不传递 http_endpoint"""
        # 创建全局配置（没有 signal_hub）
        global_config = {
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

            # 验证 SignalLogger 被调用时没有传入 http_endpoint
            mock_logger_class.assert_called_once()
            call_kwargs = mock_logger_class.call_args[1]
            assert call_kwargs.get("http_endpoint") is None

    def test_default_endpoint_from_settings_yaml(self, tmp_path):
        """使用 settings.yaml 中的默认 endpoint"""
        # 创建全局配置（使用默认 endpoint）
        global_config = {
            "signal_hub": {
                "enabled": True,
                "endpoint": "http://127.0.0.1:8891",  # 默认值
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

            # 验证 SignalLogger 被调用时传入了正确的 endpoint
            mock_logger_class.assert_called_once()
            call_kwargs = mock_logger_class.call_args[1]
            assert call_kwargs["http_endpoint"] == "http://127.0.0.1:8891"
