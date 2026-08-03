#!/usr/bin/env python3
"""
策略基类模块

导出:
- BaseState: 状态基类
- BaseStrategyCore: 核心逻辑基类
- BaseStrategy: 策略基类
- RiskControlConfig: 风控配置
- TrailingProfitConfig: 回落止盈配置
- RiskController: 风控控制器
- ExitSignal: 出场信号
- calculate_adx, calculate_bollinger: 指标计算
"""

from .state import BaseState
from .core import BaseStrategyCore
from .strategy import BaseStrategy
from .indicators import calculate_adx, calculate_bollinger
from .risk_config import RiskControlConfig, TrailingProfitConfig
from .risk_control import RiskController, ExitSignal

__all__ = [
    "BaseState",
    "BaseStrategyCore",
    "BaseStrategy",
    "RiskControlConfig",
    "TrailingProfitConfig",
    "RiskController",
    "ExitSignal",
    "calculate_adx",
    "calculate_bollinger",
]