#!/usr/bin/env python
"""Plot OBV-ATR backtest: candlestick price + equity curve for ETH and SOL."""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import pandas as pd

ETH_EQUITY = "./benchmark/backtest_obv_atr_ETHUSDT_equity.csv"
SOL_EQUITY = "./benchmark/backtest_obv_atr_SOLUSDT_equity.csv"
PRICE_DIR = Path("./data/klines")
OUTPUT = "./benchmark/obv_atr_price_equity.png"


def load_daily_price(symbol: str, start: str, end: str) -> pd.DataFrame:
    """Load per-day 1d CSVs and concatenate into one DataFrame."""
    src_dir = PRICE_DIR / symbol / "1d"
    dates = pd.date_range(start, end, freq="D")
    frames = []
    for d in dates:
        f = src_dir / f"{symbol}-1d-{d.strftime('%Y-%m-%d')}.csv"
        if f.exists():
            df = pd.read_csv(f, usecols=["timestamp", "open", "high", "low", "close"])
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    result = pd.concat(frames, ignore_index=True)
    result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True)
    result["date"] = result["timestamp"].dt.tz_localize(None).dt.normalize()
    return result.sort_values("date").reset_index(drop=True)


def fill_equity_daily(equity_df: pd.DataFrame) -> pd.DataFrame:
    """Fill equity data to daily frequency using forward fill."""
    equity_df = equity_df.copy()
    equity_df["date"] = pd.to_datetime(equity_df["date"]).dt.normalize()
    min_date = equity_df["date"].min()
    max_date = equity_df["date"].max()
    all_dates = pd.date_range(min_date, max_date, freq="D")
    filled = equity_df.set_index("date").reindex(all_dates)
    filled["equity"] = filled["equity"].ffill()
    filled["cash"] = filled["cash"].ffill() if "cash" in filled.columns else filled["equity"]
    filled = filled.reset_index().rename(columns={"index": "date"})
    filled["date"] = pd.to_datetime(filled["date"]).dt.normalize()
    return filled


def draw_candlesticks(
    ax: plt.Axes,
    df: pd.DataFrame,
    width: float = 0.6,
) -> None:
    """Draw candlestick chart on the given axes."""
    for _, row in df.iterrows():
        date = mdates.date2num(row["date"])
        o, h, l, c = row["open"], row["high"], row["low"], row["close"]
        color = "#26a69a" if c >= o else "#ef5350"
        body_bottom = min(o, c)
        body_height = abs(c - o)
        ax.plot([date, date], [l, h], color=color, linewidth=0.6)
        rect = Rectangle(
            (date - width / 2, body_bottom), width, body_height,
            facecolor=color, edgecolor=color, linewidth=0.5,
        )
        ax.add_patch(rect)


def main() -> None:
    eth_eq = pd.read_csv(ETH_EQUITY, parse_dates=["date"])
    sol_eq = pd.read_csv(SOL_EQUITY, parse_dates=["date"])

    eth_eq = fill_equity_daily(eth_eq)
    sol_eq = fill_equity_daily(sol_eq)

    start, end = "2025-01-01", "2026-03-31"

    print("Loading ETH 1d price...")
    eth_price = load_daily_price("ETHUSDT", start, end)
    print(f"  ETH price: {len(eth_price)} days")

    print("Loading SOL 1d price...")
    sol_price = load_daily_price("SOLUSDT", start, end)
    print(f"  SOL price: {len(sol_price)} days")

    eth_merged = pd.merge(eth_eq, eth_price, on="date", how="inner")
    sol_merged = pd.merge(sol_eq, sol_price, on="date", how="inner")
    print(f"  ETH merged: {len(eth_merged)} rows")
    print(f"  SOL merged: {len(sol_merged)} rows")

    fig, axes = plt.subplots(2, 1, figsize=(18, 12))
    fig.patch.set_facecolor("white")

    datasets = [
        (axes[0], eth_merged, "ETHUSDT"),
        (axes[1], sol_merged, "SOLUSDT"),
    ]

    for ax, merged, symbol in datasets:
        ax.set_facecolor("#fafafa")
        ax2 = ax.twinx()

        draw_candlesticks(ax, merged)
        ax.set_ylabel("Price (USDT)")
        price_min = merged["low"].min()
        price_max = merged["high"].max()
        price_margin = (price_max - price_min) * 0.05
        ax.set_ylim(price_min - price_margin, price_max + price_margin)
        ax.set_xlim(
            mdates.date2num(merged["date"].min()) - 1,
            mdates.date2num(merged["date"].max()) + 1,
        )

        ax2.plot(
            merged["date"], merged["equity"],
            color="#1565c0", linewidth=1.8, label="Strategy Equity",
        )
        ax2.fill_between(
            merged["date"], merged["equity"].iloc[0], merged["equity"],
            alpha=0.08, color="#1565c0",
        )
        ax2.set_ylabel("Equity (USDT)", color="#1565c0")
        ax2.tick_params(axis="y", labelcolor="#1565c0")

        eq_start = merged["equity"].iloc[0]
        eq_end = merged["equity"].iloc[-1]
        ret_pct = (eq_end / eq_start - 1) * 100
        ax.set_title(
            f"OBV-ATR Strategy: {symbol}  |  Equity {eq_start:,.0f} → {eq_end:,.0f}  ({ret_pct:+.1f}%)",
            fontsize=13, fontweight="bold",
        )

        from matplotlib.lines import Line2D
        legend_elements = [
            Line2D([0], [0], color="#26a69a", lw=6, label="Bullish candle"),
            Line2D([0], [0], color="#ef5350", lw=6, label="Bearish candle"),
            Line2D([0], [0], color="#1565c0", lw=2, label="Strategy Equity"),
        ]
        ax.legend(handles=legend_elements, loc="upper left", fontsize=9)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
        ax.xaxis.set_minor_locator(mdates.MonthLocator())
        ax.grid(True, alpha=0.2, linestyle="--")
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha="right")

    plt.tight_layout()
    plt.savefig(OUTPUT, dpi=150, bbox_inches="tight")
    print(f"\nSaved: {OUTPUT}")


if __name__ == "__main__":
    main()
