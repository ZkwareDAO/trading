#!/usr/bin/env python3
"""
测试 config_path 传递功能

验证:
1. run_strategies_manager.py 正确传递 config_path 到 FactoryClient.register()
2. FactoryClient 正确保存 config_path 到 _strategy_configs
3. FactoryClient._on_strategy_start() 正确构建包含 --config-path 的命令
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path

from strategy_core.factory_client import FactoryClient


class TestConfigPathTransmission:
    """测试 config_path 传递"""

    def test_register_saves_config_path(self):
        """测试 register() 保存 config_path 到内部配置"""
        client = FactoryClient(
            factory_endpoint="http://localhost:8888",
            global_config_path="config/settings.yaml",
            log_level="INFO",
        )

        # Mock factory proxy
        with patch.object(client, '_get_factory_proxy') as mock_proxy:
            mock_factory = Mock()
            mock_factory.register.return_value = {"status": "success"}
            mock_proxy.return_value = mock_factory

            # 调用 register，传入 dict 配置
            result = client.register({
                "strategy_id": "TEST_4H_2_BTCUSDT_LIVE",
                "name": "cta_ict_v3",
                "interval": "4h",
                "version": "2",
                "symbol": "BTCUSDT",
                "trading_mode": "live",
                "config_path": "config/strategies/cta_ict_v3/BTCUSDT.yaml",
            })

            # 验证 config_path 被保存
            saved_config = client._strategy_configs.get("TEST_4H_2_BTCUSDT_LIVE", {})
            assert "config_path" in saved_config, "config_path 应该被保存到 _strategy_configs"
            assert saved_config["config_path"] == "config/strategies/cta_ict_v3/BTCUSDT.yaml"

    def test_on_strategy_start_includes_config_path_in_command(self):
        """测试 _on_strategy_start() 构建命令时包含 --config-path"""
        client = FactoryClient(
            factory_endpoint="http://localhost:8888",
            global_config_path="config/settings.yaml",
            log_level="INFO",
        )

        # 预先设置策略配置，包含 config_path
        client._strategy_configs["TEST_4H_V2_BTCUSDT_LIVE"] = {
            "name": "cta_ict_v3",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "version": "v2",
            "trading_mode": "live",
            "config_path": "config/strategies/cta_ict_v3/BTCUSDT.yaml",
        }

        # Mock subprocess.Popen
        with patch('strategy_core.factory_client.subprocess.Popen') as mock_popen:
            mock_proc = Mock()
            mock_proc.pid = 12345
            mock_popen.return_value = mock_proc

            # 调用 _on_strategy_start
            result = client._on_strategy_start("TEST_4H_V2_BTCUSDT_LIVE")

            # 验证 Popen 被调用，且命令包含 --config-path
            assert mock_popen.called, "应该调用 subprocess.Popen"
            call_args = mock_popen.call_args
            cmd = call_args[0][0]  # 第一个位置参数是命令列表

            assert "--config-path" in cmd, "命令应该包含 --config-path 参数"
            config_path_idx = cmd.index("--config-path")
            assert cmd[config_path_idx + 1] == "config/strategies/cta_ict_v3/BTCUSDT.yaml", \
                "--config-path 后面应该是配置文件路径"


class TestStrategiesManagerConfigPath:
    """测试 run_strategies_manager.py 的 config_path 传递"""

    def test_register_passes_config_path(self):
        """测试 _register_all_to_factory 传递 config_path"""
        from run_strategies_manager import StrategyRuntime

        # 创建 mock FactoryClient
        mock_factory_client = Mock()
        mock_factory_client.register.return_value = {"status": "success"}
        mock_factory_client.query_status.return_value = {"status": "success", "registered": False}
        mock_factory_client.engine = None

        # 创建运行时实例
        runtime = StrategyRuntime.__new__(StrategyRuntime)
        runtime.factory_client = mock_factory_client
        runtime.strategy_configs = [
            {
                "strategy_id": "TEST_4H_2_BTCUSDT_LIVE",
                "name": "cta_ict_v3",
                "symbol": "BTCUSDT",
                "interval": "4h",
                "version": "2",
                "trading_mode": "live",
                "strategy_name": "ICT_4H_2_BTCUSDT_LIVE",
                "config_path": "config/strategies/cta_ict_v3/BTCUSDT.yaml",
            }
        ]

        # 调用注册方法
        runtime._register_all_to_factory()

        # 验证 register 被调用且包含 config_path
        assert mock_factory_client.register.called
        call_args = mock_factory_client.register.call_args[0][0]  # 第一个位置参数是 dict
        assert "config_path" in call_args, "register 应该接收 config_path 参数"
        assert call_args["config_path"] == "config/strategies/cta_ict_v3/BTCUSDT.yaml"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
