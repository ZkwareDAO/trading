#!/usr/bin/env python
"""Resample per-day 1m K-line CSVs into 5m/15m/30m/1h/4h/1d per-day CSVs.

Usage:
    python scripts/resample_1m_to_multi_tf.py
    python scripts/resample_1m_to_multi_tf.py --symbol BTCUSDT
    python scripts/resample_1m_to_multi_tf.py --symbol BTCUSDT,ETHUSDT --timeframes 5m,1h,1d
    python scripts/resample_1m_to_multi_tf.py --force
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

BINANCE_1M_COLUMNS = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
    "ignore",
]

OUTPUT_COLUMNS = [
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "quote_volume",
    "count",
    "taker_buy_volume",
    "taker_buy_quote_volume",
]

RESAMPLE_FREQ = {
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}

EPOCH_ORIGIN_TFS = {"4h", "2h", "6h", "8h", "12h"}

DEFAULT_TIMEFRAMES = ["5m", "15m", "30m", "1h", "4h", "1d"]
DATA_DIR = Path("./data/klines")


def read_1m_daily_csv(path: Path) -> pd.DataFrame:
    """Read a Binance 1m daily CSV (with or without header) into a DataFrame."""
    df = pd.read_csv(path, header=None)
    if str(df.iloc[0, 0]).strip() == "open_time":
        df = df.iloc[1:].reset_index(drop=True)

    df.columns = BINANCE_1M_COLUMNS[: len(df.columns)]
    df["open_time"] = pd.to_numeric(df["open_time"], errors="coerce")
    df = df.dropna(subset=["open_time"])
    df["timestamp"] = pd.to_datetime(df["open_time"].astype(int), unit="ms", utc=True)
    keep = ["timestamp", "open", "high", "low", "close", "volume",
            "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume"]
    keep = [c for c in keep if c in df.columns]
    df = df[keep]
    numeric_cols = ["open", "high", "low", "close", "volume",
                    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume"]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("timestamp").reset_index(drop=True)


def resample_df(df: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Resample a 1m DataFrame to the target timeframe."""
    freq = RESAMPLE_FREQ[tf]
    indexed = df.set_index("timestamp")

    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "quote_volume": "sum",
        "count": "sum",
        "taker_buy_volume": "sum",
        "taker_buy_quote_volume": "sum",
    }

    if tf in EPOCH_ORIGIN_TFS:
        resampled = indexed.resample(freq, origin="epoch").agg(agg)
    else:
        resampled = indexed.resample(freq).agg(agg)

    resampled = resampled.dropna().reset_index()

    if resampled["timestamp"].dt.tz is None:
        resampled["timestamp"] = resampled["timestamp"].dt.tz_localize("UTC")
    else:
        resampled["timestamp"] = resampled["timestamp"].dt.tz_convert("UTC")

    return resampled


def extract_date_from_filename(filename: str) -> str:
    """Extract date part from '...-1m-YYYY-MM-DD.csv'."""
    stem = Path(filename).stem
    parts = stem.split("-1m-")
    if len(parts) == 2:
        return parts[1]
    return stem


def process_symbol(
    symbol: str,
    timeframes: list[str],
    force: bool,
) -> dict[str, int]:
    """Process all daily 1m files for one symbol."""
    src_dir = DATA_DIR / symbol / "1m"
    if not src_dir.exists():
        logger.warning(f"{src_dir} does not exist, skipping {symbol}")
        return {}

    import re
    date_pattern = re.compile(rf"^{symbol}-1m-\d{{4}}-\d{{2}}-\d{{2}}\.csv$")
    csv_files = sorted(f for f in src_dir.glob(f"{symbol}-1m-*.csv") if date_pattern.match(f.name))
    if not csv_files:
        logger.warning(f"No 1m CSV files found in {src_dir}")
        return {}

    logger.info(f"{symbol}: {len(csv_files)} daily 1m files")

    stats: dict[str, int] = {tf: 0 for tf in timeframes}

    for src_file in csv_files:
        date_str = extract_date_from_filename(src_file.name)
        try:
            df = read_1m_daily_csv(src_file)
        except Exception as e:
            logger.warning(f"  Skip {src_file.name}: {e}")
            continue

        if df.empty:
            continue

        for tf in timeframes:
            out_dir = DATA_DIR / symbol / tf
            out_dir.mkdir(parents=True, exist_ok=True)
            out_file = out_dir / f"{symbol}-{tf}-{date_str}.csv"

            if out_file.exists() and not force:
                stats[tf] += 1
                continue

            resampled = resample_df(df, tf)
            if resampled.empty:
                continue

            resampled.to_csv(out_file, index=False)
            stats[tf] += 1

    for tf, count in stats.items():
        logger.info(f"  {tf}: {count} files")

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Resample 1m daily CSVs to multi-timeframe")
    parser.add_argument(
        "--symbol",
        default="BTCUSDT,ETHUSDT,SOLUSDT",
        help="Symbols, comma-separated (default: BTCUSDT,ETHUSDT,SOLUSDT)",
    )
    parser.add_argument(
        "--timeframes",
        default=",".join(DEFAULT_TIMEFRAMES),
        help="Target timeframes, comma-separated (default: 5m,15m,30m,1h,4h,1d)",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    symbols = [s.strip().upper() for s in args.symbol.split(",") if s.strip()]
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]

    invalid = [t for t in timeframes if t not in RESAMPLE_FREQ]
    if invalid:
        logger.error(f"Unsupported timeframes: {invalid}. Supported: {list(RESAMPLE_FREQ.keys())}")
        sys.exit(1)

    for sym in symbols:
        logger.info(f"=== {sym} ===")
        process_symbol(sym, timeframes, args.force)

    logger.info("Done.")


if __name__ == "__main__":
    main()
