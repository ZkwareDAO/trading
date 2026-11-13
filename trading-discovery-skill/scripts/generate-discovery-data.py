#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate-discovery-data.py — 把 discovery_outputs 转成 frontend-data/discovery 布局

输入（discovery.py 产物）：
    {discovery_outputs}/{项目}/{strategy}/{YYYYMMDD}/{HHMMSS}/{SYMBOL}/
        ├── backtest_result.json
        ├── config.yaml
        └── engine/...

输出（与 frontend-data-v2/discovery 同构）：
    {out}/discovery/runs.csv                          # 28 列，source=discovery
    {out}/discovery/{strategy}/meta.json
    {out}/discovery/{strategy}/backtest_results/{run_stamp}/{SYMBOL}.json
    {out}/discovery/{strategy}/backtest_results/{run_stamp}/config.json

口径：
  * data_day / run_day = run_date（目录名，YYYYMMDD）
  * run_stamp = {run_date}T{HHMMSS}
  * batch_id = {run_date}-{HHMM}（按 gap 聚簇）
  * sweep = 同策略同日轮次（0 起）
  * is_latest = 同 (strategy, symbol) 最新 run
  * display_name = source_strategy（配置策略名），不依赖任何前端文件
  * 比率字段保持小数；日期字段 YYYY-MM-DD；时间戳原样透传 ISO8601

幂等：按 (strategy, run_stamp, symbol) upsert 到已有 runs.csv，不覆盖历史行。
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

SCHEMA_VERSION = 1
DATE_RE = re.compile(r"^\d{8}$")
TIME_RE = re.compile(r"^\d{6}$")
RUN_STAMP_RE = re.compile(r"^\d{8}T\d{6}$")

RUNS_COLUMNS = [
    "schema_version", "source", "data_day", "batch_id", "run_id", "run_day",
    "run_stamp", "sweep", "strategy", "source_strategy", "strategy_display_name",
    "strategy_version", "config_version", "symbol", "start_date", "end_date",
    "status", "completed_at", "signals_processed", "trades_count",
    "annualized_return", "roe", "total_return", "max_drawdown", "win_rate",
    "total_trades", "sharpe_ratio", "is_latest",
]


# ────────────────────────────────────────────────────────────────────
# 基础工具
# ────────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    print(msg, flush=True)


def load_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def write_csv(path: Path, columns: List[str], rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: row.get(c, "") for c in columns})
    os.replace(tmp, path)


def read_csv(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")


def parse_dt(value: str) -> Optional[datetime]:
    """解析 run_stamp / ISO8601，统一为 naive UTC 用于比较。"""
    if not value:
        return None
    try:
        if RUN_STAMP_RE.match(value):
            return datetime.strptime(value, "%Y%m%dT%H%M%S")
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def norm_date(value: Any) -> str:
    """统一成 YYYY-MM-DD；无法识别返回原值字符串。"""
    if value is None:
        return ""
    text = str(value).strip()
    if re.match(r"^\d{8}$", text):
        return f"{text[:4]}-{text[4:6]}-{text[6:]}"
    return text


# ────────────────────────────────────────────────────────────────────
# 扫描 discovery_outputs
# ────────────────────────────────────────────────────────────────────
@dataclass
class Run:
    strategy: str
    source_strategy: str
    symbol: str
    run_date: str
    run_stamp: str
    run_dir: Path
    result: Dict[str, Any]
    config: Dict[str, Any]
    engine: str
    config_version: str
    sweep: int = 0
    batch_id: str = ""
    is_latest: int = 0

    @property
    def run_id(self) -> str:
        return f"{self.strategy}-{self.run_stamp}"


def detect_engine(run_dir: Path, config: Dict[str, Any]) -> str:
    explicit = str(config.get("engine") or "").strip().lower()
    if explicit in ("rust", "python"):
        return explicit
    for parent in [run_dir, *run_dir.parents]:
        if (parent / "Cargo.toml").is_file():
            return "rust"
        if (parent / "requirements.txt").is_file() or (parent / "strategy_core").is_dir():
            return "python"
    return "python"


def read_config(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError):
        return {}


def project_meta(symbol_dir: Path) -> Dict[str, Any]:
    """向上查找 discovery 回测时落盘的 .meta.json（engine/timeframe/leverage）。"""
    for parent in [symbol_dir, *list(symbol_dir.parents)[:6]]:
        path = parent / ".meta.json"
        if path.is_file():
            data = load_json(path, {})
            if isinstance(data, dict):
                return data
    return {}


def scan_runs(discovery_outputs: Path, engine_override: Optional[str] = None) -> List[Run]:
    runs: List[Run] = []
    seen: set = set()
    if not discovery_outputs.is_dir():
        sys.exit(f"❌ discovery_outputs 不存在: {discovery_outputs}")

    for result_path in sorted(discovery_outputs.rglob("backtest_result.json")):
        symbol_dir = result_path.parent
        symbol = symbol_dir.name.upper()
        time_dir = symbol_dir.parent.name
        run_date = symbol_dir.parent.parent.name
        strategy_dir = symbol_dir.parent.parent.parent.name

        # 时间目录兼容两种布局：HHMMSS 或 YYYYMMDDTHHMMSS
        if DATE_RE.match(run_date) and TIME_RE.match(time_dir):
            run_stamp = f"{run_date}T{time_dir}"
        elif RUN_STAMP_RE.match(time_dir):
            run_stamp = time_dir
            run_date = time_dir[:8]
        else:
            # 非 discovery 产物布局，跳过
            continue

        config = read_config(symbol_dir / "config.yaml")
        meta = project_meta(symbol_dir)
        if meta:
            for key in ("strategy", "timeframe", "leverage", "warmup_days"):
                if config.get(key) in (None, "") and meta.get(key) is not None:
                    config[key] = meta[key]
        strategy = str(config.get("strategy") or strategy_dir)

        key = (strategy, run_stamp, symbol)
        if key in seen:
            continue
        seen.add(key)

        result = load_json(result_path, {})
        if not isinstance(result, dict):
            continue

        runs.append(Run(
            strategy=strategy,
            source_strategy=strategy,
            symbol=symbol,
            run_date=run_date,
            run_stamp=run_stamp,
            run_dir=symbol_dir,
            result=result,
            config=config,
            engine=(engine_override or str(meta.get("engine") or "")
                    or detect_engine(symbol_dir, config)),
            config_version=str(config.get("version") or "1"),
        ))

    return runs


# ────────────────────────────────────────────────────────────────────
# 行组装 / 批次与最新标记
# ────────────────────────────────────────────────────────────────────
def build_row(run: Run, display_name: str) -> Dict[str, Any]:
    result = run.result
    metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    cfg = result.get("config") if isinstance(result.get("config"), dict) else {}

    start_date = norm_date(cfg.get("start_date") or run.config.get("start"))
    end_date = norm_date(cfg.get("end_date") or run.config.get("end"))

    return {
        "schema_version": SCHEMA_VERSION,
        "source": "discovery",
        "data_day": run.run_date,
        "batch_id": run.batch_id,
        "run_id": run.run_id,
        "run_day": run.run_date,
        "run_stamp": run.run_stamp,
        "sweep": run.sweep,
        "strategy": run.strategy,
        "source_strategy": run.source_strategy,
        "strategy_display_name": display_name,
        "strategy_version": run.run_date,
        "config_version": run.config_version,
        "symbol": run.symbol,
        "start_date": start_date,
        "end_date": end_date,
        "status": str(result.get("status") or "success"),
        "completed_at": result.get("end_time") or "",
        "signals_processed": result.get("signals_processed", 0),
        "trades_count": result.get("trades_count", 0),
        "annualized_return": metrics.get("annualized_return", ""),
        "roe": metrics.get("roe", ""),
        "total_return": metrics.get("total_return", ""),
        "max_drawdown": metrics.get("max_drawdown", ""),
        "win_rate": metrics.get("win_rate", ""),
        "total_trades": metrics.get("total_trades", ""),
        "sharpe_ratio": metrics.get("sharpe_ratio", ""),
        "is_latest": run.is_latest,
    }


def assign_batches(rows: List[Dict[str, Any]], gap_seconds: int) -> None:
    """同 (strategy, run_day) 聚簇，分配 batch_id / sweep（与 kanban 生成器同规则）。"""
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row["strategy"], row["run_day"])].append(row)

    for items in groups.values():
        items.sort(key=lambda r: r["run_stamp"])
        sweep = 0
        prev_ts: Optional[datetime] = None
        seen_symbols: set = set()
        batch_first = items[0]["run_stamp"]
        for row in items:
            ts = parse_dt(row["run_stamp"])
            new_batch = False
            if prev_ts is not None and ts is not None and (ts - prev_ts).total_seconds() > gap_seconds:
                new_batch = True
            if row["symbol"] in seen_symbols:
                new_batch = True
            if new_batch:
                sweep += 1
                seen_symbols = set()
                batch_first = row["run_stamp"]
            seen_symbols.add(row["symbol"])
            if ts is not None:
                prev_ts = ts
            row["sweep"] = sweep
            row["batch_id"] = f"{row['run_day']}-{batch_first[9:11]}{batch_first[11:13]}"


def mark_latest(rows: List[Dict[str, Any]]) -> None:
    """同 (strategy, symbol, run_day) 内最新 run 标 1（跨日不互相压制）。"""
    latest: Dict[Tuple[str, str, str], str] = {}
    for row in rows:
        key = (row["strategy"], row["symbol"], row["run_day"])
        if key not in latest or row["run_stamp"] > latest[key]:
            latest[key] = row["run_stamp"]
    for row in rows:
        key = (row["strategy"], row["symbol"], row["run_day"])
        row["is_latest"] = 1 if latest[key] == row["run_stamp"] else 0


# ────────────────────────────────────────────────────────────────────
# 输出
# ────────────────────────────────────────────────────────────────────
def strategy_config(run: Run) -> Dict[str, Any]:
    cfg = run.config
    params = cfg.get("params") if isinstance(cfg.get("params"), dict) else {}
    return {
        "version": run.config_version,
        "engine": run.engine,
        "timeframe": str(cfg.get("timeframe") or ""),
        "leverage": to_float(cfg.get("leverage"), 1.0),
        "warmup_days": to_float(cfg.get("warmup_days"), None),
        "indicators": [],
        "indicator_params": {},
        "logic": {},
        "params": params,
    }


def run_config_json(run: Run, row: Dict[str, Any], display_name: str) -> Dict[str, Any]:
    sc = strategy_config(run)
    return {
        "schema_version": SCHEMA_VERSION,
        "source": "discovery",
        "strategy": run.strategy,
        "source_strategy": run.source_strategy,
        "display_name": display_name,
        "description": str(run.config.get("description") or ""),
        "run_id": run.run_id,
        "run_day": run.run_date,
        "run_stamp": run.run_stamp,
        "sweep": run.sweep,
        "backtest": {
            "start_date": row["start_date"],
            "end_date": row["end_date"],
        },
        "config_version": run.config_version,
        "config_docs": 0,
        "config_ambiguous": False,
        "config": sc,
        "captured_at": now_iso(),
    }


def strategy_meta(strategy: str, runs: List[Run]) -> Dict[str, Any]:
    latest = max(runs, key=lambda r: r.run_stamp)
    sc = strategy_config(latest)
    return {
        "schema_version": SCHEMA_VERSION,
        "day": latest.run_date,
        "strategy": strategy,
        "source_strategy": latest.source_strategy,
        "display_name": latest.source_strategy,
        "description": str(latest.config.get("description") or ""),
        "version": latest.run_date,
        "engine": sc["engine"],
        "timeframe": sc["timeframe"],
        "leverage": sc["leverage"],
        "warmup_days": sc["warmup_days"],
        "indicators": sc["indicators"],
        "indicator_params": sc["indicator_params"],
        "logic": sc["logic"],
        "params": sc["params"],
        "config_scope": "strategy_default",
        "default_config_version": latest.config_version,
        "config_ref": f"backtest_results/{latest.run_stamp}/config.json",
        "captured_at": now_iso(),
    }


def load_display_names(path: Optional[str]) -> Dict[str, str]:
    """可选映射：兼容扁平 {k: "名"} 与富格式 {k: {"display_name": "名"}}。"""
    if not path:
        return {}
    data = load_json(Path(path), {}) or {}
    out: Dict[str, str] = {}
    if isinstance(data, dict):
        for key, value in data.items():
            if isinstance(value, str):
                out[str(key)] = value
            elif isinstance(value, dict) and value.get("display_name"):
                out[str(key)] = str(value["display_name"])
    return out


def emit(scanned: List[Run], out_root: Path, display_map: Dict[str, str],
         gap_seconds: int, prune: bool, dry_run: bool) -> None:
    discovery_out = out_root / "discovery"
    runs_csv = discovery_out / "runs.csv"

    # 1) 合并已有 runs.csv（保留历史行；新扫描结果覆盖同 key）
    merged: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for old in read_csv(runs_csv):
        key = (old.get("strategy", ""), old.get("run_stamp", ""), old.get("symbol", ""))
        merged[key] = {c: old.get(c, "") for c in RUNS_COLUMNS}

    new_rows: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    for run in scanned:
        display = display_map.get(run.source_strategy) or run.source_strategy
        row = build_row(run, display)
        key = (run.strategy, run.run_stamp, run.symbol)
        new_rows[key] = row
        merged[key] = row

    rows = list(merged.values())
    assign_batches(rows, gap_seconds)
    mark_latest(rows)

    # 把批次/最新标记同步回本轮扫描的 run 对象
    for run in scanned:
        row = new_rows[(run.strategy, run.run_stamp, run.symbol)]
        run.sweep = int(row["sweep"])
        run.batch_id = str(row["batch_id"])
        run.is_latest = int(row["is_latest"])

    log(f"  runs.csv: {len(rows)} 行（本次扫描 {len(scanned)}）")
    if dry_run:
        for row in rows:
            log(f"    {row['data_day']} {row['strategy']:24} {row['symbol']:10} "
                f"sweep={row['sweep']} latest={row['is_latest']} {row['status']}")
        return

    # 2) 写每个 run 的 JSON + config.json
    for run in scanned:
        row = new_rows[(run.strategy, run.run_stamp, run.symbol)]
        display = display_map.get(run.source_strategy) or run.source_strategy
        run_out = discovery_out / run.strategy / "backtest_results" / run.run_stamp

        result = dict(run.result)
        result["strategy_config"] = strategy_config(run)
        write_json(run_out / f"{run.symbol}.json", result)
        write_json(run_out / "config.json", run_config_json(run, row, display))

    # 3) 写策略 meta.json（每个策略取最新 run）
    by_strategy: Dict[str, List[Run]] = defaultdict(list)
    for run in scanned:
        by_strategy[run.strategy].append(run)
    for strategy, items in by_strategy.items():
        write_json(discovery_out / strategy / "meta.json", strategy_meta(strategy, items))

    # 4) 写 runs.csv
    write_csv(runs_csv, RUNS_COLUMNS, rows)

    # 5) 可选清理本次未涉及的旧策略目录
    if prune and discovery_out.is_dir():
        import shutil
        keep = set(by_strategy)
        for item in discovery_out.iterdir():
            if item.is_dir() and item.name not in keep:
                log(f"  prune: 删除旧策略目录 {item}")
                shutil.rmtree(item, ignore_errors=True)

    log(f"✅ 输出: {discovery_out}")


def main() -> None:
    ap = argparse.ArgumentParser(description="discovery_outputs → frontend-data/discovery")
    ap.add_argument("--discovery-outputs", default="./discovery_outputs",
                    help="discovery.py 产物根目录（默认 ./discovery_outputs）")
    ap.add_argument("--out", default="./frontend-data",
                    help="frontend-data 根目录（默认 ./frontend-data）")
    ap.add_argument("--display-names", default=None,
                    help="可选 JSON 映射；默认 display_name = source_strategy")
    ap.add_argument("--batch-gap", type=int, default=1800,
                    help="同策略批次聚簇间隔（秒，默认 1800）")
    ap.add_argument("--engine", choices=["rust", "python"], default=None,
                    help="覆盖引擎检测（直跑产物目录没有 Cargo.toml 时使用）")
    ap.add_argument("--prune", action="store_true",
                    help="删除输出目录下本次未涉及的旧策略目录")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    args = ap.parse_args()

    discovery_outputs = Path(args.discovery_outputs).expanduser().resolve()
    out_root = Path(args.out).expanduser().resolve()

    log("=== discovery frontend-data 转换 ===")
    log(f"  输入: {discovery_outputs}")
    log(f"  输出: {out_root / 'discovery'}")

    scanned = scan_runs(discovery_outputs, engine_override=args.engine)
    if not scanned:
        sys.exit("❌ 未找到 backtest_result.json（检查 --discovery-outputs 与目录层级）")

    display_map = load_display_names(args.display_names)
    emit(scanned, out_root, display_map, args.batch_gap, args.prune, args.dry_run)


if __name__ == "__main__":
    main()
