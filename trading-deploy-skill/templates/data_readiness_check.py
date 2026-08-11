#!/usr/bin/env python3
"""data_readiness_check.py — K线数据就绪检查 + loop (Phase 3)"""

import argparse, json, os, sys
from datetime import datetime, timedelta
from pathlib import Path

def check_kline(symbol: str, data_dir: str) -> dict:
    dp = Path(data_dir)
    info = {"symbol": symbol, "csv_exists": False, "first_date": None, "last_date": None, "row_estimate": 0}
    csv_file = None
    for pat in [f"{symbol}.csv", f"{symbol}_*.csv"]:
        m = list(dp.glob(pat))
        if m: csv_file = m[0]; break
    if not csv_file:
        sd = dp / symbol
        m = list(sd.glob("*.csv")) if sd.is_dir() else []
        if m: csv_file = m[0]
    if not csv_file: return info
    info["csv_exists"] = True
    try:
        with open(csv_file) as f:
            f.readline(); first = f.readline().strip()
            f.seek(0, 2); sz = f.tell(); f.seek(max(0, sz - 4096))
            last = f.read().strip().split('\n')[-1]
        d1 = first.split(',')[0].strip().strip('"')
        d2 = last.split(',')[0].strip().strip('"')
        if len(d1) == 10 and d1[4] == '-': d1 = d1.replace('-', '')[:8]
        if len(d2) == 10 and d2[4] == '-': d2 = d2.replace('-', '')[:8]
        info["first_date"] = d1; info["last_date"] = d2
        info["row_estimate"] = max(0, sz // 80)
    except: pass
    return info

def check_all(symbols: list, data_dir: str, required_days: int, start_date: str = "") -> dict:
    results = {}
    all_ok = True
    gaps = []
    for sym in symbols:
        k = check_kline(sym, data_dir)
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
            except: pass
        if k["row_estimate"] < required_days * 1440:  # rough: 1 row/min
            all_ok = False; gaps.append(f"{sym}: only ~{k['row_estimate']} rows, need ~{required_days * 1440}")
    return {"all_ok": all_ok, "gaps": gaps, "details": results, "required_days": required_days}

def main():
    p = argparse.ArgumentParser(description="K-line data readiness check")
    p.add_argument("--strategy-dir", required=True)
    p.add_argument("--symbols", default="")
    p.add_argument("--kline-data-dir", default="./data/strategies/1m")
    p.add_argument("--required-days", type=int, default=30)
    p.add_argument("--start-date", default="")
    p.add_argument("--json", action="store_true")
    p.add_argument("--max-retries", type=int, default=5, help="max loop retries")
    args = p.parse_args()

    symbols = [s.strip() for s in args.symbols.split(',')] if args.symbols else []

    if not symbols:
        # try to read from config
        sdir = Path(args.strategy_dir)
        for cn in ["config.test.yaml", "config.yaml"]:
            if (sdir / cn).is_file():
                try:
                    import yaml
                    with open(sdir / cn) as f: cfg = yaml.safe_load(f) or {}
                    sc = cfg.get(sdir.name, cfg)
                    if isinstance(sc, dict):
                        sym = sc.get("symbols", [])
                        symbols = [s.strip() for s in sym.split(',')] if isinstance(sym, str) else sym
                except: pass
                break

    if not symbols:
        print(json.dumps({"error": "no symbols found"}) if args.json else "ERROR: no symbols")
        return 1

    result = check_all(symbols, args.kline_data_dir, args.required_days, args.start_date)

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print("\n=== K-line Data Readiness ===")
        print(f"Required days: {args.required_days}")
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
            print(f"\nAction needed: download missing data, then re-run this check")
            print(f"Max retries: {args.max_retries}")

    return 0 if result["all_ok"] else 1

if __name__ == "__main__": sys.exit(main())
