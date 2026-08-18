#!/usr/bin/env python3
"""
测试策略名称生成和配置解析
"""

import sys
from pathlib import Path

# 添加项目根目录到 path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_extract_name_prefix():
    """测试 name_prefix 提取（私有 _extract_name_prefix，通过模块访问）"""
    import strategy_core.utils.strategy_naming as m

    assert m._extract_name_prefix("cta_ict_v3") == "ICT"
    assert m._extract_name_prefix("dolphin_trading_v2") == "DOLPHIN"
    assert m._extract_name_prefix("obv_atr_v2") == "OBVATR"
    assert m._extract_name_prefix("cta_rbreaker_v3") == "RBREAKER"
    assert m._extract_name_prefix("sar_snt3_v3") == "SARSNT3"

    print("✓ test_extract_name_prefix passed")


def test_build_strategy_name():
    """测试标准化策略 ID 生成（v6 统一函数）"""
    from strategy_core.utils.strategy_naming import build_strategy_id_from_overrides

    # version 前缀 'v/V' 被去掉
    # ICT_4H_2_BTCUSDT_LIVE
    name = build_strategy_id_from_overrides("cta_ict_v3", "BTCUSDT", "live", "4h", "v2")
    assert name == "ICT_4H_2_BTCUSDT_LIVE", f"Expected ICT_4H_2_BTCUSDT_LIVE, got {name}"

    # DOLPHIN_4H_2_ETHUSDT_PAPER
    name = build_strategy_id_from_overrides("dolphin_trading_v2", "ETHUSDT", "paper_trading", "4h", "v2")
    assert name == "DOLPHIN_4H_2_ETHUSDT_PAPER", f"Expected DOLPHIN_4H_2_ETHUSDT_PAPER, got {name}"

    # OBVATR_1H_2_SOLUSDT_LIVE
    name = build_strategy_id_from_overrides("obv_atr_v2", "SOLUSDT", "live", "1h", "v2")
    assert name == "OBVATR_1H_2_SOLUSDT_LIVE", f"Expected OBVATR_1H_2_SOLUSDT_LIVE, got {name}"

    print("✓ test_build_strategy_name passed")


def test_parse_strategies_config():
    """测试策略配置解析"""
    from run_strategies_manager import parse_strategies_config

    strategies = parse_strategies_config("config/settings.yaml")

    assert isinstance(strategies, list), f"Expected list, got {type(strategies)}"

    print(f"✓ test_parse_strategies_config passed (found {len(strategies)} strategies)")


def main():
    """运行所有测试"""
    print("=" * 50)
    print("Running paper trading tests...")
    print("=" * 50)

    test_extract_name_prefix()
    test_build_strategy_name()
    test_parse_strategies_config()

    print("=" * 50)
    print("All tests passed!")
    print("=" * 50)


if __name__ == "__main__":
    main()