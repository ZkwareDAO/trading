#!/usr/bin/env python3
"""VPVR Spot 自定义回测 — 初始持有 FIL，双维度评估（USDT / FIL）"""

import sys
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

import pandas as pd

from data_manager.indicators import compute_rsi, compute_atr, compute_adx, compute_volume_profile, VPVRProfile

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class VPVRState:
    position: Optional[str] = None  # 'long' or None
    entry_price: float = 0.0
    peak_price: float = 0.0
    stop_price: float = 0.0
    atr_at_entry: float = 0.0
    trail_anchor_price: float = 0.0
    trail_activated: bool = False
    trail_mult_at_entry: float = 2.0

    cached_poc: Optional[float] = None
    cached_vah: Optional[float] = None
    cached_val: Optional[float] = None
    cached_rsi: Optional[float] = None
    cached_adx: Optional[float] = None
    cached_atr: Optional[float] = None


@dataclass
class TradeRecord:
    timestamp: datetime
    action: str  # 'buy' or 'sell'
    price: float
    fil_amount: float
    usdt_amount: float
    reason: str = ""


@dataclass
class DailySnapshot:
    date: str
    price: float
    fil_balance: float
    usdt_balance: float
    usdt_value: float
    fil_equivalent: float
    position: str  # 'holding_fil' or 'holding_usdt'


def run_vpvr_spot_backtest(
    df_1h: pd.DataFrame,
    initial_fil: float = 10000.0,
    vpvr_bars: int = 100,
    price_bin_count: int = 50,
    value_area_pct: float = 0.70,
    rsi_period: int = 14,
    rsi_oversold: float = 45.0,
    adx_period: int = 14,
    adx_threshold: float = 25.0,
    atr_period: int = 14,
    atr_stop_multiplier: float = 1.5,
    atr_trailing_multiplier: float = 2.0,
    val_tolerance_pct: float = 0.005,
    start_date: str = "2025-01-01",
    end_date: str = "2026-04-01",
):
    state = VPVRState()
    # Initial FIL position treated as already "entered" — use start price as entry
    fil_balance = initial_fil
    usdt_balance = 0.0
    position = "holding_fil"  # start by holding FIL

    trades: List[TradeRecord] = []
    daily_snapshots: List[DailySnapshot] = []

    start_dt = pd.Timestamp(start_date, tz="UTC")
    end_dt = pd.Timestamp(end_date, tz="UTC")

    df = df_1h[(df_1h["timestamp"] >= start_dt) & (df_1h["timestamp"] <= end_dt)].copy()
    df = df.reset_index(drop=True)

    if len(df) == 0:
        print("No data in range!")
        return

    start_price = float(df["close"].iloc[0])
    initial_usdt_value = initial_fil * start_price

    # Set initial entry for the pre-held FIL position
    initial_entry_set = False

    prev_date = None

    for i in range(max(vpvr_bars, atr_period + 1, rsi_period + 1, adx_period + 1), len(df)):
        row = df.iloc[i]
        current_price = float(row["close"])
        current_time = pd.Timestamp(row["timestamp"])

        if current_time < start_dt:
            continue

        # Daily snapshot (before any continue)
        current_date = current_time.strftime("%Y-%m-%d")
        if current_date != prev_date:
            usdt_val = fil_balance * current_price + usdt_balance
            fil_eq = fil_balance + (usdt_balance / current_price if current_price > 0 else 0)
            daily_snapshots.append(DailySnapshot(
                date=current_date, price=current_price,
                fil_balance=fil_balance, usdt_balance=usdt_balance,
                usdt_value=usdt_val, fil_equivalent=fil_eq,
                position=position,
            ))
            prev_date = current_date

        # Get window for indicator calculation
        window_start = max(0, i - vpvr_bars)
        df_window = df.iloc[window_start:i]

        # Compute VPVR
        try:
            profile = compute_volume_profile(
                df_window.tail(vpvr_bars),
                bin_count=price_bin_count,
                value_area_pct=value_area_pct,
            )
        except ValueError:
            profile = None

        # Compute RSI
        rsi_series = compute_rsi(df.iloc[:i+1], column="close", period=rsi_period)
        last_rsi = float(rsi_series.iloc[-1]) if not pd.isna(rsi_series.iloc[-1]) else None

        # Compute ATR
        atr_series = compute_atr(df.iloc[:i+1], period=atr_period)
        last_atr = float(atr_series.iloc[-1]) if not pd.isna(atr_series.iloc[-1]) else None

        # Compute ADX
        adx_df = compute_adx(df.iloc[:i+1], period=adx_period)
        last_adx = (
            float(adx_df["adx"].iloc[-1])
            if not adx_df.empty and not adx_df["adx"].isna().iloc[-1]
            else None
        )

        if profile:
            state.cached_poc = profile.poc_price
            state.cached_vah = profile.vah
            state.cached_val = profile.val
        state.cached_rsi = last_rsi
        state.cached_atr = last_atr
        state.cached_adx = last_adx

        # Initialize entry for pre-held FIL on first bar (when ATR available)
        if not initial_entry_set and position == "holding_fil" and last_atr and last_atr > 0:
            state.entry_price = current_price
            state.peak_price = current_price
            state.atr_at_entry = last_atr
            state.stop_price = current_price - atr_stop_multiplier * last_atr
            state.trail_anchor_price = current_price + atr_stop_multiplier * last_atr
            state.trail_activated = False
            state.trail_mult_at_entry = atr_trailing_multiplier
            initial_entry_set = True

        # --- Exit check (holding FIL) ---
        if position == "holding_fil" and initial_entry_set:
            state.peak_price = max(state.peak_price, current_price)

            # ATR stop loss
            if current_price <= state.stop_price:
                sell_fil = fil_balance
                sell_usdt = sell_fil * current_price
                trades.append(TradeRecord(
                    timestamp=current_time, action="sell", price=current_price,
                    fil_amount=sell_fil, usdt_amount=sell_usdt,
                    reason=f"ATR止损 stop={state.stop_price:.4f}",
                ))
                usdt_balance = sell_usdt
                fil_balance = 0.0
                position = "holding_usdt"
                state = VPVRState()
                continue

            # POC take profit
            if state.cached_poc and current_price >= state.cached_poc:
                sell_fil = fil_balance
                sell_usdt = sell_fil * current_price
                trades.append(TradeRecord(
                    timestamp=current_time, action="sell", price=current_price,
                    fil_amount=sell_fil, usdt_amount=sell_usdt,
                    reason=f"POC止盈 POC={state.cached_poc:.4f}",
                ))
                usdt_balance = sell_usdt
                fil_balance = 0.0
                position = "holding_usdt"
                state = VPVRState()
                continue

            # Trailing stop
            if not state.trail_activated:
                if current_price >= state.trail_anchor_price:
                    state.trail_activated = True

            if state.trail_activated and state.atr_at_entry > 0:
                trail_stop = state.peak_price - atr_trailing_multiplier * state.atr_at_entry
                if current_price < trail_stop:
                    sell_fil = fil_balance
                    sell_usdt = sell_fil * current_price
                    trades.append(TradeRecord(
                        timestamp=current_time, action="sell", price=current_price,
                        fil_amount=sell_fil, usdt_amount=sell_usdt,
                        reason=f"移动止盈 peak={state.peak_price:.4f} trail={trail_stop:.4f}",
                    ))
                    usdt_balance = sell_usdt
                    fil_balance = 0.0
                    position = "holding_usdt"
                    state = VPVRState()
                    continue

        # --- Entry check (holding USDT, looking to buy FIL) ---
        if position == "holding_usdt":
            if last_rsi is None or last_adx is None or last_atr is None:
                continue
            if last_atr <= 0:
                continue
            # ADX filter: no buying in trending market
            if last_adx >= adx_threshold:
                continue
            # Price near VAL or HVN
            if profile is None:
                continue
            tolerance = val_tolerance_pct * current_price
            near_val = abs(current_price - profile.val) <= tolerance
            near_hvn = any(
                abs(current_price - hvn_price) <= tolerance * 2
                for hvn_price in profile.high_prices
            )
            if not near_val and not near_hvn:
                continue
            # RSI filter
            if last_rsi >= rsi_oversold:
                continue

            # BUY
            buy_usdt = usdt_balance
            buy_fil = buy_usdt / current_price
            trades.append(TradeRecord(
                timestamp=current_time, action="buy", price=current_price,
                fil_amount=buy_fil, usdt_amount=buy_usdt,
                reason=f"VPVR支撑位入场 RSI={last_rsi:.1f} ADX={last_adx:.1f}",
            ))
            fil_balance = buy_fil
            usdt_balance = 0.0
            position = "holding_fil"
            state.position = "long"
            state.entry_price = current_price
            state.peak_price = current_price
            state.stop_price = current_price - atr_stop_multiplier * last_atr
            state.trail_anchor_price = current_price + (current_price - state.stop_price)
            state.trail_activated = False
            state.atr_at_entry = last_atr
            state.trail_mult_at_entry = atr_trailing_multiplier
            continue

    # Final snapshot
    if len(df) > 0:
        final_price = float(df["close"].iloc[-1])
        final_time = pd.Timestamp(df["timestamp"].iloc[-1])
        usdt_val = fil_balance * final_price + usdt_balance
        fil_eq = fil_balance + (usdt_balance / final_price if final_price > 0 else 0)
        daily_snapshots.append(DailySnapshot(
            date=final_time.strftime("%Y-%m-%d"), price=final_price,
            fil_balance=fil_balance, usdt_balance=usdt_balance,
            usdt_value=usdt_val, fil_equivalent=fil_eq,
            position=position,
        ))

    # --- Report ---
    final_price = float(df["close"].iloc[-1])
    final_usdt_value = fil_balance * final_price + usdt_balance
    final_fil_equivalent = fil_balance + (usdt_balance / final_price if final_price > 0 else 0)

    # Buy-and-hold baseline
    hold_usdt_value = initial_fil * final_price
    hold_fil = initial_fil

    print("\n" + "=" * 70)
    print("VPVR Spot 回测报告 — FILUSDT 现货")
    print("=" * 70)
    print(f"回测区间: {start_date} ~ {end_date}")
    print(f"初始持有: {initial_fil:,.2f} FIL (≈ {initial_usdt_value:,.2f} USDT @ {start_price:.4f})")
    print(f"期末价格: {final_price:.4f} USDT/FIL")
    print()

    print("-" * 70)
    print("维度一：USDT 价值评估")
    print("-" * 70)
    print(f"  策略期末 USDT 价值:   {final_usdt_value:>12,.2f}")
    print(f"  初始 USDT 价值:       {initial_usdt_value:>12,.2f}")
    print(f"  策略 USDT 收益率:     {(final_usdt_value/initial_usdt_value - 1)*100:>11.2f}%")
    print()
    print(f"  持有不动 USDT 价值:   {hold_usdt_value:>12,.2f}")
    print(f"  持有不动 USDT 收益率: {(hold_usdt_value/initial_usdt_value - 1)*100:>11.2f}%")
    print()
    delta_usdt = final_usdt_value - hold_usdt_value
    print(f"  策略 vs 持有:         {delta_usdt:>+12,.2f} USDT ({delta_usdt/hold_usdt_value*100:+.2f}%)")

    print()
    print("-" * 70)
    print("维度二：FIL 数量评估")
    print("-" * 70)
    print(f"  策略期末 FIL:         {final_fil_equivalent:>12,.4f}")
    print(f"  初始 FIL:             {initial_fil:>12,.4f}")
    print(f"  策略 FIL 变化:        {(final_fil_equivalent/initial_fil - 1)*100:>11.2f}%")
    print()
    print(f"  持有不动 FIL:         {hold_fil:>12,.4f}")
    print()
    delta_fil = final_fil_equivalent - hold_fil
    print(f"  策略 vs 持有:         {delta_fil:>+12,.4f} FIL ({delta_fil/hold_fil*100:+.2f}%)")

    print()
    print("-" * 70)
    print(f"交易记录 ({len(trades)} 笔)")
    print("-" * 70)
    print(f"{'时间':<22} {'动作':<6} {'价格':>10} {'FIL数量':>14} {'USDT金额':>14} {'原因'}")
    print("-" * 70)
    for t in trades:
        print(f"{str(t.timestamp):<22} {t.action:<6} {t.price:>10.4f} {t.fil_amount:>14.4f} {t.usdt_amount:>14.2f} {t.reason}")

    # Daily equity CSV
    snap_df = pd.DataFrame([
        {
            "date": s.date, "price": s.price,
            "fil_balance": s.fil_balance, "usdt_balance": s.usdt_balance,
            "usdt_value": s.usdt_value, "fil_equivalent": s.fil_equivalent,
            "position": s.position,
        }
        for s in daily_snapshots
    ])
    out_dir = Path("backtest_output/vpvr_spot_custom")
    out_dir.mkdir(parents=True, exist_ok=True)
    snap_df.to_csv(out_dir / "daily_equity.csv", index=False)

    # Trades CSV
    trades_df = pd.DataFrame([
        {
            "timestamp": str(t.timestamp), "action": t.action, "price": t.price,
            "fil_amount": t.fil_amount, "usdt_amount": t.usdt_amount, "reason": t.reason,
        }
        for t in trades
    ])
    trades_df.to_csv(out_dir / "trades.csv", index=False)

    print()
    print(f"输出文件:")
    print(f"  {out_dir / 'daily_equity.csv'}")
    print(f"  {out_dir / 'trades.csv'}")

    return trades, daily_snapshots


if __name__ == "__main__":
    df = pd.read_csv("data/strategies/1h/FILUSDT_1h.csv")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    run_vpvr_spot_backtest(
        df_1h=df,
        initial_fil=10000.0,
        start_date="2026-01-01",
        end_date="2026-05-21",
    )
