#!/usr/bin/env python3
"""download_data.py — 下载并合并 Binance 1m K线数据（UTC）

代币来源（二选一，优先 symbols.yaml）:
  - --symbols-file symbols.yaml（由 sync-exee.py 生成，代币已去重）
  - --symbols BTCUSDT,ETHUSDT（手动指定）

流程（每个代币）:
  1. 检查 {data_dir}/1m/{SYMBOL}_1m.csv 本地最新K线时间(UTC)
  2. 无数据 → 用 data.binance.vision monthly/klines 批量下载历史月度数据
  3a. 月度最新时间之后 → 用 daily/klines 补到最新可用日（vision 每日 T-1 发布）
  3b. daily 不存在（今日未发布数据）→ REST API(fapi) 从该时间补到当前(UTC)
  4. 合并 1m 数据：按 timestamp 去重(取最后)、排序，存为本地 UTC 格式 CSV

下载优先级（三层，上层拿不到才用下层）:
  - monthly bulk：完整月份，覆盖历史
  - daily  bulk ：当前未完成月份里已结束的日期（到 UTC 昨天）
  - REST API   ：daily 也拿不到的最新一段（今日未发布数据）→ 补到当前
  全程时间用 UTC。

用法:
  # 读 symbols.yaml（推荐，配合 sync-exee.py 之后执行）
  python3 download_data.py --symbols-file ./snapshot/20260807/symbols.yaml

  # 手动指定代币
  python3 download_data.py --symbols BTCUSDT,ETHUSDT
  python3 download_data.py --symbols BTCUSDT --start 20240101 --data-dir ./data/klines

依赖: pandas + Python 标准库(urllib/zipfile/json/io)，无需 requests/dotenv/pyyaml
"""

import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

# data.binance.vision 期货 UM K线根
# 完整路径:
#   monthly: .../monthly/klines/{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-{YYYY-MM}.zip
#   daily  : .../daily/klines/{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-{YYYY-MM-DD}.zip
VISION_MONTHLY = "https://data.binance.vision/data/futures/um/monthly/klines"
VISION_DAILY = "https://data.binance.vision/data/futures/um/daily/klines"

# 期货 K线 REST API（补最新）
REST_KLINES = "https://fapi.binance.com/fapi/v1/klines"

TIMEFRAME = "1m"
REST_LIMIT = 1500  # 期货 klines 单次上限

# Binance 原始 CSV / REST 返回的 12 列
BINANCE_COLS = [
    "open_time", "open", "high", "low", "close", "volume",
    "close_time", "quote_volume", "count",
    "taker_buy_volume", "taker_buy_quote_volume", "ignore",
]

# 本地 CSV 保留列（对齐 kline_repository._save_dataframe）
LOCAL_COLS = [
    "timestamp", "open", "high", "low", "close", "volume",
    "quote_volume", "count", "taker_buy_volume", "taker_buy_quote_volume",
]

# 本地 CSV timestamp 字符串格式（UTC）
TS_FMT = "%Y-%m-%d %H:%M:%S+00:00"


# ---------- HTTP ----------

# 代理：优先 HTTPS_PROXY/HTTP_PROXY 环境变量，否则 None。
# data.binance.vision 国内一般直连可达；fapi.binance.com(REST 补今日最新) 常需代理。
_PROXY = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")


def _build_opener():
    """构造 urlopen opener：有代理则挂 ProxyHandler，否则默认。"""
    if _PROXY:
        handler = urllib.request.ProxyHandler({"http": _PROXY, "https": _PROXY})
        return urllib.request.build_opener(handler)
    return urllib.request.build_opener()


_OPENER = _build_opener()


def fetch_bytes(url, timeout=60, retries=2):
    """下载 URL 返回 bytes；404 返回 None；其它错误重试后返回 None

    通过 _OPENER 走环境变量 HTTPS_PROXY/HTTP_PROXY 指定的代理（若有）。
    """
    req = urllib.request.Request(url, headers={"User-Agent": "download_data/1.0"})
    for attempt in range(retries + 1):
        try:
            with _OPENER.open(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if attempt == retries:
                print(f"  ⚠ HTTP {e.code}: {url}")
                return None
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt == retries:
                print(f"  ⚠ 网络错误: {e}")
                return None
    return None


# ---------- 本地读取 ----------

def get_local_last_ts(csv_path):
    """读本地 1m CSV 最新时间戳(UTC datetime)，无数据返回 None

    本地首列为 timestamp 字符串 'YYYY-MM-DD HH:MM:SS+00:00'。
    大文件 seek 尾部读取，不全量加载。
    """
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return None
    try:
        size = csv_path.stat().st_size
        with open(csv_path, "rb") as f:
            f.seek(max(0, size - 64 * 1024))
            tail = f.read().decode("utf-8", errors="ignore")
        lines = [l for l in tail.splitlines() if l.strip()]
        if len(lines) < 2:
            return None
        ts_str = lines[-1].split(",")[0].strip().strip('"')
        return pd.to_datetime(ts_str, utc=True)
    except Exception as e:
        print(f"  ⚠ 读取本地最新时间失败 {csv_path}: {e}")
        return None


# ---------- Binance 原始 → 本地格式 ----------

def read_binance_csv(csvf):
    """读取 Binance 原始 K线 CSV → 原始列 DataFrame（含 open_time 毫秒）。

    data.binance.vision 的 zip 内 CSV 表头不统一：近期文件首行是
    表头(open_time,open,...)，历史文件无表头。
    通过检测首列是否为纯数字（open_time 毫秒时间戳）来区分：
      - 首列非数字 → 带表头，header=0 正确消费表头（不混入数据行）
      - 首列是数字 → 无表头，header=None + names 显式命名
    这样表头永远不会作为数据行混入，无需事后过滤。
    """
    raw = csvf.read().decode("utf-8", errors="ignore")
    first_line = raw.splitlines()[0] if raw else ""
    first_col = first_line.split(",")[0].strip().strip('"')
    if first_col.isdigit():
        # 无表头：首列是毫秒时间戳，显式命名列
        df = pd.read_csv(io.StringIO(raw), header=None, names=BINANCE_COLS)
    else:
        # 带表头：header=0 消费表头，列名对齐 BINANCE_COLS
        df = pd.read_csv(io.StringIO(raw), header=0)
        df.columns = BINANCE_COLS
    return df


def to_local_format(df):
    """Binance 原始 DataFrame → 本地格式（timestamp 为 UTC datetime）

    read_binance_csv 已正确处理表头，正常情况下数据行 open_time 全为数字。
    此处保留 fullmatch(r'\\d+') 过滤作为防御兜底：万一漏入空行/脏行（非表头），
    不会让 to_datetime 转换崩溃；被过滤掉的非数字行若 >0 则告警，让删除可见。
    """
    df = df.copy()
    mask = df["open_time"].astype(str).str.fullmatch(r"\d+")
    dropped = (~mask).sum()
    if dropped:
        print(f"  ⚠ 丢弃 {dropped} 行非数字 open_time（脏数据/空行）")
    df = df[mask]
    df["timestamp"] = pd.to_datetime(df["open_time"].astype("int64"),
                                    unit="ms", utc=True)
    return df[LOCAL_COLS]


# ---------- monthly bulk 下载 ----------

def fetch_monthly_zip(symbol, ym):
    """下载某月 zip，返回本地格式 DataFrame；404/不存在返回 None

    ym: 'YYYY-MM'
    URL: {VISION_MONTHLY}/{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-{YYYY-MM}.zip
    """
    url = (f"{VISION_MONTHLY}/{symbol}/{TIMEFRAME}/"
           f"{symbol}-{TIMEFRAME}-{ym}.zip")
    data = fetch_bytes(url)
    if data is None:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            name = zf.namelist()[0]
            with zf.open(name) as csvf:
                df = read_binance_csv(csvf)
        return to_local_format(df)
    except Exception as e:
        print(f"  ⚠ 解压失败 {ym}: {e}")
        return None


def fetch_daily_zip(symbol, ds):
    """下载某日 zip，返回本地格式 DataFrame；404/不存在返回 None

    ds: 'YYYY-MM-DD'
    URL: {VISION_DAILY}/{SYMBOL}/{INTERVAL}/{SYMBOL}-{INTERVAL}-{YYYY-MM-DD}.zip
    """
    url = (f"{VISION_DAILY}/{symbol}/{TIMEFRAME}/"
           f"{symbol}-{TIMEFRAME}-{ds}.zip")
    data = fetch_bytes(url)
    if data is None:
        return None
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            name = zf.namelist()[0]
            with zf.open(name) as csvf:
                df = read_binance_csv(csvf)
        return to_local_format(df)
    except Exception as e:
        print(f"  ⚠ 解压失败 {ds}: {e}")
        return None


def iter_months(start_ym, end_ym):
    """yield 'YYYY-MM' 从 start_ym 到 end_ym（含），ym 为 (year, month)"""
    y, m = start_ym
    ey, em = end_ym
    while (y, m) <= (ey, em):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m > 12:
            m, y = 1, y + 1


# ---------- REST API（补最新） ----------

def fetch_rest(symbol, start_ms, end_ms):
    """REST API 分页拉取 1m K线，返回本地格式 DataFrame 或 None

    从 start_ms 拉到 end_ms（UTC 毫秒），单次最多 REST_LIMIT 根。
    下载失败直接抛 RuntimeError，由调用方决定放弃/报错。
    """
    frames = []
    cur = start_ms
    while cur < end_ms:
        params = {
            "symbol": symbol, "interval": TIMEFRAME,
            "startTime": cur, "endTime": end_ms, "limit": REST_LIMIT,
        }
        url = REST_KLINES + "?" + urllib.parse.urlencode(params)
        data = fetch_bytes(url, timeout=30)
        if data is None:
            raise RuntimeError(f"REST 下载失败: {url}")
        try:
            rows = json.loads(data)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"REST 返回非 JSON: {url} ({e})")
        if not rows:
            break
        df = pd.DataFrame(rows, columns=BINANCE_COLS)
        frames.append(to_local_format(df))
        last_open = int(df["open_time"].iloc[-1])
        cur = last_open + 60_000  # 下一分钟
        if len(rows) < REST_LIMIT:
            break  # 已到最新
    if not frames:
        return None
    return pd.concat(frames, ignore_index=True)


# ---------- 合并保存 ----------

def merge_and_save(new_df, csv_path):
    """合并 new_df 与本地 CSV，去重排序，存为 UTC 格式。返回最终行数

    容错合并：本地旧 CSV 可能列集合与 LOCAL_COLS 不完全一致（历史格式差异、
    列名变动等）。此时按「timestamp + 两者共有列」对齐合并，缺列不补（NaN），
    绝不因列不匹配而抛异常丢弃旧数据（旧数据一旦丢失无法恢复）。
    若旧 CSV 连 timestamp 列都没有，才算无法合并，仅写新数据并告警。
    """
    frames = []
    if csv_path.exists():
        try:
            old = pd.read_csv(csv_path)
            if "timestamp" in old.columns:
                old["timestamp"] = pd.to_datetime(old["timestamp"], utc=True)
                # 只取 LOCAL_COLS 中存在的列；缺列不补（NaN），避免破坏类型
                keep = [c for c in LOCAL_COLS if c in old.columns]
                frames.append(old[keep])
            else:
                print(f"  ⚠ 旧 CSV 无 timestamp 列(无法合并，仅写新数据)")
        except Exception as e:
            print(f"  ⚠ 读取旧 CSV 失败(将仅写新数据): {e}")
    if new_df is not None and not new_df.empty:
        frames.append(new_df[LOCAL_COLS])
    if not frames:
        return 0
    combined = pd.concat(frames, ignore_index=True)
    combined["timestamp"] = pd.to_datetime(combined["timestamp"], utc=True)
    combined = (combined.drop_duplicates(subset=["timestamp"], keep="last")
                        .sort_values("timestamp").reset_index(drop=True))
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    save = combined.copy()
    save["timestamp"] = save["timestamp"].dt.strftime(TS_FMT)
    save.to_csv(csv_path, index=False)
    return len(combined)


# ---------- 单 symbol 编排 ----------

def download_symbol(symbol, data_dir, start, now):
    """对一个 symbol 跑完整 4 步流程（全程 UTC）"""
    csv_path = data_dir / TIMEFRAME / f"{symbol}_{TIMEFRAME}.csv"
    print(f"\n--- {symbol} → {csv_path} ---")

    # 步骤1: 检查本地最新时间(UTC) —— 每次下载都先读
    local_last = get_local_last_ts(csv_path)
    new_frames = []

    if local_last is None:
        # 步骤2: 无数据 → monthly bulk 拉历史（从 start 月到上月）
        print(f"  步骤1: 无本地数据")
        print(f"  步骤2: monthly bulk 回补 "
              f"{start.strftime('%Y-%m')} ~ 上月")
        last_complete_month = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
        m_start = start.replace(day=1)
        if m_start > last_complete_month:
            m_start = last_complete_month
        for ym in iter_months((m_start.year, m_start.month),
                              (last_complete_month.year,
                               last_complete_month.month)):
            df = fetch_monthly_zip(symbol, ym)
            if df is not None:
                print(f"    月度 {ym}: {len(df)} 条")
                new_frames.append(df)
            else:
                print(f"    月度 {ym}: 无（未发布）")
        latest = (pd.concat(new_frames)["timestamp"].max()
                  if new_frames else None)
    else:
        # 有本地数据：跳过 monthly，直接进步骤3 增量补最新
        print(f"  步骤1: 本地最新 {local_last.strftime('%Y-%m-%d %H:%M UTC')}")
        latest = local_last

    # 步骤3a: daily bulk 补到最新可用日（vision 每日 T-1 发布，到 UTC 昨天）
    # 起点取 monthly/本地最新时间的次日；仅覆盖「未完成月份里已结束的日期」。
    # daily 优先于 REST：daily 拿得到就不再用 REST，拿不到(今日未发布)才走 REST。
    yesterday = now.date() - timedelta(days=1)
    if latest is not None:
        day_start = (latest + pd.Timedelta(minutes=1)).date()
    else:
        day_start = start.date()
    if day_start <= yesterday:
        print(f"  步骤3a: daily bulk 补 {day_start} ~ {yesterday}")
        d = day_start
        while d <= yesterday:
            ds = d.strftime("%Y-%m-%d")
            df = fetch_daily_zip(symbol, ds)
            if df is not None:
                print(f"    日度 {ds}: {len(df)} 条")
                new_frames.append(df)
            else:
                print(f"    日度 {ds}: 无（未发布）")
            d += timedelta(days=1)

    # 计算 daily 覆盖后的最新时间，作为 REST 起点
    if new_frames:
        latest = pd.concat(new_frames)["timestamp"].max()
    elif latest is None:
        latest = start

    # 步骤3b: REST 补到当前（daily 不存在的最新一段，即今日未发布数据）
    # 下载前再次确认最新时间，REST 起点用 daily 后的最新时间。
    rest_start = latest + pd.Timedelta(minutes=1)
    rest_start_ms = int(rest_start.timestamp() * 1000)
    now_ms = int(now.timestamp() * 1000)
    if rest_start_ms < now_ms:
        print(f"  步骤3b: REST 补最新 "
              f"{rest_start.strftime('%Y-%m-%d %H:%M UTC')} ~ "
              f"{now.strftime('%Y-%m-%d %H:%M UTC')}")
        try:
            rest_df = fetch_rest(symbol, rest_start_ms, now_ms)
        except RuntimeError as e:
            # REST 失败 → 放弃该 symbol，已下载的 daily/monthly 仍合并保存
            print(f"  ❌ {symbol}: {e}（放弃 REST，回退保存已下载部分）")
            merged = pd.concat(new_frames, ignore_index=True) if new_frames else None
            total = merge_and_save(merged, csv_path)
            print(f"  步骤4: 已保存 {total} 条（REST 段缺失）")
            return False
        if rest_df is not None and not rest_df.empty:
            print(f"    REST: {len(rest_df)} 条")
            new_frames.append(rest_df)
        else:
            print(f"    REST: 无新数据")
    else:
        print(f"  步骤3b: 已是最新，无需 REST 补充")

    # 步骤4: 合并保存(UTC)
    merged = pd.concat(new_frames, ignore_index=True) if new_frames else None
    total = merge_and_save(merged, csv_path)
    if total:
        print(f"  步骤4: 合并完成，共 {total} 条 → {csv_path}")
    else:
        print(f"  步骤4: 无数据可写")
    return True


# ---------- main ----------

def parse_date(value):
    """解析 YYYYMMDD → UTC datetime"""
    return datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)


def load_symbols_from_file(path):
    """从 symbols.yaml 读取代币清单（纯文本解析，不依赖 PyYAML）

    格式:
        symbols:
          - BTCUSDT
          - ETHUSDT
    缺失文件或无内容返回 []。
    """
    p = Path(path)
    if not p.is_file():
        return []
    symbols = []
    in_list = False
    for line in p.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("symbols:"):
            in_list = True
            continue
        if in_list:
            if stripped.startswith("- "):
                symbols.append(stripped[2:].strip().strip('"').strip("'"))
            elif ":" in stripped and not stripped.startswith("-"):
                # 进入下一个顶层 key，列表结束
                in_list = False
    return [s.upper() for s in symbols if s]


def main():
    ap = argparse.ArgumentParser(description="下载并合并 Binance 1m K线数据(UTC)")
    ap.add_argument("--symbols", default=None,
                    help="代币列表，逗号分隔（如 BTCUSDT,ETHUSDT）")
    ap.add_argument("--symbols-file", default=None,
                    help="代币清单 YAML 文件路径（sync-exee.py 生成的 symbols.yaml），优先于 --symbols")
    ap.add_argument("--data-dir", default="./data/klines",
                    help="K线根目录（默认 ./data/klines，对齐 settings.csv_dir）")
    ap.add_argument("--start", default="20240101",
                    help="无本地数据时的回补起点 YYYYMMDD（默认 20240101）")
    args = ap.parse_args()

    # 代币来源：--symbols-file 优先，回退 --symbols
    if args.symbols_file:
        symbols = load_symbols_from_file(args.symbols_file)
        if not symbols:
            sys.exit(f"❌ {args.symbols_file} 中未读到代币")
        print(f"代币来源: {args.symbols_file}")
    elif args.symbols:
        symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        print("代币来源: --symbols")
    else:
        sys.exit("❌ 需指定 --symbols-file 或 --symbols")

    if not symbols:
        sys.exit("❌ 未指定 symbols")
    data_dir = Path(args.data_dir)
    start = parse_date(args.start)
    now = datetime.now(timezone.utc)

    print(f"=== download_data 开始，{len(symbols)} 个 symbol，"
          f"now={now.strftime('%Y-%m-%d %H:%M UTC')} ===")

    success, fail = 0, 0
    for sym in symbols:
        try:
            ok = download_symbol(sym, data_dir, start, now)
            if ok:
                success += 1
            else:
                fail += 1
        except Exception as e:
            print(f"  ❌ {sym} 异常: {e}")
            fail += 1

    print(f"\n=== 完成: {success} 成功, {fail} 失败 ===")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
