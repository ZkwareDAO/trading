#!/usr/bin/env python3
"""
BaseState 单元测试
"""

import pytest
from datetime import datetime, date, timezone
from strategy_core.base.state import BaseState


class TestBaseState:
    """BaseState 基类测试"""

    def test_default_values(self):
        """测试默认值"""
        state = BaseState()
        assert state.position is None
        assert state.position_id is None
        assert state.entry_timestamp is None
        assert state.entry_price == 0.0
        assert state.entry_time is None
        assert state.peak_price == 0.0
        assert state.stop_price == 0.0
        assert state.stop_loss_date is None

    def test_is_in_position_returns_false_when_no_position(self):
        """无持仓时返回 False"""
        state = BaseState()
        assert state.is_in_position() is False

    def test_is_in_position_returns_true_when_long(self):
        """做多时返回 True"""
        state = BaseState(position="long")
        assert state.is_in_position() is True

    def test_is_in_position_returns_true_when_short(self):
        """做空时返回 True"""
        state = BaseState(position="short")
        assert state.is_in_position() is True

    def test_clear_position_basic(self):
        """测试基本清仓"""
        state = BaseState(
            position="long",
            position_id="test_123",
            entry_price=100.0,
            peak_price=110.0,
        )
        state.clear_position()
        assert state.position is None
        assert state.position_id is None
        assert state.entry_price == 0.0
        assert state.peak_price == 0.0

    def test_clear_position_with_stop_loss_record(self):
        """清仓并记录止损日期"""
        now = datetime.now(timezone.utc)
        state = BaseState(
            position="long",
            position_id="test_123",
            entry_price=100.0,
        )
        state.clear_position(record_stop_loss=True, current_time=now)
        assert state.stop_loss_date == now.date()

    def test_to_persist_dict(self):
        """测试序列化"""
        entry_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        state = BaseState(
            position="long",
            position_id="test_123",
            entry_timestamp=1704110400,
            entry_price=100.0,
            entry_time=entry_time,
            peak_price=110.0,
            stop_price=95.0,
        )
        data = state.to_persist_dict()
        assert data["position"] == "long"
        assert data["position_id"] == "test_123"
        assert data["entry_timestamp"] == 1704110400
        assert data["entry_price"] == 100.0
        assert data["entry_time"] == "2024-01-01T12:00:00+00:00"
        assert data["peak_price"] == 110.0
        assert data["stop_price"] == 95.0

    def test_restore_from_dict(self):
        """测试反序列化"""
        data = {
            "position": "short",
            "position_id": "test_456",
            "entry_timestamp": 1704110400,
            "entry_price": 100.0,
            "entry_time": "2024-01-01T12:00:00+00:00",
            "peak_price": 90.0,
            "stop_price": 105.0,
        }
        state = BaseState()
        state.restore_from_dict(data)
        assert state.position == "short"
        assert state.position_id == "test_456"
        assert state.entry_timestamp == 1704110400
        assert state.entry_price == 100.0
        assert state.entry_time == datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        assert state.peak_price == 90.0
        assert state.stop_price == 105.0

    def test_restore_from_dict_handles_invalid_time(self):
        """测试无效时间格式处理"""
        data = {
            "position": "long",
            "entry_time": "invalid-time-format",
        }
        state = BaseState()
        state.restore_from_dict(data)
        assert state.entry_time is None