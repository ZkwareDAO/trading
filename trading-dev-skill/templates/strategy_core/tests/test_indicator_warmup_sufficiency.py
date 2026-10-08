#!/usr/bin/env python3
"""
测试指标预热数据量是否充足

核心不变式：**补齐的历史数据量必须让最苛刻的指标算得准**。

背景：数据不足在这个项目里是**静默**失败 ——
- `data_manager.indicators` 遇到数据不足只 `warnings.warn`，返回不准确的值，
  不抛异常、不阻断。
- `BaseStrategy._check_data_needed` 的门槛是 DEFAULT_MIN_BARS_REQUIRED=11，
  远低于 ADX 的 MIN_ROWS=100。11 根就"通过检查"。
于是策略拿着与交易所不一致的 ADX 照常发信号，实盘中只留下一行 UserWarning。

三处已修的静默降级：
1. TF_MINUTES 缺 12h/2h/3d/1w —— `.get(tf, 0)` 返回 0 后调用方 return 7 /
   continue，12h 只补 7 天（14 根）、3d 只补 7 天（2.3 根）。
2. `_calc_required_history_days` 固定 bars_needed=15 —— 4h 得 42 根、
   8h 得 30 根、1d 得 20 根，全部低于 ADX 的 100。
3. `run_strategy` 直接用 sync_history_days=30 —— 与周期无关的固定值，
   对 8h 只有 90 根、对 1d 只有 30 根。
"""

import warnings

import numpy as np
import pandas as pd
import pytest

from data_manager.indicators import compute_adx
from strategy_core.constants import (
    DEFAULT_MIN_BARS_REQUIRED,
    INDICATOR_WARMUP_BARS,
    TF_MINUTES,
)


# 线上 sar_snt3_v3 实际使用的周期组合（overrides/*.yaml）
LIVE_TIMEFRAMES = ("8h", "1h")

# indicators.py 中各指标的硬阈值，必须与源码保持同步
ADX_MIN_ROWS = 100


def days_to_bars(days: int, timeframe: str) -> float:
    """给定补齐天数，换算成该周期能得到的 K 线根数"""
    return days * 1440 / TF_MINUTES[timeframe]


class TestTfMinutesCompleteness:
    """TF_MINUTES 缺项会导致静默降级，不是"不支持" """

    @pytest.mark.parametrize("tf,minutes", [
        ("1m", 1), ("3m", 3), ("5m", 5), ("15m", 15), ("30m", 30),
        ("1h", 60), ("2h", 120), ("4h", 240), ("6h", 360),
        ("8h", 480), ("12h", 720),
        ("1d", 1440), ("3d", 4320), ("1w", 10080),
    ])
    def test_common_timeframes_registered(self, tf, minutes):
        assert TF_MINUTES.get(tf) == minutes, (
            f"{tf} 未登记或值错误。缺项会让 _calc_required_history_days "
            f"静默退回 7 天、让回测预热窗口退回默认 4h"
        )

    def test_matches_data_manager_parser(self):
        """TF_MINUTES 必须与 DataManager 的解析器一致，否则策略层算出的
        所需天数与数据层实际能提供的量对不上。
        """
        from data_manager.manager import DataManager, DataManagerConfig
        dm = DataManager(DataManagerConfig(realtime_enabled=False))
        for tf, minutes in TF_MINUTES.items():
            assert dm._parse_interval_to_minutes(tf) == minutes, (
                f"{tf}: constants={minutes} 与 DataManager 解析不一致"
            )


class TestWarmupBarsCoversIndicators:
    """预热根数必须覆盖最苛刻的指标阈值"""

    def test_warmup_covers_adx(self):
        assert INDICATOR_WARMUP_BARS >= ADX_MIN_ROWS, (
            f"预热 {INDICATOR_WARMUP_BARS} 根 < ADX 需要的 {ADX_MIN_ROWS} 根"
        )

    def test_warmup_exceeds_liveness_threshold(self):
        """预热阈值（算得准）必须严格高于运行阈值（能不能算）。
        两者混用是这个 bug 的根源。
        """
        assert INDICATOR_WARMUP_BARS > DEFAULT_MIN_BARS_REQUIRED

    def test_adx_warns_below_threshold(self):
        """锚定 ADX 的实际行为：不足时只 warn 不抛异常。
        这正是数据不足难以被发现的原因 —— 若哪天改成抛异常，
        这个测试会失败，提醒重新评估补齐策略。
        """
        n = ADX_MIN_ROWS - 1
        idx = np.arange(n, dtype=float)
        base = 100 + np.sin(idx / 7.0) * 5
        df = pd.DataFrame({
            "high": base + 0.5, "low": base - 0.5, "close": base + 0.1,
        })
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compute_adx(df, period=14)
        assert any("ADX" in str(w.message) for w in caught), (
            "ADX 数据不足未告警"
        )


class TestRequiredHistoryDays:
    """_calc_required_history_days 必须真的够指标预热"""

    def _calc(self, timeframes):
        """调用**真实**的 BaseStrategy._calc_required_history_days。

        不复刻算术：复刻会让"方法体被改回 bars_needed=15 而常量不动"
        这类退化悄悄通过。用最小子类补齐两个抽象钩子即可。
        """
        from strategy_core.base.strategy import BaseStrategy

        tf_list = list(timeframes)

        class _Probe(BaseStrategy):
            def _create_core(self):
                return None

            def _get_indicator_timeframes(self) -> set:
                # 不注入任何默认值，严格返回被测周期
                return set(tf_list)

        probe = object.__new__(_Probe)
        return probe._calc_required_history_days()

    @pytest.mark.parametrize("tf", [
        "1h", "2h", "4h", "6h", "8h", "12h", "1d", "3d",
    ])
    def test_yields_enough_bars_for_adx(self, tf):
        days = self._calc([tf])
        bars = days_to_bars(days, tf)
        assert bars >= ADX_MIN_ROWS, (
            f"{tf}: 补齐 {days} 天只得 {bars:.0f} 根，"
            f"低于 ADX 的 {ADX_MIN_ROWS} 根"
        )

    def test_live_config_gets_enough(self):
        """线上 sar_snt3_v3 的 8h + 1h 组合"""
        days = self._calc(LIVE_TIMEFRAMES)
        for tf in LIVE_TIMEFRAMES:
            bars = days_to_bars(days, tf)
            assert bars >= ADX_MIN_ROWS, (
                f"线上配置 {tf}: {days} 天只得 {bars:.0f} 根"
            )

    def test_uses_max_timeframe(self):
        """混合周期时必须按最大周期算，否则大周期吃不饱"""
        assert self._calc(["1h", "8h"]) == self._calc(["8h"])

    def test_unregistered_timeframe_still_floors_at_seven(self):
        """未登记周期退回 7 天是既有兜底行为，保持不变（不静默变 0）"""
        assert self._calc(["99x"]) == 7


class TestResolveHistoryDays:
    """run_strategy._resolve_history_days：配置值不得把数据压到算不准"""

    def _make_runner(self, required_days):
        """构造最小 runner，只装配 _resolve_history_days 依赖的部分"""
        from unittest.mock import MagicMock
        import run_strategy

        runner = object.__new__(run_strategy.StrategyProcessRunner)
        runner.strategy_name = "test"

        inst = MagicMock()
        inst._calc_required_history_days.return_value = required_days
        runner.strategy = inst
        return runner

    def test_raises_configured_value_when_insufficient(self):
        """配置 30 天但策略要 38 天（8h）→ 必须取 38"""
        runner = self._make_runner(38)
        assert runner._resolve_history_days(30) == 38

    def test_keeps_configured_value_when_larger(self):
        """配置值更大时保留 —— 运维仍可上调多备数据"""
        runner = self._make_runner(21)
        assert runner._resolve_history_days(90) == 90

    def test_survives_strategy_exception(self):
        """策略算天数抛异常时回退到配置值，不能让启动崩掉"""
        from unittest.mock import MagicMock
        import run_strategy

        runner = object.__new__(run_strategy.StrategyProcessRunner)
        runner.strategy_name = "test"
        inst = MagicMock()
        inst._calc_required_history_days.side_effect = RuntimeError("boom")
        runner.strategy = inst

        assert runner._resolve_history_days(30) == 30

    def test_handles_no_instance(self):
        """策略未加载（None）不应导致异常"""
        import run_strategy

        runner = object.__new__(run_strategy.StrategyProcessRunner)
        runner.strategy_name = "test"
        runner.strategy = None

        assert runner._resolve_history_days(30) == 30

    def test_live_8h_config_beats_default_30(self):
        """回归：线上 8h 配置在默认 30 天下只有 90 根，低于 ADX 阈值。
        修复后必须被抬到足够的天数。
        """
        required = max(
            int((INDICATOR_WARMUP_BARS * TF_MINUTES["8h"]) / 1440 + 5), 7
        )
        assert days_to_bars(30, "8h") < ADX_MIN_ROWS, "前置条件已变"
        runner = self._make_runner(required)
        resolved = runner._resolve_history_days(30)
        assert days_to_bars(resolved, "8h") >= ADX_MIN_ROWS, (
            f"解析出 {resolved} 天，8h 仍只有 "
            f"{days_to_bars(resolved, '8h'):.0f} 根"
        )


class TestHistoryDaysWiring:
    """`_resolve_history_days` 必须真的接在启动流程里。

    只测方法本身是不够的 —— 消融验证实测：把 `start()` 里那行
    `history_days = self._resolve_history_days(configured_days)`
    改回 `history_days = configured_days`，上面 5 个方法级用例**全部照常通过**。
    接线是最容易在重构中掉的一环，必须单独钉住。
    """

    def _make_runner(self, required_days, configured_days):
        from unittest.mock import AsyncMock, MagicMock
        import run_strategy

        runner = object.__new__(run_strategy.StrategyProcessRunner)
        runner.strategy_name = "test"
        runner.global_config = {
            "data_manager": {"sync_history_days": configured_days}
        }

        inst = MagicMock()
        inst._calc_required_history_days.return_value = required_days
        runner.strategy = inst

        runner.connect_data_manager = AsyncMock(return_value=True)
        runner.load_strategy = MagicMock(return_value=True)
        runner._load_historical_data = AsyncMock()
        # start() 在调用 _load_historical_data 之后还会接线 WS 回调，
        # 这里只需让它不 AttributeError —— 断言点在其之前
        runner.data_manager = MagicMock()
        return runner

    @pytest.mark.asyncio
    async def test_start_passes_resolved_days_not_configured(self):
        """配置 30 天、策略要 38 天（8h）→ start() 必须把 38 传下去。
        传 30 说明接线断了。
        """
        runner = self._make_runner(required_days=38, configured_days=30)
        await runner.start()

        runner._load_historical_data.assert_awaited_once()
        passed = runner._load_historical_data.await_args.kwargs.get("days")
        if passed is None:
            passed = runner._load_historical_data.await_args.args[0]
        assert passed == 38, (
            f"start() 传下去的是 {passed} 天而非解析后的 38 天 —— "
            f"_resolve_history_days 未接入启动流程"
        )

    @pytest.mark.asyncio
    async def test_start_yields_enough_bars_for_live_8h(self):
        """端到端：线上 8h 配置在默认 30 天下，start() 实际传下去的天数
        必须足够 ADX 预热。
        """
        required = max(
            int((INDICATOR_WARMUP_BARS * TF_MINUTES["8h"]) / 1440 + 5), 7
        )
        runner = self._make_runner(required_days=required, configured_days=30)
        await runner.start()

        passed = runner._load_historical_data.await_args.kwargs.get("days")
        if passed is None:
            passed = runner._load_historical_data.await_args.args[0]
        bars = days_to_bars(passed, "8h")
        assert bars >= ADX_MIN_ROWS, (
            f"start() 传 {passed} 天，8h 只得 {bars:.0f} 根，"
            f"低于 ADX 的 {ADX_MIN_ROWS} 根"
        )

    @pytest.mark.asyncio
    async def test_start_keeps_larger_configured_value(self):
        """配置值更大时 start() 必须沿用配置值（运维可上调）"""
        runner = self._make_runner(required_days=21, configured_days=90)
        await runner.start()

        passed = runner._load_historical_data.await_args.kwargs.get("days")
        if passed is None:
            passed = runner._load_historical_data.await_args.args[0]
        assert passed == 90
