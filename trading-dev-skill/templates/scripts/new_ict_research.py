#!/usr/bin/env python3
"""Fast 15-minute research harness for ``new_ict``.

The production strategy remains the source of execution behavior.  This harness
replays the same state transitions directly on closed 15m/4h bars so parameter
research does not pay the generic framework's one-minute dispatch cost.
"""

from __future__ import annotations

import argparse
import base64
import itertools
import json
from functools import lru_cache
from dataclasses import asdict, dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


DATA_DIR = Path("data/strategies")
DEFAULT_PARAMS: dict[str, Any] = {
    "atr_period": 14,
    "htf_pivot_left": 2,
    "htf_pivot_right": 2,
    "ltf_pivot_left": 3,
    "ltf_pivot_right": 3,
    "liquidity_expiry_bars": 96,
    "min_sweep_atr": 0.05,
    "max_sweep_atr": 0.75,
    "mss_wait_bars": 8,
    "displacement_atr": 1.5,
    "min_body_ratio": 0.60,
    "close_extreme_fraction": 0.20,
    "min_fvg_atr": 0.05,
    "entry_expiry_bars": 8,
    "stop_buffer_atr": 0.10,
    "minimum_rr": 2.0,
    "max_holding_bars": 32,
    "risk_per_trade": 0.005,
    "max_position_leverage": 1.0,
    "premium_discount_filter": True,
}


@dataclass
class Level:
    side: str
    price: float
    source: str
    origin: int
    expires: int


@dataclass
class Trade:
    direction: str
    setup_time: str
    entry_time: str
    exit_time: str
    entry: float
    stop: float
    target: float
    exit: float
    exit_reason: str
    rr: float
    net_pnl: float
    fees: float
    funding: float


def _read_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close"])
    frame = frame[frame["timestamp"].dt.year >= 2020]
    return frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)


@lru_cache(maxsize=16)
def load_data(symbol: str, start: str, end_inclusive: str, warmup_days: int = 60) -> tuple[pd.DataFrame, pd.DataFrame]:
    start_ts = pd.Timestamp(start, tz="UTC")
    end_exclusive = pd.Timestamp(end_inclusive, tz="UTC") + pd.Timedelta(days=1)
    warmup = start_ts - pd.Timedelta(days=warmup_days)
    ltf = _read_frame(DATA_DIR / "15m" / f"{symbol}_15m.csv")
    htf = _read_frame(DATA_DIR / "4h" / f"{symbol}_4h.csv")
    ltf = ltf[(ltf.timestamp >= warmup) & (ltf.timestamp < end_exclusive)].reset_index(drop=True)
    htf = htf[(htf.timestamp >= warmup - pd.Timedelta(days=10)) & (htf.timestamp < end_exclusive)].reset_index(drop=True)
    if ltf.empty or htf.empty:
        raise ValueError(f"{symbol} 在指定区间没有足够数据")
    ltf.attrs["signal_start"] = start_ts
    return ltf, htf


def wilder_atr(frame: pd.DataFrame, period: int) -> np.ndarray:
    previous = frame.close.shift(1)
    tr = pd.concat([
        frame.high - frame.low,
        (frame.high - previous).abs(),
        (frame.low - previous).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean().to_numpy(float)


def pivot_flags(values: np.ndarray, left: int, right: int, high: bool) -> np.ndarray:
    result = np.zeros(len(values), dtype=bool)
    for index in range(left, len(values) - right):
        center = values[index]
        if high:
            result[index] = center > values[index-left:index].max() and center > values[index+1:index+right+1].max()
        else:
            result[index] = center < values[index-left:index].min() and center < values[index+1:index+right+1].min()
    return result


def build_htf_context(htf: pd.DataFrame, left: int, right: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    highs = htf.high.to_numpy(float)
    lows = htf.low.to_numpy(float)
    high_flags = pivot_flags(highs, left, right, True)
    low_flags = pivot_flags(lows, left, right, False)
    bias = np.zeros(len(htf), dtype=np.int8)
    midpoint = np.full(len(htf), np.nan)
    high_pivots: list[tuple[int, float]] = []
    low_pivots: list[tuple[int, float]] = []

    for index in range(len(htf)):
        pivot_index = index - right
        if pivot_index >= 0:
            if high_flags[pivot_index]:
                high_pivots.append((pivot_index, highs[pivot_index]))
            if low_flags[pivot_index]:
                low_pivots.append((pivot_index, lows[pivot_index]))
        if len(high_pivots) < 2 or len(low_pivots) < 2:
            continue
        if high_pivots[-1][1] > high_pivots[-2][1] and low_pivots[-1][1] > low_pivots[-2][1]:
            preceding = [item for item in low_pivots if item[0] < high_pivots[-1][0]]
            if preceding and high_pivots[-1][1] > preceding[-1][1]:
                bias[index] = 1
                midpoint[index] = (high_pivots[-1][1] + preceding[-1][1]) / 2
        elif high_pivots[-1][1] < high_pivots[-2][1] and low_pivots[-1][1] < low_pivots[-2][1]:
            preceding = [item for item in high_pivots if item[0] < low_pivots[-1][0]]
            if preceding and preceding[-1][1] > low_pivots[-1][1]:
                bias[index] = -1
                midpoint[index] = (preceding[-1][1] + low_pivots[-1][1]) / 2
    close_ns = (htf.timestamp + pd.Timedelta(hours=4)).astype("int64").to_numpy()
    return bias, midpoint, close_ns


def previous_day_levels(frame: pd.DataFrame) -> dict[Any, tuple[float, float]]:
    daily = frame.assign(day=frame.timestamp.dt.date).groupby("day").agg(high=("high", "max"), low=("low", "min"))
    result: dict[Any, tuple[float, float]] = {}
    days = list(daily.index)
    for index in range(1, len(days)):
        prior = daily.loc[days[index - 1]]
        result[days[index]] = (float(prior.high), float(prior.low))
    return result


def run_backtest(
    symbol: str,
    start: str,
    end: str,
    params: dict[str, Any],
    commission: float = 0.0004,
    funding_rate_8h: float = 0.0001,
    initial_cash: float = 5000.0,
) -> dict[str, Any]:
    ltf, htf = load_data(symbol, start, end)
    p = {**DEFAULT_PARAMS, **params}
    o = ltf.open.to_numpy(float)
    h = ltf.high.to_numpy(float)
    lo = ltf.low.to_numpy(float)
    c = ltf.close.to_numpy(float)
    ts = ltf.timestamp
    atr_values = wilder_atr(ltf, int(p["atr_period"]))
    high_flags = pivot_flags(h, int(p["ltf_pivot_left"]), int(p["ltf_pivot_right"]), True)
    low_flags = pivot_flags(lo, int(p["ltf_pivot_left"]), int(p["ltf_pivot_right"]), False)
    htf_bias, htf_midpoint, htf_close_ns = build_htf_context(
        htf, int(p["htf_pivot_left"]), int(p["htf_pivot_right"]),
    )
    decision_ns = (ts + pd.Timedelta(minutes=15)).astype("int64").to_numpy()
    context_index = np.searchsorted(htf_close_ns, decision_ns, side="right") - 1
    pd_levels = previous_day_levels(ltf)
    signal_start = pd.Timestamp(start, tz="UTC")

    active: list[Level] = []
    latest_pivot_high: float | None = None
    latest_pivot_low: float | None = None
    current_day = None
    phase = "idle"
    direction = 0
    sweep_extreme = sweep_atr = structure_level = 0.0
    sweep_index = setup_age = 0
    pending_entry = pending_stop = pending_target = 0.0
    pending_expiry = -1
    position = 0
    entry = stop = target = qty = entry_fee = 0.0
    entry_index = -1
    setup_time = ""
    cash = initial_cash
    peak_equity = initial_cash
    max_drawdown = 0.0
    trades: list[Trade] = []
    setups = 0
    diagnostics = {
        "mss": 0, "mss_displacement": 0, "mss_fvg": 0,
        "pending_created": 0, "pending_expired": 0,
        "pending_invalidated": 0, "pending_target_first": 0, "pending_filled": 0,
        "target_or_rr_rejected": 0,
    }

    def close_trade(index: int, exit_price: float, reason: str) -> None:
        nonlocal cash, position, entry, stop, target, qty, entry_fee, entry_index, phase
        gross = qty * (exit_price - entry) * position
        exit_fee = qty * exit_price * commission
        held_bars = max(index - entry_index, 1)
        funding = qty * entry * funding_rate_8h * held_bars / 32
        net = gross - entry_fee - exit_fee - funding
        cash += gross - exit_fee - funding
        trades.append(Trade(
            direction="long" if position == 1 else "short",
            setup_time=setup_time,
            entry_time=ts.iloc[entry_index].isoformat(),
            exit_time=ts.iloc[index].isoformat(),
            entry=entry, stop=stop, target=target, exit=exit_price,
            exit_reason=reason, rr=abs(target-entry) / abs(entry-stop),
            net_pnl=net, fees=entry_fee + exit_fee, funding=funding,
        ))
        position = 0
        phase = "idle"

    right = int(p["ltf_pivot_right"])
    left = int(p["ltf_pivot_left"])
    for index in range(len(ltf)):
        day = ts.iloc[index].date()
        if day != current_day:
            active = [level for level in active if level.source != "previous_day"]
            if day in pd_levels:
                prior_high, prior_low = pd_levels[day]
                active.extend([
                    Level("high", prior_high, "previous_day", index, index + 95),
                    Level("low", prior_low, "previous_day", index, index + 95),
                ])
            current_day = day

        new_pivot = index - right - 1
        if new_pivot >= left:
            if high_flags[new_pivot]:
                latest_pivot_high = h[new_pivot]
                active.append(Level("high", h[new_pivot], "swing", new_pivot, new_pivot + int(p["liquidity_expiry_bars"])))
            if low_flags[new_pivot]:
                latest_pivot_low = lo[new_pivot]
                active.append(Level("low", lo[new_pivot], "swing", new_pivot, new_pivot + int(p["liquidity_expiry_bars"])))
        active = [level for level in active if level.expires >= index]

        if position:
            if position == 1 and lo[index] <= stop:
                close_trade(index, stop, "stop")
            elif position == -1 and h[index] >= stop:
                close_trade(index, stop, "stop")
            elif position == 1 and h[index] >= target:
                close_trade(index, target, "target")
            elif position == -1 and lo[index] <= target:
                close_trade(index, target, "target")
            elif index - entry_index >= int(p["max_holding_bars"]):
                close_trade(index, c[index], "time")
            active = [level for level in active if not ((level.side == "high" and h[index] >= level.price) or (level.side == "low" and lo[index] <= level.price))]
            equity = cash + (qty * (c[index] - entry) * position if position else 0.0)
            peak_equity = max(peak_equity, equity)
            max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity if peak_equity else 0.0)
            continue

        if phase == "wait_entry":
            invalid = (direction == 1 and lo[index] <= pending_stop) or (direction == -1 and h[index] >= pending_stop)
            target_first = (direction == 1 and h[index] >= pending_target) or (direction == -1 and lo[index] <= pending_target)
            filled = (direction == 1 and lo[index] <= pending_entry) or (direction == -1 and h[index] >= pending_entry)
            if index > pending_expiry or invalid or target_first:
                if index > pending_expiry:
                    diagnostics["pending_expired"] += 1
                elif invalid:
                    diagnostics["pending_invalidated"] += 1
                else:
                    diagnostics["pending_target_first"] += 1
                phase = "idle"
            elif filled and ts.iloc[index] >= signal_start:
                diagnostics["pending_filled"] += 1
                position = direction
                entry, stop, target = pending_entry, pending_stop, pending_target
                risk_distance = abs(entry - stop)
                risk_notional = cash * float(p["risk_per_trade"]) * entry / risk_distance
                notional = min(risk_notional, cash * float(p["max_position_leverage"]))
                qty = notional / entry
                entry_fee = notional * commission
                cash -= entry_fee
                entry_index = index
                phase = "position"
                active = [level for level in active if not ((level.side == "high" and h[index] >= level.price) or (level.side == "low" and lo[index] <= level.price))]
                continue

        context_pos = context_index[index]
        bias = int(htf_bias[context_pos]) if context_pos >= 0 else 0
        midpoint = float(htf_midpoint[context_pos]) if context_pos >= 0 else np.nan

        if phase == "wait_mss":
            setup_age += 1
            invalid = bias != direction or (direction == 1 and lo[index] < sweep_extreme) or (direction == -1 and h[index] > sweep_extreme)
            if invalid or setup_age > int(p["mss_wait_bars"]):
                phase = "idle"
            elif index >= 2 and np.isfinite(atr_values[index - 1]) and atr_values[index - 1] > 0:
                prior_atr = atr_values[index - 1]
                bar_range = h[index] - lo[index]
                body_ratio = abs(c[index] - o[index]) / bar_range if bar_range > 0 else 0
                if direction == 1:
                    mss = c[index] > structure_level
                    close_ok = (h[index] - c[index]) / bar_range <= float(p["close_extreme_fraction"]) if bar_range else False
                    gap_low, gap_high = h[index - 2], lo[index]
                else:
                    mss = c[index] < structure_level
                    close_ok = (c[index] - lo[index]) / bar_range <= float(p["close_extreme_fraction"]) if bar_range else False
                    gap_low, gap_high = h[index], lo[index - 2]
                valid_fvg = gap_high > gap_low and gap_high - gap_low >= float(p["min_fvg_atr"]) * prior_atr
                displacement = bar_range >= float(p["displacement_atr"]) * prior_atr and body_ratio >= float(p["min_body_ratio"])
                if mss:
                    diagnostics["mss"] += 1
                if mss and close_ok and displacement:
                    diagnostics["mss_displacement"] += 1
                if mss and close_ok and valid_fvg and displacement:
                    diagnostics["mss_fvg"] += 1
                if mss and close_ok and valid_fvg and displacement:
                    candidate_entry = (gap_low + gap_high) / 2
                    candidate_stop = sweep_extreme - float(p["stop_buffer_atr"]) * sweep_atr * direction
                    if direction == 1:
                        targets = [level.price for level in active if level.side == "high" and level.price > h[index]]
                        candidate_target = min(targets) if targets else 0.0
                    else:
                        targets = [level.price for level in active if level.side == "low" and level.price < lo[index]]
                        candidate_target = max(targets) if targets else 0.0
                    risk = abs(candidate_entry - candidate_stop)
                    reward = abs(candidate_target - candidate_entry) if candidate_target else 0.0
                    if candidate_target and risk > 0 and reward / risk >= float(p["minimum_rr"]):
                        diagnostics["pending_created"] += 1
                        phase = "wait_entry"
                        pending_entry, pending_stop, pending_target = candidate_entry, candidate_stop, candidate_target
                        pending_expiry = index + int(p["entry_expiry_bars"])
                    else:
                        diagnostics["target_or_rr_rejected"] += 1
                        phase = "idle"

        if phase == "idle" and bias and np.isfinite(midpoint) and np.isfinite(atr_values[index - 1] if index else np.nan):
            discount_ok = not bool(p["premium_discount_filter"]) or (bias == 1 and c[index] <= midpoint) or (bias == -1 and c[index] >= midpoint)
            prior_atr = atr_values[index - 1] if index else np.nan
            if discount_ok and prior_atr > 0:
                if bias == 1 and latest_pivot_high is not None:
                    candidates = [level for level in active if level.side == "low" and lo[index] < level.price < c[index] and float(p["min_sweep_atr"]) <= (level.price-lo[index])/prior_atr <= float(p["max_sweep_atr"])]
                    swept = max(candidates, key=lambda item: item.price, default=None)
                    opposing = latest_pivot_high
                elif bias == -1 and latest_pivot_low is not None:
                    candidates = [level for level in active if level.side == "high" and h[index] > level.price > c[index] and float(p["min_sweep_atr"]) <= (h[index]-level.price)/prior_atr <= float(p["max_sweep_atr"])]
                    swept = min(candidates, key=lambda item: item.price, default=None)
                    opposing = latest_pivot_low
                else:
                    swept = None
                    opposing = None
                if swept is not None and opposing is not None:
                    phase = "wait_mss"
                    direction = bias
                    sweep_extreme = lo[index] if bias == 1 else h[index]
                    sweep_atr = prior_atr
                    structure_level = float(opposing)
                    sweep_index = index
                    setup_age = 0
                    setup_time = ts.iloc[index].isoformat()
                    setups += 1

        active = [level for level in active if not ((level.side == "high" and h[index] >= level.price) or (level.side == "low" and lo[index] <= level.price))]
        equity = cash
        peak_equity = max(peak_equity, equity)
        max_drawdown = max(max_drawdown, (peak_equity - equity) / peak_equity if peak_equity else 0.0)

    if position:
        close_trade(len(ltf) - 1, c[-1], "end")

    wins = [trade for trade in trades if trade.net_pnl > 0]
    losses = [trade for trade in trades if trade.net_pnl <= 0]
    gross_profit = sum(trade.net_pnl for trade in wins)
    gross_loss = -sum(trade.net_pnl for trade in losses)
    return {
        "symbol": symbol,
        "start": start,
        "end": end,
        "initial_cash": initial_cash,
        "final_cash": cash,
        "return_pct": (cash / initial_cash - 1) * 100,
        "max_drawdown_pct": max_drawdown * 100,
        "setups": setups,
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": len(wins) / len(trades) * 100 if trades else 0.0,
        "profit_factor": gross_profit / gross_loss if gross_loss else (999.0 if gross_profit else 0.0),
        "fees": sum(trade.fees for trade in trades),
        "funding": sum(trade.funding for trade in trades),
        "diagnostics": diagnostics,
        "params": p,
        "trade_details": [asdict(trade) for trade in trades],
    }


def candidate_grid(stage: int) -> list[dict[str, Any]]:
    """Broad in stage 1, progressively local in later stages."""
    if stage == 1:
        axes = {
            "max_sweep_atr": [0.75, 1.0],
            "mss_wait_bars": [8, 12],
            "displacement_atr": [0.8, 1.0, 1.2, 1.5],
            "min_body_ratio": [0.45, 0.60],
            "minimum_rr": [1.5, 2.0],
            "max_holding_bars": [32, 48],
        }
        structural_profiles = [
            {"htf_pivot_left": 1, "htf_pivot_right": 1, "ltf_pivot_left": 2, "ltf_pivot_right": 2},
            {"htf_pivot_left": 2, "htf_pivot_right": 2, "ltf_pivot_left": 2, "ltf_pivot_right": 2},
            {"htf_pivot_left": 2, "htf_pivot_right": 2, "ltf_pivot_left": 3, "ltf_pivot_right": 3},
        ]
    else:
        axes = {
            "max_sweep_atr": [0.75, 1.0],
            "mss_wait_bars": [8, 12],
            "displacement_atr": [0.8, 1.0, 1.2],
            "min_body_ratio": [0.45, 0.55],
            "minimum_rr": [1.5, 2.0],
            "max_holding_bars": [32, 48],
            "entry_expiry_bars": [8, 12],
        }
        structural_profiles = [{}]
    keys = list(axes)
    combinations = [dict(zip(keys, values)) for values in itertools.product(*(axes[key] for key in keys))]
    return [{**profile, **combination} for profile in structural_profiles for combination in combinations]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", type=int, choices=[1, 2, 3], required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--symbols", default="BTCUSDT,ETHUSDT,SOLUSDT")
    parser.add_argument("--params", help="JSON object; bypasses the grid")
    parser.add_argument("--params-base64", help="Base64-encoded JSON object; Windows-shell-safe")
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    symbols = [item.strip().upper() for item in args.symbols.split(",") if item.strip()]
    if args.params_base64:
        candidates = [json.loads(base64.b64decode(args.params_base64).decode("utf-8"))]
    elif args.params:
        candidates = [json.loads(args.params)]
    else:
        candidates = candidate_grid(args.stage)
    ranked: list[dict[str, Any]] = []
    for number, candidate in enumerate(candidates, 1):
        results = [run_backtest(symbol, args.start, args.end, candidate) for symbol in symbols]
        best_return = max(result["return_pct"] for result in results)
        score = best_return - 0.25 * max(result["max_drawdown_pct"] for result in results)
        ranked.append({"score": score, "best_return_pct": best_return, "candidate": candidate, "results": results})
        if number % 100 == 0 or number == len(candidates):
            print(f"stage={args.stage} {number}/{len(candidates)} best={max(item['best_return_pct'] for item in ranked):.2f}%", flush=True)
    ranked.sort(key=lambda item: (item["score"], item["best_return_pct"]), reverse=True)
    payload = {
        "stage": args.stage,
        "start": args.start,
        "end": args.end,
        "commission": 0.0004,
        "funding_rate_per_8h": 0.0001,
        "candidate_count": len(candidates),
        "top": ranked[:args.top],
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "output": str(output),
        "best_return_pct": ranked[0]["best_return_pct"],
        "best_candidate": ranked[0]["candidate"],
        "results": [{k: v for k, v in result.items() if k != "trade_details"} for result in ranked[0]["results"]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
