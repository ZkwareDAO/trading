#!/usr/bin/env python3
"""
Merge daily 1m K-line CSV files and aggregate to the target timeframe.

Usage:
    python merge_klines.py --symbol BTCUSDT --start 2026-01-01 --end 2026-01-31 --timeframe 1h
"""

import argparse
from datetime import date, datetime
from pathlib import Path

import pandas as pd


# Binance kline column layout for the raw daily 1m CSV files
_RAW_COLUMNS = [
    'timestamp', 'open', 'high', 'low', 'close', 'volume',
    'close_time', 'quote_volume', 'count',
    'taker_buy_volume', 'taker_buy_quote_volume', 'ignore',
]

# Map user-facing timeframe -> pandas resample rule
_RESAMPLE_RULE = {
    '1m': '1min',
    '3m': '3min',
    '5m': '5min',
    '15m': '15min',
    '30m': '30min',
    '1h': '1h',
    '2h': '2h',
    '4h': '4h',
    '6h': '6h',
    '8h': '8h',
    '12h': '12h',
    '1d': '1D',
}


def _parse_date(text: str) -> date:
    """Accept YYYY-MM-DD or YYYYMMDD."""
    for fmt in ('%Y-%m-%d', '%Y%m%d'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"Invalid date '{text}', expected YYYY-MM-DD or YYYYMMDD"
    )


def _read_daily_csv(filepath: Path) -> pd.DataFrame:
    """Read a single daily 1m file, auto-detecting whether it has a header.

    Binance-style dumps come in two shapes across the archive:
      - headerless: first byte is a millisecond timestamp digit
      - with header: first line is "open_time,open,high,..."
    """
    with filepath.open('r', encoding='utf-8') as f:
        first = f.readline().strip()

    first_field = first.split(',', 1)[0]
    has_header = not first_field.lstrip('-').isdigit()

    if has_header:
        df = pd.read_csv(filepath)
        # Normalize the leading column name so both shapes share _RAW_COLUMNS
        df = df.rename(columns={'open_time': 'timestamp'})
        # Reorder / restrict to the canonical layout
        df = df[[c for c in _RAW_COLUMNS if c in df.columns]]
    else:
        df = pd.read_csv(filepath, header=None)
        df.columns = _RAW_COLUMNS

    # Coerce numeric columns; header-detection failures surface as NaN and are dropped
    df['timestamp'] = pd.to_numeric(df['timestamp'], errors='coerce')
    df = df.dropna(subset=['timestamp'])
    df['timestamp'] = df['timestamp'].astype('int64')
    return df


def _load_1m_range(symbol: str, start_date: date, end_date: date,
                   source_dir: Path) -> pd.DataFrame:
    """Load and concatenate raw 1m daily files in [start_date, end_date]."""
    all_dfs = []
    missing = 0
    current = start_date
    while current <= end_date:
        filename = f"{symbol}-1m-{current.strftime('%Y-%m-%d')}.csv"
        filepath = source_dir / filename
        if filepath.exists():
            try:
                all_dfs.append(_read_daily_csv(filepath))
            except Exception as e:
                print(f"Error reading {filepath}: {e}")
        else:
            missing += 1
            if missing <= 5:
                print(f"File not found: {filepath}")
        current += pd.Timedelta(days=1)

    if missing > 5:
        print(f"... {missing - 5} additional missing files suppressed")

    if not all_dfs:
        return pd.DataFrame(columns=_RAW_COLUMNS)

    merged = pd.concat(all_dfs, ignore_index=True)
    merged = merged.sort_values('timestamp').drop_duplicates('timestamp')
    return merged.reset_index(drop=True)


def _aggregate(df_1m: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Aggregate 1m OHLCV to the target timeframe."""
    if timeframe == '1m':
        return df_1m

    rule = _RESAMPLE_RULE.get(timeframe)
    if rule is None:
        raise ValueError(
            f"Unsupported timeframe '{timeframe}'. "
            f"Supported: {sorted(_RESAMPLE_RULE)}"
        )

    df = df_1m.copy()
    df['open_time'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    df = df.set_index('open_time')

    agg = df.resample(rule, label='left', closed='left').agg({
        'timestamp': 'first',
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'close_time': 'last',
        'quote_volume': 'sum',
        'count': 'sum',
        'taker_buy_volume': 'sum',
        'taker_buy_quote_volume': 'sum',
        'ignore': 'last',
    }).dropna(subset=['open']).reset_index(drop=True)

    # Preserve integer dtype for millisecond timestamps
    agg['timestamp'] = agg['timestamp'].astype('int64')
    agg['close_time'] = agg['close_time'].astype('int64')
    agg['count'] = agg['count'].astype('int64')
    return agg


def merge_klines(symbol: str, timeframe: str,
                 start_date: date, end_date: date,
                 source_dir: Path, output_dir: Path) -> int:
    """
    Merge 1m daily K-line files and aggregate to `timeframe`.

    Args:
        symbol: Trading pair symbol (e.g., "BTCUSDT")
        timeframe: Target timeframe (e.g., "1m", "5m", "1h", "1d")
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
        source_dir: Directory containing 1m daily files
                    (e.g., ./data/klines/BTCUSDT/1m)
        output_dir: Directory to write the merged file
                    (e.g., ./data/klines/{timeframe})

    Returns:
        Number of records written.
    """
    df_1m = _load_1m_range(symbol, start_date, end_date, source_dir)
    if df_1m.empty:
        print("No data found!")
        return 0

    merged = _aggregate(df_1m, timeframe)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{symbol}_{timeframe}.csv"
    merged.to_csv(output_file, index=False)

    print(f"Merged {len(merged)} records to {output_file}")
    return len(merged)


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge daily 1m K-line files and aggregate to a target timeframe."
    )
    parser.add_argument('--symbol', required=True,
                        help='Trading pair symbol, e.g., BTCUSDT')
    parser.add_argument('--start', required=True, type=_parse_date,
                        help='Start date (YYYY-MM-DD or YYYYMMDD)')
    parser.add_argument('--end', required=True, type=_parse_date,
                        help='End date (YYYY-MM-DD or YYYYMMDD)')
    parser.add_argument('--timeframe', required=True,
                        choices=sorted(_RESAMPLE_RULE),
                        help='Target timeframe to aggregate to')
    parser.add_argument('--data-root', default='./data/klines',
                        help='Root data directory (default: ./data/klines)')
    return parser


def main() -> None:
    args = _build_arg_parser().parse_args()

    if args.start > args.end:
        raise SystemExit(f"--start {args.start} is after --end {args.end}")

    data_root = Path(args.data_root)
    source_dir = data_root / args.symbol / '1m'
    output_dir = data_root / args.timeframe

    print("=" * 60)
    print(f"Merging {args.symbol} {args.timeframe} "
          f"from {args.start} to {args.end}")
    print(f"Source:  {source_dir}")
    print(f"Output:  {output_dir / f'{args.symbol}_{args.timeframe}.csv'}")
    print("=" * 60)

    count = merge_klines(
        symbol=args.symbol,
        timeframe=args.timeframe,
        start_date=args.start,
        end_date=args.end,
        source_dir=source_dir,
        output_dir=output_dir,
    )

    print("=" * 60)
    print(f"Merge completed! records={count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
