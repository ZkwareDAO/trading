#!/usr/bin/env python3
"""create_config.py — 策略部署前配置校验 + 编排登记 (Phase 4)

v3.7 起策略参数的唯一事实来源是
    strategies/<name>/overrides/<SYMBOL>.yaml
实盘 (run_strategy.py) 与回测 (run_backtest.py) 读的都是这一份文件 ——
"回测不失真"正是靠这个单一来源保证的。

因此本脚本【不再生成】另一份 runtime config。早期版本会合成一个
{strategy}-runtime.yaml，但模板没有任何代码消费它：真正生效的仍是
overrides/<SYMBOL>.yaml，而那份合成文件只会让人误以为改它就能改参数。

现在做两件真正有用的事：
  1. --check   校验待部署的 (策略, 代币) 的 overrides 是否齐备、
               trading_mode 是否符合预期，输出人类可读报告
  2. --register 把策略登记进 config/strategies.yaml（编排层，实盘回测共用），
               这才是模板认可的"上线"动作

用法:
    python3 create_config.py --strategy-dir ./strategies/sar_snt3_v3 --check
    python3 create_config.py --strategy-dir ./strategies/sar_snt3_v3 \
        --symbols BTCUSDT,ETHUSDT --check --json
    python3 create_config.py --strategy-dir ./strategies/sar_snt3_v3 \
        --symbols BTCUSDT --register --project-dir . --trading-mode paper_trading
"""

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

VALID_MODES = ("live", "paper_trading", "smoking")


def _parse_yaml(path) -> dict:
    if yaml is None:
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except (OSError, yaml.YAMLError):
        return {}


def _section(cfg: dict, name: str) -> dict:
    sc = cfg.get(name, cfg)
    return sc if isinstance(sc, dict) else cfg


def list_override_symbols(strategy_dir) -> list:
    odir = Path(strategy_dir) / "overrides"
    if not odir.is_dir():
        return []
    return sorted(f.stem for f in odir.glob("*.yaml")
                  if f.is_file() and not f.name.startswith("."))


def check_strategy(strategy_dir: str, symbols: list = None) -> dict:
    """校验策略的 per-symbol 配置齐备性与运行模式"""
    sdir = Path(strategy_dir)
    name = sdir.name
    odir = sdir / "overrides"

    r = {
        "strategy_name": name,
        "strategy_dir": str(sdir),
        "overrides_dir": str(odir),
        "available_symbols": [],
        "requested_symbols": list(symbols) if symbols else [],
        "deployable": [],
        "missing": [],
        "issues": [],
        "warnings": [],
        "per_symbol": {},
    }

    if yaml is None:
        r["issues"].append("PyYAML not installed — cannot inspect configs")
        return r

    if not sdir.is_dir():
        r["issues"].append(f"strategy dir not found: {sdir}")
        return r
    if not (sdir / "strategy.py").is_file():
        r["issues"].append("strategy.py missing")

    available = list_override_symbols(sdir)
    r["available_symbols"] = available
    if not available:
        r["issues"].append(f"no per-symbol config under {odir}/")
        return r

    targets = list(symbols) if symbols else available
    for sym in targets:
        cfg_file = odir / f"{sym}.yaml"
        if not cfg_file.is_file():
            r["missing"].append(sym)
            r["issues"].append(f"missing overrides/{sym}.yaml")
            continue

        sc = _section(_parse_yaml(cfg_file), name)
        mode = sc.get("trading_mode")
        # 缺省时 run_strategy.py 按 live 处理 —— 下真单，必须显式提示
        effective_mode = mode if mode else "live"
        tf = sc.get("timeframes", [])
        if isinstance(tf, str):
            tf = [t.strip() for t in tf.split(",") if t.strip()]

        entry = {
            "config_path": str(cfg_file),
            "trading_mode": effective_mode,
            "trading_mode_explicit": bool(mode),
            "timeframes": tf,
            "enabled": sc.get("enabled", True),
            "version": str(sc.get("version", "")),
            "capital": sc.get("capital", "not set"),
        }
        r["per_symbol"][sym] = entry
        r["deployable"].append(sym)

        if mode and mode not in VALID_MODES:
            r["issues"].append(f"{sym}: invalid trading_mode {mode!r} (expect one of {VALID_MODES})")
        if not mode:
            r["warnings"].append(f"{sym}: trading_mode not set — defaults to LIVE (real orders)")
        elif mode == "live":
            r["warnings"].append(f"{sym}: trading_mode=live — real orders")
        if sc.get("enabled") is False:
            r["warnings"].append(f"{sym}: enabled=false — manager will skip it")
        if not tf:
            r["warnings"].append(f"{sym}: no timeframes declared")

    r["ok"] = not r["issues"] and bool(r["deployable"])
    return r


def format_check(r: dict) -> str:
    lines = ["", "=" * 62,
             f"  Deployment Check — {r['strategy_name']}", "=" * 62,
             f"  Overrides dir:  {r['overrides_dir']}",
             f"  Configured:     {', '.join(r['available_symbols']) or '(none)'}"]
    if r.get("requested_symbols"):
        lines.append(f"  Requested:      {', '.join(r['requested_symbols'])}")
    lines.append(f"  Deployable:     {', '.join(r['deployable']) or '(none)'}")
    if r["missing"]:
        lines.append(f"  Missing:        {', '.join(r['missing'])}")

    if r["per_symbol"]:
        lines.append("")
        lines.append(f"  {'SYMBOL':<12s} {'MODE':<16s} {'TF':<10s} ENABLED")
        for sym, e in r["per_symbol"].items():
            mode = e["trading_mode"] + ("" if e["trading_mode_explicit"] else " (default)")
            tf = ",".join(e["timeframes"]) or "-"
            lines.append(f"  {sym:<12s} {mode:<16s} {tf:<10s} {e['enabled']}")

    for i in r["issues"]:
        lines.append(f"  [ISSUE] {i}")
    for w in r["warnings"]:
        lines.append(f"  [WARN]  {w}")

    lines.append("")
    lines.append(f"  Result: {'READY' if r.get('ok') else 'NOT READY'}")
    lines.append("=" * 62)
    lines.append("")
    lines.append("  Note: strategy params live in overrides/<SYMBOL>.yaml and are read")
    lines.append("        directly by both live and backtest. Edit that file to change")
    lines.append("        params — no separate runtime config exists.")
    return "\n".join(lines)


def register_strategy(project_dir: str, strategy_name: str, symbols: list,
                      trading_mode: str = "", dry_run: bool = False) -> dict:
    """把策略写入 config/strategies.yaml（编排层，实盘回测共用）

    用文本插入而非 yaml.safe_dump 全量重写：登记表头部的使用说明注释
    （symbols 两种格式、trading_mode 语义等）必须保留，safe_dump 会把它们全部抹掉。
    """
    if yaml is None:
        return {"ok": False, "error": "PyYAML not installed"}

    target = Path(project_dir) / "config" / "strategies.yaml"
    if not target.is_file():
        return {"ok": False, "error": f"not found: {target}"}

    cfg = _parse_yaml(target)
    strategies = cfg.get("strategies") if isinstance(cfg, dict) else None
    if strategies is None:
        # 新脚手架（trading-dev v3.7 模板）的登记表全部注释，yaml 解析为 None
        # —— 这不是错误，是"尚未登记任何策略"的初始态
        strategies = {}
    if not isinstance(strategies, dict):
        return {"ok": False, "error": f"{target} has no 'strategies' mapping"}

    entry = strategies.get(strategy_name)
    if not isinstance(entry, dict):
        entry = {}
    if trading_mode:
        entry["trading_mode"] = trading_mode

    existing = entry.get("symbols") or []
    # symbols 支持字符串数组或对象数组，两种都要兼容
    existing_names = [
        s.get("name") if isinstance(s, dict) else s for s in existing
    ]
    added = [s for s in symbols if s not in existing_names]
    merged = list(existing) + added
    entry["symbols"] = merged

    result = {
        "ok": True,
        "target": str(target),
        "strategy": strategy_name,
        "added_symbols": added,
        "total_symbols": [s.get("name") if isinstance(s, dict) else s for s in merged],
        "trading_mode": entry.get("trading_mode", "(inherited)"),
        "dry_run": dry_run,
    }

    if dry_run:
        return result

    # --- 文本插入：找到 strategies: 段内最后一个非注释条目之后追加 ---
    text = target.read_text(encoding="utf-8")
    if strategy_name in strategies:
        # 已有条目 → 全量重写不可避免（要改它的 symbols），但这种情况罕见，
        # 登记表头部注释已在首次创建时承担过职责
        strategies[strategy_name] = entry
        cfg["strategies"] = strategies
        with open(target, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
        return result

    # 新条目：定位 strategies: 段，找段内最后一个顶层子项行（缩进两格的 key）的行号
    lines = text.split("\n")
    seg_start = None
    for i, ln in enumerate(lines):
        if ln.rstrip() == "strategies:":
            seg_start = i
            break
    if seg_start is None:
        # 没有 strategies: 键（理论上 cfg.get 已含），追加到文件尾
        text = text.rstrip("\n") + "\nstrategies:\n"
        seg_start = len(text.split("\n")) - 1
        lines = text.split("\n")

    insert_at = seg_start
    child_re = re.compile(r"^  [A-Za-z0-9_\-]+:")
    for i in range(seg_start + 1, len(lines)):
        ln = lines[i]
        if child_re.match(ln):
            insert_at = i
            continue
        if ln and not ln.startswith((" ", "#")):
            break  # 下一个顶层键，段结束
        if ln.strip() and not ln.startswith("#") and not ln.startswith(" "):
            break
    block = [f"  {strategy_name}:"]
    if trading_mode:
        block.append(f'    trading_mode: "{trading_mode}"')
    block.append("    symbols:")
    block.extend(f"      - {s}" for s in merged)
    lines[insert_at + 1:insert_at + 1] = block

    target.write_text("\n".join(lines), encoding="utf-8")
    return result


def main():
    p = argparse.ArgumentParser(description="Validate / register strategy for deployment")
    p.add_argument("--strategy-dir", required=True)
    p.add_argument("--symbols", default="", help="comma-separated; default = all overrides")
    p.add_argument("--check", action="store_true", help="validate per-symbol configs (default)")
    p.add_argument("--register", action="store_true",
                   help="add to config/strategies.yaml orchestration roster")
    p.add_argument("--project-dir", default=".", help="CTA project root (for --register)")
    p.add_argument("--trading-mode", default="", choices=["", *VALID_MODES],
                   help="trading_mode to write when registering")
    p.add_argument("--dry-run", action="store_true", help="with --register, show diff only")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()] or None

    r = check_strategy(args.strategy_dir, symbols)
    if args.json:
        print(json.dumps(r, indent=2, ensure_ascii=False, default=str))
    else:
        print(format_check(r))

    if not args.register:
        return 0 if r.get("ok") else 1

    if not r.get("ok"):
        print("\nRefusing to register: check did not pass.", file=sys.stderr)
        return 1

    reg = register_strategy(
        args.project_dir, r["strategy_name"], r["deployable"],
        args.trading_mode, args.dry_run,
    )
    if args.json:
        print(json.dumps(reg, indent=2, ensure_ascii=False))
    elif reg.get("ok"):
        verb = "would add" if reg["dry_run"] else "added"
        print(f"\nRegistered in {reg['target']}")
        print(f"  {verb}: {', '.join(reg['added_symbols']) or '(nothing new)'}")
        print(f"  roster now: {', '.join(str(s) for s in reg['total_symbols'])}")
        print(f"  trading_mode: {reg['trading_mode']}")
        print("\nStart the full roster with ./start.sh")
    else:
        print(f"\nERROR: {reg.get('error')}", file=sys.stderr)
        return 1

    return 0 if reg.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
