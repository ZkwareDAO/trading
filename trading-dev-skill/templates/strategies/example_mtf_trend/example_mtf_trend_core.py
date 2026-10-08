#!/usr/bin/env python3
"""example_mtf_trend — 多周期核心逻辑（参考实现）

策略：三周期共振趋势跟随
    1d 定方向：收盘价在 EMA50 上方 → 只允许做多；下方 → 只允许做空
    4h 找触发：MA10 上穿/下穿 MA30（主周期 = timeframes[0]）
    1h 做确认：RSI14 > 55 / < 45，过滤逆小势的假交叉
    三个条件同时满足才入场；止损 = 2 × ATR14(4h)

读这个文件重点看多周期的标准写法（标 ★）：
    每个周期都单独 get_closed_data()、单独做数据不足检查，
    任何一根未闭合 K 线都不能进指标。
纯 pandas，无 talib 依赖。
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd

from strategy_core.base import BaseState, BaseStrategyCore
from strategy_core.position_persistence import PositionPersistence


@dataclass
class ExampleMtfTrendState(BaseState):
    """多周期示例状态。BaseState 的字段不重复定义。"""

    # ---- 持久化字段 ----
    atr_at_entry: float = 0.0
    trend_ema_at_entry: float = 0.0

    # ---- 缓存字段（不进 to_persist_dict）----
    latest_rsi: float = 50.0

    def to_persist_dict(self) -> Dict[str, Any]:
        data = super().to_persist_dict()
        data.update({
            "atr_at_entry": self.atr_at_entry,
            "trend_ema_at_entry": self.trend_ema_at_entry,
        })
        return data

    def restore_from_dict(self, data: Dict[str, Any]) -> None:
        super().restore_from_dict(data)
        self.atr_at_entry = data.get("atr_at_entry", 0.0)
        self.trend_ema_at_entry = data.get("trend_ema_at_entry", 0.0)

    def clear_position(self, record_stop_loss: bool = False,
                       current_time: Optional[datetime] = None) -> None:
        """所有平仓路径（含统一风控兜底）都会走到这里。"""
        super().clear_position(record_stop_loss=record_stop_loss,
                               current_time=current_time)
        self.atr_at_entry = 0.0
        self.trend_ema_at_entry = 0.0
        self.latest_rsi = 50.0


class ExampleMtfTrendCore(BaseStrategyCore[ExampleMtfTrendState]):
    """三周期共振核心逻辑。"""

    def __init__(self, symbols, timeframes, params=None, global_config=None):
        super().__init__(symbols, timeframes, params, global_config)

        # ★ 各分析周期用显式参数指定，不依赖 timeframes 列表顺序的隐含约定
        self.trend_tf = self.params.get("trend_timeframe", "1d")
        self.trigger_tf = timeframes[0] if timeframes else "4h"   # 主周期
        self.confirm_tf = self.params.get("confirm_timeframe", "1h")

        self.trend_ema_period = int(self.params.get("trend_ema_period", 50))
        self.fast_period = int(self.params.get("ma_fast_period", 10))
        self.slow_period = int(self.params.get("ma_slow_period", 30))
        self.rsi_period = int(self.params.get("rsi_period", 14))
        self.rsi_long = float(self.params.get("rsi_long_threshold", 55))
        self.rsi_short = float(self.params.get("rsi_short_threshold", 45))
        self.atr_period = int(self.params.get("atr_period", 14))
        self.atr_stop_mult = float(self.params.get("atr_stop_mult", 2.0))

        # 各周期需要的最小已闭合行数
        self.min_rows_trend = self.trend_ema_period + 5
        self.min_rows_trigger = self.slow_period + 5
        self.min_rows_confirm = self.rsi_period + 5

        # Core 拿不到 capital.leverage，只能从 params 读（与 capital.leverage 保持一致）
        self.leverage = float(self.params.get("leverage", 1))

    # ========== 必需实现 ==========

    def _get_state(self, symbol: str) -> ExampleMtfTrendState:
        if symbol not in self._state:
            self._state[symbol] = ExampleMtfTrendState()
        return self._state[symbol]

    def get_status(self) -> Dict[str, Any]:
        return {
            "symbols": self.symbols,
            "timeframes": self.timeframes,
            "states": {s: self._get_state(s).to_persist_dict() for s in self.symbols},
        }

    # ========== 指标（纯 pandas）==========

    @staticmethod
    def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
        """Wilder RSI。"""
        delta = close.diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
        # avg_loss=0 时 RSI 约定为 100（只涨不跌）；两者都 0（横盘）为 50
        rsi = pd.Series(50.0, index=close.index)
        both = (avg_gain > 0) & (avg_loss > 0)
        rsi[both] = 100 - 100 / (1 + avg_gain[both] / avg_loss[both])
        rsi[(avg_gain > 0) & (avg_loss == 0)] = 100.0
        rsi[(avg_gain == 0) & (avg_loss > 0)] = 0.0
        return rsi

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
        high, low, close = df["high"], df["low"], df["close"]
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    def _hold_result(self, reason: str, price: float = 0.0) -> Dict[str, Any]:
        return {"action": "hold", "price": price, "strength": 0.0,
                "metadata": {"reason": reason}}

    # ========== 入场 ==========

    def analyze(self, symbol, klines_data, current_time=None,
                realtime_price=None, current_cash=None) -> Dict[str, Any]:
        state = self._get_state(symbol)

        if current_time is None:
            return self._hold_result("current_time 缺失")
        if state.stop_loss_date == current_time.date():
            return self._hold_result("今日已触发止损，禁止开仓")
        if state.is_in_position():
            return self._hold_result(f"已有持仓: {state.position}")

        # ★★ 多周期标准写法：每个周期单独取已闭合 K 线 + 单独做数据检查
        trend_df = self.get_closed_data(
            klines_data, self.trend_tf,
            min_rows=self.min_rows_trend, current_time=current_time)
        if trend_df.empty or len(trend_df) < self.min_rows_trend:
            return self._hold_result(f"{self.trend_tf} K 线数据不足")

        trigger_df = self.get_closed_data(
            klines_data, self.trigger_tf,
            min_rows=self.min_rows_trigger, current_time=current_time)
        if trigger_df.empty or len(trigger_df) < self.min_rows_trigger:
            return self._hold_result(f"{self.trigger_tf} K 线数据不足")

        confirm_df = self.get_closed_data(
            klines_data, self.confirm_tf,
            min_rows=self.min_rows_confirm, current_time=current_time)
        if confirm_df.empty or len(confirm_df) < self.min_rows_confirm:
            return self._hold_result(f"{self.confirm_tf} K 线数据不足")

        # ===== 1d：趋势方向 =====
        trend_close = trend_df["close"].astype(float)
        ema = trend_close.ewm(span=self.trend_ema_period, adjust=False).mean()
        trend_last = float(trend_close.iloc[-1])
        ema_last = float(ema.iloc[-1])
        if pd.isna(ema_last):
            return self._hold_result("趋势 EMA 数据不足")
        trend_up = trend_last > ema_last

        # ===== 4h：交叉触发（用最后两根已闭合 bar 判断）=====
        fast = trigger_df["close"].astype(float).rolling(self.fast_period).mean()
        slow = trigger_df["close"].astype(float).rolling(self.slow_period).mean()
        if fast.isna().iloc[-1] or slow.isna().iloc[-1] or fast.isna().iloc[-2]:
            return self._hold_result("触发均线数据不足")
        f_now, f_prev = float(fast.iloc[-1]), float(fast.iloc[-2])
        s_now, s_prev = float(slow.iloc[-1]), float(slow.iloc[-2])
        golden = f_prev <= s_prev and f_now > s_now
        death = f_prev >= s_prev and f_now < s_now

        # ===== 1h：RSI 确认 =====
        rsi = self._rsi(confirm_df["close"].astype(float), self.rsi_period)
        if pd.isna(rsi.iloc[-1]):
            return self._hold_result("RSI 数据不足")
        rsi_now = float(rsi.iloc[-1])
        state.latest_rsi = rsi_now

        # ===== ATR 止损（4h）=====
        atr = self._atr(trigger_df, self.atr_period)
        atr_last = float(atr.iloc[-1])
        if pd.isna(atr_last) or atr_last <= 0:
            return self._hold_result("ATR 数据不足")

        # ===== 入场价：实时价优先，退回触发周期收盘价 =====
        if realtime_price and realtime_price > 0:
            entry_price = float(realtime_price)
        else:
            entry_price = float(trigger_df["close"].iloc[-1])

        # ===== 三周期共振 + direction 单向过滤 =====
        long_ok = trend_up and golden and rsi_now > self.rsi_long
        short_ok = (not trend_up) and death and rsi_now < self.rsi_short

        if long_ok and self.direction in ("neutral", "long"):
            return self._open(
                symbol, state, "long", entry_price, current_time,
                atr_last, ema_last, current_cash,
                f"1d 趋势向上({trend_last:.0f}>EMA{self.trend_ema_period}{ema_last:.0f}) "
                f"+ 4h 金叉 + 1h RSI {rsi_now:.0f}>{self.rsi_long:.0f}")

        if short_ok and self.direction in ("neutral", "short"):
            return self._open(
                symbol, state, "short", entry_price, current_time,
                atr_last, ema_last, current_cash,
                f"1d 趋势向下({trend_last:.0f}<EMA{self.trend_ema_period}{ema_last:.0f}) "
                f"+ 4h 死叉 + 1h RSI {rsi_now:.0f}<{self.rsi_short:.0f}")

        return self._hold_result("三周期未共振")

    def _open(self, symbol, state, side, entry_price, current_time,
              atr_value, ema_value, current_cash, reason) -> Dict[str, Any]:
        """完整入场分支（与 example_ma_cross 同一套契约）。"""
        is_long = side == "long"
        stop_price = (entry_price - self.atr_stop_mult * atr_value if is_long
                      else entry_price + self.atr_stop_mult * atr_value)

        state.position = side
        state.position_id = PositionPersistence.generate_position_id(
            self._strategy_name, symbol, int(current_time.timestamp()))
        state.entry_price = entry_price
        state.entry_time = current_time
        state.entry_timestamp = int(current_time.timestamp())
        state.stop_price = stop_price
        state.peak_price = entry_price
        state.atr_at_entry = atr_value
        state.trend_ema_at_entry = ema_value

        self._notify_position_enter(symbol, state)

        return {
            "action": "buy" if is_long else "sell",
            "price": entry_price,
            "strength": 0.8,
            "metadata": {
                "reason": reason,
                "atr": atr_value,
                "trend_ema": ema_value,
                "rsi": state.latest_rsi,
                "stop_price": stop_price,
                "target_notional": (current_cash or 0.0) * self.leverage,
            },
        }

    # ========== 出场：ATR 硬止损；其余交给统一风控兜底 ==========

    def check_realtime_exit(self, symbol, current_price, current_time=None,
                            bar_high=None, bar_low=None) -> Dict[str, Any]:
        state = self._get_state(symbol)

        if not state.is_in_position():
            return self._hold_result("无持仓", price=current_price)

        state.update_pnl_extremes(current_price)
        check_high, check_low = self._get_exit_detection_prices(
            current_price, bar_high, bar_low)

        if state.position == "long" and check_low <= state.stop_price:
            return self._close(symbol, state, state.stop_price,
                               f"ATR 止损: {check_low:.2f} ≤ {state.stop_price:.2f}",
                               True, current_time)

        if state.position == "short" and check_high >= state.stop_price:
            return self._close(symbol, state, state.stop_price,
                               f"ATR 止损: {check_high:.2f} ≥ {state.stop_price:.2f}",
                               True, current_time)

        return self._hold_result("持仓中", price=current_price)

    def _close(self, symbol, state, price, reason, is_stop_loss, current_time):
        action = self._notify_exit_and_clear(
            symbol=symbol, state=state, exit_price=price,
            exit_reason=reason, is_stop_loss=is_stop_loss, exit_time=current_time)
        return {
            "action": action,
            "price": price,
            "strength": 0.8,
            "metadata": {"reason": reason, "is_stop_loss": is_stop_loss},
        }
