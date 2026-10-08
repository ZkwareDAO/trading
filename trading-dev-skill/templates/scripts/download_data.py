#!/usr/bin/env python3
"""
K 线数据下载脚本 — 开箱即用

从 Binance 公共数据源下载历史 K 线，写入 {data_dir}/{interval}/{SYMBOL}_{interval}.csv。
无需 API key。国内网络可通过 .env 的 HTTPS_PROXY / HTTP_PROXY 走代理。

输出路径与回测/实盘一致（config/settings.yaml 的 csv_dir、config/backtest.yaml 的 data_dir
都指向 ./data/klines），下载完即可直接回测。

**默认增量**：读现有 CSV 末根，只补「末根 → 现在」这一段，merge 后落盘。
反复运行不会销毁已有历史。`--days` 仅在 CSV 不存在或 `--force` 时决定起点。

**长缺口自动分块**：缺口跨天/跨月时改用 Binance 归档包（data.binance.vision），
完整月走 monthly zip、零头天走 daily zip，归档尚未发布的今日尾部用 fapi 补齐。
一年数据 12 次请求即可，而逐页 fapi 需要 ~350 次。

本脚本是**运维前置备料工具**，与 data_manager/ 的运行时增量拉取职责分离，
不 import 任何项目模块。

使用方式:
    # 补齐 BTCUSDT 到最新（CSV 不存在时下载最近 30 天）
    python scripts/download_data.py --symbol BTCUSDT --interval 1m --days 30

    # 下载多个 symbol
    python scripts/download_data.py --symbol BTCUSDT,ETHUSDT --interval 1m --days 30

    # 忽略现有 CSV，按 --days 全量重下并覆盖
    python scripts/download_data.py --symbol BTCUSDT --days 30 --force

    # 指定输出目录
    python scripts/download_data.py --symbol BTCUSDT --days 7 --data-dir ./data/klines
"""

import argparse
import calendar
import io
import os
import sys
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv()

BINANCE_FAPI_BASE = "https://fapi.binance.com"
KLINES_ENDPOINT = "/fapi/v1/klines"
MAX_LIMIT = 1500  # Binance 单次请求上限

# 归档包（USDT 永续合约）。monthly 只发布已结束的完整月，daily 只到昨天，
# 故今天的数据必须走 fapi —— 已实测确认：daily/-2026-08-21.zip 与
# monthly/-2026-08.zip 在 2026-08-21 当天均返回 404。
BINANCE_ARCHIVE_BASE = "https://data.binance.vision/data/futures/um"
# 归档 GET 会间歇性抛 SSL EOF（实测首次失败、立即重试即 200）。
# --days 365 要拉 12 个 zip，无重试几乎必然中途失败。
ARCHIVE_MAX_RETRIES = 3
ARCHIVE_RETRY_BACKOFF = 2.0

# 归档 zip 内 CSV 的 12 列表头（首行即表头，与 fapi 的裸数组不同）
ARCHIVE_COLUMNS = [
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

# Binance K 线返回的 12 列，只保留前 6 列（与项目 CSV 格式一致）
CSV_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]

# plan_chunks 返回的块，三种形态：
#   ("monthly", year:int, month:int)   整个自然月（该月已结束）
#   ("daily", d:date)                  单天（早于今天）
#   ("fapi", start_ms:int, end_ms:int) 归档未覆盖的尾部
Chunk = Tuple[Any, ...]

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


def _get_with_retry(url: str, **kwargs: Any) -> requests.Response:
    """带重试的 GET。

    实测 fapi 与归档两条链路都会间歇抛 SSL EOF（`UNEXPECTED_EOF_WHILE_READING`），
    立即重试即成功。跨月补齐要发几十次请求，不重试则中途失败概率很高
    —— 一次真实的跨月 E2E 就是在第 13500 根时被这个异常打断的。
    """
    last_error: Optional[Exception] = None
    for attempt in range(ARCHIVE_MAX_RETRIES):
        try:
            return requests.get(url, **kwargs)
        except requests.RequestException as e:
            last_error = e
            if attempt < ARCHIVE_MAX_RETRIES - 1:
                time.sleep(ARCHIVE_RETRY_BACKOFF * (attempt + 1))
    assert last_error is not None
    raise last_error


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
            resp = _get_with_retry(
                f"{BINANCE_FAPI_BASE}{KLINES_ENDPOINT}",
                params=params,
                proxies=proxies,
                timeout=30,
            )
        except requests.RequestException as e:
            # 不在此处 sys.exit：多 symbol 时第 2 个失败会让第 3、4 个永不下载，
            # 连汇总行都打不出。交由 main 统一决定退出码。
            raise RuntimeError(
                f"请求异常: {e}\n"
                "    国内网络请在 .env 配置 HTTPS_PROXY / HTTP_PROXY 后重试"
            ) from e

        if resp.status_code != 200:
            raise RuntimeError(
                f"Binance 返回 {resp.status_code}: {resp.text[:200]}"
            )

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


# ============================================================
# 现有 CSV 读取与合并（增量补齐）
# ============================================================


def read_existing_csv(csv_path: Path) -> Optional[pd.DataFrame]:
    """读取现有 CSV，timestamp 转为 tz-aware datetime。

    文件不存在或无法解析时返回 None（调用方退回按 --days 全量下载）。
    坏文件不静默当成"无数据" —— 那会让下一步覆盖写抹掉一个可能只是
    列名写错的文件，故打印警告。
    """
    if not csv_path.exists():
        return None

    try:
        df = pd.read_csv(csv_path)
    except Exception as e:
        print(f"  ! 现有 CSV 无法读取（将按 --days 全量下载）: {e}", file=sys.stderr)
        return None

    if df.empty or "timestamp" not in df.columns:
        print(
            f"  ! 现有 CSV 缺少 timestamp 列或为空（将按 --days 全量下载）: {csv_path}",
            file=sys.stderr,
        )
        return None

    # 兼容两种历史格式：毫秒整数（Binance 原始）与 ISO 字符串（本脚本产出）
    if pd.api.types.is_numeric_dtype(df["timestamp"]):
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    else:
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")

    if df["timestamp"].isna().all():
        print(
            f"  ! 现有 CSV 时间戳全部无法解析（将按 --days 全量下载）: {csv_path}",
            file=sys.stderr,
        )
        return None

    return df.dropna(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)


def merge_klines(old_df: Optional[pd.DataFrame], new_df: pd.DataFrame) -> pd.DataFrame:
    """合并新旧 K 线：新数据覆盖同时间戳的旧值。

    新数据放在**后面** + keep="last"：进程被杀时最后一根 1m 可能未闭合就已落盘
    （带残缺 volume/high），重新拉取到的完整值必须能覆盖它。这也是补齐起点取
    末根本身、而非末根 + 1 周期的原因。与框架侧 _merge_kline_data 语义一致。

    两侧 timestamp 类型可能不同（read_existing_csv 给 tz-aware datetime，
    下载路径给 ISO 字符串），直接 concat 后排序会抛
    `'<' not supported between 'str' and 'Timestamp'`，故先统一成 datetime。
    """
    if old_df is None or old_df.empty:
        combined = new_df.copy()
    elif new_df.empty:
        combined = old_df.copy()
    else:
        combined = pd.concat(
            [_as_datetime_timestamp(old_df), _as_datetime_timestamp(new_df)],
            ignore_index=True,
        )

    combined = _as_datetime_timestamp(combined)
    combined = combined.drop_duplicates(subset="timestamp", keep="last")
    return combined.sort_values("timestamp").reset_index(drop=True)


def _as_datetime_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    """把 timestamp 列统一成 tz-aware datetime（已是则原样返回副本）。"""
    out = df.copy()
    if "timestamp" not in out.columns or out.empty:
        return out
    if not pd.api.types.is_datetime64_any_dtype(out["timestamp"]):
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
    return out


def _normalize_timestamp_column(df: pd.DataFrame) -> pd.DataFrame:
    """把 timestamp 列统一成落盘用的 ISO 字符串（`2026-08-20 07:21:00+00:00`）。

    该格式是 backtest 侧 _ensure_normalized_csv 期望的规范化形式，写成这样
    可避免回测启动时被判定为原始格式而重写整个文件。
    """
    out = df.copy()
    if pd.api.types.is_datetime64_any_dtype(out["timestamp"]):
        out["timestamp"] = out["timestamp"].astype(str)
    return out


# ============================================================
# 分块规划（纯函数，不发网络请求）
# ============================================================


def plan_chunks(start_dt: datetime, end_dt: datetime, today: date) -> List[Chunk]:
    """把 [start_dt, end_dt) 切成归档/fapi 块，按时间升序。

    归档包只发布已完结的区间 —— monthly 仅完整月、daily 仅到昨天（均已实测：
    当天的 daily zip 与当月的 monthly zip 都返回 404）。因此：
      - 完整且已结束的自然月 → monthly zip（1 次请求顶一个月）
      - 其余早于今天的整天   → daily zip
      - 今天及归档未覆盖的尾部 → fapi 分页

    Args:
        start_dt: 缺口起点（含）
        end_dt: 缺口终点（不含）
        today: 当前 UTC 日期，决定归档可用边界（注入以便测试）

    缺口不足一天时结果自然只有一个 fapi 块：daily 分支要求
    `cursor + 1天 <= end_dt`，monthly 要求整月落在缺口内，两者都不可能满足，
    故不为此另写一层提前返回的守卫 —— 曾写过，但移除它后全部用例仍绿
    （702 个 <1 天的起点/时长组合穷举验证输出完全一致），说明那是死分支。
    """
    if start_dt >= end_dt:
        return []

    chunks: List[Chunk] = []
    cursor = start_dt

    while cursor < end_dt:
        # 整个自然月都落在缺口内、且该月已结束 → monthly
        month_start = cursor.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        days_in_month = calendar.monthrange(cursor.year, cursor.month)[1]
        next_month_start = month_start + timedelta(days=days_in_month)
        month_is_over = next_month_start.date() <= today

        if cursor == month_start and next_month_start <= end_dt and month_is_over:
            chunks.append(("monthly", cursor.year, cursor.month))
            cursor = next_month_start
            continue

        # 整天且早于今天 → daily
        day_start = cursor.replace(hour=0, minute=0, second=0, microsecond=0)
        next_day_start = day_start + timedelta(days=1)

        if cursor == day_start and next_day_start <= end_dt and cursor.date() < today:
            chunks.append(("daily", cursor.date()))
            cursor = next_day_start
            continue

        # 未对齐的零头：只用 fapi 补到**下一个整天边界**，然后回到循环继续切块。
        # 若在此直接 fapi 到 end_dt 并 break，一个 06-02 03:18 这样的起点会让
        # 整个跨月缺口退化成单个巨型 fapi 范围（实测 13500+ 根仍在翻页），
        # 归档完全用不上 —— 这正是分块要解决的问题。
        if cursor < next_day_start < end_dt:
            chunks.append(("fapi", _to_ms(cursor), _to_ms(next_day_start)))
            cursor = next_day_start
            continue

        # 真正的尾巴（今天，或最后一段不足整天）→ fapi
        chunks.append(("fapi", _to_ms(cursor), _to_ms(end_dt)))
        break

    return chunks


def _to_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


# ============================================================
# 归档包下载
# ============================================================


def _archive_url(symbol: str, interval: str, kind: str, key: Any) -> str:
    """构造归档 zip URL。kind 为 "monthly" 时 key 是 (year, month)，否则是 date。"""
    sym = symbol.upper()
    if kind == "monthly":
        year, month = key
        stem = f"{sym}-{interval}-{year:04d}-{month:02d}"
        return f"{BINANCE_ARCHIVE_BASE}/monthly/klines/{sym}/{interval}/{stem}.zip"
    stem = f"{sym}-{interval}-{key.isoformat()}"
    return f"{BINANCE_ARCHIVE_BASE}/daily/klines/{sym}/{interval}/{stem}.zip"


def fetch_archive_chunk(
    symbol: str,
    interval: str,
    kind: str,
    key: Any,
    proxies: Optional[dict] = None,
    as_rows: bool = False,
):
    """下载并解析一个归档 zip。

    as_rows=False（默认）返回 6 列 DataFrame；as_rows=True 返回 12 列原始行
    （与 fapi 裸数组同构），供运行时补洞直接合并、不落盘。

    404 → 返回 None（归档尚未发布，调用方降级到 fapi），不视为错误。
    其它失败重试 ARCHIVE_MAX_RETRIES 次后抛 RuntimeError —— 实测归档 GET 会
    间歇抛 SSL EOF（首次失败、立即重试即 200），不重试则多块下载几乎必然中断。
    """
    url = _archive_url(symbol, interval, kind, key)
    last_error: Optional[Exception] = None

    for attempt in range(ARCHIVE_MAX_RETRIES):
        try:
            resp = requests.get(url, proxies=proxies, timeout=120)
        except requests.RequestException as e:
            last_error = e
            time.sleep(ARCHIVE_RETRY_BACKOFF * (attempt + 1))
            continue

        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            last_error = RuntimeError(f"HTTP {resp.status_code}")
            time.sleep(ARCHIVE_RETRY_BACKOFF * (attempt + 1))
            continue

        return (
            archive_zip_to_rows(resp.content)
            if as_rows
            else archive_zip_to_dataframe(resp.content)
        )

    raise RuntimeError(f"归档下载失败（重试 {ARCHIVE_MAX_RETRIES} 次）: {url} — {last_error}")


def fetch_range_rows(
    symbol: str,
    interval: str,
    start_dt: datetime,
    end_dt: datetime,
    proxies: Optional[dict] = None,
) -> List[list]:
    """归档优先取回 [start_dt, end_dt) 的原始 12 列 K 线，**不落盘**。

    运行时补洞使用：完整月/天走归档 zip（一次请求顶一个月，几乎不占 fapi
    限额），归档未发布的零头与 404 块走 fapi 分页。与 download_range 的
    分块规划完全一致，只是输出原始行而非 merge 落盘 —— 调用方（DataManager）
    仍需通过 kline_repo 的加锁路径合并，避免与 WS 追加写竞态。

    按 open_time 去重排序（分页/归档边界可能重复）。
    """
    symbol_upper = symbol.upper()
    chunks = plan_chunks(start_dt, end_dt, end_dt.date())
    all_rows: List[list] = []

    for kind, *key in chunks:
        if kind == "fapi":
            all_rows.extend(
                fetch_klines(symbol_upper, interval, key[0], key[1], proxies)
            )
            continue

        label = (
            f"{key[0]:04d}-{key[1]:02d}" if kind == "monthly" else key[0].isoformat()
        )
        archive_key = (key[0], key[1]) if kind == "monthly" else key[0]
        chunk_rows = fetch_archive_chunk(
            symbol_upper, interval, kind, archive_key, proxies, as_rows=True
        )
        if chunk_rows is None:
            # 归档尚未发布该区间 → 用 fapi 兜住，避免静默丢一整块
            fb_start, fb_end = _chunk_bounds(kind, archive_key, end_dt)
            all_rows.extend(
                fetch_klines(
                    symbol_upper, interval,
                    _to_ms(fb_start), _to_ms(fb_end), proxies,
                )
            )
            continue

        print(f"    归档 {kind} {label}: {len(chunk_rows)} 根")
        all_rows.extend(chunk_rows)

    # open_time 去重（保持首次出现；各块均为权威完整数据）后排序
    deduped = {int(row[0]): row for row in all_rows}
    return [deduped[ms] for ms in sorted(deduped)]


def archive_zip_to_rows(payload: bytes) -> List[list]:
    """归档 zip（内含单个 12 列 CSV）→ 12 列原始行（open_time 为 int 毫秒）。

    与 fapi klines 返回的裸数组同构（其余 11 列保持归档里的字符串形态），
    供运行时补洞直接合并到缓存，避免落盘再读回。

    归档 CSV **首行是表头**（`open_time,open,...`），历史上部分归档包不带
    表头，故按首格是否可转数字来判断，两种都能吃。
    """
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
        if not names:
            return []
        raw = zf.read(names[0])

    df = pd.read_csv(io.BytesIO(raw), header=None, names=ARCHIVE_COLUMNS)
    # 丢掉表头行（若存在）：open_time 不可转数字即为表头
    first = pd.to_numeric(df["open_time"].iloc[:1], errors="coerce")
    if first.isna().all():
        df = df.iloc[1:]

    if df.empty:
        return []

    rows: List[list] = []
    for r in df.itertuples(index=False, name=None):
        rows.append([int(r[0])] + [str(v) for v in r[1:]])
    return rows


def archive_zip_to_dataframe(payload: bytes) -> pd.DataFrame:
    """归档 zip（内含单个 12 列 CSV）→ 项目 6 列格式。"""
    rows = archive_zip_to_rows(payload)
    if not rows:
        return pd.DataFrame(columns=CSV_COLUMNS)

    df = pd.DataFrame(rows).iloc[:, :6]
    df.columns = CSV_COLUMNS
    df["timestamp"] = pd.to_datetime(
        df["timestamp"].astype("int64"), unit="ms", utc=True
    )
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = df[col].astype(float)

    df = df.drop_duplicates(subset="timestamp").sort_values("timestamp")
    df["timestamp"] = df["timestamp"].astype(str)
    return df.reset_index(drop=True)


def download_symbol(
    symbol: str,
    interval: str,
    days: int,
    data_dir: str,
    proxies: Optional[dict] = None,
    force: bool = False,
) -> Optional[Path]:
    """下载单个 symbol 并写入 CSV（默认增量补齐）。返回输出路径。

    默认读现有 CSV 末根作为补齐起点，只拉缺口，最后与现有数据 merge 后落盘。
    force=True 时忽略现有 CSV，按 days 全量重下并覆盖。

    本函数只负责**算出区间**，实际下载与落盘委托 download_range。
    """
    symbol_upper = symbol.upper()
    end_dt = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    out_dir = Path(data_dir) / interval
    out_path = out_dir / f"{symbol_upper}_{interval}.csv"

    existing = None if force else read_existing_csv(out_path)

    if existing is not None and not existing.empty:
        latest = existing["timestamp"].max()
        # 起点取末根**本身**而非 +1 周期：崩溃时未闭合就落盘的残缺末根需要被
        # 完整值覆盖（merge_klines 用 keep="last" 保证覆盖方向正确）。
        start_dt = latest.to_pydatetime()
        print(
            f"  {symbol_upper} {interval}: 现有 {len(existing)} 根"
            f"（末根 {latest:%Y-%m-%d %H:%M}），补齐至 {end_dt:%Y-%m-%d %H:%M}"
        )
    else:
        start_dt = end_dt - timedelta(days=days)
        print(f"  {symbol_upper} {interval}: {start_dt:%Y-%m-%d} ~ {end_dt:%Y-%m-%d}")

    if start_dt >= end_dt:
        print(f"  = {symbol_upper} 已是最新，无需下载")
        return out_path

    return download_range(
        symbol_upper, interval, start_dt, end_dt, data_dir, proxies,
        force=force, existing=existing,
    )


def download_range(
    symbol: str,
    interval: str,
    start_dt: datetime,
    end_dt: datetime,
    data_dir: str,
    proxies: Optional[dict] = None,
    force: bool = False,
    existing: Optional[pd.DataFrame] = None,
) -> Optional[Path]:
    """下载 [start_dt, end_dt) 并 merge 进现有 CSV，返回 CSV 路径。

    与 download_symbol 的区别：区间由**调用方给定**，不从现有 CSV 末根推导。
    回测侧需要「补到 warm-up 起点之前」这种由策略参数算出的区间，末根推导表达不了。

    走同一条 plan_chunks → 归档/fapi → merge_klines → _normalize_timestamp_column
    链路，落盘格式（ISO 字符串）与 download_symbol 完全一致 —— CSV 只有一种格式，
    否则回测侧 _ensure_normalized_csv 会重写整个文件。

    Args:
        start_dt: 区间起点（含）。补尾部缺口时应传现有末根**本身**而非 +1 周期，
            让残缺末根被完整值覆盖。
        end_dt: 区间终点（不含）。不得晚于当前时刻，否则等于向交易所索要未来 K 线。
        force: True 时忽略现有 CSV，下载结果直接覆盖（不 merge）。
        existing: 调用方已读好的现有 CSV，传入可省一次读盘。为 None 时本函数自己读。
            1m CSV 常有百万行级（实测 190 万行读一次 ~3.4s），故 download_symbol
            把它已读的那份传下来，而不是让这里重读一遍。

    Returns:
        CSV 路径；无数据可写且原本也无 CSV 时返回 None。
    """
    symbol_upper = symbol.upper()
    out_dir = Path(data_dir) / interval
    out_path = out_dir / f"{symbol_upper}_{interval}.csv"

    if force:
        existing = None
    elif existing is None:
        existing = read_existing_csv(out_path)

    chunks = plan_chunks(start_dt, end_dt, end_dt.date())
    frames: List[pd.DataFrame] = []

    for kind, *key in chunks:
        if kind == "fapi":
            rows = fetch_klines(symbol_upper, interval, key[0], key[1], proxies)
            if rows:
                frames.append(klines_to_dataframe(rows))
            continue

        label = (
            f"{key[0]:04d}-{key[1]:02d}" if kind == "monthly" else key[0].isoformat()
        )
        archive_key = (key[0], key[1]) if kind == "monthly" else key[0]
        df_chunk = fetch_archive_chunk(
            symbol_upper, interval, kind, archive_key, proxies
        )
        if df_chunk is None:
            # 归档尚未发布该区间 → 用 fapi 兜住，避免静默丢一整块
            print(f"    归档缺 {kind} {label}，改用 fapi 补齐")
            fb_start, fb_end = _chunk_bounds(kind, archive_key, end_dt)
            rows = fetch_klines(
                symbol_upper, interval, _to_ms(fb_start), _to_ms(fb_end), proxies
            )
            if rows:
                frames.append(klines_to_dataframe(rows))
            continue

        print(f"    归档 {kind} {label}: {len(df_chunk)} 根")
        frames.append(df_chunk)

    new_df = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=CSV_COLUMNS)
    )

    if new_df.empty and existing is None:
        print(f"  ✗ {symbol_upper} 无数据返回", file=sys.stderr)
        return None

    df = merge_klines(existing, new_df)
    df = _normalize_timestamp_column(df)

    out_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)

    size_mb = out_path.stat().st_size / 1024 / 1024
    added = len(df) - (0 if existing is None else len(existing))
    print(f"  ✓ {out_path} （{len(df)} 根，新增 {added}，{size_mb:.2f} MB）")
    return out_path


def _chunk_bounds(kind: str, key: Any, end_dt: datetime) -> Tuple[datetime, datetime]:
    """归档块对应的 [start, end) 时间边界，用于 404 时降级 fapi。"""
    if kind == "monthly":
        year, month = key
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        days_in_month = calendar.monthrange(year, month)[1]
        stop = start + timedelta(days=days_in_month)
    else:
        start = datetime(key.year, key.month, key.day, tzinfo=timezone.utc)
        stop = start + timedelta(days=1)
    return start, min(stop, end_dt)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从 Binance 公共数据源下载 K 线数据（无需 API key，默认增量补齐）"
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
        help="CSV 不存在（或 --force）时下载最近 N 天（默认 30）；"
             "CSV 已存在时起点由末根决定，此参数不生效",
    )
    parser.add_argument(
        "--data-dir",
        default="./data/klines",
        help="输出目录（默认 ./data/klines，与 settings.yaml 的 csv_dir 一致）",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="忽略现有 CSV，按 --days 全量重下并覆盖（默认是增量 merge，不销毁历史）",
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

    mode = "全量覆盖" if args.force else "增量补齐"
    print(f"下载 {len(symbols)} 个交易对到 {args.data_dir}/{args.interval}/（{mode}）")
    ok_count = 0
    for symbol in symbols:
        # 单个 symbol 失败不阻断后续：原实现在 fetch_klines 内 sys.exit，
        # 多 symbol 时第 2 个网络抖动会让第 3、4 个永不下载。
        try:
            if download_symbol(
                symbol, args.interval, args.days, args.data_dir, proxies, args.force
            ):
                ok_count += 1
        except RuntimeError as e:
            print(f"  ✗ {symbol.upper()} 下载失败: {e}", file=sys.stderr)

    print(f"\n完成: {ok_count}/{len(symbols)} 成功")
    if ok_count < len(symbols):
        sys.exit(1)


if __name__ == "__main__":
    main()
