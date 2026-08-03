"""数据加载器 - K 线数据和交易数据"""

import logging
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

logger = logging.getLogger(__name__)


def load_kline_data(symbol: str, kline_dir: str, start: str, end: str, interval: str = "15m") -> pd.DataFrame:
    """加载 K 线数据"""
    kline_file = Path(kline_dir) / f"{symbol}_{interval}.csv"
    if not kline_file.exists():
        raise FileNotFoundError(f"K 线文件不存在: {kline_file}")

    kline = pd.read_csv(kline_file)
    kline["timestamp"] = pd.to_datetime(kline["timestamp"]).dt.tz_localize(None)
    start_dt = pd.to_datetime(start.replace("-", "") if "-" in start else start)
    end_dt = pd.to_datetime(end.replace("-", "") if "-" in end else end)
    filtered = kline[(kline["timestamp"] >= start_dt) & (kline["timestamp"] <= end_dt)].copy()
    logger.info(f"加载 K 线数据: {len(filtered)} 条 ({start} ~ {end})")
    return filtered


def load_trade_data(backtest_dir: str, start: str, end: str) -> List[Dict[str, Any]]:
    """加载回测交易数据并配对"""
    trades_file = Path(backtest_dir) / "backtest_trades.csv"
    if not trades_file.exists():
        logger.warning(f"交易文件不存在: {trades_file}")
        return []

    trades_df = pd.read_csv(trades_file)
    trades_df["timestamp"] = pd.to_datetime(trades_df["timestamp"]).dt.tz_localize(None)
    start_dt = pd.to_datetime(start.replace("-", "") if "-" in start else start)
    end_dt = pd.to_datetime(end.replace("-", "") if "-" in end else end)
    trades_period = trades_df[(trades_df["timestamp"] >= start_dt) & (trades_df["timestamp"] <= end_dt)].copy()

    trade_pairs = []
    trades_list = trades_period.sort_values("timestamp").to_dict("records")
    i = 0
    while i < len(trades_list):
        t = trades_list[i]
        if t["side"] == "BUY":
            for j in range(i + 1, len(trades_list)):
                if trades_list[j]["side"] == "SELL_CLOSE":
                    trade_pairs.append({"entry_time": t["timestamp"], "entry_price": t["price"],
                        "exit_time": trades_list[j]["timestamp"], "exit_price": trades_list[j]["price"],
                        "pnl": trades_list[j]["pnl"], "type": "LONG"})
                    break
        elif t["side"] == "SELL":
            for j in range(i + 1, len(trades_list)):
                if trades_list[j]["side"] == "BUY_CLOSE":
                    trade_pairs.append({"entry_time": t["timestamp"], "entry_price": t["price"],
                        "exit_time": trades_list[j]["timestamp"], "exit_price": trades_list[j]["price"],
                        "pnl": trades_list[j]["pnl"], "type": "SHORT"})
                    break
        i += 1
    logger.info(f"加载交易数据: {len(trade_pairs)} 对")
    return trade_pairs