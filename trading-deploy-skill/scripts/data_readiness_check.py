#!/usr/bin/env python3
"""data_readiness_check.py — K线数据就绪检查 + loop (Phase 3)"""

import argparse, json, os, sys
from datetime import datetime, timedelta
from pathlib import Path

def check_kline(symbol: str, data_dir: str, timeframe: str = "") -> dict:
    dp = Path(data_dir)
    info = {"symbol": symbol, "csv_exists": False, "first_date": None, "last_date": None,
            "row_estimate": 0, "csv_path": None}
    csv_file = None
    # 模板 K 线布局是按周期分目录: {csv_dir}/{tf}/{SYMBOL}_{tf}.csv
    if timeframe:
        for cand in [dp / timeframe / f"{symbol}_{timeframe}.csv",
                     dp / timeframe / f"{symbol}.csv"]:
            if cand.is_file(): csv_file = cand; break
    if not csv_file:
        for pat in [f"{symbol}.csv", f"{symbol}_*.csv"]:
            m = sorted(dp.glob(pat))
            if m: csv_file = m[0]; break
    if not csv_file:
        sd = dp / symbol
        m = sorted(sd.glob("*.csv")) if sd.is_dir() else []
        if m: csv_file = m[0]
    if not csv_file:
        # 兜底递归搜索
        m = sorted(dp.rglob(f"{symbol}*.csv")) if dp.is_dir() else []
        if m: csv_file = m[0]
    if not csv_file: return info
    info["csv_exists"] = True
    info["csv_path"] = str(csv_file)
    try:
        with open(csv_file) as f:
            f.readline(); first = f.readline().strip()
            f.seek(0, 2); sz = f.tell(); f.seek(max(0, sz - 4096))
            tail = f.read().strip().split('\n')
            last = tail[-1] if tail else ""
        d1 = _norm_date(first)
        d2 = _norm_date(last)
        info["first_date"] = d1; info["last_date"] = d2
        # 按实际行长估算行数，而不是硬编码 80 字节
        avg = max(1, len(first) + 1) if first else 80
        info["row_estimate"] = max(0, sz // avg - 1)
    except (OSError, ValueError): pass
    return info


def _norm_date(csv_line: str):
    """从 CSV 行首列取日期，统一成 YYYYMMDD。

    模板 CSV 首列形如 "2026-06-02 00:00:00+00:00"（长度 25），
    只判 len==10 会漏掉它并产出 "2026-06-" 这种非法值，
    使后续所有日期比较静默失效。
    """
    if not csv_line: return None
    d = csv_line.split(',')[0].strip().strip('"')
    if not d: return None
    if len(d) >= 10 and d[4] == '-' and d[7] == '-':
        head = d[:10]
        if head[:4].isdigit() and head[5:7].isdigit() and head[8:10].isdigit():
            return head.replace('-', '')
    if len(d) == 8 and d.isdigit(): return d
    try:
        ts = int(d)
        if ts > 1e12: ts = ts // 1000
        return datetime.fromtimestamp(ts).strftime('%Y%m%d')
    except (ValueError, OSError):
        return None


def _bars_per_day(timeframe: str) -> int:
    """该周期一天有多少根 K 线（用于把"需要 N 天数据"换算成行数）"""
    tf = (timeframe or "1h").strip().lower()
    try:
        num = int(''.join(c for c in tf if c.isdigit()) or 1)
    except ValueError:
        num = 1
    if tf.endswith('m'): per_day = 1440 // max(1, num)
    elif tf.endswith('h'): per_day = 24 // max(1, num)
    elif tf.endswith('d'): per_day = max(1, 1 // max(1, num))
    else: per_day = 24
    return max(1, per_day)


def check_all(symbols: list, data_dir: str, required_days: int, start_date: str = "",
              timeframe: str = "") -> dict:
    results = {}
    all_ok = True
    gaps = []
    # 行数下限按实际周期换算。早期版本固定用 1440 行/天（1m 口径），
    # 于是 8h 策略的数据永远"不足"，把真实 gap 淹没在假警告里。
    per_day = _bars_per_day(timeframe)
    min_rows = required_days * per_day
    for sym in symbols:
        k = check_kline(sym, data_dir, timeframe)
        results[sym] = k
        if not k["csv_exists"]:
            all_ok = False; gaps.append(f"{sym}: no CSV"); continue
        if start_date and k["first_date"]:
            try:
                bt = datetime.strptime(start_date, '%Y%m%d')
                need = bt - timedelta(days=required_days)
                fd = datetime.strptime(k["first_date"], '%Y%m%d')
                if fd > need:
                    all_ok = False
                    gaps.append(f"{sym}: data starts {k['first_date']}, need {need.strftime('%Y%m%d')}")
            except ValueError: pass
        if k["row_estimate"] < min_rows:
            all_ok = False
            gaps.append(f"{sym}: only ~{k['row_estimate']} rows, need ~{min_rows} ({timeframe or '1h'})")
    return {"all_ok": all_ok, "gaps": gaps, "details": results,
            "required_days": required_days, "timeframe": timeframe or "1h",
            "min_rows": min_rows}

def main():
    p = argparse.ArgumentParser(description="K-line data readiness check")
    p.add_argument("--strategy-dir", required=True)
    p.add_argument("--symbols", default="")
    p.add_argument("--kline-data-dir", default="./data/klines")
    p.add_argument("--timeframe", default="", help="K-line timeframe, e.g. 8h (default: read from overrides)")
    p.add_argument("--required-days", type=int, default=30)
    p.add_argument("--start-date", default="")
    p.add_argument("--json", action="store_true")
    p.add_argument("--max-retries", type=int, default=5, help="max loop retries")
    args = p.parse_args()

    sdir = Path(args.strategy_dir)
    symbols = [s.strip() for s in args.symbols.split(',') if s.strip()] if args.symbols else []
    timeframe = args.timeframe

    # v3.7 单一事实来源: strategies/<name>/overrides/<SYMBOL>.yaml
    # symbols 取该目录下的文件名全集（每份 overrides 只描述一个 symbol，
    # 读单份的 symbols 字段会漏掉其余标的）
    odir = sdir / "overrides"
    override_symbols = sorted(
        f.stem for f in odir.glob("*.yaml")
        if f.is_file() and not f.name.startswith('.')
    ) if odir.is_dir() else []

    if not symbols:
        symbols = override_symbols

    if not timeframe and override_symbols:
        # 主周期决定数据行数要求，从代表性 overrides 读取
        rep = odir / f"{(symbols[0] if symbols else override_symbols[0])}.yaml"
        if not rep.is_file():
            rep = odir / f"{override_symbols[0]}.yaml"
        try:
            import yaml
            with open(rep) as f: cfg = yaml.safe_load(f) or {}
            sc = cfg.get(sdir.name, cfg)
            if isinstance(sc, dict):
                tf = sc.get("timeframes", [])
                if isinstance(tf, str):
                    tf = [t.strip() for t in tf.split(',') if t.strip()]
                if tf: timeframe = tf[0]
        except (ImportError, OSError, ValueError): pass

    if not symbols:
        msg = f"no symbols found (looked in {odir}/<SYMBOL>.yaml)"
        print(json.dumps({"error": msg}) if args.json else f"ERROR: {msg}")
        return 1

    result = check_all(symbols, args.kline_data_dir, args.required_days,
                       args.start_date, timeframe)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print("\n=== K-line Data Readiness ===")
        print(f"Timeframe:     {result['timeframe']}")
        print(f"Required days: {args.required_days} (~{result['min_rows']} rows)")
        for sym, k in result["details"].items():
            if k["csv_exists"]:
                print(f"  {sym}: OK  {k['first_date']} ~ {k['last_date']}  (~{k['row_estimate']} rows)")
            else:
                print(f"  {sym}: MISSING")
        if result["all_ok"]:
            print("\nAll data ready.")
        else:
            print(f"\nGaps ({len(result['gaps'])}):")
            for g in result["gaps"]: print(f"  - {g}")
            print("\nAction needed: download missing data, then re-run this check")
            print(f"Max retries: {args.max_retries}")

    return 0 if result["all_ok"] else 1

if __name__ == "__main__": sys.exit(main())
