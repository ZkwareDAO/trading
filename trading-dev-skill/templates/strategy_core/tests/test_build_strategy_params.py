#!/usr/bin/env python3
"""
测试 engine._build_strategy_params 读取新格式 risk 配置

验证:
- fixed_stop_loss_pct 正确映射到 StopLossThreshold
- trailing_profit.activation_pct 正确映射到 TakeProfitBackThreshold
- trailing_profit.drawdown_pct 正确映射到 TakeProfitBackDynamicFallPercent
"""

import pytest
from unittest.mock import MagicMock

from strategy_core.strategy_engine.engine import StrategyEngine


class TestBuildStrategyParamsNewRiskFormat:
    """测试 _build_strategy_params 读取新格式 risk 配置"""

    def setup_method(self):
        """每个测试前初始化"""
        self.engine = StrategyEngine(
            factory_endpoint="http://127.0.0.1:8888",
            strategies_dir="./strategies",
        )

    def test_new_risk_format_fixed_stop_loss(self):
        """新格式: fixed_stop_loss_pct -> StopLossThreshold"""
        entry = MagicMock()
        entry.config = {
            "params": {"threshold": 0.005},
            "risk": {
                "enabled": True,
                "fixed_stop_loss_pct": 2.0,
                "trailing_profit": {
                    "enabled": True,
                    "activation_pct": 5.0,
                    "drawdown_pct": 20.0,
                },
                "fixed_take_profit_pct": 0.0,
            },
        }

        params = self.engine._build_strategy_params(entry)

        # fixed_stop_loss_pct: 2.0 -> StopLossThreshold: 2.0
        assert params["StopLossThreshold"] == 2.0

    def test_new_risk_format_trailing_activation(self):
        """新格式: trailing_profit.activation_pct -> TakeProfitBackThreshold"""
        entry = MagicMock()
        entry.config = {
            "risk": {
                "trailing_profit": {
                    "enabled": True,
                    "activation_pct": 5.0,
                    "drawdown_pct": 20.0,
                },
            },
        }

        params = self.engine._build_strategy_params(entry)

        # activation_pct: 5.0 -> TakeProfitBackThreshold: 5.0
        assert params["TakeProfitBackThreshold"] == 5.0

    def test_new_risk_format_trailing_drawdown(self):
        """新格式: trailing_profit.drawdown_pct -> TakeProfitBackDynamicFallPercent"""
        entry = MagicMock()
        entry.config = {
            "risk": {
                "trailing_profit": {
                    "enabled": True,
                    "activation_pct": 5.0,
                    "drawdown_pct": 20.0,
                },
            },
        }

        params = self.engine._build_strategy_params(entry)

        # drawdown_pct: 20.0 -> TakeProfitBackDynamicFallPercent: 20.0
        assert params["TakeProfitBackDynamicFallPercent"] == 20.0

    def test_new_risk_format_all_fields(self):
        """新格式: 所有风控字段正确映射"""
        entry = MagicMock()
        entry.config = {
            "params": {"threshold": 0.005},
            "risk": {
                "enabled": True,
                "fixed_stop_loss_pct": 3.0,
                "trailing_profit": {
                    "enabled": True,
                    "activation_pct": 10.0,
                    "drawdown_pct": 15.0,
                },
                "fixed_take_profit_pct": 0.0,
            },
        }

        params = self.engine._build_strategy_params(entry)

        assert params["StopLossThreshold"] == 3.0
        assert params["TakeProfitBackThreshold"] == 10.0
        assert params["TakeProfitBackDynamicFallPercent"] == 15.0

    def test_old_risk_format_still_works(self):
        """向后兼容: 旧格式仍然工作"""
        entry = MagicMock()
        entry.config = {
            "risk": {
                "stop_loss_pct": 2.0,
                "trailing_profit_activation": 5.0,
                "trailing_profit_drawdown": 20.0,
            },
        }

        params = self.engine._build_strategy_params(entry)

        # 旧格式也应该能工作
        assert params["StopLossThreshold"] == 2.0
        assert params["TakeProfitBackThreshold"] == 5.0
        assert params["TakeProfitBackDynamicFallPercent"] == 20.0

    def test_no_risk_config_uses_defaults(self):
        """无 risk 配置时使用默认值"""
        entry = MagicMock()
        entry.config = {}

        params = self.engine._build_strategy_params(entry)

        # 应使用默认值
        from strategy_core.constants import (
            DEFAULT_STOP_LOSS_PCT,
            DEFAULT_TRAILING_PROFIT_ACTIVATION,
            DEFAULT_TRAILING_PROFIT_DRAWDOWN,
        )
        assert params["StopLossThreshold"] == DEFAULT_STOP_LOSS_PCT
        assert params["TakeProfitBackThreshold"] == DEFAULT_TRAILING_PROFIT_ACTIVATION
        assert params["TakeProfitBackDynamicFallPercent"] == DEFAULT_TRAILING_PROFIT_DRAWDOWN

    def test_new_format_overrides_old_format(self):
        """新格式优先于旧格式（当两者都存在时）"""
        entry = MagicMock()
        entry.config = {
            "risk": {
                # 旧格式
                "stop_loss_pct": 10.0,
                "trailing_profit_activation": 10.0,
                "trailing_profit_drawdown": 10.0,
                # 新格式（应该优先）
                "fixed_stop_loss_pct": 2.0,
                "trailing_profit": {
                    "activation_pct": 5.0,
                    "drawdown_pct": 20.0,
                },
            },
        }

        params = self.engine._build_strategy_params(entry)

        # 新格式应该优先
        assert params["StopLossThreshold"] == 2.0
        assert params["TakeProfitBackThreshold"] == 5.0
        assert params["TakeProfitBackDynamicFallPercent"] == 20.0

    def test_capital_leverage_is_injected(self):
        """capital.leverage 正确注入到 params"""
        entry = MagicMock()
        entry.config = {
            "capital": {
                "max_cash": 200,
                "max_parts": 1,
                "leverage": 10,  # 自定义杠杆
            },
        }

        params = self.engine._build_strategy_params(entry)

        # leverage 应该被注入
        assert params["leverage"] == 10

    def test_capital_leverage_missing_uses_default(self):
        """capital.leverage 缺失时不注入（使用 CtaSignalCSV 默认值 5）"""
        entry = MagicMock()
        entry.config = {
            "capital": {
                "max_cash": 200,
                "max_parts": 1,
                # 无 leverage
            },
        }

        params = self.engine._build_strategy_params(entry)

        # leverage 不应该在 params 中（CtaSignalCSV 会使用默认值 5）
        assert "leverage" not in params

    def test_capital_leverage_zero_is_passed(self):
        """capital.leverage=0 时仍被注入（业务层应拒绝，而非配置层）"""
        entry = MagicMock()
        entry.config = {
            "capital": {
                "leverage": 0,  # 无效值：零杠杆
            },
        }

        params = self.engine._build_strategy_params(entry)

        # 当前行为：直接传递（下游 CtaSignalCSV 或交易系统应验证）
        assert params["leverage"] == 0

    def test_capital_leverage_negative_is_passed(self):
        """capital.leverage=-1 时仍被注入（业务层应拒绝，而非配置层）"""
        entry = MagicMock()
        entry.config = {
            "capital": {
                "leverage": -1,  # 无效值：负杠杆
            },
        }

        params = self.engine._build_strategy_params(entry)

        # 当前行为：直接传递（下游应验证）
        assert params["leverage"] == -1

    def test_capital_leverage_float_is_converted(self):
        """capital.leverage=5.5 时仍被注入（CtaSignalCSV 接受 int）"""
        entry = MagicMock()
        entry.config = {
            "capital": {
                "leverage": 5.5,  # 浮点数
            },
        }

        params = self.engine._build_strategy_params(entry)

        # 当前行为：直接传递（CtaSignalCSV.from_signal 接受 int，会丢失精度）
        assert params["leverage"] == 5.5

    def test_capital_leverage_very_large_is_passed(self):
        """capital.leverage=1000 时仍被注入（业务层应限制杠杆范围）"""
        entry = MagicMock()
        entry.config = {
            "capital": {
                "leverage": 1000,  # 极大值
            },
        }

        params = self.engine._build_strategy_params(entry)

        # 当前行为：直接传递（交易系统可能拒绝）
        assert params["leverage"] == 1000
