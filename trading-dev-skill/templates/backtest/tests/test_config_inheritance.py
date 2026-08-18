#!/usr/bin/env python3
"""
测试配置覆盖合并功能

覆盖：
- merge_config_with_overrides: 深度合并配置

注：原 TestResolveStrategyConfigPath 已随 legacy 配置路径解析函数
（resolve_strategy_config_path）一并删除——per-symbol 路径现由
StrategiesLoader 统一生成为 strategies/<name>/overrides/<SYMBOL>.yaml。
"""

import pytest
from backtest.config_loader import merge_config_with_overrides


class TestMergeConfigWithOverrides:
    """测试深度合并配置"""

    def test_empty_overrides(self):
        """测试空 overrides"""
        base = {"version": "3", "enabled": True}
        result = merge_config_with_overrides(base, {})
        assert result == {"version": "3", "enabled": True}

    def test_simple_field_override(self):
        """测试简单字段覆盖"""
        base = {"version": "3", "enabled": True}
        overrides = {"enabled": False}
        result = merge_config_with_overrides(base, overrides)
        assert result == {"version": "3", "enabled": False}

    def test_nested_field_override(self):
        """测试嵌套字段覆盖（深度合并）"""
        base = {"capital": {"max_cash": 50, "leverage": 5}}
        overrides = {"capital": {"leverage": 10}}
        result = merge_config_with_overrides(base, overrides)
        assert result == {"capital": {"max_cash": 50, "leverage": 10}}

    def test_deep_nested_override(self):
        """测试深层嵌套覆盖"""
        base = {
            "risk": {
                "enabled": True,
                "trailing_profit": {
                    "enabled": True,
                    "activation_pct": 5.0,
                    "drawdown_pct": 20.0,
                },
            }
        }
        overrides = {
            "risk": {
                "trailing_profit": {
                    "enabled": False,
                }
            }
        }
        result = merge_config_with_overrides(base, overrides)
        assert result == {
            "risk": {
                "enabled": True,
                "trailing_profit": {
                    "enabled": False,
                    "activation_pct": 5.0,
                    "drawdown_pct": 20.0,
                },
            }
        }

    def test_array_replacement(self):
        """测试数组替换（不合并）"""
        base = {"params": {"ote_levels": [0.62, 0.705, 0.79]}}
        overrides = {"params": {"ote_levels": [0.5, 0.618]}}
        result = merge_config_with_overrides(base, overrides)
        assert result == {"params": {"ote_levels": [0.5, 0.618]}}

    def test_null_value_deletion(self):
        """测试 null 值删除字段"""
        base = {"capital": {"max_cash": 50, "leverage": 5}}
        overrides = {"capital": {"leverage": None}}
        result = merge_config_with_overrides(base, overrides)
        assert result == {"capital": {"max_cash": 50}}
        assert "leverage" not in result["capital"]

    def test_new_field_addition(self):
        """测试新增字段"""
        base = {"version": "3"}
        overrides = {"new_field": "new_value"}
        result = merge_config_with_overrides(base, overrides)
        assert result == {"version": "3", "new_field": "new_value"}

    def test_multiple_nested_objects(self):
        """测试多个嵌套对象同时覆盖"""
        base = {
            "params": {"cooldown_bars": 15, "fvg_min_size": 0.001},
            "capital": {"max_cash": 50, "leverage": 5},
            "risk": {"enabled": True},
        }
        overrides = {
            "params": {"cooldown_bars": 30},
            "capital": {"max_cash": 100},
        }
        result = merge_config_with_overrides(base, overrides)
        assert result == {
            "params": {"cooldown_bars": 30, "fvg_min_size": 0.001},
            "capital": {"max_cash": 100, "leverage": 5},
            "risk": {"enabled": True},
        }

    def test_base_unchanged(self):
        """测试原配置不被修改（不可变性）"""
        base = {"capital": {"max_cash": 50, "leverage": 5}}
        base_copy = {"capital": {"max_cash": 50, "leverage": 5}}
        overrides = {"capital": {"leverage": 10}}
        result = merge_config_with_overrides(base, overrides)
        # base 应保持不变
        assert base["capital"]["leverage"] == 5
        assert result["capital"]["leverage"] == 10
