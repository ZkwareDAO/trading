#!/usr/bin/env python3
"""example_ma_cross 核心逻辑测试（参考实现）

这份测试同时是"新策略该测什么"的清单。照抄结构，把断言换成你自己的逻辑：

  1. 前置检查   —— current_time 缺失 / 止损日冷却 / 已有持仓 / 数据不足
  2. 入场       —— 条件成立时 action、价格、state 七个字段、metadata 都对
  3. 未来函数   —— 未闭合 K 线不能影响结果（最重要的一条）
  4. 方向过滤   —— direction=long 时不开空
  5. 出场       —— 止损触发、stop_loss_date 记上、状态清干净
  6. 持久化     —— to_persist_dict / restore_from_dict 往返，缓存字段不落盘
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from strategies.example_ma_cross.example_ma_cross_core import (
    ExampleMaCrossCore,
    ExampleMaCrossState,
)

SYMBOL = "BTCUSDT"
TF = "4h"
BASE = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)


def make_klines(closes, tf_hours: int = 4) -> pd.DataFrame:
    """按收盘价列表造 K 线。第 i 根的 timestamp = BASE + i*4h。"""
    rows = []
    for i, c in enumerate(closes):
        rows.append({
            "timestamp": BASE + timedelta(hours=tf_hours * i),
            "open": c,
            "high": c * 1.01,
            "low": c * 0.99,
            "close": c,
            "volume": 1000.0,
        })
    return pd.DataFrame(rows)


def closed_time(n_bars: int, tf_hours: int = 4) -> datetime:
    """让前 n_bars 根全部闭合的 current_time（= 最后一根的 bar_end）。"""
    return BASE + timedelta(hours=tf_hours * n_bars)


# 10 根 100 打底，让快慢线都等于 100；第 11 根拉高/砸低即制造交叉
FLAT = [100.0] * 10
GOLDEN = FLAT + [130.0]   # fast(3)=110 > slow(5)=106，前一根相等 → 金叉
DEATH = FLAT + [70.0]     # fast(3)=90  < slow(5)=94，前一根相等 → 死叉


@pytest.fixture
def core():
    c = ExampleMaCrossCore(
        symbols=[SYMBOL],
        timeframes=[TF],
        params={
            "ma_timeframes": TF,
            "ma_fast_period": 3,
            "ma_slow_period": 5,
            "stop_loss_pct": 2.0,
            "strong_spread_pct": 0.3,
            "leverage": 2,
        },
    )
    c.set_strategy_name("EXAMPLEMACROSS_4H_1_BTCUSDT_PAPER")
    return c


# ============================================================
# 1. 前置检查
# ============================================================

class TestPreChecks:

    def test_current_time_missing_returns_hold(self, core):
        """current_time 为 None 时只能 hold，不许 fallback 到 datetime.now()。"""
        result = core.analyze(SYMBOL, {TF: make_klines(GOLDEN)}, current_time=None)
        assert result["action"] == "hold"
        assert "current_time" in result["metadata"]["reason"]

    def test_insufficient_data_returns_hold(self, core):
        """K 线不够 min_rows（slow_period+5=10）时 hold。"""
        result = core.analyze(
            SYMBOL, {TF: make_klines([100.0] * 6)},
            current_time=closed_time(6))
        assert result["action"] == "hold"
        assert "不足" in result["metadata"]["reason"]

    def test_missing_timeframe_returns_hold(self, core):
        """klines_data 里没有该周期（_get_indicator_timeframes 漏收集）时 hold。"""
        result = core.analyze(SYMBOL, {"1h": make_klines(GOLDEN)},
                              current_time=closed_time(11))
        assert result["action"] == "hold"

    def test_stop_loss_cooldown_blocks_entry(self, core):
        """当天已止损，即使金叉也不开仓。"""
        ct = closed_time(11)
        core._get_state(SYMBOL).stop_loss_date = ct.date()
        result = core.analyze(SYMBOL, {TF: make_klines(GOLDEN)}, current_time=ct)
        assert result["action"] == "hold"
        assert "止损" in result["metadata"]["reason"]

    def test_existing_position_blocks_entry(self, core):
        core._get_state(SYMBOL).position = "long"
        result = core.analyze(SYMBOL, {TF: make_klines(GOLDEN)},
                              current_time=closed_time(11))
        assert result["action"] == "hold"
        assert "已有持仓" in result["metadata"]["reason"]

    def test_no_cross_returns_hold(self, core):
        """一路横盘，快慢线相等，不算交叉。"""
        result = core.analyze(SYMBOL, {TF: make_klines([100.0] * 12)},
                              current_time=closed_time(12))
        assert result["action"] == "hold"
        assert "未出现交叉" in result["metadata"]["reason"]


# ============================================================
# 2. 入场
# ============================================================

class TestEntry:

    def test_golden_cross_opens_long(self, core):
        ct = closed_time(11)
        result = core.analyze(
            SYMBOL, {TF: make_klines(GOLDEN)},
            current_time=ct, realtime_price=131.0, current_cash=200.0)

        # --- 返回值 ---
        assert result["action"] == "buy"          # 开多是 "buy"，不是 "long"
        assert result["price"] == 131.0           # 用 realtime_price，不是收盘价 130
        assert result["strength"] == 0.8          # 价差 3.77% ≥ 0.3 → 强信号
        assert result["metadata"]["target_notional"] == 400.0  # cash 200 × leverage 2

        # --- state 七个必填字段 ---
        state = core._get_state(SYMBOL)
        assert state.position == "long"
        assert state.position_id.startswith("EXAMPLEMACROSS_4H_1_BTCUSDT_PAPER")
        assert state.entry_price == 131.0
        assert state.entry_time == ct
        assert state.entry_timestamp == int(ct.timestamp())
        assert len(str(state.entry_timestamp)) == 10        # 秒级，不是毫秒
        assert state.peak_price == 131.0
        assert state.stop_price == pytest.approx(131.0 * 0.98)

        # --- 策略特有字段 ---
        assert state.ma_fast_at_entry == pytest.approx(110.0)
        assert state.ma_slow_at_entry == pytest.approx(106.0)

    def test_death_cross_opens_short(self, core):
        ct = closed_time(11)
        result = core.analyze(
            SYMBOL, {TF: make_klines(DEATH)},
            current_time=ct, realtime_price=69.0, current_cash=200.0)

        assert result["action"] == "sell"         # 开空是 "sell"
        state = core._get_state(SYMBOL)
        assert state.position == "short"
        # 空头止损在上方
        assert state.stop_price == pytest.approx(69.0 * 1.02)

    def test_falls_back_to_closed_close_without_realtime_price(self, core):
        result = core.analyze(SYMBOL, {TF: make_klines(GOLDEN)},
                              current_time=closed_time(11), realtime_price=None)
        assert result["price"] == 130.0           # 已闭合 K 线的收盘价

    def test_direction_long_blocks_short(self, core):
        """direction=long 时，死叉不该开空。"""
        core.direction = "long"
        result = core.analyze(SYMBOL, {TF: make_klines(DEATH)},
                              current_time=closed_time(11))
        assert result["action"] == "hold"
        assert not core._get_state(SYMBOL).is_in_position()

    def test_direction_short_blocks_long(self, core):
        core.direction = "short"
        result = core.analyze(SYMBOL, {TF: make_klines(GOLDEN)},
                              current_time=closed_time(11))
        assert result["action"] == "hold"


# ============================================================
# 3. 未来函数（最重要）
# ============================================================

class TestNoLookahead:

    def test_unclosed_bar_is_ignored(self, core):
        """多喂一根未闭合的极端 K 线，结果必须和没喂时完全一致。

        这是本框架最容易踩的坑：直接用 klines_data 原始 df 算指标，
        最后一根未闭合 bar 会把指标"拉过去"，回测赚翻实盘亏穿。
        """
        ct = closed_time(11)
        baseline = core.analyze(SYMBOL, {TF: make_klines(GOLDEN)},
                                current_time=ct, realtime_price=131.0)
        core._get_state(SYMBOL).clear_position()

        # 第 12 根 bar 的 bar_end = BASE+48h > current_time，属于未闭合
        polluted = make_klines(GOLDEN + [99999.0])
        result = core.analyze(SYMBOL, {TF: polluted},
                              current_time=ct, realtime_price=131.0)

        assert result["action"] == baseline["action"]
        assert result["price"] == baseline["price"]
        assert result["metadata"]["ma_fast"] == baseline["metadata"]["ma_fast"]
        assert result["metadata"]["ma_slow"] == baseline["metadata"]["ma_slow"]


# ============================================================
# 4. 出场
# ============================================================

class TestExit:

    def test_no_position_returns_hold(self, core):
        result = core.check_realtime_exit(SYMBOL, 100.0)
        assert result["action"] == "hold"

    def test_long_stop_loss(self, core):
        ct = datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc)
        state = core._get_state(SYMBOL)
        state.position = "long"
        state.entry_price = 100.0
        state.stop_price = 98.0
        state.peak_price = 100.0

        # bar_low 96 击穿止损位 98
        result = core.check_realtime_exit(
            SYMBOL, 97.0, current_time=ct, bar_high=99.0, bar_low=96.0)

        assert result["action"] == "sell_close"       # 平多是 sell_close
        assert result["price"] == 98.0                # 按止损位成交，不是当前价
        assert result["metadata"]["is_stop_loss"] is True
        # 状态被清空 + 记上止损日
        assert not state.is_in_position()
        assert state.stop_loss_date == ct.date()
        assert state.ma_fast_at_entry == 0.0          # 特有字段也被重置

    def test_short_stop_loss(self, core):
        ct = datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc)
        state = core._get_state(SYMBOL)
        state.position = "short"
        state.entry_price = 100.0
        state.stop_price = 102.0
        state.peak_price = 100.0

        result = core.check_realtime_exit(
            SYMBOL, 101.0, current_time=ct, bar_high=103.0, bar_low=100.0)

        assert result["action"] == "buy_close"        # 平空是 buy_close
        assert result["metadata"]["is_stop_loss"] is True

    def test_holding_updates_pnl_extremes(self, core):
        state = core._get_state(SYMBOL)
        state.position = "long"
        state.entry_price = 100.0
        state.stop_price = 90.0

        core.check_realtime_exit(SYMBOL, 110.0, bar_high=110.0, bar_low=109.0)
        core.check_realtime_exit(SYMBOL, 95.0, bar_high=96.0, bar_low=95.0)

        assert state.max_pnl_pct == pytest.approx(10.0)
        assert state.min_pnl_pct == pytest.approx(-5.0)
        assert state.is_in_position()                 # 都没到止损位，继续持有


# ============================================================
# 5. 持久化
# ============================================================

class TestPersistence:

    def test_custom_fields_roundtrip(self):
        state = ExampleMaCrossState()
        state.position = "long"
        state.entry_price = 100.0
        state.entry_timestamp = 1767225600
        state.ma_fast_at_entry = 110.0
        state.ma_slow_at_entry = 106.0

        data = state.to_persist_dict()

        restored = ExampleMaCrossState()
        restored.restore_from_dict(data)
        assert restored.position == "long"
        assert restored.ma_fast_at_entry == 110.0
        assert restored.ma_slow_at_entry == 106.0

    def test_cache_fields_not_persisted(self):
        """缓存字段每根 K 线重算，不该落盘。"""
        state = ExampleMaCrossState()
        state.latest_ma_fast = 123.0
        data = state.to_persist_dict()
        assert "latest_ma_fast" not in data
        assert "latest_ma_slow" not in data

    def test_clear_position_resets_custom_fields(self):
        state = ExampleMaCrossState()
        state.position = "long"
        state.ma_fast_at_entry = 110.0
        state.latest_ma_fast = 111.0

        state.clear_position()

        assert state.position is None
        assert state.ma_fast_at_entry == 0.0
        assert state.latest_ma_fast == 0.0

    def test_clear_position_records_stop_loss_date(self):
        ct = datetime(2026, 1, 3, 12, 0, tzinfo=timezone.utc)
        state = ExampleMaCrossState()
        state.position = "long"

        state.clear_position(record_stop_loss=True, current_time=ct)

        assert state.stop_loss_date == ct.date()
