#!/usr/bin/env python3
"""回归测试：entry_price=None 时 clear_position 不应崩溃

背景：2026-08-11 线上 SARSNT3_8H_3_WLDUSDT 触发 SAR 跟踪止损，
远程仓位查询返回 EntryPrice=None，导致 state.entry_price 被置为 None，
clear_position() 的诊断日志 `f"...prev_entry={prev_entry:.4f}"` 抛 TypeError，
中断整个清仓流程，仓位无法关闭。
"""

from datetime import datetime, timezone
from strategy_core.base.state import BaseState


def test_clear_position_with_none_entry_price():
    """entry_price=None 时 clear_position 应正常完成，不抛 TypeError"""
    state = BaseState()
    state.position = "long"
    state.entry_price = None  # 模拟远程仓位 EntryPrice=None 的恢复路径

    # 不应抛异常
    state.clear_position(record_stop_loss=True,
                         current_time=datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc))

    assert state.position is None
    assert state.entry_price == 0.0
    assert state.stop_loss_date is not None


def test_clear_position_with_normal_entry_price():
    """正常 float entry_price 仍然正常工作"""
    state = BaseState()
    state.position = "long"
    state.entry_price = 0.3406

    state.clear_position(record_stop_loss=False, current_time=None)

    assert state.position is None
    assert state.entry_price == 0.0


if __name__ == "__main__":
    test_clear_position_with_none_entry_price()
    test_clear_position_with_normal_entry_price()
    print("OK")
