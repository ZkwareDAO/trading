"""
输入验证和安全性测试

测试 StrategiesLoader 和 BatchBacktestRunner 的输入验证功能：
1. strategy 字段验证
2. symbol 字段验证
3. config_path 路径遍历防护
"""

import pytest
from pathlib import Path

from strategy_core.utils.strategies_loader import (
    StrategiesLoader,
    StrategyInstance,
)


# =============================================================================
# 字段验证测试
# =============================================================================

class TestFieldValidation:
    """测试字段验证功能"""

    def test_validate_strategy_name_valid(self):
        """测试有效的策略名称"""
        valid_names = [
            "cta_ict_v3",
            "cta_rbreaker_v3",
            "dolphin_trading_v2",
            "obv_atr_v2",
            "strategy_123",
            "simple",
        ]
        for name in valid_names:
            assert StrategiesLoader.is_valid_strategy_name(name), f"'{name}' should be valid"

    def test_validate_strategy_name_invalid(self):
        """测试无效的策略名称"""
        invalid_names = [
            "strategy-with-dash",
            "strategy.name",
            "strategy name",
            "../../../etc/passwd",
            "'; rm -rf /",
            "",
        ]
        for name in invalid_names:
            assert not StrategiesLoader.is_valid_strategy_name(name), f"'{name}' should be invalid"

    def test_validate_symbol_valid(self):
        """测试有效的交易对"""
        valid_symbols = [
            "BTCUSDT",
            "ETHUSDT",
            "SOLUSDT",
            "BNBUSDT",
            "DOGEUSDT",
            "BTC",
            "ETH",
        ]
        for symbol in valid_symbols:
            assert StrategiesLoader.is_valid_symbol(symbol), f"'{symbol}' should be valid"

    def test_validate_symbol_invalid(self):
        """测试无效的交易对"""
        invalid_symbols = [
            "btcusdt",  # 小写
            "BTC-USDT",  # 包含连字符
            "BTC.USDT",  # 包含点
            "BTC USDT",  # 包含空格
            "../../../etc/passwd",
            "'; DROP TABLE--",
            "",
        ]
        for symbol in invalid_symbols:
            assert not StrategiesLoader.is_valid_symbol(symbol), f"'{symbol}' should be invalid"

    def test_validate_config_path_valid(self):
        """测试有效的配置路径"""
        valid_paths = [
            "config/zktrading/cta_ict_v3/BTCUSDT.yaml",
            "./config/zktrading/strategy/SYMBOL.yaml",
            "/absolute/path/to/config.yaml",
        ]
        for path in valid_paths:
            assert StrategiesLoader.is_valid_config_path(path), f"'{path}' should be valid"

    def test_validate_config_path_traversal_attack(self):
        """测试路径遍历攻击"""
        invalid_paths = [
            "../../../etc/passwd",
            "config/../../../etc/shadow",
            "./config/../../secret.yaml",
            "config/..%2F..%2Fetc%2Fpasswd",  # URL 编码
        ]
        for path in invalid_paths:
            assert not StrategiesLoader.is_valid_config_path(path), f"'{path}' should be blocked"


# =============================================================================
# StrategyInstance 验证测试
# =============================================================================

class TestStrategyInstanceValidation:
    """测试 StrategyInstance 验证"""

    def test_instance_validate_success(self):
        """测试实例验证成功"""
        instance = StrategyInstance(
            name="cta_ict_v3",
            symbol="BTCUSDT",
            interval="4h",
            version="v2",
            enabled=True,
            trading_mode="live",
            config_path="config/zktrading/cta_ict_v3/BTCUSDT.yaml",
        )
        # 应该不抛出异常
        instance.validate()

    def test_instance_validate_invalid_strategy_name(self):
        """测试无效策略名称抛出异常"""
        instance = StrategyInstance(
            name="../../../etc/passwd",
            symbol="BTCUSDT",
            interval="4h",
            version="v2",
            enabled=True,
            trading_mode="live",
            config_path="config/test.yaml",
        )
        with pytest.raises(ValueError, match="Invalid strategy name"):
            instance.validate()

    def test_instance_validate_invalid_symbol(self):
        """测试无效交易对抛出异常"""
        instance = StrategyInstance(
            name="cta_ict_v3",
            symbol="btc-usdt",
            interval="4h",
            version="v2",
            enabled=True,
            trading_mode="live",
            config_path="config/test.yaml",
        )
        with pytest.raises(ValueError, match="Invalid symbol"):
            instance.validate()

    def test_instance_validate_path_traversal(self):
        """测试路径遍历抛出异常"""
        instance = StrategyInstance(
            name="cta_ict_v3",
            symbol="BTCUSDT",
            interval="4h",
            version="v2",
            enabled=True,
            trading_mode="live",
            config_path="../../../etc/passwd",
        )
        with pytest.raises(ValueError, match="Invalid config_path"):
            instance.validate()


# =============================================================================
# 缓存优化测试
# =============================================================================

class TestQueryCache:
    """测试查询缓存功能"""

    def test_get_strategy_cached(self, tmp_path: Path):
        """测试查询结果被缓存"""
        config_content = """
strategies:
  cta_ict_v3:
    symbols: [BTCUSDT, ETHUSDT, SOLUSDT]
"""
        config_file = tmp_path / "test.yaml"
        config_file.write_text(config_content, encoding="utf-8")

        loader = StrategiesLoader(str(config_file)).load()

        # 第一次查询
        instance1 = loader.get_strategy_by_name_symbol("cta_ict_v3", "BTCUSDT")

        # 第二次查询应该使用缓存
        instance2 = loader.get_strategy_by_name_symbol("cta_ict_v3", "BTCUSDT")

        # 应该是同一个对象（缓存命中）
        assert instance1 is instance2

    def test_cache_invalidation(self, tmp_path: Path):
        """测试缓存失效（重新 load）"""
        config_content = """
strategies:
  cta_ict_v3:
    symbols: [BTCUSDT]
"""
        config_file = tmp_path / "test.yaml"
        config_file.write_text(config_content, encoding="utf-8")

        loader = StrategiesLoader(str(config_file)).load()
        loader.get_strategy_by_name_symbol("cta_ict_v3", "BTCUSDT")

        # 重新加载应该清除缓存
        loader.load()
        assert not hasattr(loader, '_instance_map') or loader._instance_map is None
