#!/usr/bin/env python3
"""calc_data_requirements.py — K线数据需求计算 (Phase 1.6)

从策略配置中提取技术指标参数，计算至少需要提前准备多少天 K 线数据。
对比本地已有数据，输出 gap 分析。

用法:
    python3 calc_data_requirements.py --strategy-dir ./strategies/ema_rsi
    python3 calc_data_requirements.py --strategy-dir ./strategies/ema_rsi --symbol BTCUSDT
    python3 calc_data_requirements.py --strategy-dir ./strategies/ema_rsi --start 20260601 --end 20260701
    python3 calc_data_requirements.py --strategy-dir ./strategies/ema_rsi --json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# ----- YAML parsing (self-contained) -----

def _parse_yaml(path: str) -> dict:
    try:
        import yaml
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        return _simple_parse(path)


def _simple_parse(path: str) -> dict:
    result = {}
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            s = line.rstrip()
            if not s or s.lstrip().startswith('#'):
                continue
            if line[0] not in (' ', '\t') and ':' in s:
                k, _, v = s.partition(':')
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if v:
                    result[k] = _coerce(v)
                else:
                    result[k] = {}
    return result


def _coerce(v: str):
    if v.lower() in ('true', 'yes'):
        return True
    if v.lower() in ('false', 'no'):
        return False
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


# ----- timeframe → minutes -----

TF_MINUTES = {
    "1m": 1, "3m": 3, "5m": 5, "15m": 15, "30m": 30,
    "1h": 60, "2h": 120, "4h": 240, "6h": 360, "8h": 480, "12h": 720,
    "1d": 1440, "1w": 10080,
}


def _tf_to_minutes(tf: str) -> int:
    tf = tf.strip().lower()
    if tf in TF_MINUTES:
        return TF_MINUTES[tf]
    m = re.match(r'^(\d+)\s*(m|min|h|hour|d|day|w|week)$', tf)
    if m:
        val, unit = int(m.group(1)), m.group(2)
        if unit in ('m', 'min'):
            return val
        if unit in ('h', 'hour'):
            return val * 60
        if unit in ('d', 'day'):
            return val * 1440
        if unit in ('w', 'week'):
            return val * 10080
    return 0


# ----- indicator period extraction -----

_PERIOD_KEYWORDS = [
    "period", "length", "window", "lookback",
    "fast", "slow", "signal", "short", "long",
    "ma", "ema", "sma", "atr", "rsi", "obv",
    "bb", "macd", "adx", "cci", "stoch", "vwap",
]


def _is_period_key(key: str) -> bool:
    kl = key.lower()
    return any(kw in kl for kw in _PERIOD_KEYWORDS)


def extract_max_period(config: dict) -> int:
    """从策略配置中提取最大技术指标周期值"""
    best = 0

    def _walk(obj, depth=0):
        nonlocal best
        if depth > 3:
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if isinstance(v, (int, float)) and _is_period_key(k):
                    best = max(best, int(v))
                elif isinstance(v, dict):
                    _walk(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item, depth + 1)

    params = config.get("params", {})
    if isinstance(params, dict):
        _walk(params)
    _walk(config)
    return best


# ----- local K-line check -----

def check_local_kline(symbol: str, data_dir: str) -> dict:
    info = {"symbol": symbol, "csv_exists": False, "first_date": None, "last_date": None}
    dp = Path(data_dir)

    csv_file = None
    for pat in [f"{symbol}.csv", f"{symbol}_*.csv"]:
        m = list(dp.glob(pat))
        if m:
            csv_file = m[0]
            break
    if not csv_file:
        sd = dp / symbol
        m = list(sd.glob("*.csv")) if sd.is_dir() else []
        csv_file = m[0] if m else None
    if not csv_file:
        m = list(dp.rglob(f"{symbol}*.csv"))
        csv_file = m[0] if m else None
    if not csv_file:
        return info

    info["csv_exists"] = True
    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            f.readline()
            first = f.readline().strip()
            f.seek(0, 2)
            sz = f.tell()
            f.seek(max(0, sz - 4096))
            last = f.read().strip().split('\n')[-1]
        info["first_date"] = _extract_date(first)
        info["last_date"] = _extract_date(last)
    except (IOError, OSError):
        pass
    return info


def _extract_date(line: str) -> Optional[str]:
    if not line:
        return None
    d = line.split(',')[0].strip().strip('"')
    if len(d) == 10 and d[4] == '-':
        return d.replace('-', '')[:8]
    if len(d) == 8 and d.isdigit():
        return d
    try:
        ts = int(d)
        if ts > 1e12:
            ts //= 1000
        return datetime.fromtimestamp(ts).strftime('%Y%m%d')
    except (ValueError, OSError):
        return d[:8] if len(d) >= 8 else None


# ----- core -----

def calculate(strategy_dir: str, symbol: str = "",
              start_date: str = "", end_date: str = "",
              kline_data_dir: str = "./data/klines") -> dict:
    sdir = Path(strategy_dir)
    if not sdir.is_dir():
        return {"error": f"策略目录不存在: {strategy_dir}"}

    name = sdir.name

    # 找配置：v3.7 单一事实来源是 strategies/<name>/overrides/<SYMBOL>.yaml。
    # 指定 --symbol 时读该 symbol 的那份；否则取 overrides/ 下第一份作为代表
    # （指标周期在同策略各 symbol 间通常一致，仅用于估算数据天数）。
    odir = sdir / "overrides"
    override_symbols = sorted(
        f.stem for f in odir.glob("*.yaml")
        if f.is_file() and not f.name.startswith(".")
    ) if odir.is_dir() else []

    cfg_path = None
    if symbol:
        c = odir / f"{symbol}.yaml"
        if c.is_file():
            cfg_path = str(c)
        else:
            return {
                "error": f"缺少 per-symbol 配置: {c}",
                "strategy_name": name,
                "available_symbols": override_symbols,
            }
    elif override_symbols:
        cfg_path = str(odir / f"{override_symbols[0]}.yaml")

    if not cfg_path:
        return {
            "error": f"未找到 per-symbol 配置（{odir}/<SYMBOL>.yaml 不存在）",
            "strategy_name": name,
        }

    data = _parse_yaml(cfg_path)
    sc = data.get(name, data)
    if not isinstance(sc, dict):
        sc = data

    # symbols 取 overrides/ 文件名全集，而非单份配置里的 symbols 字段
    # （每份 overrides 只描述自己那一个 symbol）
    if symbol:
        symbols = [symbol]
    elif override_symbols:
        symbols = override_symbols
    else:
        symbols = sc.get("symbols", [])
        if isinstance(symbols, str):
            symbols = [s.strip() for s in symbols.split(',')]

    timeframes = sc.get("timeframes", ["1h"])
    if isinstance(timeframes, str):
        timeframes = [t.strip() for t in timeframes.split(',')]

    max_p = extract_max_period(sc)
    if max_p == 0:
        max_p = 50

    # 最坏 timeframe
    worst_tf, worst_min = "1h", 60
    for tf in timeframes:
        m = _tf_to_minutes(tf)
        if m > worst_min:
            worst_min, worst_tf = m, tf

    candles = max_p
    min_days = max(1, (candles * worst_min + 1439) // 1440)
    rec_days = int(min_days * 1.2) + 1

    # 本地数据
    ks = {}
    for sym in symbols:
        ks[sym] = check_local_kline(sym, kline_data_dir)

    sufficient = True
    gaps = []

    req_start = ""
    if start_date:
        try:
            bt = datetime.strptime(start_date, '%Y%m%d')
            req_start = (bt - timedelta(days=rec_days)).strftime('%Y%m%d')
        except ValueError:
            pass

    for sym in symbols:
        k = ks[sym]
        if not k["csv_exists"]:
            sufficient = False
            gaps.append(f"{sym}: 无本地K线数据")
        elif req_start and k["first_date"] and k["first_date"] > req_start:
            sufficient = False
            gaps.append(f"{sym}: 数据从{k['first_date']}开始, 需要从{req_start}开始(提前{rec_days}天)")

    return {
        "strategy_name": name, "config_path": cfg_path,
        "symbols": symbols, "timeframes": timeframes,
        "max_period": max_p, "worst_timeframe": worst_tf,
        "worst_timeframe_minutes": worst_min,
        "min_candles_needed": candles,
        "min_data_days": min_days,
        "recommended_data_days": rec_days,
        "kline_status": ks,
        "data_sufficient": sufficient,
        "gap_summary": "; ".join(gaps) if gaps else "数据充足",
    }


# ----- output -----

def format_terminal(r: dict) -> str:
    if "error" in r:
        return f"❌ {r['error']}"

    lines = [
        "", "=" * 60,
        "  K线数据需求分析",
        "=" * 60,
        f"  策略:       {r['strategy_name']}",
        f"  配置:       {r['config_path']}",
        f"  代币:       {', '.join(r['symbols'])}",
        f"  时间框架:   {', '.join(r['timeframes'])}",
        "",
        f"  最大指标周期: {r['max_period']} 根K线",
        f"  最坏时间框架: {r['worst_timeframe']} ({r['worst_timeframe_minutes']}min/根)",
        f"  最少需要K线:  {r['min_candles_needed']} 根",
        f"  最少数据天数: {r['min_data_days']} 天",
        f"  建议准备天数: {r['recommended_data_days']} 天 (+20% 安全边际)",
        "", "  --- 本地K线数据状态 ---",
    ]

    for sym, k in r.get("kline_status", {}).items():
        if k["csv_exists"]:
            fd = k.get("first_date") or "?"
            ld = k.get("last_date") or "?"
            lines.append(f"  {sym}: ✅ {fd} ~ {ld}")
        else:
            lines.append(f"  {sym}: ❌ 无数据")

    lines.extend([
        "",
        f"  数据充足: {'✅ 是' if r['data_sufficient'] else '❌ 否'}",
        f"  Gap: {r['gap_summary']}",
        "=" * 60,
    ])
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description="K线数据需求计算")
    p.add_argument("--strategy-dir", required=True, help="策略目录路径")
    p.add_argument("--symbol", default="", help="指定代币")
    p.add_argument("--start", default="", help="回测开始日期 (YYYYMMDD)")
    p.add_argument("--end", default="", help="回测结束日期 (YYYYMMDD)")
    p.add_argument("--kline-data-dir", default="./data/klines")
    p.add_argument("--json", action="store_true")
    p.add_argument("--output", default="")
    args = p.parse_args()

    r = calculate(args.strategy_dir, args.symbol, args.start, args.end, args.kline_data_dir)

    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    else:
        print(format_terminal(r))

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(r, f, indent=2, ensure_ascii=False, default=str)

    if r.get("data_sufficient") is False:
        sys.exit(1)


if __name__ == "__main__":
    main()
