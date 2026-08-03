#!/usr/bin/env python3
"""
回测信号标注 K 线图生成器

生成 K 线蜡烛图，标注买卖信号，显示权益曲线。
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

COLORS = {
    "bull_body": "#26A69A",
    "bear_body": "#EF5350",
    "bull_edge": "#00897B",
    "bear_edge": "#C62828",
    "buy_marker": "#00C853",
    "sell_marker": "#FF1744",
    "close_long": "#FF9800",
    "close_short": "#2196F3",
    "trade_win": "#00C853",
    "trade_loss": "#FF1744",
    "equity_line": "#1565C0",
    "grid": "#E0E0E0",
}


def generate_backtest_chart(
    df_kline: pd.DataFrame,
    signals: list,
    trades: List[Dict[str, Any]],
    daily_equity: List[Dict[str, Any]],
    symbol: str,
    strategy_name: str,
    output_path: str,
    timeframe: str = "1h",
) -> str:
    """
    生成回测信号标注 K 线图。

    Args:
        df_kline: K 线 DataFrame (timestamp, open, high, low, close, volume)
        signals: Signal 对象列表
        trades: 配对交易列表 (entry_price, exit_price, entry_time, exit_time, pnl_pct, direction)
        daily_equity: 日权益曲线 [{date, equity}]
        symbol: 交易对
        strategy_name: 策略名称
        output_path: 输出文件路径
        timeframe: K 线时间框架

    Returns:
        输出文件路径
    """
    plt.rcParams["font.sans-serif"] = ["Arial", "DejaVu Sans", "sans-serif"]
    plt.rcParams["axes.unicode_minus"] = False

    df = df_kline.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)

    fig, (ax_price, ax_equity) = plt.subplots(
        2, 1, figsize=(24, 14),
        gridspec_kw={"height_ratios": [3, 1], "hspace": 0.15},
    )

    fig.suptitle(
        f"{symbol} {strategy_name} Backtest — {timeframe} ({df['timestamp'].iloc[0].strftime('%Y-%m-%d')} ~ {df['timestamp'].iloc[-1].strftime('%Y-%m-%d')})",
        fontsize=16, fontweight="bold",
    )

    _plot_candlesticks(ax_price, df)
    _plot_signals(ax_price, df, signals)
    _plot_trades(ax_price, df, trades)
    _plot_equity(ax_equity, daily_equity)

    _setup_x_axis(ax_price, df)
    _setup_x_axis_equity(ax_equity, daily_equity)

    ax_price.set_ylabel("Price (USDT)", fontsize=12)
    ax_price.grid(True, alpha=0.3, color=COLORS["grid"])
    ax_price.legend(loc="upper left", fontsize=9, framealpha=0.8)

    ax_equity.set_ylabel("Equity", fontsize=12)
    ax_equity.set_xlabel("Date", fontsize=12)
    ax_equity.grid(True, alpha=0.3, color=COLORS["grid"])

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    logger.info(f"图表已保存: {output_path}")
    return output_path


def _plot_candlesticks(ax, df: pd.DataFrame):
    """绘制 K 线蜡烛图"""
    n = len(df)
    width = max(0.4, min(0.8, 200 / n))

    for i, (_, row) in enumerate(df.iterrows()):
        o, h, lo, c = row["open"], row["high"], row["low"], row["close"]
        is_bull = c >= o

        body_color = COLORS["bull_body"] if is_bull else COLORS["bear_body"]
        edge_color = COLORS["bull_edge"] if is_bull else COLORS["bear_edge"]

        ax.plot([i, i], [lo, h], color=edge_color, linewidth=0.8, alpha=0.8)

        body_bottom = min(o, c)
        body_height = abs(c - o) or (h - lo) * 0.01
        rect = plt.Rectangle(
            (i - width / 2, body_bottom), width, body_height,
            facecolor=body_color, edgecolor=edge_color, linewidth=0.5,
        )
        ax.add_patch(rect)

    ax.set_xlim(-1, n)


def _plot_signals(ax, df: pd.DataFrame, signals: list):
    """在 K 线图上标注信号"""
    if not signals:
        return

    ts_index = df["timestamp"].values

    buy_x, buy_y = [], []
    sell_x, sell_y = [], []
    close_long_x, close_long_y = [], []
    close_short_x, close_short_y = [], []

    for sig in signals:
        sig_ts = pd.Timestamp(sig.timestamp).tz_localize("UTC") if sig.timestamp.tzinfo is None else pd.Timestamp(sig.timestamp)
        idx = _find_nearest_index(ts_index, sig_ts)
        if idx is None:
            continue

        action = sig.signal_type.value
        price = sig.price
        price_range = df["high"].max() - df["low"].min()
        offset = price_range * 0.015

        if action == "buy":
            buy_x.append(idx)
            buy_y.append(price - offset)
        elif action == "sell":
            sell_x.append(idx)
            sell_y.append(price + offset)
        elif action == "sell_close":
            close_long_x.append(idx)
            close_long_y.append(price + offset)
        elif action == "buy_close":
            close_short_x.append(idx)
            close_short_y.append(price - offset)

    if buy_x:
        ax.scatter(buy_x, buy_y, marker="^", color=COLORS["buy_marker"],
                   s=80, zorder=5, label="BUY", edgecolors="black", linewidths=0.5)
    if sell_x:
        ax.scatter(sell_x, sell_y, marker="v", color=COLORS["sell_marker"],
                   s=80, zorder=5, label="SELL", edgecolors="black", linewidths=0.5)
    if close_long_x:
        ax.scatter(close_long_x, close_long_y, marker="x", color=COLORS["close_long"],
                   s=60, zorder=5, label="SELL_CLOSE", linewidths=2)
    if close_short_x:
        ax.scatter(close_short_x, close_short_y, marker="x", color=COLORS["close_short"],
                   s=60, zorder=5, label="BUY_CLOSE", linewidths=2)


def _plot_trades(ax, df: pd.DataFrame, trades: List[Dict[str, Any]]):
    """用虚线连接配对的开仓→平仓"""
    if not trades:
        return

    ts_index = df["timestamp"].values

    for tr in trades:
        entry_ts = pd.Timestamp(tr["entry_time"])
        exit_ts = pd.Timestamp(tr["exit_time"])
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.tz_localize("UTC")
        if exit_ts.tzinfo is None:
            exit_ts = exit_ts.tz_localize("UTC")

        entry_idx = _find_nearest_index(ts_index, entry_ts)
        exit_idx = _find_nearest_index(ts_index, exit_ts)
        if entry_idx is None or exit_idx is None:
            continue

        is_win = tr.get("pnl_pct", 0) > 0
        color = COLORS["trade_win"] if is_win else COLORS["trade_loss"]

        ax.plot(
            [entry_idx, exit_idx],
            [tr["entry_price"], tr["exit_price"]],
            color=color, linestyle="--", linewidth=1, alpha=0.6,
        )


def _plot_equity(ax, daily_equity: List[Dict[str, Any]]):
    """绘制权益曲线"""
    if not daily_equity:
        return

    dates = [d["date"] for d in daily_equity]
    equities = [d["equity"] for d in daily_equity]

    ax.plot(range(len(dates)), equities, color=COLORS["equity_line"], linewidth=1.5)
    ax.fill_between(range(len(dates)), equities, equities[0],
                     where=[e >= equities[0] for e in equities],
                     alpha=0.15, color=COLORS["trade_win"])
    ax.fill_between(range(len(dates)), equities, equities[0],
                     where=[e < equities[0] for e in equities],
                     alpha=0.15, color=COLORS["trade_loss"])

    num_ticks = min(12, len(dates))
    if num_ticks > 0:
        step = max(1, len(dates) // num_ticks)
        positions = list(range(0, len(dates), step))
        labels = [_format_date(dates[i]) for i in positions]
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)


def _format_date(date_val) -> str:
    """格式化日期显示为年-月-日格式"""
    if isinstance(date_val, str):
        try:
            dt = pd.to_datetime(date_val)
            return dt.strftime("%Y-%m-%d")
        except:
            return date_val
    elif isinstance(date_val, (pd.Timestamp, datetime)):
        return date_val.strftime("%Y-%m-%d")
    else:
        return str(date_val)


def _setup_x_axis(ax, df: pd.DataFrame):
    """设置价格图 X 轴"""
    n = len(df)
    num_ticks = min(20, n)
    if num_ticks > 0:
        step = max(1, n // num_ticks)
        positions = list(range(0, n, step))
        labels = [df.iloc[i]["timestamp"].strftime("%m-%d %H:%M") for i in positions]
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)


def _setup_x_axis_equity(ax, daily_equity: List[Dict[str, Any]]):
    """权益图 X 轴已在 _plot_equity 中设置"""
    pass


def _find_nearest_index(ts_array: np.ndarray, target_ts: pd.Timestamp) -> Optional[int]:
    """找到最接近目标时间戳的索引"""
    target = np.datetime64(target_ts)
    diffs = np.abs(ts_array - target)
    min_idx = int(np.argmin(diffs))
    min_diff = diffs[min_idx]
    if min_diff > np.timedelta64(2, "h"):
        return None
    return min_idx
