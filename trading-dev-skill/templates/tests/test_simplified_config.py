"""
简化配置格式测试

测试目标：验证 strategies.yaml 只保留 strategies 字段的简化格式
删除：mode, backtest, defaults, templates

每个策略直接定义完整配置：
- interval
- version
- trading_mode
- symbols
- config_dir (可选)
"""

import pytest
import yaml
from pathlib import Path
from typing import Dict, Any

from strategy_core.utils.strategies_loader import (
    StrategiesLoader,
    StrategyInstance,
)


# =============================================================================
# Fixtures - 简化配置格式
# =============================================================================

@pytest.fixture
def simplified_config(tmp_path: Path) -> Path:
    """创建简化格式的配置文件（只有 strategies 字段）"""
    config_content = """
# 简化配置格式 - 只有 strategies 字段
strategies:
  cta_ict_v3:
    interval: "4h"
    version: "v2"
    trading_mode: "live"
    config_dir: "config/zktrading"
    symbols:
      - BTCUSDT
      - ETHUSDT
      - name: SOLUSDT
        trading_mode: "paper_trading"

  cta_rbreaker_v3:
    interval: "15m"
    version: "v2"
    trading_mode: "paper_trading"
    config_dir: "config/zktrading"
    symbols: [BTCUSDT, ETHUSDT]

  dolphin_trading_v2:
    interval: "4h"
    version: "v2"
    trading_mode: "live"
    config_dir: "config/zktrading"
    symbols: [BTCUSDT]
    overrides:
      params:
        cooldown_bars: 30
"""
    config_file = tmp_path / "simplified_strategies.yaml"
    config_file.write_text(config_content, encoding="utf-8")
    return config_file


@pytest.fixture
def minimal_simplified_config(tmp_path: Path) -> Path:
    """最小简化配置（只有必需字段）"""
    config_content = """
strategies:
  test_strategy:
    symbols: [BTCUSDT]
"""
    config_file = tmp_path / "minimal_simplified.yaml"
    config_file.write_text(config_content, encoding="utf-8")
    return config_file


# =============================================================================
# RED 阶段：测试简化配置加载
# =============================================================================

class TestSimplifiedConfigLoad:
    """测试简化配置加载（RED 阶段）"""

    def test_load_simplified_config(self, simplified_config: Path):
        """测试加载简化配置文件"""
        loader = StrategiesLoader(config_path=str(simplified_config))
        loader.load()

        # 验证配置已加载
        instances = loader.expand_strategies()
        assert len(instances) > 0

    def test_no_mode_field_needed(self, simplified_config: Path):
        """测试不再需要 mode 字段"""
        loader = StrategiesLoader(config_path=str(simplified_config))
        loader.load()

        # mode 应该默认为 "live" 或不再使用
        # trading_mode 在策略级别定义
        instances = loader.expand_strategies()

        # 验证 trading_mode 从策略配置中获取
        live_instances = [i for i in instances if i.trading_mode == "live"]
        paper_instances = [i for i in instances if i.trading_mode == "paper_trading"]

        assert len(live_instances) > 0
        assert len(paper_instances) > 0

    def test_no_backtest_field_in_strategies_yaml(self, simplified_config: Path):
        """测试 strategies.yaml 不再包含 backtest 配置"""
        loader = StrategiesLoader(config_path=str(simplified_config))
        loader.load()

        # 简化配置格式：不再有 backtest_config 属性
        # 回测配置已移到 backtest/config/main.yaml
        assert not hasattr(loader, 'backtest_config')




    def test_symbol_level_trading_mode_override(self, simplified_config: Path):
        """测试 symbol 级别 trading_mode 覆盖"""
        loader = StrategiesLoader(config_path=str(simplified_config))
        loader.load()

        instances = loader.expand_strategies()

        # SOLUSDT 在 cta_ict_v3 中覆盖为 paper_trading
        sol_ict = next(
            (i for i in instances if i.name == "cta_ict_v3" and i.symbol == "SOLUSDT"),
            None
        )
        assert sol_ict is not None
        assert sol_ict.trading_mode == "paper_trading"

    def test_overrides_preserved(self, simplified_config: Path):
        """测试 overrides 仍然支持"""
        loader = StrategiesLoader(config_path=str(simplified_config))
        loader.load()

        instances = loader.expand_strategies()

        # dolphin_trading_v2 有 overrides
        dolphin_instance = next(
            (i for i in instances if i.name == "dolphin_trading_v2"),
            None
        )
        assert dolphin_instance is not None
        assert dolphin_instance.overrides == {"params": {"cooldown_bars": 30}}







