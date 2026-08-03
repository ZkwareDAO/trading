#!/usr/bin/env python3
"""
FactoryClient.register() 动态参数测试

测试目标：register 方法只接收一个 JSON 参数
该 JSON 可包含 strategy_id 和任意其他字段
"""

import pytest
from unittest.mock import Mock
from strategy_core.factory_client import FactoryClient


class TestRegisterDynamicParams:
    """测试动态参数注册"""

    @pytest.fixture
    def client(self):
        """创建 FactoryClient 实例"""
        return FactoryClient(
            factory_endpoint="http://127.0.0.1:8888",
            callback_url="http://127.0.0.1:8892",
        )

    def test_register_accepts_single_dict_param(self, client):
        """register 只接收一个字典参数"""
        mock_proxy = Mock()
        mock_proxy.register.return_value = {"status": "success"}
        client._factory_proxy = mock_proxy

        result = client.register({
            "strategy_id": "TEST_STRATEGY",
            "name": "test_strategy",
            "symbol": "BTCUSDT",
        })

        assert result["status"] == "success"
        # 验证调用时只传了一个 JSON 参数
        call_args = mock_proxy.register.call_args
        assert len(call_args[0]) == 1
        assert isinstance(call_args[0][0], dict)
        assert call_args[0][0]["strategy_id"] == "TEST_STRATEGY"

    def test_register_includes_all_fields_in_json(self, client):
        """所有字段都包含在 JSON 参数中"""
        mock_proxy = Mock()
        mock_proxy.register.return_value = {"status": "success"}
        client._factory_proxy = mock_proxy

        result = client.register({
            "strategy_id": "DOLPHIN_4H_V2_BTCUSDT_LIVE",
            "name": "dolphin_trading_v2",
            "interval": "4h",
            "version": "v2",
            "symbol": "BTCUSDT",
            "trading_mode": "live",
            "script": "strategies/dolphin_trading_v2/strategy.py",
            "user_id": 42,  # 新增字段
        })

        assert result["status"] == "success"
        call_args = mock_proxy.register.call_args[0][0]
        assert call_args["strategy_id"] == "DOLPHIN_4H_V2_BTCUSDT_LIVE"
        assert call_args["name"] == "dolphin_trading_v2"
        assert call_args["interval"] == "4h"
        assert call_args["user_id"] == 42

    def test_register_stores_config_locally(self, client):
        """register 保存配置到本地 _strategy_configs"""
        mock_proxy = Mock()
        mock_proxy.register.return_value = {"status": "success"}
        client._factory_proxy = mock_proxy

        client.register({
            "strategy_id": "TEST_001",
            "name": "test",
            "custom_field": "value",
        })

        assert "TEST_001" in client._strategy_configs
        assert client._strategy_configs["TEST_001"]["name"] == "test"
        assert client._strategy_configs["TEST_001"]["custom_field"] == "value"
        assert client._strategy_configs["TEST_001"]["strategy_id"] == "TEST_001"

    def test_register_handles_minimal_params(self, client):
        """只传 strategy_id 时正常工作"""
        mock_proxy = Mock()
        mock_proxy.register.return_value = {"status": "success"}
        client._factory_proxy = mock_proxy

        result = client.register({"strategy_id": "MINIMAL"})

        assert result["status"] == "success"
        call_args = mock_proxy.register.call_args[0][0]
        assert call_args["strategy_id"] == "MINIMAL"

    def test_register_returns_error_on_failure(self, client):
        """注册失败时返回错误信息"""
        mock_proxy = Mock()
        mock_proxy.register.side_effect = Exception("Connection refused")
        client._factory_proxy = mock_proxy

        result = client.register({
            "strategy_id": "FAIL_TEST",
            "name": "test",
        })

        assert result["status"] == "error"
        assert "Connection refused" in result["message"]

    def test_register_supports_arbitrary_new_fields(self, client):
        """支持任意新增字段"""
        mock_proxy = Mock()
        mock_proxy.register.return_value = {"status": "success"}
        client._factory_proxy = mock_proxy

        result = client.register({
            "strategy_id": "NEW_FIELDS",
            "name": "test",
            "new_field_1": "value1",
            "new_field_2": 123,
            "nested": {"key": "value"},
        })

        assert result["status"] == "success"
        call_args = mock_proxy.register.call_args[0][0]
        assert call_args["strategy_id"] == "NEW_FIELDS"
        assert call_args["new_field_1"] == "value1"
        assert call_args["new_field_2"] == 123
        assert call_args["nested"] == {"key": "value"}

    def test_register_missing_strategy_id_returns_error(self, client):
        """缺少 strategy_id 时返回错误"""
        mock_proxy = Mock()
        mock_proxy.register.return_value = {"status": "success"}
        client._factory_proxy = mock_proxy

        result = client.register({"name": "test"})

        assert result["status"] == "error"
        assert "strategy_id" in result["message"]

