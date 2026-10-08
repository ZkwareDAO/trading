#!/usr/bin/env python3
"""example_ma_cross — 核心逻辑（参考实现）

策略：双均线交叉
    入场：快线上穿慢线 → 做多；快线下穿慢线 → 做空
    出场：固定百分比硬止损；此外由基类统一风控（overrides 的 risk 段）兜底

这个策略的交易逻辑故意做得很笨，因为它的用途是**把框架契约演示清楚**，
不是赚钱。读的时候重点看注释里标 ★ 的地方 —— 那些是骨架模板里看不出来、
写错了又不会报错（只会静默不发信号）的约定。

不依赖 talib，纯 pandas，复制过去就能跑。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd

from strategy_core.base import BaseState, BaseStrategyCore
from strategy_core.position_persistence import PositionPersistence


@dataclass  # ★ 必须加：BaseState 是 dataclass，子类漏了装饰器新增字段不会生效
class ExampleMaCrossState(BaseState):
    """策略状态。

    BaseState 已经带了 position / position_id / entry_price / entry_time /
    entry_timestamp / peak_price / stop_price / stop_loss_date /
    max_pnl_pct / min_pnl_pct / trail_activated / trail_trigger_pct，
    ★ 不要重复定义这些字段。
    """

    # ---- 持久化字段：重启后需要恢复的 ----
    ma_fast_at_entry: float = 0.0
    ma_slow_at_entry: float = 0.0

    # ---- 缓存字段：每次 analyze() 重算，★ 不进 to_persist_dict() ----
    latest_ma_fast: float = 0.0
    latest_ma_slow: float = 0.0

    def to_persist_dict(self) -> Dict[str, Any]:
        data = super().to_persist_dict()
        data.update({
            "ma_fast_at_entry": self.ma_fast_at_entry,
            "ma_slow_at_entry": self.ma_slow_at_entry,
        })
        return data

    def restore_from_dict(self, data: Dict[str, Any]) -> None:
        super().restore_from_dict(data)
        self.ma_fast_at_entry = data.get("ma_fast_at_entry", 0.0)
        self.ma_slow_at_entry = data.get("ma_slow_at_entry", 0.0)

    def clear_position(self, record_stop_loss: bool = False,
                       current_time: Optional[datetime] = None) -> None:
        """★ 重置策略特有字段的推荐位置。

        比在 _close() 里逐个重置更可靠：平仓有两条路径 —— 策略自己的
        check_realtime_exit()，以及基类统一风控兜底（strategy.py:614-634）。
        后者不会经过你的 _close()，但一定会走到 clear_position()。
        """
        super().clear_position(record_stop_loss=record_stop_loss,
                               current_time=current_time)
        self.ma_fast_at_entry = 0.0
        self.ma_slow_at_entry = 0.0
        self.latest_ma_fast = 0.0
        self.latest_ma_slow = 0.0


class ExampleMaCrossCore(BaseStrategyCore[ExampleMaCrossState]):
    """双均线交叉核心逻辑。"""

    def __init__(self, symbols, timeframes, params=None, global_config=None):
        super().__init__(symbols, timeframes, params, global_config)

        # 指标周期：★ 每个指标都要有自己的 *_timeframes 参数，
        # 并且 Strategy._get_indicator_timeframes() 里要把它收集进去
        self.ma_timeframe = self.params.get(
            "ma_timeframes", timeframes[0] if timeframes else "4h")

        self.fast_period = int(self.params.get("ma_fast_period", 10))
        self.slow_period = int(self.params.get("ma_slow_period", 30))
        self.stop_loss_pct = float(self.params.get("stop_loss_pct", 2.0))
        # 量化"金叉够不够干脆"，用来区分强弱信号
        self.strong_spread_pct = float(self.params.get("strong_spread_pct", 0.3))

        # 慢线要够长才有值，再留几根余量
        self.min_rows = self.slow_period + 5

        # ★ 杠杆的坑：Strategy 层从 capital.leverage 读到 self.leverage，
        # 但它**不会**传给 Core。Core 只能从 params 拿。
        # 所以 overrides 里 params.leverage 要和 capital.leverage 写成一样的值。
        self.leverage = float(self.params.get("leverage", 1))

        # self.direction 由基类从 params["direction"] 解析（core.py:46），
        # 取值 neutral / long / short，用来做单向过滤

    # ========== 必需实现 ==========

    def _get_state(self, symbol: str) -> ExampleMaCrossState:
        if symbol not in self._state:
            self._state[symbol] = ExampleMaCrossState()
        return self._state[symbol]

    def get_status(self) -> Dict[str, Any]:
        return {
            "symbols": self.symbols,
            "timeframes": self.timeframes,
            "states": {s: self._get_state(s).to_persist_dict() for s in self.symbols},
        }

    # ========== 辅助方法 ==========

    def _hold_result(self, reason: str, price: float = 0.0) -> Dict[str, Any]:
        """不动作时的统一返回。★ 四个键一个都不能少，基类会直接下标取值。"""
        return {"action": "hold", "price": price, "strength": 0.0,
                "metadata": {"reason": reason}}

    def _compute_ma(self, closed: pd.DataFrame) -> tuple:
        """返回 (快线, 慢线)，都是 pd.Series。"""
        close = closed["close"].astype(float)
        return (close.rolling(self.fast_period).mean(),
                close.rolling(self.slow_period).mean())

    def _open(
        self,
        symbol: str,
        state: ExampleMaCrossState,
        side: str,
        entry_price: float,
        current_time: datetime,
        ma_fast: float,
        ma_slow: float,
        strength: float,
        reason: str,
        current_cash: Optional[float],
    ) -> Dict[str, Any]:
        """★★ 完整的入场分支 —— 这段是骨架模板里最缺的东西。

        少做任何一步都不会报错，但会静默出问题：
          - 漏 position_id            → 平仓时持久化 JSON 清不掉，重启后仓位诈尸
          - 漏 _notify_position_enter → 仓位根本没落盘，进程一重启就丢
          - action 拼错字符串          → _create_signal() 返回 None，信号被静默丢弃
        """
        is_long = side == "long"
        stop_price = (entry_price * (1 - self.stop_loss_pct / 100) if is_long
                      else entry_price * (1 + self.stop_loss_pct / 100))

        # --- 1. 写状态：这 7 个字段是基类持久化和历史仓位记录要用的 ---
        state.position = side
        state.position_id = PositionPersistence.generate_position_id(
            self._strategy_name, symbol, int(current_time.timestamp()))
        state.entry_price = entry_price
        state.entry_time = current_time
        state.entry_timestamp = int(current_time.timestamp())  # ★ 秒级，不是毫秒
        state.stop_price = stop_price
        state.peak_price = entry_price
        # --- 2. 写策略特有字段 ---
        state.ma_fast_at_entry = ma_fast
        state.ma_slow_at_entry = ma_slow

        # --- 3. ★ 通知基类落盘（回测模式下基类内部会自动跳过）---
        self._notify_position_enter(symbol, state)

        # --- 4. 返回信号 ---
        # ★ 入场 action 只有 "buy"（开多）和 "sell"（开空）两个合法值。
        #   平仓的 "sell_close" / "buy_close" 不要在这里出现。
        #   合法值全集见 docs/SIGNAL_CSV_FORMAT.md。
        return {
            "action": "buy" if is_long else "sell",
            "price": entry_price,
            # ★ strength < overrides 里的 signal.min_strength 时，
            #   基类会丢弃这个信号（strategy.py:449）——调不出信号先查这里
            "strength": strength,
            "metadata": {
                "reason": reason,
                "ma_fast": ma_fast,
                "ma_slow": ma_slow,
                "stop_price": stop_price,
                # ★ 下单量：下游按名义值下单，策略不算张数。
                #   current_cash 由基类从 capital.max_cash 传入（strategy.py:435）
                "target_notional": (current_cash or 0.0) * self.leverage,
            },
        }

    def _close(
        self,
        symbol: str,
        state: ExampleMaCrossState,
        price: float,
        reason: str,
        is_stop_loss: bool = False,
        current_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """平仓。★ 一律走 _notify_exit_and_clear()，不要自己调 clear_position()。

        基类那一个方法里做了四件事：触发 _on_before_exit_clear 钩子、
        通知平仓回调（写历史仓位 CSV + 清持久化）、清状态、
        is_stop_loss=True 时记 stop_loss_date。返回值就是正确的 action 字符串。
        """
        action = self._notify_exit_and_clear(
            symbol=symbol, state=state, exit_price=price,
            exit_reason=reason, is_stop_loss=is_stop_loss, exit_time=current_time,
        )
        return {
            "action": action,  # "sell_close"（平多）/ "buy_close"（平空）
            "price": price,
            "strength": 0.8,
            "metadata": {"reason": reason, "is_stop_loss": is_stop_loss},
        }

    # ========== 入场 ==========

    def analyze(self, symbol, klines_data, current_time=None,
                realtime_price=None, current_cash=None) -> Dict[str, Any]:
        """入场分析。基类每根 1m K 线都会调用一次（无持仓时）。"""
        state = self._get_state(symbol)

        # --- 前置检查，顺序别改 ---
        if current_time is None:
            # ★ 禁止在这里 fallback 到 datetime.now()：信号时间戳必须可重现
            return self._hold_result("current_time 缺失")

        if state.stop_loss_date == current_time.date():
            return self._hold_result("今日已触发止损，禁止开仓")

        if state.is_in_position():
            return self._hold_result(f"已有持仓: {state.position}")

        # --- 取已闭合 K 线 ---
        # ★ min_rows 只是"原始数据不足就返回空"的门槛，过滤掉未闭合 bar 之后
        #   仍可能不够（core.py:341-351），所以下面必须再判一次 len()
        closed = self.get_closed_data(
            klines_data, self.ma_timeframe,
            min_rows=self.min_rows, current_time=current_time)
        if closed.empty or len(closed) < self.min_rows:
            return self._hold_result("K 线数据不足")

        # --- 算指标：★ 只能用 closed，绝不能用 klines_data 原始 df ---
        fast_series, slow_series = self._compute_ma(closed)
        if (fast_series.isna().iloc[-1] or slow_series.isna().iloc[-1]
                or fast_series.isna().iloc[-2] or slow_series.isna().iloc[-2]):
            return self._hold_result("均线数据不足")

        fast_now, fast_prev = float(fast_series.iloc[-1]), float(fast_series.iloc[-2])
        slow_now, slow_prev = float(slow_series.iloc[-1]), float(slow_series.iloc[-2])

        state.latest_ma_fast = fast_now
        state.latest_ma_slow = slow_now

        # --- 入场价 ---
        # ★ 优先 realtime_price（1m 实时价），退回已闭合 K 线收盘价。
        #   绝不能用大周期最后一根未闭合 bar 的 close —— 那是未来函数。
        if realtime_price and realtime_price > 0:
            entry_price = float(realtime_price)
        else:
            entry_price = float(closed["close"].iloc[-1])

        # --- 判信号 ---
        golden_cross = fast_prev <= slow_prev and fast_now > slow_now
        death_cross = fast_prev >= slow_prev and fast_now < slow_now

        spread_pct = abs(fast_now - slow_now) / slow_now * 100 if slow_now else 0.0
        strength = 0.8 if spread_pct >= self.strong_spread_pct else 0.6

        # ★ self.direction 做单向过滤，neutral 表示多空都做
        if golden_cross and self.direction in ("neutral", "long"):
            return self._open(
                symbol, state, "long", entry_price, current_time,
                fast_now, slow_now, strength,
                f"金叉 MA{self.fast_period}({fast_now:.2f}) 上穿 "
                f"MA{self.slow_period}({slow_now:.2f})，价差 {spread_pct:.2f}%",
                current_cash,
            )

        if death_cross and self.direction in ("neutral", "short"):
            return self._open(
                symbol, state, "short", entry_price, current_time,
                fast_now, slow_now, strength,
                f"死叉 MA{self.fast_period}({fast_now:.2f}) 下穿 "
                f"MA{self.slow_period}({slow_now:.2f})，价差 {spread_pct:.2f}%",
                current_cash,
            )

        return self._hold_result("未出现交叉")

    # ========== 出场 ==========

    def check_realtime_exit(self, symbol, current_price, current_time=None,
                            bar_high=None, bar_low=None) -> Dict[str, Any]:
        """出场检查。基类每根 1m K 线都会调用一次（有持仓时）。

        这里只做策略自己的硬止损。回落止盈、固定止盈等通用风控由基类
        统一风控兜底 —— 本方法返回 hold 之后，基类会接着查 check_risk_control()
        （strategy.py:614-634），配置在 overrides 的 risk 段。
        """
        state = self._get_state(symbol)

        if not state.is_in_position():
            return self._hold_result("无持仓", price=current_price)

        # ★ 必须第一时间调用：历史仓位 CSV 的 max_pnl_pct / min_pnl_pct 靠它
        state.update_pnl_extremes(current_price)

        # ★ 用基类方法拿检测价：配置 use_bar_high_low_for_exit=True 时
        #   用 bar 的高低点判断触及，比只看收盘价更接近真实成交
        check_high, check_low = self._get_exit_detection_prices(
            current_price, bar_high, bar_low)

        is_long = state.position == "long"

        if is_long and check_low <= state.stop_price:
            return self._close(
                symbol, state, state.stop_price,
                f"止损: 最低价 {check_low:.2f} ≤ 止损位 {state.stop_price:.2f}",
                is_stop_loss=True, current_time=current_time)

        if not is_long and check_high >= state.stop_price:
            return self._close(
                symbol, state, state.stop_price,
                f"止损: 最高价 {check_high:.2f} ≥ 止损位 {state.stop_price:.2f}",
                is_stop_loss=True, current_time=current_time)

        return self._hold_result("持仓中", price=current_price)
