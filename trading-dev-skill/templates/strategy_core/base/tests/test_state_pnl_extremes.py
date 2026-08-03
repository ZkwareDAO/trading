#!/usr/bin/env python3
"""测试 BaseState 新增字段 max_pnl_pct 和 min_pnl_pct"""

import pytest
from datetime import datetime, date
from strategy_core.base.state import BaseState


class TestBaseStatePnlExtremes:
    """测试盈亏极值字段"""

    def test_default_values(self):
        """默认值为 0.0"""
        state = BaseState()
        assert state.max_pnl_pct == 0.0
        assert state.min_pnl_pct == 0.0

    def test_max_pnl_pct_positive(self):
        """max_pnl_pct 应该记录最大盈利百分比"""
        state = BaseState()
        state.max_pnl_pct = 5.5  # 5.5% 盈利
        assert state.max_pnl_pct == 5.5

    def test_min_pnl_pct_negative(self):
        """min_pnl_pct 应该记录最大亏损百分比（负数）"""
        state = BaseState()
        state.min_pnl_pct = -3.2  # -3.2% 亏损
        assert state.min_pnl_pct == -3.2

    def test_to_persist_dict_includes_pnl_extremes(self):
        """to_persist_dict 应该包含盈亏极值字段"""
        state = BaseState()
        state.position = "long"
        state.position_id = "test_123"
        state.entry_price = 100.0
        state.max_pnl_pct = 5.5
        state.min_pnl_pct = -2.0

        data = state.to_persist_dict()
        assert "max_pnl_pct" in data
        assert "min_pnl_pct" in data
        assert data["max_pnl_pct"] == 5.5
        assert data["min_pnl_pct"] == -2.0

    def test_restore_from_dict_restores_pnl_extremes(self):
        """restore_from_dict 应该恢复盈亏极值字段"""
        state = BaseState()
        data = {
            "position": "long",
            "position_id": "test_123",
            "entry_price": 100.0,
            "entry_time": "2024-01-15T10:00:00",
            "max_pnl_pct": 8.5,
            "min_pnl_pct": -4.0,
        }
        state.restore_from_dict(data)
        assert state.max_pnl_pct == 8.5
        assert state.min_pnl_pct == -4.0

    def test_clear_position_resets_pnl_extremes(self):
        """clear_position 应该重置盈亏极值"""
        state = BaseState()
        state.position = "long"
        state.position_id = "test_123"
        state.entry_price = 100.0
        state.max_pnl_pct = 5.5
        state.min_pnl_pct = -2.0

        state.clear_position()

        assert state.max_pnl_pct == 0.0
        assert state.min_pnl_pct == 0.0


class TestUpdatePnlExtremes:
    """测试盈亏极值更新逻辑"""

    def test_update_pnl_extremes_long_profit(self):
        """long 仓位价格上涨，更新 max_pnl_pct"""
        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 价格涨到 105，盈利 5%
        state.update_pnl_extremes(105.0)
        assert state.max_pnl_pct == 5.0
        assert state.min_pnl_pct == 0.0

    def test_update_pnl_extremes_long_loss(self):
        """long 仓位价格下跌，更新 min_pnl_pct"""
        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 价格跌到 95，亏损 -5%
        state.update_pnl_extremes(95.0)
        assert state.max_pnl_pct == 0.0
        assert state.min_pnl_pct == -5.0

    def test_update_pnl_extremes_long_both(self):
        """long 仓位先涨后跌，记录两个极值"""
        state = BaseState()
        state.position = "long"
        state.entry_price = 100.0

        # 先涨到 110，盈利 10%
        state.update_pnl_extremes(110.0)
        assert state.max_pnl_pct == 10.0

        # 后跌到 90，亏损 -10%
        state.update_pnl_extremes(90.0)
        assert state.max_pnl_pct == 10.0
        assert state.min_pnl_pct == -10.0

    def test_update_pnl_extremes_short_profit(self):
        """short 仓位价格下跌，更新 max_pnl_pct"""
        state = BaseState()
        state.position = "short"
        state.entry_price = 100.0

        # 价格跌到 95，盈利 5%
        state.update_pnl_extremes(95.0)
        assert state.max_pnl_pct == 5.0
        assert state.min_pnl_pct == 0.0

    def test_update_pnl_extremes_short_loss(self):
        """short 仓位价格上涨，更新 min_pnl_pct"""
        state = BaseState()
        state.position = "short"
        state.entry_price = 100.0

        # 价格涨到 105，亏损 -5%
        state.update_pnl_extremes(105.0)
        assert state.max_pnl_pct == 0.0
        assert state.min_pnl_pct == -5.0

    def test_update_pnl_extremes_no_position(self):
        """无仓位时不更新"""
        state = BaseState()
        state.position = None
        state.entry_price = 100.0

        state.update_pnl_extremes(105.0)
        assert state.max_pnl_pct == 0.0
        assert state.min_pnl_pct == 0.0

    def test_update_pnl_extremes_zero_entry_price(self):
        """入场价格为 0 时不更新"""
        state = BaseState()
        state.position = "long"
        state.entry_price = 0.0

        state.update_pnl_extremes(105.0)
        assert state.max_pnl_pct == 0.0
        assert state.min_pnl_pct == 0.0
