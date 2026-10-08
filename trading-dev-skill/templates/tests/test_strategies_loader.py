"""
策略配置加载器单元测试

测试 StrategiesLoader 的核心功能：
1. 配置加载和解析
2. 策略展开
3. overrides 支持
4. 过滤功能
5. symbol 级别 trading_mode 覆盖
"""

import pytest
import yaml
from pathlib import Path

from strategy_core.utils.strategies_loader import (
    StrategiesLoader,
    StrategyInstance,
)


# =============================================================================
# Fixtures - 简化配置格式
# =============================================================================

@pytest.fixture
def sample_config(tmp_path: Path) -> Path:
    """创建示例配置文件（简化格式，不含 interval/version）"""
    config_content = """
strategies:
  cta_ict_v3:
    trading_mode: "live"
    config_dir: "config/zktrading"
    symbols: [BTCUSDT, ETHUSDT, SOLUSDT]

  cta_rbreaker_v3:
    trading_mode: "paper_trading"
    symbols: [BTCUSDT, ETHUSDT]

  obv_atr_v2:
    trading_mode: "live"
    symbols: [BTCUSDT]
    overrides:
      params:
        cooldown_bars: 30
"""
    config_file = tmp_path / "strategies.yaml"
    config_file.write_text(config_content, encoding="utf-8")
    return config_file


@pytest.fixture
def minimal_config(tmp_path: Path) -> Path:
    """创建最小配置文件"""
    config_content = """
strategies:
  test_strategy:
    symbols: [BTCUSDT]
"""
    config_file = tmp_path / "minimal.yaml"
    config_file.write_text(config_content, encoding="utf-8")
    return config_file


# =============================================================================
# 测试 StrategyInstance 数据类
# =============================================================================

class TestStrategyInstance:
    """测试 StrategyInstance 数据类"""

    def test_create_instance_with_required_fields(self):
        """测试创建实例（必需字段）"""
        instance = StrategyInstance(
            name="cta_ict_v3",
            symbol="BTCUSDT",
            interval="4h",
            version="2",
            enabled=True,
            trading_mode="live",
            config_path="config/zktrading/cta_ict_v3/BTCUSDT.yaml",
        )

        assert instance.name == "cta_ict_v3"
        assert instance.symbol == "BTCUSDT"
        assert instance.interval == "4h"
        assert instance.version == "2"
        assert instance.enabled is True
        assert instance.trading_mode == "live"
        assert instance.overrides == {}

    def test_create_instance_with_overrides(self):
        """测试创建实例（带 overrides）"""
        instance = StrategyInstance(
            name="cta_ict_v3",
            symbol="BTCUSDT",
            interval="4h",
            version="2",
            enabled=True,
            trading_mode="live",
            config_path="config/zktrading/cta_ict_v3/BTCUSDT.yaml",
            overrides={"params": {"cooldown_bars": 30}},
        )

        assert instance.overrides == {"params": {"cooldown_bars": 30}}


# =============================================================================
# 测试 StrategiesLoader - 配置加载
# =============================================================================

class TestStrategiesLoaderLoad:
    """测试 StrategiesLoader 配置加载"""

    def test_load_config_file_exists(self, sample_config: Path):
        """测试加载存在的配置文件"""
        loader = StrategiesLoader(config_path=str(sample_config))
        loader.load()

        instances = loader.expand_strategies()
        assert len(instances) == 6


    def test_load_minimal_config(self, minimal_config: Path):
        """测试加载最小配置文件"""
        loader = StrategiesLoader(config_path=str(minimal_config))
        loader.load()

        instances = loader.expand_strategies()
        assert len(instances) == 1
        # 默认值应该被应用
        assert instances[0].interval == "4h"
        assert instances[0].trading_mode == "live"


# =============================================================================
# 测试 StrategiesLoader - 策略展开
# =============================================================================

class TestStrategiesLoaderExpand:
    """测试 StrategiesLoader 策略展开"""

    def test_expand_strategies_basic(self, sample_config: Path):
        """测试展开策略（基本功能）"""
        loader = StrategiesLoader(config_path=str(sample_config))
        loader.load()

        instances = loader.expand_strategies()

        # 3 + 2 + 1 = 6 个实例
        assert len(instances) == 6


    def test_expand_strategies_interval_from_config(self, sample_config: Path):
        """测试展开策略（interval/version 从默认值获取）"""
        loader = StrategiesLoader(config_path=str(sample_config))
        loader.load()

        instances = loader.expand_strategies()

        # interval/version 不再从 strategies.yaml 读取
        # 从 zktrading/{strategy}/{symbol}.yaml 读取，如果不存在则使用默认值
        # 注意：sample_config 中的 config_dir 指向真实目录，所以会读取真实配置
        ict_instances = [i for i in instances if i.name == "cta_ict_v3"]
        for instance in ict_instances:
            # 验证 interval/version 有值（从 zktrading 或默认值）
            assert instance.interval  # 非空
            assert instance.version  # 非空

    def test_expand_strategies_trading_mode(self, sample_config: Path):
        """测试展开策略（运行模式）"""
        loader = StrategiesLoader(config_path=str(sample_config))
        loader.load()

        instances = loader.expand_strategies()

        # cta_ict_v3 是 live
        ict_instances = [i for i in instances if i.name == "cta_ict_v3"]
        for instance in ict_instances:
            assert instance.trading_mode == "live"

        # cta_rbreaker_v3 是 paper_trading
        rbreaker_instances = [i for i in instances if i.name == "cta_rbreaker_v3"]
        for instance in rbreaker_instances:
            assert instance.trading_mode == "paper_trading"

    def test_expand_strategies_with_overrides(self, sample_config: Path):
        """测试展开策略（带 overrides）"""
        loader = StrategiesLoader(config_path=str(sample_config))
        loader.load()

        instances = loader.expand_strategies()

        # obv_atr_v2 有 overrides
        obv_instance = next(i for i in instances if i.name == "obv_atr_v2")
        assert obv_instance.overrides == {"params": {"cooldown_bars": 30}}


# =============================================================================
# 测试 StrategiesLoader - 过滤功能
# =============================================================================

class TestStrategiesLoaderFilter:
    """测试 StrategiesLoader 过滤功能"""

    def test_filter_enabled_only(self, sample_config: Path):
        """测试过滤（仅启用）"""
        loader = StrategiesLoader(config_path=str(sample_config))
        loader.load()

        instances = loader.filter(enabled_only=True)

        # 所有策略都是 enabled=true
        assert len(instances) == 6

    def test_filter_by_trading_mode(self, sample_config: Path):
        """测试过滤（按运行模式）"""
        loader = StrategiesLoader(config_path=str(sample_config))
        loader.load()

        live_instances = loader.filter(trading_mode="live")
        paper_instances = loader.filter(trading_mode="paper_trading")

        # live: cta_ict_v3(3) + obv_atr_v2(1) = 4
        assert len(live_instances) == 4

        # paper_trading: cta_rbreaker_v3(2) = 2
        assert len(paper_instances) == 2

    def test_filter_combined(self, sample_config: Path):
        """测试过滤（组合条件）"""
        loader = StrategiesLoader(config_path=str(sample_config))
        loader.load()

        instances = loader.filter(enabled_only=True, trading_mode="live")

        assert len(instances) == 4


# =============================================================================
# 测试 StrategiesLoader - 查询功能
# =============================================================================

class TestStrategiesLoaderQuery:
    """测试 StrategiesLoader 查询功能"""

    def test_get_strategy_by_name_symbol(self, sample_config: Path):
        """测试按名称和交易对获取策略"""
        loader = StrategiesLoader(config_path=str(sample_config))
        loader.load()

        instance = loader.get_strategy_by_name_symbol("cta_ict_v3", "BTCUSDT")

        assert instance is not None
        assert instance.name == "cta_ict_v3"
        assert instance.symbol == "BTCUSDT"

    def test_get_strategy_not_found(self, sample_config: Path):
        """测试获取不存在的策略"""
        loader = StrategiesLoader(config_path=str(sample_config))
        loader.load()

        instance = loader.get_strategy_by_name_symbol("not_exists", "BTCUSDT")

        assert instance is None


# =============================================================================
# 测试边界情况
# =============================================================================

class TestEdgeCases:
    """测试边界情况"""

    def test_empty_symbols(self, tmp_path: Path):
        """测试空 symbols 列表"""
        config_content = """
strategies:
  test_strategy:
    symbols: []
"""
        config_file = tmp_path / "empty_symbols.yaml"
        config_file.write_text(config_content, encoding="utf-8")

        loader = StrategiesLoader(config_path=str(config_file))
        loader.load()

        instances = loader.expand_strategies()

        assert len(instances) == 0

    def test_missing_optional_fields(self, tmp_path: Path):
        """测试缺失可选字段时使用默认值"""
        config_content = """
strategies:
  test_strategy:
    symbols: [BTCUSDT]
"""
        config_file = tmp_path / "minimal.yaml"
        config_file.write_text(config_content, encoding="utf-8")

        loader = StrategiesLoader(config_path=str(config_file))
        loader.load()

        instances = loader.expand_strategies()

        assert len(instances) == 1
        assert instances[0].interval == "4h"  # 默认值
        assert instances[0].version == "2"   # 默认值
        assert instances[0].trading_mode == "live"  # 默认值

