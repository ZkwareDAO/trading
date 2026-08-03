#!/usr/bin/env python3
"""
1m K 线数据下载脚本

从 Binance Data Vision (https://data.binance.vision) 下载历史 K 线数据。
优先下载 monthly zip（更快），再下载 daily zip 补充最近数据。
无需 API Key，无需认证。

用法:
  python utils/prepare_data.py --symbol BTCUSDT --start 20250101
  python utils/prepare_data.py --symbol BTCUSDT,ETHUSDT,SOLUSDT --start 20250101
  python utils/prepare_data.py --output ./data/strategies/1m --symbol BTCUSDT,ETHUSDT,SOLUSDT

输出格式 (CSV):
  timestamp,open,high,low,close,volume
  2022-12-30 00:00:00+00:00,16630.3,16633.7,16629.2,16629.3,337.988

输出文件命名: {SYMBOL}_1m.csv
输出路径: {output_dir}/{SYMBOL}_1m.csv

数据来源:
  月度: https://data.binance.vision/data/futures/um/monthly/klines/{SYMBOL}/1m/{SYMBOL}-1m-{YYYY-MM}.zip
  日度: https://data.binance.vision/data/futures/um/daily/klines/{SYMBOL}/1m/{SYMBOL}-1m-{YYYY-MM-DD}.zip
"""

import argparse
import io
import os
import sys
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

try:
    import pandas as pd
except ImportError:
    print("❌ 需要 pandas: pip install pandas")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("❌ 需要 requests: pip install requests")
    sys.exit(1)


# Binance Data Vision URL 模板
BASE_URL = "https://data.binance.vision/data/futures/um"
MONTHLY_URL = f"{BASE_URL}/monthly/klines/{{symbol}}/1m/{{symbol}}-1m-{{year_month}}.zip"
DAILY_URL = f"{BASE_URL}/daily/klines/{{symbol}}/1m/{{symbol}}-1m-{{date}}.zip"

# Binance CSV 列名（无 header 的原始格式）
BINANCE_COLUMNS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "count",
    "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]

RATE_LIMIT_PAUSE = 0.3  # 秒
MAX_RETRIES = 3


def download_zip(url: str, retry: int = 0) -> Optional[bytes]:
    """下载 zip 文件内容

    Returns:
        zip 文件的 bytes，失败返回 None
    """
    try:
        resp = requests.get(url, timeout=60)
        if resp.status_code == 404:
            return None  # 数据不存在（未来日期或未交易日期）
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 60))
            print(f"  ⏳ 限频，等待 {wait}s...")
            import time
            time.sleep(wait)
            return download_zip(url, retry)
        if resp.status_code != 200:
            return None
        return resp.content

    except requests.exceptions.RequestException as e:
        if retry < MAX_RETRIES:
            import time
            time.sleep(2 ** retry)
            return download_zip(url, retry + 1)
        return None


def parse_zip_to_dataframe(zip_bytes: bytes) -> Optional[pd.DataFrame]:
    """从 zip bytes 解析 CSV 为 DataFrame

    Binance Data Vision 的 zip 内含一个 CSV 文件，无 header。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
            if not csv_names:
                return None

            with zf.open(csv_names[0]) as f:
                df = pd.read_csv(f, header=None, names=BINANCE_COLUMNS)

                # 转换类型
                df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = df[col].astype(float)

                # 只保留标准列
                df = df[["timestamp", "open", "high", "low", "close", "volume"]]
                return df

    except Exception as e:
        return None


def download_symbol(
    symbol: str,
    start_date: str,
    end_date: str,
    output_dir: Path,
) -> bool:
    """下载单个交易对的 1m K 线数据

    策略：
    1. 先下载 monthly zip（大文件，效率高）
    2. 再下载 daily zip 补充最近不完整月份
    3. 与已有数据合并（断点续传）
    """
    import time

    symbol = symbol.upper()
    output_file = output_dir / f"{symbol}_1m.csv"

    # 检查已有数据
    existing_df = None
    existing_end = None
    if output_file.exists():
        try:
            existing_df = pd.read_csv(output_file)
            if len(existing_df) > 0 and "timestamp" in existing_df.columns:
                existing_end = pd.to_datetime(existing_df["timestamp"].iloc[-1])
                print(f"  📁 已有数据: {len(existing_df):,} 行，截止 {existing_end}")
        except Exception:
            existing_df = None

    # 日期范围
    start = datetime.strptime(start_date, "%Y%m%d")
    end = datetime.strptime(end_date, "%Y%m%d")

    # 如果已有数据覆盖请求范围，跳过
    if existing_end and existing_end >= pd.Timestamp(end, tz="UTC"):
        print(f"  ✅ 已有数据覆盖请求范围，跳过下载")
        return True

    all_dfs = []

    # ---- 第一步：下载 monthly zip ----
    print(f"  📥 下载 {symbol} 月度数据...")
    current = start.replace(day=1)
    end_month = end.replace(day=1)
    monthly_count = 0

    while current <= end_month:
        # 跳过已有数据的月份
        if existing_end and pd.Timestamp(current, tz="UTC") <= existing_end:
            # 检查这个月是否已有完整数据
            month_end = (current + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            if existing_end >= pd.Timestamp(month_end, tz="UTC"):
                current = (current + timedelta(days=32)).replace(day=1)
                continue
            # 部分有数据，跳过这个月，后面用 daily 补充
            current = (current + timedelta(days=32)).replace(day=1)
            continue

        year_month = current.strftime("%Y-%m")
        url = MONTHLY_URL.format(symbol=symbol, year_month=year_month)

        zip_bytes = download_zip(url)
        if zip_bytes:
            df = parse_zip_to_dataframe(zip_bytes)
            if df is not None and not df.empty:
                all_dfs.append(df)
                monthly_count += 1

        time.sleep(RATE_LIMIT_PAUSE)
        current = (current + timedelta(days=32)).replace(day=1)

    print(f"  📊 月度数据: {monthly_count} 个文件")

    # ---- 第二步：下载 daily zip（补充最近不完整月份 + 缺失月份）----
    # 找出需要 daily 补充的日期范围
    # 最近 1-2 个月通常没有 monthly 数据，用 daily 补充
    daily_start = end - timedelta(days=45)  # 最近 45 天
    if daily_start < start:
        daily_start = start

    # 如果已有数据，从最后日期的下一天开始
    if existing_end:
        next_day = (existing_end + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if next_day > pd.Timestamp(daily_start, tz="UTC"):
            daily_start = next_day.to_pydatetime().replace(tzinfo=None)

    print(f"  📥 下载 {symbol} 日度数据: {daily_start.strftime('%Y-%m-%d')} → {end.strftime('%Y-%m-%d')}...")
    daily_count = 0
    failed_days = 0

    current = daily_start
    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        url = DAILY_URL.format(symbol=symbol, date=date_str)

        zip_bytes = download_zip(url)
        if zip_bytes:
            df = parse_zip_to_dataframe(zip_bytes)
            if df is not None and not df.empty:
                all_dfs.append(df)
                daily_count += 1
        else:
            failed_days += 1

        time.sleep(RATE_LIMIT_PAUSE)
        current += timedelta(days=1)

    print(f"  📊 日度数据: {daily_count} 个文件, {failed_days} 天无数据")

    if not all_dfs and existing_df is None:
        print(f"  ❌ {symbol}: 无数据下载成功")
        return False

    # ---- 第三步：合并所有数据 ----
    if all_dfs:
        new_df = pd.concat(all_dfs, ignore_index=True)
        new_df = new_df.sort_values("timestamp").drop_duplicates(
            subset=["timestamp"], keep="last"
        ).reset_index(drop=True)
        print(f"  📦 新数据: {len(new_df):,} 行")
    else:
        new_df = pd.DataFrame()

    # 与已有数据合并
    if existing_df is not None and not new_df.empty:
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        combined = combined.sort_values("timestamp").drop_duplicates(
            subset=["timestamp"], keep="last"
        ).reset_index(drop=True)
    elif not new_df.empty:
        combined = new_df
    else:
        print(f"  ⚠ {symbol}: 无新数据，保留已有文件")
        return True

    # 格式化 timestamp
    if combined["timestamp"].dtype == object:
        combined["timestamp"] = pd.to_datetime(combined["timestamp"])
    if combined["timestamp"].dt.tz is None:
        combined["timestamp"] = combined["timestamp"].dt.tz_localize("UTC")
    else:
        combined["timestamp"] = combined["timestamp"].dt.tz_convert("UTC")

    # 保存
    output_dir.mkdir(parents=True, exist_ok=True)
    combined["timestamp"] = combined["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S+00:00")
    combined.to_csv(output_file, index=False)

    size_mb = output_file.stat().st_size / 1024 / 1024
    print(f"  ✅ {symbol}: {len(combined):,} 行 → {output_file} ({size_mb:.1f} MB)")

    return True


def main():
    parser = argparse.ArgumentParser(
        description="从 Binance Data Vision 下载 1m K 线数据",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 下载 BTCUSDT 2025 全年数据
  python utils/prepare_data.py --symbol BTCUSDT --start 20250101

  # 下载多个交易对
  python utils/prepare_data.py --symbol BTCUSDT,ETHUSDT,SOLUSDT --start 20250101

  # 指定输出目录
  python utils/prepare_data.py --output ./data/strategies/1m --symbol BTCUSDT,ETHUSDT,SOLUSDT

数据来源:
  https://data.binance.vision/data/futures/um/monthly/klines/{SYMBOL}/1m/
  https://data.binance.vision/data/futures/um/daily/klines/{SYMBOL}/1m/
        """,
    )
    parser.add_argument(
        "--symbol", required=True,
        help="交易对，多个用逗号分隔（如 BTCUSDT,ETHUSDT,SOLUSDT）",
    )
    parser.add_argument(
        "--start", default="20250101",
        help="起始日期 (YYYYMMDD)，默认 20250101",
    )
    parser.add_argument(
        "--end", default=None,
        help="结束日期 (YYYYMMDD)，默认昨天",
    )
    parser.add_argument(
        "--output", default=None,
        help="输出目录，默认读取 KLINE_DATA_DIR 或 DATA_PATH/strategies/1m",
    )

    args = parser.parse_args()

    # 输出目录
    if args.output:
        output_dir = Path(args.output)
    else:
        kline_dir = os.getenv("KLINE_DATA_DIR")
        data_path = os.getenv("DATA_PATH", "./data")
        if kline_dir:
            output_dir = Path(kline_dir)
        else:
            output_dir = Path(data_path) / "strategies" / "1m"

    # 结束日期（默认昨天，因为今天的数据可能不完整）
    end_date = args.end or (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    # 交易对列表
    symbols = [s.strip().upper() for s in args.symbol.split(",")]

    print("=" * 60)
    print("📥 1m K 线数据下载 (Binance Data Vision)")
    print(f"  交易对: {', '.join(symbols)}")
    print(f"  时间范围: {args.start} → {end_date}")
    print(f"  输出目录: {output_dir}")
    print(f"  数据源: https://data.binance.vision/data/futures/um/")
    print("=" * 60)

    results = {}
    for symbol in symbols:
        print(f"\n{'─' * 40}")
        success = download_symbol(symbol, args.start, end_date, output_dir)
        results[symbol] = success

    # 汇总
    print(f"\n{'=' * 60}")
    print("📊 下载汇总:")
    for symbol, success in results.items():
        status = "✅" if success else "❌"
        output_file = output_dir / f"{symbol}_1m.csv"
        if output_file.exists():
            size_mb = output_file.stat().st_size / 1024 / 1024
            print(f"  {status} {symbol}: {size_mb:.1f} MB")
        else:
            print(f"  {status} {symbol}: 无数据")

    all_success = all(results.values())
    sys.exit(0 if all_success else 1)


if __name__ == "__main__":
    main()
