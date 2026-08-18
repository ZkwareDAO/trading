"""
策略配置加载器集成测试

使用实际配置文件测试 StrategiesLoader 的功能。
"""

import pytest
from pathlib import Path

from strategy_core.utils.strategies_loader import (
    StrategiesLoader,
    StrategyInstance,
)


# =============================================================================
# 使用实际配置文件的测试
# =============================================================================

class TestWithActualConfig:
    """使用实际配置文件的集成测试"""

    @pytest.fixture
    def actual_config_path(self) -> str:
        """返回实际配置文件路径"""
        return "config/strategies.yaml"

    def test_load_actual_config(self, actual_config_path: str):
        """测试加载实际配置文件"""
        loader = StrategiesLoader(config_path=actual_config_path)

        # 应该成功加载
        result = loader.load()
        assert result is loader  # 返回 self

    def test_actual_config_has_strategies(self, actual_config_path: str):
        """测试实际配置文件包含策略"""
        loader = StrategiesLoader(config_path=actual_config_path)
        loader.load()

        instances = loader.expand_strategies()

        # 应该有多个策略实例
        assert len(instances) > 0

    def test_actual_config_backtest_settings(self, actual_config_path: str):
        """测试简化配置不再包含回测设置"""
        loader = StrategiesLoader(config_path=actual_config_path)
        loader.load()

        # 简化配置格式：回测配置已移到 backtest/config/main.yaml
        # StrategiesLoader 不再处理回测配置
        assert not hasattr(loader, 'backtest_config')





    def test_actual_config_symbols_uppercase(self, actual_config_path: str):
        """测试所有 symbol 都是大写"""
        loader = StrategiesLoader(config_path=actual_config_path)
        loader.load()

        instances = loader.expand_strategies()

        for instance in instances:
            assert instance.symbol == instance.symbol.upper()


# =============================================================================
# 配置路径验证测试
# =============================================================================

class TestConfigPathValidation:
    """测试配置路径生成"""


    def test_config_path_special_symbols(self):
        """测试特殊交易对配置路径"""
        loader = StrategiesLoader(config_path="config/strategies.yaml")
        loader.load()

        # 测试 HYPERUSDT（包含特殊字符）
        instance = loader.get_strategy_by_name_symbol("cta_ict_v3", "HYPERUSDT")
        if instance:
            assert instance.config_path == "config/zktrading/cta_ict_v3/HYPERUSDT.yaml"
