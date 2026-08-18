#!/usr/bin/env python3
"""
K 线数据下载脚本 — 开箱即用

从 Binance 公共 fapi 下载历史 K 线，写入 {data_dir}/{interval}/{SYMBOL}_{interval}.csv。
无需 API key。国内网络可通过 .env 的 HTTPS_PROXY / HTTP_PROXY 走代理。

输出路径与回测/实盘一致（config/settings.yaml 的 csv_dir、config/backtest.yaml 的 data_dir
都指向 ./data/klines），下载完即可直接回测。

使用方式:
    # 下载 BTCUSDT 最近 30 天 1m 数据
    python scripts/download_data.py --symbol BTCUSDT --interval 1m --days 30

    # 下载多个 symbol
    python scripts/download_data.py --symbol BTCUSDT,ETHUSDT --interval 1m --days 30

    # 指定输出目录
    python scripts/download_data.py --symbol BTCUSDT --days 7 --data-dir ./data/klines
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

BINANCE_FAPI_BASE = "https://fapi.binance.com"
KLINES_ENDPOINT = "/fapi/v1/klines"
MAX_LIMIT = 1500  # Binance 单次请求上限

# Binance K 线返回的 12 列，只保留前 6 列（与项目 CSV 格式一致）
CSV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

INTERVAL_MS = {
    "1m": 60_000,
    "3m": 180_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
}


def _redact_proxy(url: str) -> str:
    """隐去代理 URL 中的密码，供日志安全打印。

    代理常写成 http://user:pass@host:port，原样打印会把密码写进
    终端回滚与 CI 日志。此处只保留用户名与主机端口。
    URL 无法解析时退回打印 "<代理已配置>"，宁可少信息也不泄漏。
    """
    try:
        parts = urlsplit(url)
        if not parts.password:
            return url
        netloc = f"{parts.username or ''}:***@{parts.hostname or ''}"
        if parts.port:
            netloc += f":{parts.port}"
        return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    except ValueError:
        return "<代理已配置>"


def _get_proxies() -> Optional[dict]:
    """从环境变量读代理配置（国内网络访问 Binance 通常需要）。"""
    https_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    http_proxy = os.environ.get("HTTP_PROXY") or os.environ.get("http_proxy")
    if not https_proxy and not http_proxy:
        return None
    proxies = {}
    if https_proxy:
        proxies["https"] = https_proxy
    if http_proxy:
        proxies["http"] = http_proxy
    return proxies


def fetch_klines(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    proxies: Optional[dict] = None,
) -> List[list]:
    """分页拉取指定时间范围的 K 线。

    Binance 单次最多返回 1500 根，超出需分页。返回原始 12 列列表。
    """
    step = INTERVAL_MS[interval]
    all_rows: List[list] = []
    cursor = start_ms

    while cursor < end_ms:
        params = {
            "symbol": symbol.upper(),
            "interval": interval,
            "startTime": cursor,
            "endTime": end_ms,
            "limit": MAX_LIMIT,
        }
        try:
            resp = requests.get(
                f"{BINANCE_FAPI_BASE}{KLINES_ENDPOINT}",
                params=params,
                proxies=proxies,
                timeout=30,
            )
        except requests.RequestException as e:
            print(f"  ✗ 请求异常: {e}", file=sys.stderr)
            print(
                "    国内网络请在 .env 配置 HTTPS_PROXY / HTTP_PROXY 后重试",
                file=sys.stderr,
            )
            sys.exit(1)

        if resp.status_code != 200:
            print(
                f"  ✗ Binance 返回 {resp.status_code}: {resp.text[:200]}",
                file=sys.stderr,
            )
            sys.exit(1)

        rows = resp.json()
        if not rows:
            break

        all_rows.extend(rows)
        # 下一页从最后一根 K 线的开盘时间 + 一个周期开始
        last_open = int(rows[-1][0])
        cursor = last_open + step

        print(f"    已获取 {len(all_rows)} 根（游标 {_ms_to_str(cursor)}）", end="\r")
        time.sleep(0.2)  # 轻微限速，避免触发 Binance 频率限制

    print()  # 换行结束进度行
    return all_rows


def _ms_to_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


def klines_to_dataframe(rows: List[list]) -> pd.DataFrame:
    """Binance 原始 K 线 → 项目 CSV 格式（timestamp 为带时区字符串）。"""
    if not rows:
        return pd.DataFrame(columns=CSV_COLUMNS)

    df = pd.DataFrame(rows).iloc[:, :6]
    df.columns = CSV_COLUMNS
    df["timestamp"] = pd.to_datetime(df["timestamp"].astype("int64"), unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)

    # 去重排序（分页边界可能重复）
    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp")
    df["timestamp"] = df["timestamp"].astype(str)
    return df.reset_index(drop=True)


def download_symbol(
    symbol: str,
    interval: str,
    days: int,
    data_dir: str,
    proxies: Optional[dict] = None,
) -> Optional[Path]:
    """下载单个 symbol 并写入 CSV。返回输出路径。"""
    symbol_upper = symbol.upper()
    end_dt = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=days)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    print(f"  {symbol_upper} {interval}: {start_dt:%Y-%m-%d} ~ {end_dt:%Y-%m-%d}")
    rows = fetch_klines(symbol_upper, interval, start_ms, end_ms, proxies)
    if not rows:
        print(f"  ✗ {symbol_upper} 无数据返回", file=sys.stderr)
        return None

    df = klines_to_dataframe(rows)

    out_dir = Path(data_dir) / interval
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{symbol_upper}_{interval}.csv"
    df.to_csv(out_path, index=False)

    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"  ✓ {out_path} （{len(df)} 根，{size_mb:.2f} MB）")
    return out_path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从 Binance 公共 fapi 下载 K 线数据（无需 API key）"
    )
    parser.add_argument(
        "--symbol",
        required=True,
        help="交易对，支持逗号分隔多个（如 BTCUSDT 或 BTCUSDT,ETHUSDT）",
    )
    parser.add_argument(
        "--interval",
        default="1m",
        choices=sorted(INTERVAL_MS.keys()),
        help="K 线周期（默认 1m；回测按 1m 驱动，大周期由框架自动聚合）",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="下载最近 N 天（默认 30）",
    )
    parser.add_argument(
        "--data-dir",
        default="./data/klines",
        help="输出目录（默认 ./data/klines，与 settings.yaml 的 csv_dir 一致）",
    )

    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbol.split(",") if s.strip()]
    if not symbols:
        parser.error("--symbol 不能为空")

    # days < 1 会算出起点晚于终点，Binance 返回空数据但看不出原因，故提前拦截
    if args.days < 1:
        parser.error(f"--days 必须 >= 1，收到 {args.days}")

    proxies = _get_proxies()
    if proxies:
        safe = {k: _redact_proxy(v) for k, v in proxies.items()}
        print(f"使用代理: {safe}")

    print(f"下载 {len(symbols)} 个交易对到 {args.data_dir}/{args.interval}/")
    ok_count = 0
    for symbol in symbols:
        if download_symbol(symbol, args.interval, args.days, args.data_dir, proxies):
            ok_count += 1

    print(f"\n完成: {ok_count}/{len(symbols)} 成功")
    if ok_count < len(symbols):
        sys.exit(1)


if __name__ == "__main__":
    main()
