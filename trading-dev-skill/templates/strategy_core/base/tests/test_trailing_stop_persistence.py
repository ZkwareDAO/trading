#!/usr/bin/env python3
"""移动止损状态必须能落盘（Prove-It 复现测试）

**已知缺陷**：`BaseStrategyCore._notify_position_update()` 没有任何调用者，
导致 `peak_price` / `stop_price` / `trail_activated` 的运行时变更永不持久化。

接线现状：
- `strategy.py:_on_position_update()` 定义了真实回调，会写 PositionPersistence
- `strategy.py` 把它注册进 core（`on_update=self._on_position_update`）
- `core.py:_notify_position_update()` 包裹并会调用它 —— **但没人调用这个包裹方法**

对比参照：`_notify_position_enter` 有 2 个调用者（sar_snt3_v3_core.py:659/699），
`_notify_position_exit` 由 `_notify_exit_and_clear` 调用，唯独 update 漏了。

后果：`state.py` 会从持久化文件**读取**这三个字段，`risk_control.py` 与
`sar_snt3_v3_core.py` 运行中会**推进**它们，但写回路径断开 —— 进程重启后
移动止损峰值归零、已抬高的止损位丢失，等于止损保护被静默重置。
回测因 `not self._backtest_mode` 判据不受影响，故全绿测试掩盖了此缺陷。
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from strategy_core.base.core import BaseStrategyCore
from strategy_core.base.state import BaseState


class MockState(BaseState):
    pass


class RecordingCore(BaseStrategyCore[MockState]):
    """记录 on_update 回调是否被触发的 Core"""

    def __init__(self):
        super().__init__(symbols=["BTCUSDT"], timeframes=["1h"], params=None)
        self.update_calls = []
        # 模拟 strategy.py 的注册动作
        self._on_position_update = self._record_update

    def _record_update(self, symbol: str, state) -> None:
        self.update_calls.append(
            {
                "symbol": symbol,
                "peak_price": state.peak_price,
                "stop_price": state.stop_price,
            }
        )

    def _get_state(self, symbol: str) -> MockState:
        if symbol not in self._state:
            self._state[symbol] = MockState()
        return self._state[symbol]

    def analyze(self, symbol, klines_data, current_time=None) -> Dict[str, Any]:
        return {"action": "hold"}

    def check_realtime_exit(
        self, symbol, current_price, current_time=None, bar_high=None, bar_low=None
    ) -> Dict[str, Any]:
        return {"action": "hold"}

    def get_status(self) -> Dict[str, Any]:
        return {}


class TestTrailingStopStatePersistence:
    """移动止损状态推进后必须触发持久化回调"""

    def test_notify_position_update_forwards_to_callback(self):
        """_notify_position_update 应把状态转发给已注册的回调

        这是最基础的契约。若此测试失败，说明包裹方法本身也坏了。
        """
        core = RecordingCore()
        state = core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 50000.0
        state.peak_price = 52000.0
        state.stop_price = 51000.0

        core._notify_position_update("BTCUSDT", state)

        assert len(core.update_calls) == 1
        assert core.update_calls[0]["peak_price"] == 52000.0
        assert core.update_calls[0]["stop_price"] == 51000.0

    def test_backtest_mode_skips_persistence(self):
        """回测模式不应触发持久化（避免回测写实盘状态文件）"""
        core = RecordingCore()
        core._backtest_mode = True
        state = core._get_state("BTCUSDT")
        state.position = "long"
        state.peak_price = 52000.0

        core._notify_position_update("BTCUSDT", state)

        assert core.update_calls == []

    def test_notify_position_update_has_at_least_one_caller_in_production(self):
        """**核心缺陷断言**：生产代码中必须有人调用 _notify_position_update

        当前它零调用者，所以移动止损状态永不落盘。本测试会失败，
        直到在仓位状态变更处（移动止损推进后）接上该调用。

        用静态扫描而非行为断言，因为缺陷正是「调用点缺失」本身。
        """
        import re
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        callers = []
        for py in repo_root.rglob("*.py"):
            parts = py.parts
            if any(
                p in parts for p in ("__pycache__", ".venv", "docs", "tests")
            ) or py.name.startswith("test_"):
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for m in re.finditer(r"_notify_position_update\s*\(", text):
                line_no = text[: m.start()].count("\n") + 1
                line = text.splitlines()[line_no - 1]
                # 排除定义行本身
                if line.lstrip().startswith("def "):
                    continue
                callers.append(f"{py.relative_to(repo_root)}:{line_no}")

        assert callers, (
            "_notify_position_update 在生产代码中零调用者 —— "
            "peak_price / stop_price / trail_activated 的运行时变更永不落盘，"
            "进程重启后移动止损峰值归零、已抬高的止损位丢失。"
            "对比：_notify_position_enter 有 2 个调用者，_notify_position_exit "
            "由 _notify_exit_and_clear 调用。修法是在移动止损推进处调用它。"
        )


class TestPersistOnlyWhenChanged:
    """`_persist_position_update_if_changed` 的行为契约

    直接测基类的判定逻辑：只在字段真变化、且仍持仓时才落盘。
    """

    def _make_strategy(self):
        """构造一个最小可用的 BaseStrategy，仅用于测判定逻辑"""
        from strategy_core.base.strategy import BaseStrategy

        class Strat(BaseStrategy):
            def _create_core(self, *a, **kw):
                return RecordingCore()

            def _get_indicator_timeframes(self):
                return ["1h"]

        strat = Strat.__new__(Strat)  # 跳过重量级 __init__
        strat._core = RecordingCore()
        return strat

    def test_persists_when_stop_price_advanced(self):
        """止损位被推高 → 必须落盘"""
        strat = self._make_strategy()
        state = strat._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 50000.0
        state.stop_price = 51000.0  # 已被 SAR 推高
        state.peak_price = 52000.0

        snapshot = {"peak_price": 52000.0, "stop_price": 49000.0}  # 推进前
        strat._persist_position_update_if_changed(
            "BTCUSDT", state, snapshot, trail_before=False
        )

        assert len(strat._core.update_calls) == 1
        assert strat._core.update_calls[0]["stop_price"] == 51000.0

    def test_persists_when_trail_activated_flips(self):
        """trail_activated 由 False 变 True → 必须落盘"""
        strat = self._make_strategy()
        state = strat._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 50000.0
        state.stop_price = 49000.0
        state.peak_price = 52000.0
        state.trail_activated = True  # 刚被 risk_control 激活

        snapshot = {"peak_price": 52000.0, "stop_price": 49000.0}
        strat._persist_position_update_if_changed(
            "BTCUSDT", state, snapshot, trail_before=False
        )

        assert len(strat._core.update_calls) == 1

    def test_does_not_persist_when_nothing_changed(self):
        """字段无变化 → 不产生 IO（避免每根 K 线都写盘）"""
        strat = self._make_strategy()
        state = strat._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 50000.0
        state.stop_price = 49000.0
        state.peak_price = 52000.0

        snapshot = {"peak_price": 52000.0, "stop_price": 49000.0}
        strat._persist_position_update_if_changed(
            "BTCUSDT", state, snapshot, trail_before=False
        )

        assert strat._core.update_calls == []

    def test_does_not_persist_after_position_cleared(self):
        """已平仓（state 被清空）→ 绝不落盘

        check_realtime_exit 平仓时会清空 state，且 _notify_position_exit
        已清理持久化文件。此时若再写，会把清空后的状态覆盖回磁盘。
        """
        strat = self._make_strategy()
        state = strat._core._get_state("BTCUSDT")
        state.position = None  # 已被平仓清空
        state.stop_price = 0.0
        state.peak_price = 0.0

        snapshot = {"peak_price": 52000.0, "stop_price": 49000.0}  # 平仓前有值
        strat._persist_position_update_if_changed(
            "BTCUSDT", state, snapshot, trail_before=True
        )

        assert strat._core.update_calls == [], (
            "平仓后仍触发持久化 —— 会把清空的状态覆盖回磁盘，"
            "抵消 _notify_position_exit 的清理"
        )
