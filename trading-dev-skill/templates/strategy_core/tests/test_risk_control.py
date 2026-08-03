#!/usr/bin/env python3
"""
风控控制器单元测试

测试统一风控模块的各种场景
"""

import pytest
from datetime import datetime, timezone

from strategy_core.base.state import BaseState
from strategy_core.base.risk_config import RiskControlConfig, TrailingProfitConfig
from strategy_core.base.risk_control import RiskController, ExitSignal


class TestRiskControlConfig:
    """测试风控配置"""

    def test_default_config(self):
        """默认配置"""
        config = RiskControlConfig()
        assert config.enabled == True
        assert config.fixed_stop_loss_pct == 20.0
        assert config.trailing_profit.enabled == True
        assert config.trailing_profit.activation_pct == 20.0
        assert config.trailing_profit.drawdown_pct == 20.0  # 新默认值
        assert config.fixed_take_profit_pct == 0.0

    def test_from_dict_full(self):
        """从完整字典解析"""
        data = {
            "enabled": True,
            "fixed_stop_loss_pct": 15.0,
            "trailing_profit": {
                "enabled": True,
                "activation_pct": 10.0,
                "drawdown_pct": 3.0,
            },
            "fixed_take_profit_pct": 5.0,
        }
        config = RiskControlConfig.from_dict(data)
        assert config.enabled == True
        assert config.fixed_stop_loss_pct == 15.0
        assert config.trailing_profit.activation_pct == 10.0
        assert config.trailing_profit.drawdown_pct == 3.0
        assert config.fixed_take_profit_pct == 5.0

    def test_from_dict_partial(self):
        """从部分字典解析（使用默认值）"""
        data = {"enabled": False}
        config = RiskControlConfig.from_dict(data)
        assert config.enabled == False
        assert config.fixed_stop_loss_pct == 20.0  # 默认值

    def test_from_dict_empty(self):
        """从空字典解析"""
        config = RiskControlConfig.from_dict({})
        assert config.enabled == True  # 默认值


class TestRiskControllerFixedStopLoss:
    """测试固定止损"""

    def setup_method(self):
        """每个测试前初始化"""
        self.config = RiskControlConfig(
            enabled=True,
            fixed_stop_loss_pct=20.0,  # 20%
            trailing_profit=TrailingProfitConfig(enabled=False),
            fixed_take_profit_pct=0.0,
        )
        self.controller = RiskController(self.config)

    def test_long_stop_loss_triggered(self):
        """多头止损触发"""
        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 亏损 21%，超过 20% 阈值
        exit_signal = self.controller.check_exit(state, 79.0)

        assert exit_signal is not None
        assert exit_signal.action == "sell_close"
        assert exit_signal.is_stop_loss == True
        assert "固定止损" in exit_signal.reason

    def test_long_stop_loss_not_triggered(self):
        """多头止损未触发"""
        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 亏损 15%，未达到 20% 阈值
        exit_signal = self.controller.check_exit(state, 85.0)

        assert exit_signal is None

    def test_short_stop_loss_triggered(self):
        """空头止损触发"""
        state = BaseState()
        state.position = "short"
        state.entry_price = 100.0

        # 价格上涨 21%，亏损超过 20% 阈值
        exit_signal = self.controller.check_exit(state, 121.0)

        assert exit_signal is not None
        assert exit_signal.action == "buy_close"
        assert exit_signal.is_stop_loss == True

    def test_short_stop_loss_not_triggered(self):
        """空头止损未触发"""
        state = BaseState()
        state.position = "short"
        state.entry_price = 100.0

        # 价格上涨 15%，亏损未达阈值
        exit_signal = self.controller.check_exit(state, 115.0)

        assert exit_signal is None

    def test_stop_loss_boundary(self):
        """止损边界值（刚好触发）"""
        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 亏损刚好 20%
        exit_signal = self.controller.check_exit(state, 80.0)

        assert exit_signal is not None
        assert exit_signal.is_stop_loss == True


class TestRiskControllerTrailingProfit:
    """测试回落止盈（百分比回落模式）"""

    def setup_method(self):
        """每个测试前初始化"""
        self.config = RiskControlConfig(
            enabled=True,
            fixed_stop_loss_pct=50.0,  # 设置很大，避免触发
            trailing_profit=TrailingProfitConfig(
                enabled=True,
                activation_pct=20.0,  # 20%
                drawdown_pct=20.0,    # 20%（从最大盈利回落 20%）
            ),
            fixed_take_profit_pct=0.0,
        )
        self.controller = RiskController(self.config)

    def test_trailing_activation_pct_drawdown(self):
        """回落止盈激活 - 百分比回落模式"""
        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 盈利 25%，超过激活阈值 20%
        # 触发百分比 = 25% × (1 - 20%) = 20%
        self.controller.check_exit(state, 125.0)

        assert state.trail_activated == True
        assert state.max_pnl_pct == 25.0
        assert state.trail_trigger_pct == 20.0  # 25 * 0.8

    def test_trailing_activation_6_pct_drawdown(self):
        """最大盈利 6%，回落 20% -> 触发百分比 4.8%"""
        # 使用较低的激活阈值来测试 6% 盈利的场景
        config = RiskControlConfig(
            enabled=True,
            fixed_stop_loss_pct=50.0,
            trailing_profit=TrailingProfitConfig(
                enabled=True,
                activation_pct=5.0,   # 5% 激活阈值
                drawdown_pct=20.0,    # 20% 回落
            ),
            fixed_take_profit_pct=0.0,
        )
        controller = RiskController(config)

        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 盈利 6%，超过激活阈值 5%
        # 触发百分比 = 6% × 0.8 = 4.8%
        controller.check_exit(state, 106.0)

        assert state.trail_activated == True
        assert state.max_pnl_pct == 6.0
        assert state.trail_trigger_pct == pytest.approx(4.8)  # 6 * 0.8

    def test_trailing_not_activated_below_threshold(self):
        """盈利未达激活阈值"""
        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 盈利 15%，未达激活阈值 20%
        self.controller.check_exit(state, 115.0)

        assert state.trail_activated == False

    def test_trailing_triggered_after_drawdown(self):
        """回落触发止盈 - 百分比模式"""
        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0
        state.max_pnl_pct = 25.0
        state.trail_activated = True
        state.trail_trigger_pct = 20.0  # 25% × 0.8

        # 盈利回落到 19%，低于触发百分比 20%
        exit_signal = self.controller.check_exit(state, 119.0)

        assert exit_signal is not None
        assert exit_signal.action == "sell_close"
        assert exit_signal.is_stop_loss == False
        assert "回落止盈" in exit_signal.reason

    def test_trailing_not_triggered_above_trigger(self):
        """回落但仍在触发线以上"""
        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0
        state.max_pnl_pct = 25.0
        state.trail_activated = True
        state.trail_trigger_pct = 20.0  # 25% × 0.8

        # 盈利回落到 21%，仍高于触发百分比 20%
        exit_signal = self.controller.check_exit(state, 121.0)

        assert exit_signal is None

    def test_short_trailing_activation(self):
        """空头回落止盈激活"""
        state = BaseState()
        state.position = "short"
        state.entry_price = 100.0

        # 价格下跌 25%，盈利 25%
        # 触发百分比 = 25% × 0.8 = 20%
        self.controller.check_exit(state, 75.0)

        assert state.trail_activated == True
        assert state.max_pnl_pct == 25.0
        assert state.trail_trigger_pct == 20.0

    def test_short_trailing_triggered(self):
        """空头回落触发止盈"""
        state = BaseState()
        state.position = "short"
        state.entry_price = 100.0
        state.max_pnl_pct = 25.0
        state.trail_activated = True
        state.trail_trigger_pct = 20.0  # 25% × 0.8

        # 价格回升到 81%，盈利回落到 19%
        exit_signal = self.controller.check_exit(state, 81.0)

        assert exit_signal is not None
        assert exit_signal.action == "buy_close"
        assert exit_signal.is_stop_loss == False


class TestRiskControllerFixedTakeProfit:
    """测试固定止盈"""

    def setup_method(self):
        """每个测试前初始化"""
        self.config = RiskControlConfig(
            enabled=True,
            fixed_stop_loss_pct=50.0,
            trailing_profit=TrailingProfitConfig(enabled=False),
            fixed_take_profit_pct=4.0,  # 4% 固定止盈
        )
        self.controller = RiskController(self.config)

    def test_fixed_take_profit_triggered(self):
        """固定止盈触发"""
        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 盈利 5%，超过 4% 阈值
        exit_signal = self.controller.check_exit(state, 105.0)

        assert exit_signal is not None
        assert exit_signal.action == "sell_close"
        assert exit_signal.is_stop_loss == False
        assert "固定止盈" in exit_signal.reason

    def test_fixed_take_profit_not_triggered(self):
        """固定止盈未触发"""
        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 盈利 3%，未达 4% 阈值
        exit_signal = self.controller.check_exit(state, 103.0)

        assert exit_signal is None

    def test_fixed_take_profit_disabled(self):
        """固定止盈禁用（0值）"""
        config = RiskControlConfig(
            fixed_take_profit_pct=0.0,
        )
        controller = RiskController(config)

        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 盈利 50%，但因禁用不触发
        exit_signal = controller.check_exit(state, 150.0)

        assert exit_signal is None


class TestRiskControllerDisabled:
    """测试风控禁用"""

    def test_risk_disabled(self):
        """风控总开关禁用"""
        config = RiskControlConfig(enabled=False)
        controller = RiskController(config)

        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 亏损 50%，但因禁用不触发
        exit_signal = controller.check_exit(state, 50.0)

        assert exit_signal is None

    def test_trailing_profit_disabled(self):
        """回落止盈禁用"""
        config = RiskControlConfig(
            trailing_profit=TrailingProfitConfig(enabled=False),
        )
        controller = RiskController(config)

        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0
        state.max_pnl_pct = 0.30
        state.trail_activated = True
        state.trail_trigger_pct = 0.25

        # 盈利大幅回落，但因禁用不触发
        exit_signal = controller.check_exit(state, 101.0)

        assert exit_signal is None


class TestRiskControllerEdgeCases:
    """测试边界情况"""

    def test_no_position(self):
        """无持仓"""
        config = RiskControlConfig()
        controller = RiskController(config)

        state = BaseState()  # position = None

        exit_signal = controller.check_exit(state, 100.0)

        assert exit_signal is None

    def test_zero_entry_price(self):
        """开仓价格为0"""
        config = RiskControlConfig()
        controller = RiskController(config)

        state = BaseState()
        state.position = "long"
        state.entry_price = 0.0

        exit_signal = controller.check_exit(state, 100.0)

        assert exit_signal is None  # 无法计算盈亏

    def test_state_pnl_extremes_updated(self):
        """状态盈亏极值被更新"""
        config = RiskControlConfig(
            trailing_profit=TrailingProfitConfig(enabled=False),
        )
        controller = RiskController(config)

        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0
        state.max_pnl_pct = 0.0

        # 检查风控，应更新 max_pnl_pct
        controller.check_exit(state, 110.0)

        assert state.max_pnl_pct == 10.0  # 百分比形式

    def test_max_pnl_updates_trail_trigger(self):
        """最大盈利更新时，触发百分比也更新（百分比回落模式）"""
        config = RiskControlConfig(
            trailing_profit=TrailingProfitConfig(
                enabled=True,
                activation_pct=15.0,  # 15%
                drawdown_pct=20.0,    # 20%
            ),
        )
        controller = RiskController(config)

        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 第一次盈利 20%
        # 触发百分比 = 20% × 0.8 = 16%
        controller.check_exit(state, 120.0)
        assert state.trail_trigger_pct == 16.0  # 20 * 0.8

        # 继续盈利到 30%
        # 触发百分比 = 30% × 0.8 = 24%
        controller.check_exit(state, 130.0)
        assert state.trail_trigger_pct == 24.0  # 30 * 0.8