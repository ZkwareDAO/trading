#!/usr/bin/env python3
"""
风控配置数据类
"""

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class TrailingProfitConfig:
    """回落止盈配置

    注意：百分比使用数值形式，如 20 表示 20%
    drawdown_pct: 从最大盈利回落的百分比
        例如：drawdown_pct=20 表示从最大盈利回落 20%
        若最大盈利为 6%，则触发百分比为 6% × (1 - 0.2) = 4.8%
    """
    enabled: bool = True
    activation_pct: float = 20.0    # 激活阈值 (%)
    drawdown_pct: float = 20.0      # 回落百分比 (%)，从最大盈利回落的百分比


@dataclass
class RiskControlConfig:
    """风控配置

    注意：百分比使用数值形式，如 20 表示 20%
    """
    enabled: bool = True
    fixed_stop_loss_pct: float = 20.0    # 固定止损百分比 (%)
    trailing_profit: TrailingProfitConfig = field(default_factory=TrailingProfitConfig)
    fixed_take_profit_pct: float = 0.0   # 固定止盈百分比 (%)，0 表示禁用

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RiskControlConfig':
        """从配置字典解析"""
        if not data:
            return cls()

        trailing_data = data.get('trailing_profit', {})

        return cls(
            enabled=data.get('enabled', True),
            fixed_stop_loss_pct=data.get('fixed_stop_loss_pct', 20.0),
            trailing_profit=TrailingProfitConfig(
                enabled=trailing_data.get('enabled', True),
                activation_pct=trailing_data.get('activation_pct', 20.0),
                drawdown_pct=trailing_data.get('drawdown_pct', 20.0),
            ),
            fixed_take_profit_pct=data.get('fixed_take_profit_pct', 0.0),
        )
