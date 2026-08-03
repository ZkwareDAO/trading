#!/usr/bin/env python3
"""
strategy_engine/engine.py 单元测试

测试 StrategyEngine 类的类型安全
"""

from unittest.mock import MagicMock, patch
from typing import Dict, Any

from strategy_core.strategy_engine.engine import StrategyEngine


class TestStrategyEngineConnectToFactory:
    """测试 connect_to_factory 方法的类型安全"""

    @patch('xmlrpc.client.ServerProxy')
    def test_connect_to_factory_factory_client_type(self, mock_server_proxy):
        """测试连接后 factory_client 不为 None"""
        # 模拟 ServerProxy 实例
        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_server_proxy.return_value = mock_client

        engine = StrategyEngine(factory_endpoint="http://127.0.0.1:8888")
        result = engine.connect_to_factory()

        assert result is True
        assert engine.factory_client is not None
        # 验证 factory_client 有 health_check 方法
        assert hasattr(engine.factory_client, 'health_check')

    @patch('xmlrpc.client.ServerProxy')
    def test_connect_to_factory_uses_health_check_first(self, mock_server_proxy):
        """测试连接时优先使用 health_check"""
        mock_client = MagicMock()
        mock_client.health_check.return_value = True
        mock_server_proxy.return_value = mock_client

        engine = StrategyEngine()
        engine.connect_to_factory()

        # 验证 health_check 被调用
        mock_client.health_check.assert_called_once()
        # list 不应该被调用
        mock_client.list.assert_not_called()

    @patch('xmlrpc.client.ServerProxy')
    def test_connect_to_factory_fallback_to_list(self, mock_server_proxy):
        """测试当 health_check 不存在时使用 list"""
        mock_client = MagicMock(spec=['list'])
        mock_client.list.return_value = ['strategy1']
        mock_server_proxy.return_value = mock_client

        engine = StrategyEngine()
        result = engine.connect_to_factory()

        # 连接应该成功（因为 fallback 到 list）
        assert result is True


class TestStrategyEngineLoadStrategy:
    """测试 load_strategy 方法的类型安全"""

    @patch.object(StrategyEngine, 'discover_strategies')
    def test_load_strategy_with_valid_config(self, mock_discover, tmp_path):
        """测试加载策略使用有效配置"""
        mock_discover.return_value = []

        engine = StrategyEngine(strategies_dir=str(tmp_path))
        config: Dict[str, Any] = {
            "symbols": ["BTCUSDT"],
            "timeframes": ["1m"]
        }

        # 即使实例化失败，类型检查应该通过
        # 这里主要测试配置参数的类型
        result = engine.load_strategy("test_strategy", config, "test_001")

        # 由于没有实际的策略模块，返回 False 是正常的
        assert result is False

    def test_load_strategy_with_optional_strategy_id(self, tmp_path):
        """测试 strategy_id 参数是可选的"""
        engine = StrategyEngine(strategies_dir=str(tmp_path))

        # 不提供 strategy_id 时应该使用默认值
        config: Dict[str, Any] = {}
        result = engine.load_strategy("test_strategy", config)

        # 返回 False 是因为没有实际策略模块，但类型检查应通过
        assert result is False


class TestStrategyEngineGetStatus:
    """测试 get_status 方法的返回类型"""

    def test_get_status_with_strategy_id_returns_dict(self, tmp_path):
        """测试获取单个策略状态返回 dict"""
        engine = StrategyEngine(strategies_dir=str(tmp_path))

        # 即使策略不存在，类型检查应通过
        result = engine.get_status("test_strategy")
        assert result is None or isinstance(result, dict)

    def test_get_status_without_strategy_id_returns_dict(self, tmp_path):
        """测试获取所有策略状态返回 dict"""
        engine = StrategyEngine(strategies_dir=str(tmp_path))

        result = engine.get_status()
        assert isinstance(result, dict)


class TestBuildStrategyParams:
    """测试 _build_strategy_params 方法"""

    def _make_entry(self, config):
        entry = MagicMock()
        entry.config = config
        return entry

    def test_injects_user_id_from_config(self, tmp_path):
        """user_id 应从策略 config.yaml 顶层注入"""
        engine = StrategyEngine(strategies_dir=str(tmp_path))
        entry = self._make_entry({
            "user_id": 10001,
            "params": {"threshold": 0.01},
        })

        params = engine._build_strategy_params(entry)
        assert params.get("user_id") == 10001

    def test_user_id_absent_when_not_in_config(self, tmp_path):
        """配置中没有 user_id 时 params 不应包含它"""
        engine = StrategyEngine(strategies_dir=str(tmp_path))
        entry = self._make_entry({
            "params": {"threshold": 0.01},
        })

        params = engine._build_strategy_params(entry)
        assert "user_id" not in params

    def test_injects_all_signal_fields(self, tmp_path):
        """所有信号相关字段应从配置正确注入"""
        engine = StrategyEngine(strategies_dir=str(tmp_path))
        entry = self._make_entry({
            "user_id": 10001,
            "strategy_type": "CTAFutureFactory",
            "risk_strategy_type": "traditional",
            "pos_type": 2,
            "version": "v2",
            "valid_before": "2030-12-31 08:00:00",
            "signal": {
                "exchange": "binance",
                "order_type": 2,
                "slippage": 0.001,
                "valid_before_hours": 48,
                "quantity": 0.5,
            },
            "capital": {"max_cash": 200, "max_parts": 2},
            "params": {"threshold": 0.01},
        })

        params = engine._build_strategy_params(entry)

        assert params["user_id"] == 10001
        assert params["strategy_type"] == "CTAFutureFactory"
        assert params["risk_strategy_type"] == "traditional"
        assert params["pos_type"] == 2
        assert params["strategy_version"] == "v2"
        assert params["strategy_valid_before"] == "2030-12-31 08:00:00"
        assert params["signal_exchange"] == "binance"
        assert params["signal_order_type"] == 2
        assert params["signal_slippage"] == 0.001
        assert params["signal_valid_before_hours"] == 48
        assert params["signal_quantity"] == 0.5
        assert params["strategy_cash"] == 200
        assert params["strategy_parts"] == 2

    def test_signal_fields_absent_when_not_in_config(self, tmp_path):
        """配置中没有的信号字段不应出现在 params 中"""
        engine = StrategyEngine(strategies_dir=str(tmp_path))
        entry = self._make_entry({
            "params": {"threshold": 0.01},
        })

        params = engine._build_strategy_params(entry)

        assert "strategy_type" not in params
        assert "risk_strategy_type" not in params
        assert "pos_type" not in params
        assert "strategy_version" not in params
        assert "strategy_valid_before" not in params
        assert "signal_exchange" not in params
        assert "signal_order_type" not in params
        assert "signal_slippage" not in params
        assert "signal_valid_before_hours" not in params
        assert "signal_quantity" not in params
        assert "strategy_cash" not in params
        assert "strategy_parts" not in params

    def test_partial_signal_config(self, tmp_path):
        """部分信号配置时只注入存在的字段"""
        engine = StrategyEngine(strategies_dir=str(tmp_path))
        entry = self._make_entry({
            "user_id": 42,
            "signal": {
                "exchange": "binance",
                "order_type": 1,
            },
            "capital": {"max_cash": 100},
            "params": {},
        })

        params = engine._build_strategy_params(entry)

        assert params["user_id"] == 42
        assert params["signal_exchange"] == "binance"
        assert params["signal_order_type"] == 1
        assert params["strategy_cash"] == 100
        assert "signal_slippage" not in params
        assert "signal_quantity" not in params
        assert "strategy_parts" not in params
