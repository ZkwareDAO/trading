#!/usr/bin/env python3
"""
为 dolphin_trading 回测准备多币对多时间框架数据

时间范围：2025-01-01 ~ 2026-03-31（含预热缓冲）
币对：BTCUSDT, ETHUSDT, SOLUSDT
时间框架：1m, 15m, 1h, 4h
"""

import sys
from pathlib import Path
from datetime import datetime
import concurrent.futures

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_manager.klines_loader import read_binance_klines_csv, transform_binance_klines, resample_ohlcv

SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
PRELOAD_START = datetime(2024, 12, 1)
START_DATE = datetime(2025, 1, 1)
END_DATE = datetime(2026, 3, 31)
TIMEFRAMES_TO_RESAMPLE = ["15m", "1h", "4h"]
SOURCE_DIR = Path("./data/klines")
OUTPUT_DIR = Path("./data/strategies")


def load_daily_file(filepath: Path):
    try:
        df = read_binance_klines_csv(filepath)
        df = transform_binance_klines(df, "timestamp")
        return df
    except Exception as e:
        print(f"  WARN: {filepath.name}: {e}")
        return None


def load_1m_data(symbol: str) -> pd.DataFrame:
    timeframe_dir = SOURCE_DIR / symbol / "1m"
    if not timeframe_dir.exists():
        print(f"  ERROR: {timeframe_dir} 不存在")
        return pd.DataFrame()

    daily_files = []
    current = PRELOAD_START
    while current <= END_DATE:
        date_str = current.strftime("%Y-%m-%d")
        daily_file = timeframe_dir / f"{symbol}-1m-{date_str}.csv"
        if daily_file.exists():
            daily_files.append(daily_file)
        current += pd.Timedelta(days=1)

    print(f"  找到 {len(daily_files)} 个每日文件")

    all_dfs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(load_daily_file, f): f for f in daily_files}
        for future in concurrent.futures.as_completed(futures):
            df = future.result()
            if df is not None and not df.empty:
                all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    combined = combined.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    combined = combined.reset_index(drop=True)
    print(f"  合并 {len(combined):,} 条 1m 记录")
    return combined


def save_csv(df: pd.DataFrame, symbol: str, timeframe: str):
    out_dir = OUTPUT_DIR / timeframe
    out_dir.mkdir(parents=True, exist_ok=True)
    filepath = out_dir / f"{symbol}_{timeframe}.csv"

    df_out = df[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    df_out["timestamp"] = df_out["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S+00:00")
    df_out.to_csv(filepath, index=False)
    print(f"  保存 {filepath} ({len(df_out):,} 条)")


def process_symbol(symbol: str):
    print(f"\n{'='*50}")
    print(f"处理 {symbol}")
    print(f"{'='*50}")

    df_1m = load_1m_data(symbol)
    if df_1m.empty:
        print(f"  ERROR: {symbol} 无数据")
        return

    save_csv(df_1m, symbol, "1m")

    for tf in TIMEFRAMES_TO_RESAMPLE:
        print(f"  重采样 → {tf}...")
        df_tf = resample_ohlcv(df_1m, tf, datetime_column="timestamp")
        print(f"    {len(df_tf):,} 条")
        save_csv(df_tf, symbol, tf)


def main():
    print("dolphin_trading 回测数据准备")
    print(f"范围: {PRELOAD_START.date()} ~ {END_DATE.date()} (含预热)")
    print(f"币对: {SYMBOLS}")

    for symbol in SYMBOLS:
        process_symbol(symbol)

    print(f"\n{'='*50}")
    print("完成！")


if __name__ == "__main__":
    main()
