#!/usr/bin/env python3
"""
K线数据重采样工具 — 从 1m 数据聚合到多时间框架

使用方式:
    python -m backtest.backtest_resample --symbol BTCUSDT --start 20250101 --end 20260331
    python -m backtest.backtest_resample --symbol BTCUSDT,ETHUSDT,SOLUSDT --timeframes 5m,15m,1h,4h,1d
"""

import argparse
import logging
from datetime import datetime
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

RESAMPLE_MAP = {
    "5m": "5min",
    "15m": "15min",
    "1h": "1h",
    "4h": "4h",
    "1d": "1D",
}


def resample_1m(
    symbol: str,
    start_date: str,
    end_date: str,
    timeframes: list[str],
    data_dir: str = "./data/strategies",
) -> dict[str, Path]:
    src = Path(data_dir) / "1m" / f"{symbol}_1m.csv"
    if not src.exists():
        logger.error(f"1m 数据不存在: {src}")
        return {}

    logger.info(f"读取 {src} ...")
    df = pd.read_csv(src)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.set_index("timestamp")

    start = pd.Timestamp(datetime.strptime(start_date, "%Y%m%d"), tz="UTC")
    end = pd.Timestamp(datetime.strptime(end_date, "%Y%m%d"), tz="UTC").replace(
        hour=23, minute=59, second=59
    )
    df = df.loc[start:end]
    logger.info(f"{symbol} 1m 过滤后: {len(df)} 行 ({start.date()} ~ {end.date()})")

    if df.empty:
        logger.warning(f"{symbol} 在指定时间范围内无数据")
        return {}

    outputs: dict[str, Path] = {}
    for tf in timeframes:
        rule = RESAMPLE_MAP.get(tf)
        if not rule:
            logger.warning(f"不支持的时间框架: {tf}，跳过")
            continue

        agg = df.resample(rule).agg(
            {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
        ).dropna()

        out_dir = Path(data_dir) / tf
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{symbol}_{tf}.csv"

        agg = agg.reset_index()
        agg.to_csv(out_path, index=False)
        outputs[tf] = out_path
        logger.info(f"  {tf}: {len(agg)} 行 → {out_path}")

    return outputs


def main():
    parser = argparse.ArgumentParser(description="K线 1m → 多时间框架聚合")
    parser.add_argument("--symbol", required=True, help="标的，逗号分隔 (如 BTCUSDT,ETHUSDT)")
    parser.add_argument("--start", required=True, help="开始日期 (YYYYMMDD)")
    parser.add_argument("--end", required=True, help="结束日期 (YYYYMMDD)")
    parser.add_argument("--timeframes", default="5m,15m,1h,4h,1d", help="目标时间框架，逗号分隔")
    parser.add_argument("--data-dir", default="./data/strategies", help="数据目录")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    symbols = [s.strip().upper() for s in args.symbol.split(",") if s.strip()]
    timeframes = [t.strip() for t in args.timeframes.split(",") if t.strip()]

    for sym in symbols:
        logger.info(f"=== {sym} ===")
        resample_1m(sym, args.start, args.end, timeframes, args.data_dir)

    logger.info("完成")


if __name__ == "__main__":
    main()
