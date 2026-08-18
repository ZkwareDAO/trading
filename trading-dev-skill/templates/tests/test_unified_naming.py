"""
Test unified strategy_id generation — v6 统一命名方案

唯一对外生成函数: build_strategy_id_from_overrides
- prefix 由 strategy_dir 推导（内部 _extract_name_prefix）
- 格式: {PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}_{MODE}
- sar_snt3_v3/BTCUSDT/4h/v3/paper → SARSNT3_4H_3_BTCUSDT_PAPER

已删除（不应再可导入）: build_strategy_id, build_strategy_name, extract_name_prefix(对外)
"""

import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestBuildStrategyIdFromOverrides:
    """唯一权威生成函数 build_strategy_id_from_overrides"""

    def test_sar_snt3_v3_paper(self):
        from strategy_core.utils.strategy_naming import build_strategy_id_from_overrides
        sid = build_strategy_id_from_overrides(
            "sar_snt3_v3", "BTCUSDT", "paper_trading", "4h", "3"
        )
        assert sid == "SARSNT3_4H_3_BTCUSDT_PAPER"

    def test_sar_snt3_v3_live_version_v3(self):
        """version v3 与 3 等价（去 v/V 前缀）"""
        from strategy_core.utils.strategy_naming import build_strategy_id_from_overrides
        sid = build_strategy_id_from_overrides(
            "sar_snt3_v3", "BTCUSDT", "live", "4h", "v3"
        )
        assert sid == "SARSNT3_4H_3_BTCUSDT_LIVE"

    def test_obv_atr_v2(self):
        from strategy_core.utils.strategy_naming import build_strategy_id_from_overrides
        sid = build_strategy_id_from_overrides(
            "obv_atr_v2", "SOLUSDT", "live", "1h", "v2"
        )
        assert sid == "OBVATR_1H_2_SOLUSDT_LIVE"

    def test_cta_rbreaker_v3(self):
        """cta_ 前缀被剥离"""
        from strategy_core.utils.strategy_naming import build_strategy_id_from_overrides
        sid = build_strategy_id_from_overrides(
            "cta_rbreaker_v3", "BNBUSDT", "paper_trading", "15m", "3"
        )
        assert sid == "RBREAKER_15M_3_BNBUSDT_PAPER"

    def test_interval_default(self):
        """interval 未传时回退默认 1h"""
        from strategy_core.utils.strategy_naming import build_strategy_id_from_overrides
        sid = build_strategy_id_from_overrides(
            "sar_snt3_v3", "BTCUSDT", "live", version="3"
        )
        assert sid == "SARSNT3_1H_3_BTCUSDT_LIVE"

    def test_version_default(self):
        """version 未传时回退默认 1"""
        from strategy_core.utils.strategy_naming import build_strategy_id_from_overrides
        sid = build_strategy_id_from_overrides(
            "sar_snt3_v3", "BTCUSDT", "live", "4h"
        )
        assert sid == "SARSNT3_4H_1_BTCUSDT_LIVE"

    def test_symbol_uppercased(self):
        """symbol 自动大写"""
        from strategy_core.utils.strategy_naming import build_strategy_id_from_overrides
        sid = build_strategy_id_from_overrides(
            "sar_snt3_v3", "btcusdt", "live", "4h", "3"
        )
        assert sid == "SARSNT3_4H_3_BTCUSDT_LIVE"

    def test_smoking_mode(self):
        from strategy_core.utils.strategy_naming import build_strategy_id_from_overrides
        sid = build_strategy_id_from_overrides(
            "sar_snt3_v3", "BTCUSDT", "smoking", "4h", "3"
        )
        assert sid == "SARSNT3_4H_3_BTCUSDT_SMOKING"


class TestRemovedLegacyFunctions:
    """旧函数应已删除，不可导入"""

    def test_build_strategy_id_removed(self):
        import strategy_core.utils.strategy_naming as m
        assert not hasattr(m, "build_strategy_id"), "build_strategy_id 应已删除"

    def test_build_strategy_name_removed(self):
        import strategy_core.utils.strategy_naming as m
        assert not hasattr(m, "build_strategy_name"), "build_strategy_name 应已删除"

    def test_extract_name_prefix_not_public(self):
        """extract_name_prefix 降为私有 _extract_name_prefix，不再对外"""
        import strategy_core.utils.strategy_naming as m
        assert not hasattr(m, "extract_name_prefix"), "extract_name_prefix 应降为私有"

    def test_get_strategy_name_params_removed(self):
        """strategy_loader 模块已整体删除"""
        import importlib
        assert importlib.util.find_spec("strategy_core.utils.strategy_loader") is None, \
            "strategy_loader 模块应已删除"


class TestBaseStrategyNamingConsolidation:
    """BaseStrategy 命名收口到 _external_strategy_name"""

    def test_strategy_id_for_removed(self):
        from strategy_core.base.strategy import BaseStrategy
        assert not hasattr(BaseStrategy, "strategy_id_for"), \
            "strategy_id_for 应删除，改用 _external_strategy_name"

    def test_strategy_name_for_removed(self):
        from strategy_core.base.strategy import BaseStrategy
        assert not hasattr(BaseStrategy, "strategy_name_for"), \
            "strategy_name_for 应删除"

    def test_strategy_prefix_removed(self):
        from strategy_core.base.strategy import BaseStrategy
        assert not hasattr(BaseStrategy, "STRATEGY_PREFIX"), \
            "STRATEGY_PREFIX 类属性应删除"

    def test_strategy_name_property_returns_external(self):
        """strategy_name property 直接返回 _external_strategy_name，无回退分支"""
        from strategy_core.base.strategy import BaseStrategy
        # 用一个最小具体子类绕过 ABC 抽象检查，仅测 property
        class _Concrete(BaseStrategy):
            def _create_core(self):
                return None
        instance = _Concrete.__new__(_Concrete)
        instance._external_strategy_name = "SARSNT3_4H_3_BTCUSDT_PAPER"
        assert instance.strategy_name == "SARSNT3_4H_3_BTCUSDT_PAPER"
