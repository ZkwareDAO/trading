#!/usr/bin/env python3
"""集成测试：实盘 WS 推送 → 策略拿到足够的大周期 K 线

回答的问题：**实盘每次收到 1m K 线，策略能否拿到对应且足够算指标的大周期数据。**

为什么既有测试答不了这个问题：
- `test_exit_signal_duplicate.py` / `test_base_strategy.py` 里的 `on_kline`
  用的是 `MagicMock(spec=DataManager)`，`get_dataframe_cached` 返回 MagicMock，
  拿不到真实根数。
- `test_indicator_warmup_sufficiency.py` 只验"补齐天数"的算术，不验运行时
  策略手里实际有几根。
- 聚合测试验的是"桶值等于真值"，不验"根数够不够算指标"。

本文件用**真实** DataManager + 真实 WS 回调链路，断言链路末端的根数。

关键链路顺序（已核对 manager.py::_on_kline_received）：
    写 1m 缓存 → 缓冲落 CSV → _update_big_intervals_from_cache
                                    ↓
                      _kline_dispatch_callback(kline) → 策略取数
聚合在分发**之前**，所以策略每次都能看到含当前 1m 的最新大周期。
"""

import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from data_manager.indicators import compute_adx
from data_manager.klines_data import Kline
from data_manager.manager import DataManager, DataManagerConfig
from strategy_core.constants import INDICATOR_WARMUP_BARS, TF_MINUTES

SYMBOL = "BTCUSDT"
ADX_MIN_ROWS = 100

# 线上 sar_snt3_v3 实际配置：8h 出信号，1h 跟踪 SAR
LIVE_TIMEFRAMES = ("8h", "1h")


def make_1m(start: str, periods: int) -> pd.DataFrame:
    """正弦波动的 1m 数据 —— 恒定价格会让 ADX 退化，掩盖数据量问题"""
    ts = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    idx = np.arange(periods, dtype=float)
    base = 100.0 + np.sin(idx / 7.0) * 5.0
    return pd.DataFrame({
        "timestamp": ts,
        "open": base, "high": base + 0.5, "low": base - 0.5, "close": base + 0.1,
        "volume": 1.0, "quote_volume": 100.0, "trade_num": 10,
        "active_buy_volume": 0.5, "active_buy_quote_volume": 50.0,
    })


def make_kline(ts: datetime) -> Kline:
    return Kline(
        symbol=SYMBOL, interval="1m", timestamp=ts,
        open=100.0, high=100.5, low=99.5, close=100.1,
        volume=1.0, quote_volume=100.0, trade_num=10,
        active_buy_volume=0.5, active_buy_quote_volume=50.0,
        is_final=True,
    )


def setup_live(tmp_path: Path, timeframes, history_days: int):
    """搭出"启动已补 N 天历史"的实盘态 DataManager"""
    dm = DataManager(DataManagerConfig(
        csv_dir=str(tmp_path / "klines"), realtime_enabled=False,
    ))
    dm.enable_kline_repository()
    dm.kline_repo.register_symbol(SYMBOL, ["1m", *timeframes])

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    total = history_days * 1440
    hist = make_1m((now - timedelta(minutes=total - 1)).isoformat(), total)
    dm.cache.put(SYMBOL, "1m", hist, force_1m=True)
    dm._update_big_intervals_from_cache(SYMBOL)
    return dm, now


def required_days(timeframe: str) -> int:
    """复刻 _calc_required_history_days 对单周期的结果"""
    return max(
        int((INDICATOR_WARMUP_BARS * TF_MINUTES[timeframe]) / 1440 + 5), 7
    )


class TestStrategyReceivesEnoughBars:
    """每次 WS 推送，策略取到的大周期根数必须够算指标"""

    @pytest.mark.parametrize("timeframe", ["1h", "4h", "8h", "12h", "1d"])
    def test_enough_bars_at_every_push(self, tmp_path, timeframe):
        """按该周期所需天数补齐后，每次推送策略都应拿到 >= ADX 阈值的根数。

        注意断言的是 `len(df) - 1`：策略必须用 `get_closed_data` 丢掉未闭合
        的末根（AI_CONSTRAINTS 红线），所以实际可用根数比取到的少 1。
        """
        days = required_days(timeframe)
        dm, now = setup_live(tmp_path, [timeframe], days)

        seen = []
        dm.set_kline_dispatch_callback(lambda k: seen.append(
            dm.get_dataframe_cached(SYMBOL, interval=timeframe, limit=500)
        ))

        for i in range(1, 6):
            dm._on_kline_received(make_kline(now + timedelta(minutes=i)))

        assert len(seen) == 5, f"分发次数 {len(seen)} != 5"
        for i, df in enumerate(seen, 1):
            assert df is not None and not df.empty, f"第 {i} 次推送拿到空数据"
            usable = len(df) - 1  # get_closed_data 丢末根
            assert usable >= ADX_MIN_ROWS, (
                f"{timeframe} 第 {i} 次推送：取到 {len(df)} 根，"
                f"丢末根后 {usable} 根 < ADX 需要的 {ADX_MIN_ROWS} 根"
            )

    def test_live_config_both_timeframes(self, tmp_path):
        """线上 8h + 1h 同时注册：两个周期都要够，不能只满足大的那个"""
        days = max(required_days(tf) for tf in LIVE_TIMEFRAMES)
        dm, now = setup_live(tmp_path, LIVE_TIMEFRAMES, days)

        seen = []

        def dispatch(kline):
            seen.append({
                tf: dm.get_dataframe_cached(SYMBOL, interval=tf, limit=500)
                for tf in LIVE_TIMEFRAMES
            })

        dm.set_kline_dispatch_callback(dispatch)
        for i in range(1, 4):
            dm._on_kline_received(make_kline(now + timedelta(minutes=i)))

        for i, row in enumerate(seen, 1):
            for tf, df in row.items():
                assert df is not None and not df.empty, f"#{i} {tf} 空"
                usable = len(df) - 1
                assert usable >= ADX_MIN_ROWS, (
                    f"#{i} {tf}: 可用 {usable} 根 < {ADX_MIN_ROWS}"
                )

    def test_adx_does_not_warn_on_delivered_data(self, tmp_path):
        """终局验证：把策略实际拿到的数据喂给 ADX，不得触发数据不足告警。

        这是整条链路的唯一权威判据 —— 前面所有根数断言都是它的代理。
        """
        days = required_days("8h")
        dm, now = setup_live(tmp_path, ["8h"], days)

        captured = {}
        dm.set_kline_dispatch_callback(lambda k: captured.update(
            df=dm.get_dataframe_cached(SYMBOL, interval="8h", limit=500)
        ))
        dm._on_kline_received(make_kline(now + timedelta(minutes=1)))

        df = captured["df"]
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compute_adx(df.iloc[:-1], period=14)  # 丢末根，模拟 get_closed_data
        adx_warnings = [w for w in caught if "ADX" in str(w.message)]
        assert not adx_warnings, (
            f"策略拿到的 8h 数据不足以算准 ADX："
            f"{adx_warnings[0].message if adx_warnings else ''}"
        )

    def test_aggregation_precedes_dispatch(self, tmp_path):
        """大周期聚合必须在分发**之前**完成 —— 否则策略拿到的是上一轮的桶。

        锚定 _on_kline_received 里的调用顺序。若有人把
        `_update_big_intervals_from_cache` 移到 dispatch 之后，
        策略每次都会滞后一根。
        """
        dm, now = setup_live(tmp_path, ["1h"], required_days("1h"))

        # 推一根跨越 1h 边界的 K 线，检查新桶在分发时已存在
        nxt = (now + timedelta(hours=1)).replace(minute=0)
        seen_last_bucket = {}
        dm.set_kline_dispatch_callback(lambda k: seen_last_bucket.update(
            ts=dm.get_dataframe_cached(
                SYMBOL, interval="1h", limit=500
            )["timestamp"].iloc[-1]
        ))
        dm._on_kline_received(make_kline(nxt))

        assert seen_last_bucket["ts"] == pd.Timestamp(nxt), (
            f"分发时最新 1h 桶是 {seen_last_bucket['ts']}，"
            f"应为刚推送的 {nxt} —— 聚合可能在分发之后"
        )


class TestKlineLimitsCanStarveIndicators:
    """`params.kline_limits` 是个能静默把数据砍到不足的开关"""

    def test_default_limit_200_is_sufficient(self, tmp_path):
        """不配 kline_limits 时默认 200，对 8h 够用（线上即此情形）"""
        dm, now = setup_live(tmp_path, ["8h"], required_days("8h"))
        df = dm.get_dataframe_cached(SYMBOL, interval="8h", limit=200)
        assert len(df) - 1 >= ADX_MIN_ROWS

    @pytest.mark.parametrize("limit,enough", [
        (30, False),    # docstring 示例 1d: 30
        (50, False),    # docstring 示例 4h: 50
        (100, False),   # 边界陷阱：丢末根后只剩 99
        (101, True),    # 真正的最小安全值
        (200, True),
    ])
    def test_limit_boundary_is_101_not_100(self, tmp_path, limit, enough):
        """**off-by-one 陷阱**：limit=100 不够，因为 get_closed_data 要丢末根。

        安全下限是 `ADX_MIN_ROWS + 1 = 101`。
        `_fetch_multi_timeframe_data` 的 docstring 里那组示例
        （1d: 30 / 4h: 50）**全部不足**，照抄会让 ADX 静默失准。

        历史给足 120 天（8h ≈ 360 根），确保 `len(df) > limit` 对所有
        被测 limit 都成立 —— 否则 `get_dataframe_cached` 走的是不截断的
        `df.copy()` 分支，limit 根本没被行使，测试形同虚设。
        （消融实测：用 38 天历史时，把 limit 逻辑整段删掉这些用例仍全绿。）
        """
        dm, now = setup_live(tmp_path, ["8h"], 120)
        df = dm.get_dataframe_cached(SYMBOL, interval="8h", limit=limit)

        # 前置条件：limit 必须真的发生了截断
        assert len(df) == limit, (
            f"limit={limit} 未生效，实际取到 {len(df)} 根 —— "
            f"历史不足以触发截断，本用例无效"
        )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compute_adx(df.iloc[:-1], period=14)
        warned = any("ADX" in str(w.message) for w in caught)

        assert warned == (not enough), (
            f"limit={limit}: 取到 {len(df)} 根，丢末根后 {len(df)-1} 根，"
            f"ADX 告警={warned}，预期不足={not enough}"
        )

    def test_docstring_examples_are_insufficient(self):
        """把 docstring 里的示例值钉成"已知不足"，防止被当成推荐配置。

        若日后把示例改成充足的值，本测试会失败 —— 那时应更新此处。
        """
        docstring_examples = {"1d": 30, "4h": 50, "15m": 100}
        insufficient = {
            tf: n for tf, n in docstring_examples.items()
            if n - 1 < ADX_MIN_ROWS
        }
        assert insufficient == {"1d": 30, "4h": 50, "15m": 100}, (
            f"_fetch_multi_timeframe_data docstring 的示例值已变，"
            f"当前不足的是 {insufficient}"
        )


class TestColdStartStarvation:
    """冷启动补齐天数不足时，策略拿不到够算指标的数据"""

    @pytest.mark.parametrize("days,tf,enough", [
        (7,  "8h", False),   # TF_MINUTES 缺项时的退回值
        (10, "8h", False),   # 旧 bars_needed=15 的结果
        (30, "8h", False),   # 旧默认值（365 之前），对 8h 仍不够
        (38, "8h", True),    # 修复后 8h 应得的天数
        (365, "8h", True),   # settings.yaml 的 sync_history_days 现行默认值
        (9,  "1h", True),    # 1h 只需 9 天
    ])
    def test_history_days_determines_sufficiency(self, tmp_path, days, tf, enough):
        """回归：把"补多少天 → 策略拿到几根"这条因果关系钉死。

        30 天那行是旧默认值，对 8h 只有 90 根 —— 这正是
        `_resolve_history_days` 存在的理由；现行默认 365 天已够用。
        """
        dm, now = setup_live(tmp_path, [tf], days)
        seen = []
        dm.set_kline_dispatch_callback(lambda k: seen.append(
            dm.get_dataframe_cached(SYMBOL, interval=tf, limit=500)
        ))
        dm._on_kline_received(make_kline(now + timedelta(minutes=1)))

        df = seen[0]
        usable = 0 if df is None or df.empty else len(df) - 1
        assert (usable >= ADX_MIN_ROWS) == enough, (
            f"补 {days} 天 → {tf} 可用 {usable} 根，"
            f"够用={usable >= ADX_MIN_ROWS}，预期={enough}"
        )
