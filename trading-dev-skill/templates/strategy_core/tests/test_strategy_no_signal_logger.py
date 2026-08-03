#!/usr/bin/env python3
"""
测试 Phase 1-3: 策略不再持有 signal_logger

验证:
1. 策略构造函数不再需要 signal_logger 参数
2. lifecycle.instantiate_strategy 不再传入 signal_logger
3. 策略实例没有 signal_logger 属性
"""

from unittest.mock import MagicMock
from datetime import datetime, timezone

from strategy_core.signal_logging.storage import Signal


def _make_basic_signal():
    """创建测试用 Signal 对象"""
    signal = MagicMock(spec=Signal)
    signal.signal_id = "sig-test-001"
    signal.signal_type = "BUY"
    signal.symbol = "BTCUSDT"
    signal.price = 50000.0
    signal.strength = 0.8
    signal.timestamp = datetime.now(timezone.utc)
    signal.metadata = {}
    return signal


class TestStrategyNoSignalLogger:
    """测试策略不再持有 signal_logger"""

    def test_rbreaker_strategy_ctor_no_signal_logger_param(self):
        """cta_rbreaker_v3 策略构造函数不应有 signal_logger 参数"""
        import inspect
        from strategies.cta_rbreaker_v3.strategy import Strategy
        sig = inspect.signature(Strategy.__init__)
        params = list(sig.parameters.keys())
        assert 'signal_logger' not in params, (
            f"cta_rbreaker_v3 Strategy.__init__ 仍有 signal_logger 参数: {params}"
        )

    def test_trend_strategy_ctor_no_signal_logger_param(self):
        """cta_trend 策略构造函数不应有 signal_logger 参数"""
        import inspect
        from strategies.cta_trend.strategy import Strategy
        sig = inspect.signature(Strategy.__init__)
        params = list(sig.parameters.keys())
        assert 'signal_logger' not in params, (
            f"cta_trend Strategy.__init__ 仍有 signal_logger 参数: {params}"
        )

    def test_ict_strategy_ctor_no_signal_logger_param(self):
        """cta_ict_v3 策略构造函数不应有 signal_logger 参数"""
        import inspect
        from strategies.cta_ict_v3.strategy import Strategy
        sig = inspect.signature(Strategy.__init__)
        params = list(sig.parameters.keys())
        assert 'signal_logger' not in params, (
            f"cta_ict_v3 Strategy.__init__ 仍有 signal_logger 参数: {params}"
        )

    def test_trend_strength_strategy_ctor_no_signal_logger_param(self):
        """cta_trend_strength 策略构造函数不应有 signal_logger 参数"""
        import inspect
        from strategies.cta_trend_strength.strategy import Strategy
        sig = inspect.signature(Strategy.__init__)
        params = list(sig.parameters.keys())
        assert 'signal_logger' not in params, (
            f"cta_trend_strength Strategy.__init__ 仍有 signal_logger 参数: {params}"
        )


class TestLifecycleNoSignalLogger:
    """测试 lifecycle 不再传入 signal_logger"""

    def test_instantiate_strategy_without_signal_logger(self, tmp_path):
        """instantiate_strategy 不应需要 signal_logger 参数"""
        from strategy_core.strategy_engine.registry import StrategyRegistry
        from strategy_core.strategy_engine.lifecycle import LifecycleManager

        registry = StrategyRegistry()
        registry.register(
            strategy_id="test_001",
            strategy_name="cta_rbreaker_v3",
            module_path="strategies.cta_rbreaker_v3.strategy",
            config={
                'symbols': ['BTCUSDT'],
                'timeframes': ['15m'],
                'direction': 'neutral',
                'params': {'threshold': 0.005},
                'signal': {'min_strength': 0.5, 'cooldown_ms': 60000},
                'risk': {},
                'adx': {},
                'price_line': {},
            },
        )

        lifecycle = LifecycleManager(registry)

        # 调用时应不再需要 signal_logger 参数
        # 如果旧代码还有 signal_logger 参数，这行会报 TypeError
        import inspect
        sig = inspect.signature(lifecycle.instantiate_strategy)
        param_names = list(sig.parameters.keys())
        assert 'signal_logger' not in param_names, (
            f"instantiate_strategy 仍保留 signal_logger 参数: {paramNames}"
        )


class TestLifecycleUserIdPassThrough:
    """测试 lifecycle 正确传递 user_id 到策略实例"""

    def test_user_id_passed_from_config_to_strategy(self, tmp_path):
        """user_id 应从配置传递到策略实例"""
        from strategy_core.strategy_engine.registry import StrategyRegistry
        from strategy_core.strategy_engine.lifecycle import LifecycleManager
        from data_manager import DataManager, DataManagerConfig

        registry = StrategyRegistry()
        registry.register(
            strategy_id="test_user_id_001",
            strategy_name="cta_rbreaker_v3",
            module_path="strategies.cta_rbreaker_v3.strategy",
            config={
                'symbols': ['BTCUSDT'],
                'timeframes': ['15m'],
                'direction': 'neutral',
                'params': {'threshold': 0.005},
                'signal': {'min_strength': 0.5, 'cooldown_ms': 60000},
                'risk': {},
                'user_id': 'test_user_123',  # 配置中的 user_id
            },
        )

        lifecycle = LifecycleManager(registry)

        # 创建 DataManager
        dm_config = DataManagerConfig(csv_dir=str(tmp_path))
        data_manager = DataManager(dm_config)

        # 实例化策略
        entry = registry.get("test_user_id_001")
        success = lifecycle.instantiate_strategy(
            entry,
            data_manager,
            strategy_name="test_strategy",
            trading_mode="live",
        )

        assert success, "策略实例化失败"

        # 验证策略实例持有 user_id
        strategy = registry.get("test_user_id_001").instance
        assert strategy is not None, "策略实例为 None"
        assert strategy._user_id == 'test_user_123', (
            f"策略 _user_id 应为 'test_user_123'，实际为 '{strategy._user_id}'"
        )

    def test_user_id_defaults_to_empty_string(self, tmp_path):
        """配置中没有 user_id 时，应默认为空字符串"""
        from strategy_core.strategy_engine.registry import StrategyRegistry
        from strategy_core.strategy_engine.lifecycle import LifecycleManager
        from data_manager import DataManager, DataManagerConfig

        registry = StrategyRegistry()
        registry.register(
            strategy_id="test_no_user_id",
            strategy_name="cta_rbreaker_v3",
            module_path="strategies.cta_rbreaker_v3.strategy",
            config={
                'symbols': ['BTCUSDT'],
                'timeframes': ['15m'],
                'direction': 'neutral',
                'params': {'threshold': 0.005},
                'signal': {'min_strength': 0.5, 'cooldown_ms': 60000},
                'risk': {},
                # 不设置 user_id
            },
        )

        lifecycle = LifecycleManager(registry)

        dm_config = DataManagerConfig(csv_dir=str(tmp_path))
        data_manager = DataManager(dm_config)

        entry = registry.get("test_no_user_id")
        success = lifecycle.instantiate_strategy(
            entry,
            data_manager,
            strategy_name="test_strategy",
            trading_mode="live",
        )

        assert success, "策略实例化失败"

        strategy = registry.get("test_no_user_id").instance
        assert strategy._user_id == '', (
            f"策略 _user_id 应为空字符串，实际为 '{strategy._user_id}'"
        )
