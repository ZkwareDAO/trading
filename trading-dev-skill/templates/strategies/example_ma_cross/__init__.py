#!/usr/bin/env python3
"""example_ma_cross — 参考实现（reference implementation）策略模块"""

from .strategy import Strategy
from .example_ma_cross_core import ExampleMaCrossCore, ExampleMaCrossState

__all__ = ["Strategy", "ExampleMaCrossCore", "ExampleMaCrossState"]
