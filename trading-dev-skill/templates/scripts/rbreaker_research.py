#!/usr/bin/env python3
"""Fast, fee-aware research harness for ``cta_rbreaker_v3``.

The production framework deliberately replays every 1-minute bar through the
full DataManager/strategy stack.  That is appropriate for final integration
checks but unnecessarily slow for parameter screening.  This harness mirrors
the refactored core's UTC-session rules and supports 15-minute screening plus
exact 1-minute validation.

Example:
    python scripts/rbreaker_research.py --start 20260601 --end 20260709
    python scripts/rbreaker_research.py --start 20250101 --end 20260709 \
        --threshold 0.01 --adx-period 21 --adx-threshold 30
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import talib


@dataclass(frozen=True)
class ResearchParams:
    threshold: float = 0.01
    adx_period: int = 21
    adx_threshold: float = 30.0
    direction: str = "bearish"
    entry_start_hour_utc: float = 0.0
    entry_cutoff_hour_utc: float = 16.0
    force_close_hour_utc: int = 23
    force_close_minute_utc: int = 55
    stop_loss_pct: float = 0.0
    max_trades_per_day: int = 1
    leverage: float = 1.0
    commission: float = 0.0004
    trend_filter: str = "none"
    trend_ema_period: int = 0
    trend_slope_lookback_days: int = 5
    take_profit_pct: float = 0.0
    exit_threshold_multiplier: float = 1.0


@dataclass
class ResearchMetrics:
    symbol: str
    start: str
    end: str
    total_return: float
    annualized_return: float
    max_drawdown: float
    trades: int
    win_rate: float
    profit_factor: float
    total_fees: float
    final_equity: float


def _parse_date(value: str) -> pd.Timestamp:
    return pd.Timestamp(datetime.strptime(value, "%Y%m%d"), tz="UTC")


def load_bars(
    data_root: Path,
    symbol: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    params: ResearchParams,
    execution_timeframe: str,
) -> pd.DataFrame:
    """Load enough warm-up data and build look-ahead-safe research columns."""
    path = data_root / "1m" / f"{symbol}_1m.csv"
    frame = pd.read_csv(
        path,
        usecols=["timestamp", "open", "high", "low", "close", "volume"],
    )
    frame.index = pd.to_datetime(frame.pop("timestamp"), unit="ms", utc=True)
    warmup_days = max(
        7,
        params.trend_ema_period + params.trend_slope_lookback_days + 10,
    )
    warmup_start = start - pd.Timedelta(days=warmup_days)
    frame = frame.loc[warmup_start : end + pd.Timedelta(days=1)]

    daily = frame.resample("1D", label="left", closed="left").agg(
        high=("high", "max"), low=("low", "min"), close=("close", "last")
    )
    previous = daily.shift(1)
    pivot = (previous.high + previous.low + previous.close) / 3.0

    bars_15m = frame.resample("15min", label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    ).dropna()
    adx_values = talib.ADX(
        bars_15m.high.to_numpy(dtype=float),
        bars_15m.low.to_numpy(dtype=float),
        bars_15m.close.to_numpy(dtype=float),
        timeperiod=params.adx_period,
    )
    # A bar labelled 10:00 is not closed until 10:15.  Shift before forward
    # filling so the research harness cannot see an unfinished indicator bar.
    closed_adx = pd.Series(
        adx_values,
        index=bars_15m.index + pd.Timedelta(minutes=15),
        name="adx",
    )

    if execution_timeframe == "1m":
        bars = frame.copy()
    else:
        bars = bars_15m.copy()
    bars["pivot"] = pivot.reindex(bars.index, method="ffill")
    bars["adx"] = closed_adx.reindex(bars.index, method="ffill")
    bars["previous_close"] = previous.close.reindex(bars.index, method="ffill")
    if params.trend_filter != "none":
        daily_ema = daily.close.ewm(
            span=params.trend_ema_period,
            adjust=False,
            min_periods=params.trend_ema_period,
        ).mean()
        bars["trend_ema"] = daily_ema.shift(1).reindex(
            bars.index, method="ffill"
        )
        bars["trend_ema_slope"] = (
            daily_ema.shift(1)
            - daily_ema.shift(1 + params.trend_slope_lookback_days)
        ).reindex(bars.index, method="ffill")
    else:
        bars["trend_ema"] = np.nan
        bars["trend_ema_slope"] = np.nan
    bars = bars.loc[start : end + pd.Timedelta(hours=23, minutes=59)]
    return bars.dropna(subset=["pivot"])


def simulate(
    symbol: str,
    bars: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    params: ResearchParams,
    initial_cash: float = 100.0,
) -> ResearchMetrics:
    """Replay the same entry, opposite-rail exit, and UTC lock rules as core."""
    high = bars.high.to_numpy(dtype=float)
    low = bars.low.to_numpy(dtype=float)
    close = bars.close.to_numpy(dtype=float)
    pivot = bars["pivot"].to_numpy(dtype=float)
    adx = bars["adx"].to_numpy(dtype=float)
    previous_close = bars["previous_close"].to_numpy(dtype=float)
    trend_ema = bars["trend_ema"].to_numpy(dtype=float)
    trend_ema_slope = bars["trend_ema_slope"].to_numpy(dtype=float)
    hours = bars.index.hour.to_numpy() + bars.index.minute.to_numpy() / 60.0
    dates = pd.factorize(bars.index.date)[0]

    cash = float(initial_cash)
    position = 0
    entry_price = 0.0
    size = 0.0
    entry_fee = 0.0
    trades_today = 0
    current_day = -1
    locked = False
    peak_equity = cash
    max_drawdown = 0.0
    fees = 0.0
    trade_pnls: list[float] = []

    for index in range(len(bars)):
        day = int(dates[index])
        if day != current_day:
            current_day = day
            trades_today = 0
            locked = False

        forced = (int(hours[index]), int(round(hours[index] % 1 * 60))) >= (
            params.force_close_hour_utc,
            params.force_close_minute_utc,
        )
        upper = pivot[index] * (1.0 + params.threshold)
        lower = pivot[index] * (1.0 - params.threshold)

        if position:
            raw_return = (close[index] / entry_price - 1.0) * position
            stopped = params.stop_loss_pct > 0 and (
                (position == 1 and low[index] <= entry_price * (1 - params.stop_loss_pct))
                or (
                    position == -1
                    and high[index] >= entry_price * (1 + params.stop_loss_pct)
                )
            )
            exit_lower = pivot[index] * (
                1.0 - params.threshold * params.exit_threshold_multiplier
            )
            exit_upper = pivot[index] * (
                1.0 + params.threshold * params.exit_threshold_multiplier
            )
            took_profit = params.take_profit_pct > 0 and (
                (
                    position == 1
                    and high[index] >= entry_price * (1 + params.take_profit_pct)
                )
                or (
                    position == -1
                    and low[index] <= entry_price * (1 - params.take_profit_pct)
                )
            )
            opposite_rail = (position == 1 and low[index] <= exit_lower) or (
                position == -1 and high[index] >= exit_upper
            )
            if forced or stopped or took_profit or opposite_rail:
                gross = (close[index] - entry_price) * size * position
                exit_fee = abs(size) * close[index] * params.commission
                cash += gross - exit_fee
                fees += exit_fee
                trade_pnls.append(gross - entry_fee - exit_fee)
                position = 0
                size = 0.0
                if forced or stopped or trades_today >= params.max_trades_per_day:
                    locked = True

        if (
            not position
            and not locked
            and trades_today < params.max_trades_per_day
            and params.entry_start_hour_utc <= hours[index] < params.entry_cutoff_hour_utc
            and np.isfinite(adx[index])
            and adx[index] >= params.adx_threshold
        ):
            direction = 0
            long_allowed = params.direction in ("bullish", "neutral")
            short_allowed = params.direction in ("bearish", "neutral")
            if params.trend_filter != "none":
                above_ema = previous_close[index] > trend_ema[index]
                below_ema = previous_close[index] < trend_ema[index]
                rising = trend_ema_slope[index] > 0
                falling = trend_ema_slope[index] < 0
                if params.trend_filter == "ema":
                    long_allowed &= above_ema
                    short_allowed &= below_ema
                elif params.trend_filter == "ema_and_slope":
                    long_allowed &= above_ema and rising
                    short_allowed &= below_ema and falling
                elif params.trend_filter == "ema_slope":
                    long_allowed &= rising
                    short_allowed &= falling
            if long_allowed and close[index] >= upper:
                direction = 1
            elif short_allowed and close[index] <= lower:
                direction = -1
            if direction:
                notional = cash * params.leverage
                size = notional / close[index]
                entry_price = close[index]
                entry_fee = notional * params.commission
                cash -= entry_fee
                fees += entry_fee
                position = direction
                trades_today += 1

        equity = cash
        if position:
            equity += (close[index] - entry_price) * size * position
        peak_equity = max(peak_equity, equity)
        max_drawdown = max(max_drawdown, 1.0 - equity / peak_equity)

    if position:
        gross = (close[-1] - entry_price) * size * position
        exit_fee = abs(size) * close[-1] * params.commission
        cash += gross - exit_fee
        fees += exit_fee
        trade_pnls.append(gross - entry_fee - exit_fee)

    total_return = cash / initial_cash - 1.0
    calendar_days = (end.date() - start.date()).days + 1
    annualized = (
        (1.0 + total_return) ** (365.0 / calendar_days) - 1.0
        if total_return > -1.0
        else -1.0
    )
    pnl = np.asarray(trade_pnls, dtype=float)
    wins = pnl[pnl > 0]
    losses = pnl[pnl < 0]
    profit_factor = (
        float(wins.sum() / -losses.sum())
        if losses.size
        else (math.inf if wins.size else 0.0)
    )
    return ResearchMetrics(
        symbol=symbol,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        total_return=float(total_return),
        annualized_return=float(annualized),
        max_drawdown=float(max_drawdown),
        trades=int(pnl.size),
        win_rate=float((pnl > 0).mean()) if pnl.size else 0.0,
        profit_factor=profit_factor,
        total_fees=float(fees),
        final_equity=float(cash),
    )


def _symbols(value: str) -> Iterable[str]:
    return (item.strip().upper() for item in value.split(",") if item.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    parser.add_argument("--data-root", default="data/strategies")
    parser.add_argument("--execution-timeframe", choices=("1m", "15m"), default="1m")
    parser.add_argument("--threshold", type=float, default=0.01)
    parser.add_argument("--adx-period", type=int, default=21)
    parser.add_argument("--adx-threshold", type=float, default=30.0)
    parser.add_argument("--direction", choices=("bullish", "bearish", "neutral"), default="bearish")
    parser.add_argument("--entry-cutoff-hour-utc", type=float, default=16.0)
    parser.add_argument("--stop-loss-pct", type=float, default=0.0)
    parser.add_argument("--take-profit-pct", type=float, default=0.0)
    parser.add_argument("--exit-threshold-multiplier", type=float, default=1.0)
    parser.add_argument("--leverage", type=float, default=1.0)
    parser.add_argument("--commission", type=float, default=0.0004)
    parser.add_argument(
        "--trend-filter",
        choices=("none", "ema", "ema_and_slope", "ema_slope"),
        default="none",
    )
    parser.add_argument("--trend-ema-period", type=int, default=0)
    parser.add_argument("--trend-slope-lookback-days", type=int, default=5)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    start = _parse_date(args.start)
    end = _parse_date(args.end)
    params = ResearchParams(
        threshold=args.threshold,
        adx_period=args.adx_period,
        adx_threshold=args.adx_threshold,
        direction=args.direction,
        entry_cutoff_hour_utc=args.entry_cutoff_hour_utc,
        stop_loss_pct=args.stop_loss_pct,
        take_profit_pct=args.take_profit_pct,
        exit_threshold_multiplier=args.exit_threshold_multiplier,
        leverage=args.leverage,
        commission=args.commission,
        trend_filter=args.trend_filter,
        trend_ema_period=args.trend_ema_period,
        trend_slope_lookback_days=args.trend_slope_lookback_days,
    )
    results = []
    for symbol in _symbols(args.symbols):
        bars = load_bars(
            Path(args.data_root),
            symbol,
            start,
            end,
            params,
            args.execution_timeframe,
        )
        results.append(asdict(simulate(symbol, bars, start, end, params)))

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_timeframe": args.execution_timeframe,
        "params": asdict(params),
        "results": results,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
