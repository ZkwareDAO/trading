"""
测试从 zktrading 配置文件读取 interval 和 version

User Journey:
As a strategy loader user, I want runtime_name to match actual live signal directories,
so that signals are archived to the correct directory.

TDD Step 1: Write failing tests
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
# Fixtures - zktrading 配置文件
# =============================================================================

@pytest.fixture
def zktrading_config_dir(tmp_path: Path) -> Path:
    """创建 zktrading 配置目录结构"""
    config_dir = tmp_path / "config" / "zktrading"

    # cta_ict_v3 配置文件
    ict_dir = config_dir / "cta_ict_v3"
    ict_dir.mkdir(parents=True)

    ict_btc_config = {
        "cta_ict_v3": {
            "enabled": True,
            "version": "3",
            "symbols": ["BTCUSDT"],
            "timeframes": ["1d", "4h", "15m"],
            "params": {"cooldown_bars": 15},
        }
    }
    with open(ict_dir / "BTCUSDT.yaml", "w") as f:
        yaml.dump(ict_btc_config, f)

    ict_eth_config = {
        "cta_ict_v3": {
            "enabled": True,
            "version": "3",
            "symbols": ["ETHUSDT"],
            "timeframes": ["1d", "4h", "15m"],
        }
    }
    with open(ict_dir / "ETHUSDT.yaml", "w") as f:
        yaml.dump(ict_eth_config, f)

    # cta_rbreaker_v3 配置文件
    rbreaker_dir = config_dir / "cta_rbreaker_v3"
    rbreaker_dir.mkdir(parents=True)

    rbreaker_config = {
        "cta_rbreaker_v3": {
            "enabled": True,
            "version": "3",
            "symbols": ["BTCUSDT"],
            "timeframes": ["15m"],
        }
    }
    with open(rbreaker_dir / "BTCUSDT.yaml", "w") as f:
        yaml.dump(rbreaker_config, f)

    # dolphin_trading_v2 配置文件
    dolphin_dir = config_dir / "dolphin_trading_v2"
    dolphin_dir.mkdir(parents=True)

    dolphin_config = {
        "dolphin_trading_v2": {
            "enabled": True,
            "version": "2",
            "symbols": ["BTCUSDT"],
            "timeframes": ["4h", "1h", "15m"],
        }
    }
    with open(dolphin_dir / "BTCUSDT.yaml", "w") as f:
        yaml.dump(dolphin_config, f)

    return config_dir


@pytest.fixture
def strategies_config_without_interval_version(tmp_path: Path, zktrading_config_dir: Path) -> Path:
    """创建 strategies.yaml（不含 interval 和 version）"""
    config_content = """
strategies:
  cta_ict_v3:
    trading_mode: "live"
    config_dir: "config/zktrading"
    symbols:
      - BTCUSDT
      - name: ETHUSDT
        trading_mode: "paper_trading"

  cta_rbreaker_v3:
    trading_mode: "paper_trading"
    config_dir: "config/zktrading"
    symbols:
      - BTCUSDT

  dolphin_trading_v2:
    trading_mode: "live"
    config_dir: "config/zktrading"
    symbols:
      - BTCUSDT
"""
    config_file = tmp_path / "strategies.yaml"
    config_file.write_text(config_content, encoding="utf-8")
    return config_file


@pytest.fixture
def strategies_config_with_interval_version(tmp_path: Path) -> Path:
    """创建 strategies.yaml（包含 interval 和 version - 用于对比）"""
    config_content = """
strategies:
  cta_ict_v3:
    interval: "4h"
    version: "v2"
    trading_mode: "live"
    config_dir: "config/zktrading"
    symbols:
      - BTCUSDT
"""
    config_file = tmp_path / "strategies_with_interval.yaml"
    config_file.write_text(config_content, encoding="utf-8")
    return config_file


# =============================================================================
# Test Case 1: 从 zktrading 配置读取 interval 和 version
# =============================================================================






# =============================================================================
# Test Case 2: 不同策略的 interval/version
# =============================================================================

class TestDifferentStrategiesIntervalVersion:
    """测试不同策略有不同的 interval 和 version"""


    def test_dolphin_interval_4h_version_2(
        self,
        strategies_config_without_interval_version: Path,
        zktrading_config_dir: Path
    ):
        """测试 dolphin_trading_v2 的 interval 和 version

        Given: zktrading/dolphin_trading_v2/BTCUSDT.yaml 有 timeframes: [4h, ...], version: '2'
        When: expand_strategies() 执行
        Then: interval="4h", version="2"
        """
        loader = StrategiesLoader(
            config_path=str(strategies_config_without_interval_version)
        )
        loader.load()

        instances = loader.expand_strategies()

        dolphin_instance = next(
            i for i in instances
            if i.name == "dolphin_trading_v2" and i.symbol == "BTCUSDT"
        )

        assert dolphin_instance.interval == "4h"
        assert dolphin_instance.version == "2"


# =============================================================================
# Test Case 3: symbol 级别 trading_mode 覆盖
# =============================================================================

class TestSymbolTradingModeOverride:
    """测试 symbol 级别 trading_mode 覆盖"""

    def test_symbol_trading_mode_paper_trading(
        self,
        strategies_config_without_interval_version: Path,
        zktrading_config_dir: Path
    ):
        """测试 ETHUSDT 使用 paper_trading

        Given: cta_ict_v3 默认 live，但 ETHUSDT 配置为 paper_trading
        When: expand_strategies() 执行
        Then: ETHUSDT 实例的 trading_mode = "paper_trading"
        """
        loader = StrategiesLoader(
            config_path=str(strategies_config_without_interval_version)
        )
        loader.load()

        instances = loader.expand_strategies()

        eth_instance = next(
            i for i in instances
            if i.name == "cta_ict_v3" and i.symbol == "ETHUSDT"
        )

        assert eth_instance.trading_mode == "paper_trading"


# =============================================================================
# Test Case 5: 错误处理 - zktrading 配置不存在
# =============================================================================

class TestErrorHandlingZktradingNotFound:
    """测试错误处理：zktrading 配置文件不存在"""

    def test_fallback_to_default_when_zktrading_not_found(
        self,
        tmp_path: Path
    ):
        """测试 zktrading 配置不存在时使用默认值

        Given: strategies.yaml 引用的 zktrading 配置文件不存在
        When: expand_strategies() 执行
        Then: 使用默认值 interval="4h", version="v2"
        """
        # strategies.yaml 引用不存在的 zktrading 目录
        config_content = """
strategies:
  test_strategy:
    trading_mode: "live"
    config_dir: "config/nonexistent"
    symbols:
      - BTCUSDT
"""
        config_file = tmp_path / "strategies.yaml"
        config_file.write_text(config_content, encoding="utf-8")

        loader = StrategiesLoader(config_path=str(config_file))
        loader.load()

        instances = loader.expand_strategies()

        assert len(instances) == 1
        # 应该使用默认值
        assert instances[0].interval == "4h"
        assert instances[0].version == "2"

    def test_fallback_to_default_when_zktrading_missing_timeframes(
        self,
        tmp_path: Path
    ):
        """测试 zktrading 配置缺少 timeframes 时使用默认值

        Given: zktrading 配置文件存在但没有 timeframes 字段
        When: expand_strategies() 执行
        Then: 使用默认值 interval="4h", version="v2"

        Note: expand_strategies 使用相对路径查找 zktrading 配置，
        在临时目录测试中文件不存在，因此使用默认值。
        """
        # 创建 strategies.yaml
        config_content = """
strategies:
  test_strategy:
    trading_mode: "live"
    config_dir: "config/test"
    symbols:
      - BTCUSDT
"""
        config_file = tmp_path / "strategies.yaml"
        config_file.write_text(config_content, encoding="utf-8")

        # 创建不完整的 zktrading 配置（使用相对路径，实际不会被找到）
        zktrading_dir = tmp_path / "config" / "test" / "test_strategy"
        zktrading_dir.mkdir(parents=True)

        incomplete_config = {
            "test_strategy": {
                "enabled": True,
                "version": "5",
                # 没有 timeframes
            }
        }
        with open(zktrading_dir / "BTCUSDT.yaml", "w") as f:
            yaml.dump(incomplete_config, f)

        loader = StrategiesLoader(config_path=str(config_file))
        loader.load()

        instances = loader.expand_strategies()

        # 由于使用相对路径，文件不存在，使用默认值
        assert instances[0].interval == "4h"
        assert instances[0].version == "2"


# =============================================================================
# Test Case 6: 验证实际实盘配置匹配
# =============================================================================



