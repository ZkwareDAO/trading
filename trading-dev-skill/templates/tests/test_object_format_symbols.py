"""
对象格式 symbols 测试

测试 symbols 支持两种格式：
1. 字符串数组（向后兼容）: [BTCUSDT, ETHUSDT]
2. 对象数组（新格式）: [{name: BTCUSDT, trading_mode: "paper_trading"}]
"""

import pytest
from pathlib import Path

from strategy_core.utils.strategies_loader import (
    StrategiesLoader,
    StrategyInstance,
)


# =============================================================================
# 对象格式 symbols 测试
# =============================================================================

class TestObjectFormatSymbols:
    """测试对象格式 symbols"""

    @pytest.fixture
    def object_format_config(self, tmp_path: Path) -> Path:
        """创建对象格式配置文件"""
        config_content = """
templates:
  cta_ict_v3:
    interval: "4h"
    version: "v2"

strategies:
  cta_ict_v3:
    trading_mode: "live"  # 默认值
    symbols:
      - name: BTCUSDT
        # 使用默认 trading_mode
      - name: ETHUSDT
        trading_mode: "live"
      - name: SOLUSDT
        trading_mode: "paper_trading"
      - name: NEARUSDT
        trading_mode: "paper_trading"
"""
        config_file = tmp_path / "object_format.yaml"
        config_file.write_text(config_content, encoding="utf-8")
        return config_file

    @pytest.fixture
    def mixed_format_config(self, tmp_path: Path) -> Path:
        """创建混合格式配置文件（字符串 + 对象）"""
        config_content = """
templates:
  cta_ict_v3:
    interval: "4h"

strategies:
  cta_ict_v3:
    trading_mode: "live"
    symbols:
      - BTCUSDT  # 字符串格式，使用默认 trading_mode
      - name: ETHUSDT
        trading_mode: "paper_trading"  # 对象格式，覆盖默认
      - SOLUSDT  # 字符串格式
"""
        config_file = tmp_path / "mixed_format.yaml"
        config_file.write_text(config_content, encoding="utf-8")
        return config_file

    def test_object_format_symbols(self, object_format_config: Path):
        """测试对象格式 symbols 展开"""
        loader = StrategiesLoader(str(object_format_config)).load()
        instances = loader.expand_strategies()

        assert len(instances) == 4

        # 验证 trading_mode
        btc = next(i for i in instances if i.symbol == "BTCUSDT")
        assert btc.trading_mode == "live"  # 使用默认值

        eth = next(i for i in instances if i.symbol == "ETHUSDT")
        assert eth.trading_mode == "live"  # 显式指定

        sol = next(i for i in instances if i.symbol == "SOLUSDT")
        assert sol.trading_mode == "paper_trading"

        near = next(i for i in instances if i.symbol == "NEARUSDT")
        assert near.trading_mode == "paper_trading"

    def test_mixed_format_symbols(self, mixed_format_config: Path):
        """测试混合格式 symbols（字符串 + 对象）"""
        loader = StrategiesLoader(str(mixed_format_config)).load()
        instances = loader.expand_strategies()

        assert len(instances) == 3

        btc = next(i for i in instances if i.symbol == "BTCUSDT")
        assert btc.trading_mode == "live"  # 字符串格式，使用默认

        eth = next(i for i in instances if i.symbol == "ETHUSDT")
        assert eth.trading_mode == "paper_trading"  # 对象格式，覆盖

        sol = next(i for i in instances if i.symbol == "SOLUSDT")
        assert sol.trading_mode == "live"  # 字符串格式，使用默认

    def test_filter_by_trading_mode_with_object_format(self, object_format_config: Path):
        """测试按 trading_mode 过滤（对象格式）"""
        loader = StrategiesLoader(str(object_format_config)).load()

        live_instances = loader.filter(trading_mode="live")
        paper_instances = loader.filter(trading_mode="paper_trading")

        assert len(live_instances) == 2
        assert len(paper_instances) == 2


# =============================================================================
# 向后兼容测试
# =============================================================================

class TestBackwardCompatibility:
    """测试向后兼容性"""

    @pytest.fixture
    def string_format_config(self, tmp_path: Path) -> Path:
        """创建字符串格式配置文件（旧格式）"""
        config_content = """
templates:
  cta_ict_v3:
    interval: "4h"

strategies:
  cta_ict_v3:
    symbols: [BTCUSDT, ETHUSDT, SOLUSDT]
    trading_mode: "live"
"""
        config_file = tmp_path / "string_format.yaml"
        config_file.write_text(config_content, encoding="utf-8")
        return config_file

    def test_string_format_still_works(self, string_format_config: Path):
        """测试字符串格式仍然有效"""
        loader = StrategiesLoader(str(string_format_config)).load()
        instances = loader.expand_strategies()

        assert len(instances) == 3

        for instance in instances:
            assert instance.trading_mode == "live"

    def test_string_format_filter(self, string_format_config: Path):
        """测试字符串格式的过滤功能"""
        loader = StrategiesLoader(str(string_format_config)).load()

        live_instances = loader.filter(trading_mode="live")
        paper_instances = loader.filter(trading_mode="paper_trading")

        assert len(live_instances) == 3
        assert len(paper_instances) == 0


# =============================================================================
# 边界情况测试
# =============================================================================

class TestEdgeCasesForObjectFormat:
    """测试边界情况"""

    @pytest.fixture
    def empty_trading_mode_config(self, tmp_path: Path) -> Path:
        """创建无 trading_mode 的配置"""
        config_content = """
defaults:
  trading_mode: "live"

strategies:
  cta_ict_v3:
    symbols:
      - BTCUSDT
      - name: ETHUSDT
"""
        config_file = tmp_path / "empty_trading_mode.yaml"
        config_file.write_text(config_content, encoding="utf-8")
        return config_file

    def test_missing_trading_mode_uses_default(self, empty_trading_mode_config: Path):
        """测试缺失 trading_mode 时使用默认值"""
        loader = StrategiesLoader(str(empty_trading_mode_config)).load()
        instances = loader.expand_strategies()

        assert len(instances) == 2

        for instance in instances:
            assert instance.trading_mode == "live"  # 使用全局默认值

    def test_symbol_object_with_only_name(self, tmp_path: Path):
        """测试对象格式只有 name 字段"""
        config_content = """
strategies:
  test:
    trading_mode: "paper_trading"
    symbols:
      - name: BTCUSDT
"""
        config_file = tmp_path / "only_name.yaml"
        config_file.write_text(config_content, encoding="utf-8")

        loader = StrategiesLoader(str(config_file)).load()
        instances = loader.expand_strategies()

        assert len(instances) == 1
        assert instances[0].symbol == "BTCUSDT"
        assert instances[0].trading_mode == "paper_trading"
