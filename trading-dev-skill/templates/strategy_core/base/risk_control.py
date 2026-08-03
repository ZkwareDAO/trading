#!/usr/bin/env python3
"""
统一风控控制器
"""

from dataclasses import dataclass
from typing import Optional

from .state import BaseState
from .risk_config import RiskControlConfig


@dataclass
class ExitSignal:
    """出场信号"""
    action: str           # "sell_close" / "buy_close"
    reason: str           # 出场原因
    is_stop_loss: bool    # 是否止损


class RiskController:
    """统一风控控制器"""

    def __init__(self, config: RiskControlConfig):
        self.config = config

    def check_exit(self, state: BaseState, current_price: float) -> Optional[ExitSignal]:
        """检查止盈止损"""
        if not self.config.enabled or not state.is_in_position() or state.entry_price <= 0:
            return None

        pnl_pct = self._calculate_pnl_pct(state, current_price)
        state.update_pnl_extremes(current_price)

        # 按优先级检查：固定止损 > 回落止盈 > 固定止盈
        return (
            self._check_fixed_stop_loss(state, pnl_pct)
            or self._check_trailing_profit(state, pnl_pct)
            or self._check_fixed_take_profit(state, pnl_pct)
        )

    def _calculate_pnl_pct(self, state: BaseState, current_price: float) -> float:
        """计算盈亏百分比（返回百分比形式，如 25.0 表示 25%）"""
        if state.position == "long":
            return (current_price - state.entry_price) / state.entry_price * 100
        return (state.entry_price - current_price) / state.entry_price * 100

    def _get_close_action(self, state: BaseState) -> str:
        """获取平仓动作"""
        return "sell_close" if state.position == "long" else "buy_close"

    def _check_fixed_stop_loss(self, state: BaseState, pnl_pct: float) -> Optional[ExitSignal]:
        """检查固定止损"""
        if pnl_pct > -self.config.fixed_stop_loss_pct:
            return None
        return ExitSignal(
            action=self._get_close_action(state),
            reason=f"固定止损: {pnl_pct:.2f}%",
            is_stop_loss=True,
        )

    def _check_trailing_profit(self, state: BaseState, pnl_pct: float) -> Optional[ExitSignal]:
        """检查回落止盈（百分比回落模式）"""
        tp_config = self.config.trailing_profit
        if not tp_config.enabled:
            return None

        # 激活检查
        if pnl_pct >= tp_config.activation_pct:
            state.trail_activated = True
            # 百分比回落：触发百分比 = 最大盈利 × (1 - 回落百分比/100)
            state.trail_trigger_pct = state.max_pnl_pct * (1 - tp_config.drawdown_pct / 100)

        # 触发检查
        if state.trail_activated and pnl_pct <= state.trail_trigger_pct:
            return ExitSignal(
                action=self._get_close_action(state),
                reason=f"回落止盈: max={state.max_pnl_pct:.2f}%, 当前={pnl_pct:.2f}%",
                is_stop_loss=False,
            )
        return None

    def _check_fixed_take_profit(self, state: BaseState, pnl_pct: float) -> Optional[ExitSignal]:
        """检查固定止盈"""
        if self.config.fixed_take_profit_pct <= 0 or pnl_pct < self.config.fixed_take_profit_pct:
            return None
        return ExitSignal(
            action=self._get_close_action(state),
            reason=f"固定止盈: {pnl_pct:.2f}%",
            is_stop_loss=False,
        )