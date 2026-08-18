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

def list_override_symbols(strategy_dir) -> list:
    """列出 strategies/<name>/overrides/ 下的 symbol 全集。

    v3.7 起策略参数按 (策略, 代币) 拆分成 overrides/<SYMBOL>.yaml，
    文件名即该策略实际配好的标的清单。
    """
    odir = Path(strategy_dir) / "overrides"
    if not odir.is_dir(): return []
    return sorted(f.stem for f in odir.glob("*.yaml")
                  if f.is_file() and not f.name.startswith('.'))

def resolve_params_config(strategy_dir, symbol: str = "") -> str:
    """定位策略参数文件（v3.7 单一事实来源）。

    symbol 为空时取 overrides/ 下第一份作为代表（用于读 timeframes/params
    等在同策略各 symbol 间一致的元信息）。找不到返回空串。
    """
    odir = Path(strategy_dir) / "overrides"
    if symbol:
        c = odir / f"{symbol}.yaml"
        return str(c) if c.is_file() else ""
    for s in list_override_symbols(strategy_dir):
        c = odir / f"{s}.yaml"
        if c.is_file(): return str(c)
    return ""

def _extract_section(cfg: dict, name: str) -> dict:
    """取出策略配置段（overrides 文件顶层 key 为策略名）"""
    sc = cfg.get(name, cfg)
    return sc if isinstance(sc, dict) else cfg

def list_strategies(strategies_dir: str) -> list:
    sdir = Path(strategies_dir)
    if not sdir.is_dir(): return []
    result = []
    for d in sorted(sdir.iterdir()):
        if not d.is_dir() or d.name.startswith('.'): continue
        if d.name == "__pycache__": continue
        info = {"name": d.name, "symbols": [], "timeframes": [], "configs_found": 0}
        # symbols 来自 overrides/ 文件名，而非某一份配置里的 symbols 字段
        # （每份 overrides 只描述自己那一个 symbol，读单份会漏掉其余标的）
        info["symbols"] = list_override_symbols(d)
        info["configs_found"] = len(info["symbols"])
        cfg_path = resolve_params_config(d)
        if cfg_path:
            info["config_path"] = cfg_path
            try:
                sc = _extract_section(_parse_yaml(cfg_path), d.name)
                tf = sc.get("timeframes", [])
                info["timeframes"] = [t.strip() for t in tf.split(',')] if isinstance(tf, str) else tf
            except Exception: pass
        info["has_strategy_py"] = (d / "strategy.py").is_file()
        core = list(d.glob("*_core.py"))
        info["core_file"] = core[0].name if core else None
        info["file_count"] = sum(1 for _ in d.rglob("*.py") if _.is_file())
        result.append(info)
    return result

def analyze_strategy(strategy_dir: str, symbol: str = "") -> dict:
    sdir = Path(strategy_dir)
    name = sdir.name
    r = {"strategy_name": name, "issues": [], "warnings": []}
    r["symbols"] = list_override_symbols(sdir)
    config_path = resolve_params_config(sdir, symbol)
    if not config_path:
        if symbol:
            r["issues"].append(f"missing overrides/{symbol}.yaml")
        else:
            r["issues"].append("no per-symbol config under overrides/")
        return r
    r["config_path"] = config_path
    sc = _extract_section(_parse_yaml(config_path), name)
    tf = sc.get("timeframes", [])
    r["timeframes"] = [t.strip() for t in tf.split(',')] if isinstance(tf, str) else tf
    r["direction"] = sc.get("direction", "neutral")
    r["params"] = sc.get("params", {})
    # trading_mode 缺省时 run_strategy.py 按 live 处理：不显式配置就会下真单，
    # 必须在部署前让操作者看到实际生效的模式
    r["trading_mode"] = sc.get("trading_mode") or "live (default)"
    r["has_strategy_py"] = (sdir / "strategy.py").is_file()
    core = list(sdir.glob("*_core.py"))
    r["core_file"] = core[0].name if core else None
    if not r["has_strategy_py"]: r["issues"].append("strategy.py missing")
    if not r["core_file"]: r["warnings"].append("no *_core.py")
    if str(r["trading_mode"]).startswith("live"):
        r["warnings"].append("trading_mode=live — places real orders")
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
    lines.append(f"  Mode:       {r.get('trading_mode', '?')}")
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

def _print_list(strategies: list) -> None:
    print(f"\nStrategies ({len(strategies)}):")
    for s in strategies:
        sym = ','.join(s.get('symbols', []))
        n = s.get('configs_found', 0)
        print(f"  {s['name']:<20s} {n:>2d} overrides | symbols: {sym}")

def main():
    p = argparse.ArgumentParser(description="git pull + strategy analysis")
    p.add_argument("--git-url", default="")
    p.add_argument("--strategies-dir", default="./strategies")
    p.add_argument("--branch", default="main")
    p.add_argument("--strategy", default="")
    p.add_argument("--symbol", default="", help="analyze a specific symbol's overrides")
    p.add_argument("--analyze", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--list", action="store_true")
    args = p.parse_args()
    git_url = args.git_url or os.environ.get("STRATEGIES_GIT_URL", "")
    if args.list:
        strategies = list_strategies(args.strategies_dir)
        if args.json: print(json.dumps(strategies, indent=2, ensure_ascii=False))
        else: _print_list(strategies)
        return 0
    if args.analyze:
        if not args.strategy: print("need --strategy", file=sys.stderr); return 1
        r = analyze_strategy(os.path.join(args.strategies_dir, args.strategy), args.symbol)
        print(json.dumps(r, indent=2, ensure_ascii=False) if args.json else format_analysis(r))
        # issues 意味着这个策略当前无法部署，退出码要反映出来
        return 1 if r.get("issues") else 0
    if not git_url: print("need STRATEGIES_GIT_URL or --git-url"); return 1
    if not clone_or_pull(git_url, args.strategies_dir, args.branch): return 1
    strategies = list_strategies(args.strategies_dir)
    if strategies: _print_list(strategies)
    return 0

if __name__ == "__main__": sys.exit(main())
