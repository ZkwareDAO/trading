#!/usr/bin/env python3
"""init_overrides.py — 为缺少 per-symbol 配置的代币创建 overrides/<SYMBOL>.yaml

v3.7 策略参数的唯一事实来源是 strategies/<name>/overrides/<SYMBOL>.yaml。
git pull 拉来的策略若没有目标代币的那一份，回测和实盘都无法启动：
  - scripts/run_backtest_batch.sh 的 precheck_overrides 拒绝整批
  - calc_data_requirements.py 返回 error（读不到 timeframes/指标周期）
本脚本负责把这一步补上，让"拉代码 → 建配置 → 算数据 → 回测"能连起来。

模板来源按可信度排序（前者可用就不用后者）：

  1. 同策略已有的 overrides/<其它SYMBOL>.yaml
     最可信：结构完整（capital/risk/signal/cooldown_timeframe/user_id 全有），
     且参数是调过的。复制它能保证新代币与老代币口径一致、回测可比。

  2. strategies/<name>/.strategy-spec.yaml 的 default_params
     由 trading-dev 脚手架生成。仅够拼出骨架 —— 实测它缺 5 个
     timeframe 类参数（sar_timeframes / snt3_timeframes / adx_timeframes /
     sar_tracking_timeframe / cooldown_bars），也没有 capital/risk/signal，
     且值可能已与调优后的 override 漂移（如 adx_threshold spec=20 / 实际=25）。
     因此走这条路时一律标 TODO 并要求用户复核，不假装配置已就绪。

  3. 都没有 → 报错退出，不凭空编造参数值。

安全约定：
  - 新建配置一律 trading_mode: paper_trading。新代币未经回测验证就继承
    live 会直接下真单。要上实盘必须由人显式改这一行。
  - 已存在的文件默认不覆盖（--force 才覆盖），避免抹掉用户调好的参数。
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("需要 PyYAML: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

SAFE_MODE = "paper_trading"


def _load_yaml(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception as e:
        print(f"⚠ 解析失败 {path}: {e}", file=sys.stderr)
        return {}


def list_override_symbols(strategy_dir: Path) -> list:
    odir = strategy_dir / "overrides"
    if not odir.is_dir():
        return []
    return sorted(
        f.stem for f in odir.glob("*.yaml")
        if f.is_file() and not f.name.startswith(".")
    )


def _strategy_section(cfg: dict, name: str) -> tuple:
    """overrides 顶层通常是 {strategy_name: {...}}，也兼容平铺写法。

    返回 (section, is_wrapped)，便于写回时保持原有嵌套形式。
    """
    sec = cfg.get(name)
    if isinstance(sec, dict):
        return sec, True
    return cfg, False


def build_from_sibling(strategy_dir: Path, name: str, template_symbol: str,
                       new_symbol: str) -> tuple:
    """以同策略已有 override 为模板，只替换 symbol 相关字段。

    params 原样保留 —— 同策略各 symbol 的指标参数通常一致，且保持一致
    才能让新老代币的回测结果可比。要为新代币单独调参是后续的事，
    不该在"创建配置"这一步偷偷改值。
    """
    src = strategy_dir / "overrides" / f"{template_symbol}.yaml"
    cfg = _load_yaml(src)
    if not cfg:
        return None, []

    sec, wrapped = _strategy_section(cfg, name)
    notes = []

    sec["symbols"] = [new_symbol]

    old_mode = sec.get("trading_mode")
    if old_mode != SAFE_MODE:
        sec["trading_mode"] = SAFE_MODE
        notes.append(
            f"trading_mode 由 {old_mode or '未声明(=live)'} 强制改为 {SAFE_MODE}"
            "（新代币未经回测验证，不应直接下真单）"
        )

    out = {name: sec} if wrapped else sec
    return out, notes


def build_from_spec(strategy_dir: Path, name: str, new_symbol: str) -> tuple:
    """以 .strategy-spec.yaml 的 default_params 拼骨架。

    spec 不含 capital/risk/signal，也常缺 timeframe 类参数，
    因此产出的是"待补全骨架"而非可直接投产的配置。
    """
    spec_path = strategy_dir / ".strategy-spec.yaml"
    spec = _load_yaml(spec_path)
    if not spec:
        return None, []

    params = spec.get("default_params") or {}
    timeframes = spec.get("timeframes") or ["1h"]
    if isinstance(timeframes, str):
        timeframes = [t.strip() for t in timeframes.split(",") if t.strip()]

    sec = {
        "strategy": {"name": spec.get("prefix") or name.upper()},
        "enabled": True,
        "version": str(spec.get("version", "1")),
        "trading_mode": SAFE_MODE,
        "direction": spec.get("direction", "neutral"),
        "symbols": [new_symbol],
        "timeframes": list(timeframes),
        "params": dict(params),
    }

    notes = [
        f"来源 .strategy-spec.yaml（无同策略 override 可复制）",
        "spec 只有 default_params，缺 capital / risk / signal 等段 —— "
        "这些段缺失时框架按内置缺省处理，务必人工确认是否符合预期",
        "spec 的参数值可能与调优后的实际值漂移，回测前请复核 params",
    ]
    if not params:
        notes.append("⚠ spec 的 default_params 为空，params 需完全人工填写")

    return {name: sec}, notes


def init_symbol(strategy_dir: Path, name: str, symbol: str,
                force: bool = False) -> dict:
    r = {
        "symbol": symbol,
        "status": "",          # created / exists / error
        "source": "",          # sibling:<SYM> / spec
        "path": "",
        "notes": [],
        "needs_review": False,
    }

    odir = strategy_dir / "overrides"
    target = odir / f"{symbol}.yaml"
    r["path"] = str(target)

    if target.is_file() and not force:
        r["status"] = "exists"
        r["notes"].append("已存在，未改动（--force 可覆盖）")
        return r

    existing = [s for s in list_override_symbols(strategy_dir) if s != symbol]

    cfg, notes = (None, [])
    if existing:
        template_symbol = existing[0]
        cfg, notes = build_from_sibling(strategy_dir, name, template_symbol, symbol)
        if cfg:
            r["source"] = f"sibling:{template_symbol}"
            notes.insert(0, f"以 {template_symbol}.yaml 为模板复制，params 原样保留")

    if cfg is None:
        cfg, notes = build_from_spec(strategy_dir, name, symbol)
        if cfg:
            r["source"] = "spec"
            r["needs_review"] = True

    if cfg is None:
        r["status"] = "error"
        r["notes"].append(
            "既无同策略 override 可复制，也无 .strategy-spec.yaml —— "
            "无法凭空生成参数值，请手工创建第一份 overrides/<SYMBOL>.yaml"
        )
        return r

    odir.mkdir(parents=True, exist_ok=True)
    try:
        with open(target, "w", encoding="utf-8") as f:
            yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False,
                           default_flow_style=False)
    except Exception as e:
        r["status"] = "error"
        r["notes"].append(f"写入失败: {e}")
        return r

    r["status"] = "created"
    r["notes"].extend(notes)
    return r


def format_report(results: list, strategy_name: str) -> str:
    created = [r for r in results if r["status"] == "created"]
    exists = [r for r in results if r["status"] == "exists"]
    errors = [r for r in results if r["status"] == "error"]
    review = [r for r in created if r["needs_review"]]

    lines = [
        "=" * 62,
        f"  per-symbol 配置初始化: {strategy_name}",
        "=" * 62,
        "",
        f"  新建: {len(created)}   已存在: {len(exists)}   失败: {len(errors)}",
        "",
    ]

    if created:
        lines.append("  [新建]")
        for r in created:
            lines.append(f"    ✅ {r['symbol']}  ← {r['source']}")
            lines.append(f"       {r['path']}")
            for n in r["notes"]:
                lines.append(f"       · {n}")
        lines.append("")

    if exists:
        lines.append("  [已存在，未改动]")
        for r in exists:
            lines.append(f"    ⏭ {r['symbol']}")
        lines.append("")

    if errors:
        lines.append("  [失败]")
        for r in errors:
            lines.append(f"    ❌ {r['symbol']}")
            for n in r["notes"]:
                lines.append(f"       · {n}")
        lines.append("")

    if created:
        lines.append("  " + "-" * 58)
        lines.append("  ⚠ 全部新建配置的 trading_mode 均为 paper_trading。")
        lines.append("    要走实盘必须人工改对应文件，本工具不会替你改。")
    if review:
        lines.append("")
        lines.append("  ⚠ 以下配置来源为 .strategy-spec.yaml，属待补全骨架，")
        lines.append("    回测前请复核 params 与缺失段:")
        for r in review:
            lines.append(f"      - {r['path']}")

    lines.append("=" * 62)
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser(
        description="为缺少 per-symbol 配置的代币创建 overrides/<SYMBOL>.yaml")
    p.add_argument("--strategy-dir", required=True,
                   help="策略目录，如 ./strategies/sar_snt3_v3")
    p.add_argument("--symbols", required=True,
                   help="逗号分隔的代币列表")
    p.add_argument("--force", action="store_true",
                   help="覆盖已存在的配置（默认跳过，避免抹掉调好的参数）")
    p.add_argument("--dry-run", action="store_true",
                   help="只报告将创建哪些文件，不写盘")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    sdir = Path(args.strategy_dir).resolve()
    if not sdir.is_dir():
        print(f"❌ 策略目录不存在: {sdir}", file=sys.stderr)
        sys.exit(1)

    name = sdir.name
    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        print("❌ --symbols 为空", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        existing = list_override_symbols(sdir)
        has_spec = (sdir / ".strategy-spec.yaml").is_file()
        plan = []
        for sym in symbols:
            if sym in existing and not args.force:
                plan.append({"symbol": sym, "action": "skip (已存在)"})
            elif [s for s in existing if s != sym]:
                src = [s for s in existing if s != sym][0]
                plan.append({"symbol": sym, "action": f"copy from {src}.yaml"})
            elif has_spec:
                plan.append({"symbol": sym, "action": "build from .strategy-spec.yaml (骨架)"})
            else:
                plan.append({"symbol": sym, "action": "ERROR 无模板可用"})
        if args.json:
            print(json.dumps({"strategy_name": name, "dry_run": True,
                              "plan": plan}, ensure_ascii=False, indent=2))
        else:
            print(f"[dry-run] {name}")
            for x in plan:
                print(f"  {x['symbol']}: {x['action']}")
        sys.exit(0)

    results = [init_symbol(sdir, name, sym, args.force) for sym in symbols]

    if args.json:
        print(json.dumps({
            "strategy_name": name,
            "results": results,
            "created": sum(1 for r in results if r["status"] == "created"),
            "errors": sum(1 for r in results if r["status"] == "error"),
            "needs_review": [r["path"] for r in results if r["needs_review"]],
        }, ensure_ascii=False, indent=2))
    else:
        print(format_report(results, name))

    sys.exit(1 if any(r["status"] == "error" for r in results) else 0)


if __name__ == "__main__":
    main()
