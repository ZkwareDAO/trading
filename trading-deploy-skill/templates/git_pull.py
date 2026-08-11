#!/usr/bin/env python3
"""git_pull.py — 策略代码拉取 + AI 分析 (Phase 2)"""

import argparse, json, os, subprocess, sys
from pathlib import Path

def _parse_yaml(path: str) -> dict:
    try:
        import yaml
        with open(path) as f: return yaml.safe_load(f) or {}
    except ImportError: return {}

def clone_or_pull(git_url: str, target_dir: str, branch: str = "main") -> bool:
    target = Path(target_dir)
    if (target / ".git").is_dir():
        print(f"git pull (branch: {branch})...")
        r = subprocess.run(["git", "-C", str(target), "pull", "origin", branch], capture_output=True, text=True)
    else:
        target.mkdir(parents=True, exist_ok=True)
        print(f"git clone {git_url} -> {target_dir}")
        r = subprocess.run(["git", "clone", "-b", branch, git_url, str(target)], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"ERROR: {r.stderr.strip()}", file=sys.stderr)
        return False
    print("OK")
    return True

def list_strategies(strategies_dir: str) -> list:
    sdir = Path(strategies_dir)
    if not sdir.is_dir(): return []
    result = []
    for d in sorted(sdir.iterdir()):
        if not d.is_dir() or d.name.startswith('.'): continue
        info = {"name": d.name, "symbols": [], "timeframes": [], "configs_found": 0}
        for cn in ["config.test.yaml", "config.yaml"]:
            c = d / cn
            if c.is_file(): info["config_path"] = str(c); info["configs_found"] = 1; break
        if not info.get("config_path"):
            cd = d / "config"
            if cd.is_dir():
                for c in sorted(cd.glob("*.yaml")): info["config_path"] = str(c); info["configs_found"] = 1; break
        if info.get("config_path"):
            try:
                cfg = _parse_yaml(info["config_path"])
                sc = cfg.get(d.name, cfg)
                if isinstance(sc, dict):
                    sym = sc.get("symbols", [])
                    info["symbols"] = [s.strip() for s in sym.split(',')] if isinstance(sym, str) else sym
                    tf = sc.get("timeframes", [])
                    info["timeframes"] = [t.strip() for t in tf.split(',')] if isinstance(tf, str) else tf
            except: pass
        info["has_strategy_py"] = (d / "strategy.py").is_file()
        core = list(d.glob("*_core.py"))
        info["core_file"] = core[0].name if core else None
        info["file_count"] = sum(1 for _ in d.rglob("*.py") if _.is_file())
        result.append(info)
    return result

def analyze_strategy(strategy_dir: str) -> dict:
    sdir = Path(strategy_dir)
    name = sdir.name
    r = {"strategy_name": name, "issues": [], "warnings": []}
    config_path = None
    for cn in ["config.test.yaml", "config.yaml"]:
        if (sdir / cn).is_file(): config_path = str(sdir / cn); break
    if not config_path:
        cd = sdir / "config"
        if cd.is_dir():
            for c in sorted(cd.glob("*.yaml")): config_path = str(c); break
    if not config_path: r["issues"].append("no config"); return r
    r["config_path"] = config_path
    cfg = _parse_yaml(config_path)
    sc = cfg.get(name, cfg)
    if not isinstance(sc, dict): sc = cfg
    sym = sc.get("symbols", [])
    r["symbols"] = [s.strip() for s in sym.split(',')] if isinstance(sym, str) else sym
    tf = sc.get("timeframes", [])
    r["timeframes"] = [t.strip() for t in tf.split(',')] if isinstance(tf, str) else tf
    r["direction"] = sc.get("direction", "neutral")
    r["params"] = sc.get("params", {})
    r["has_strategy_py"] = (sdir / "strategy.py").is_file()
    core = list(sdir.glob("*_core.py"))
    r["core_file"] = core[0].name if core else None
    if not r["has_strategy_py"]: r["issues"].append("strategy.py missing")
    if not r["core_file"]: r["warnings"].append("no *_core.py")
    indicators = []
    for k, v in r["params"].items():
        if any(kw in k.lower() for kw in ["period", "length", "window", "fast", "slow", "ma", "ema"]):
            indicators.append({"param": k, "value": v})
    r["indicators"] = indicators
    r["capital"] = sc.get("capital", "not set")
    r["leverage"] = sc.get("leverage", "not set")
    return r

def format_analysis(r: dict) -> str:
    lines = ["", "=" * 60, f"  AI Strategy Analysis — {r['strategy_name']}", "=" * 60]
    if r.get("config_path"): lines.append(f"  Config:     {r['config_path']}")
    lines.append(f"  Symbols:    {', '.join(r.get('symbols', []))}")
    lines.append(f"  Timeframes: {', '.join(r.get('timeframes', []))}")
    lines.append(f"  Direction:  {r.get('direction', 'neutral')}")
    inds = r.get("indicators", [])
    if inds:
        lines.append(""); lines.append("  Indicators:")
        for i in inds: lines.append(f"    {i['param']}={i['value']}")
    lines.append(f"  Capital: {r.get('capital', '?')}"); lines.append(f"  Leverage: {r.get('leverage', '?')}")
    code = [f"strategy.py {'OK' if r.get('has_strategy_py') else 'MISSING'}"]
    if r.get('core_file'): code.append(f"{r['core_file']} OK")
    lines.append(f"  Code: {' | '.join(code)}")
    for i in r.get("issues", []): lines.append(f"  [ISSUE] {i}")
    for w in r.get("warnings", []): lines.append(f"  [WARN] {w}")
    lines.append("=" * 60)
    return '\n'.join(lines)

def main():
    p = argparse.ArgumentParser(description="git pull + strategy analysis")
    p.add_argument("--git-url", default="")
    p.add_argument("--strategies-dir", default="./strategies")
    p.add_argument("--branch", default="main")
    p.add_argument("--strategy", default="")
    p.add_argument("--analyze", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--list", action="store_true")
    args = p.parse_args()
    git_url = args.git_url or os.environ.get("STRATEGIES_GIT_URL", "")
    if args.list:
        strategies = list_strategies(args.strategies_dir)
        if args.json: print(json.dumps(strategies, indent=2, ensure_ascii=False))
        else:
            print(f"\nStrategies ({len(strategies)}):")
            for s in strategies:
                sym = ','.join(s.get('symbols', []))
                cfg = os.path.basename(s.get('config_path', 'no config'))
                print(f"  {s['name']:<20s} {cfg:<20s} | symbols: {sym}")
        return 0
    if args.analyze:
        if not args.strategy: print("need --strategy", file=sys.stderr); return 1
        r = analyze_strategy(os.path.join(args.strategies_dir, args.strategy))
        print(json.dumps(r, indent=2, ensure_ascii=False) if args.json else format_analysis(r))
        return 0
    if not git_url: print("need STRATEGIES_GIT_URL or --git-url"); return 1
    if not clone_or_pull(git_url, args.strategies_dir, args.branch): return 1
    strategies = list_strategies(args.strategies_dir)
    if strategies:
        print(f"\nStrategies ({len(strategies)}):")
        for s in strategies:
            sym = ','.join(s.get('symbols', []))
            cfg = os.path.basename(s.get('config_path', 'no config'))
            print(f"  {s['name']:<20s} {cfg:<20s} | symbols: {sym}")
    return 0

if __name__ == "__main__": sys.exit(main())
