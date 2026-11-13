#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
generate-kanban-data.py — 把 replay_data（实盘快照）+ replay_outputs（每日回放回测）
转换成 strategy-kanban 前端 frontend-data v2 布局（CSV，参数化版）。

目标格式（唯一参照，逐列对齐）：
    strategy-kanban/docs/frontend-data-sample/README.md
产物布局：
    {out}/catalog.csv
    {out}/{day}/manifest.csv
    {out}/{day}/backtest_runs.csv
    {out}/{day}/{strategy}/meta.json
    {out}/{day}/{strategy}/manifest.csv
    {out}/{day}/{strategy}/backtest_runs.csv         （has_backtest 时）
    {out}/{day}/{strategy}/live_positions.csv        （has_live 且有仓位时）
    {out}/{day}/{strategy}/live_signals.csv          （has_live 且有信号时）
    {out}/{day}/{strategy}/backtest_positions.csv    （有成交时）
    {out}/{day}/{strategy}/backtest_signals.csv      （有成交时）
    {out}/{day}/{strategy}/signal_comparison.csv     （有 live 或回测信号时）
    {out}/{day}/{strategy}/backtest_results/{run_stamp}/{SYMBOL}.json

数据流：
    replay_data/{day}/{项目}/data/state/{day}/{signal,position,history_position}.csv
    replay_data/{day}/{项目}/data/state/history_positions/{runtime}/{day}.csv   → 实盘侧
    replay_outputs/{day}/{项目}/{strategy}/{run_date}/{HHMMSS}/{SYMBOL}/        → 回测侧
        ├── backtest_result.json      → backtest_results/{run_stamp}/{SYMBOL}.json
        ├── config.yaml               → meta.json / leverage / timeframe
        └── engine/state/history_positions/{runtime}/*.csv → backtest_positions.csv

口径（README 第 8 节）：
  * 时间 ISO8601 UTC `2026-10-26T01:34:09Z`；日期目录 YYYYMMDD
  * run_stamp / batch_id / run_id 是标识符不是时间
  * 比率小数（roe=0.0164）；pnl_pct / price_diff_pct 百分数
  * total_pnl / floating_pnl = 金额 ÷ 初始资金（result.config.initial_cash，兜底 10000）
  * sweep：同 (strategy, run_day) 内按 run_stamp 升序贪心——每个 run 归入第一个
    「尚无该标的」的轮次，从 0 起
  * is_latest：回放按 (strategy, symbol) 本日内最新 run；页面必须过滤
  * 空回测（signals_processed=0）不生成 positions/signals CSV
  * 没有数据就不建文件，不用表头占位

用法：
    python3 generate-kanban-data.py                    # replay_data 最新一天
    python3 generate-kanban-data.py --date 20261026
    python3 generate-kanban-data.py --all
    python3 generate-kanban-data.py --out /path/to/frontend-data
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

UTC = timezone.utc
SCHEMA_VERSION = 1
DEFAULT_INITIAL_CASH = 10000.0

MODE_SUFFIX_RE = re.compile(r"_(LIVE|PAPER(?:_TRADING)?|SMOKING|BACKTEST|PROD|PRODUCTION)$", re.I)
TIMEFRAME_RE = re.compile(r"(?:_\d+[A-Za-z]+_\d+)+$")
QUOTE_SUFFIXES = ("FDUSD", "BUSD", "USDT", "USDC", "TUSD", "USD")
DATE_RE = re.compile(r"^\d{8}$")
HHMMSS_RE = re.compile(r"^\d{6}$")
RUN_STAMP_RE = re.compile(r"^\d{8}T\d{6}$")
_NANO_RE = re.compile(r"^(.*\.\d{6})\d+(\+.*)?$")

# ── 列定义（逐列对齐 docs/frontend-data-sample）──────────────────────
CATALOG_COLUMNS = [
    "schema_version", "day", "strategies", "has_live", "has_backtest", "updated_at",
]

DAY_MANIFEST_COLUMNS = [
    "schema_version", "data_day", "strategy", "source_strategy", "strategy_display_name",
    "strategy_version", "symbol", "runtime_name", "engine", "trading_mode", "status",
    "has_live", "has_backtest", "total_trades", "winning_trades", "losing_trades",
    "win_rate", "total_pnl", "open_positions", "floating_pnl", "latest_run_id",
    "latest_annualized_return", "latest_roe", "latest_max_drawdown", "strategy_path",
]

STRATEGY_MANIFEST_COLUMNS = [
    "schema_version", "data_day", "strategy", "symbol", "runtime_name", "engine",
    "trading_mode", "status", "has_live", "has_backtest",
]

RUNS_COLUMNS = [
    "schema_version", "source", "data_day", "batch_id", "run_id", "run_day", "run_stamp",
    "sweep", "strategy", "source_strategy", "strategy_display_name", "strategy_version",
    "config_version", "symbol", "start_date", "end_date", "status", "completed_at",
    "signals_processed", "trades_count", "annualized_return", "roe", "total_return",
    "max_drawdown", "win_rate", "total_trades", "sharpe_ratio", "is_latest",
]

LIVE_POSITIONS_COLUMNS = [
    "schema_version", "data_day", "strategy", "source_strategy", "strategy_display_name",
    "strategy_version", "symbol", "runtime_name", "engine", "trading_mode", "position_id",
    "side", "status", "qty", "entry_time", "entry_price", "exit_time", "exit_price",
    "realized_pnl", "pnl_pct", "max_pnl_pct", "min_pnl_pct", "leverage", "exit_reason",
    "updated_at",
]

LIVE_SIGNALS_COLUMNS = [
    "schema_version", "data_day", "strategy", "source_strategy", "strategy_display_name",
    "strategy_version", "symbol", "runtime_name", "engine", "trading_mode", "signal_id",
    "signal_time", "side", "action", "direction", "price", "qty", "status", "filled_price",
    "filled_qty", "reason",
]

BACKTEST_POSITIONS_COLUMNS = [
    "schema_version", "source", "data_day", "strategy", "source_strategy",
    "strategy_display_name", "strategy_version", "symbol", "run_id", "batch_id", "run_day",
    "run_stamp", "sweep", "is_latest", "engine", "trading_mode", "position_id", "side",
    "status", "qty", "entry_time", "entry_price", "exit_time", "exit_price", "realized_pnl",
    "pnl_pct", "max_pnl_pct", "min_pnl_pct", "leverage", "exit_reason", "updated_at",
]

BACKTEST_SIGNALS_COLUMNS = [
    "schema_version", "source", "data_day", "strategy", "source_strategy",
    "strategy_display_name", "strategy_version", "symbol", "run_id", "batch_id", "run_day",
    "run_stamp", "sweep", "is_latest", "engine", "trading_mode", "signal_id", "signal_time",
    "side", "action", "direction", "price", "qty", "status", "filled_price", "filled_qty",
    "reason",
]

COMPARISON_COLUMNS = [
    "schema_version", "data_day", "strategy", "source_strategy", "strategy_display_name",
    "symbol", "run_id", "batch_id", "record_type", "match_type", "signal_action",
    "live_signal_id", "backtest_signal_id", "live_time", "backtest_time",
    "time_diff_seconds", "live_price", "backtest_price", "price_diff_pct", "status",
]


# ────────────────────────────────────────────────────────────────────
# 基础工具
# ────────────────────────────────────────────────────────────────────
def log(msg: str) -> None:
    print(msg, flush=True)


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_json(path: Path, default: Any = None) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def parse_payload(row: Dict[str, str]) -> Dict[str, Any]:
    raw = row.get("payload_json") or row.get("payload") or ""
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, ValueError):
        return {}


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_dt(value: Any) -> Optional[datetime]:
    """兼容纳秒 / +00:00 / 无时区 / epoch 秒毫秒，统一返回 UTC datetime。"""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e11:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    if re.fullmatch(r"\d+(?:\.\d+)?", s):
        return parse_dt(float(s))
    s = s.replace("Z", "+00:00")
    m = _NANO_RE.match(s)
    if m:
        s = m.group(1) + (m.group(2) or "")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.fromisoformat(s[:19])
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def fmt_z(dt: Optional[datetime]) -> str:
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else ""


def day_start_end(day: str) -> Tuple[datetime, datetime]:
    d = datetime.strptime(day, "%Y%m%d").replace(tzinfo=UTC)
    return d, d + timedelta(days=1)


def day_of(dt: Optional[datetime]) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%d") if dt else ""


def normalize_day(value: str) -> str:
    s = str(value).strip()
    if re.fullmatch(r"\d{8}", s):
        return s
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s.replace("-", "")
    raise argparse.ArgumentTypeError(f"日期格式错误: {value}，应为 YYYYMMDD 或 YYYY-MM-DD")


def norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def loose_name(name: str) -> str:
    return norm_name(TIMEFRAME_RE.sub("", name or ""))


def num(value: Any) -> Any:
    """CSV 数字格式化：int 原样；float 保留全精度（保证与 JSON 勾稽精确一致）。"""
    if value is None or value == "":
        return ""
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return value
    f = float(value)
    if f == int(f) and abs(f) < 1e15:
        return int(f)
    return f


def parse_runtime(runtime: str, symbol_hint: str = "") -> Tuple[str, str, Optional[str]]:
    """sar_supertrend_4H_3_BTCUSDT_LIVE -> (sar_supertrend_4H_3, BTCUSDT, live)。"""
    name = (runtime or "").strip()
    mode: Optional[str] = None
    base = name
    m = MODE_SUFFIX_RE.search(name)
    if m:
        mode = m.group(1).lower()
        if mode == "paper_trading":
            mode = "paper"
        elif mode in ("prod", "production"):
            mode = "live"
        base = name[: m.start()]
    if symbol_hint:
        suffix = "_" + symbol_hint
        if base.upper().endswith(suffix.upper()):
            return base[: -len(suffix)], symbol_hint, mode
    parts = base.split("_")
    for i in range(len(parts) - 1, 0, -1):
        candidate = parts[i]
        if len(candidate) >= 5 and candidate.upper().endswith(QUOTE_SUFFIXES):
            return "_".join(parts[:i]), candidate, mode
    return base, symbol_hint, mode


def action_from(kind: str, direction: str) -> Tuple[str, str]:
    """(kind, direction) -> (side BUY/SELL, action open/close)。"""
    k = (kind or "").lower().strip()
    long_ = (direction or "").lower().strip() in ("long", "buy", "1")
    if k in ("open", "entry"):
        return ("BUY", "open") if long_ else ("SELL", "open")
    if k in ("close", "exit"):
        return ("SELL", "close") if long_ else ("BUY", "close")
    return ("", "")


def direction_for_action(side: str, action: str) -> str:
    """(BUY,open)/(SELL,close)=long；(SELL,open)/(BUY,close)=short。"""
    if (side, action) in (("BUY", "open"), ("SELL", "close")):
        return "long"
    if (side, action) in (("SELL", "open"), ("BUY", "close")):
        return "short"
    return ""


def pnl_pct_of(entry: float, exit_: Optional[float], side: str) -> float:
    if entry <= 0 or exit_ is None:
        return 0.0
    if side == "short":
        return (entry - exit_) / entry * 100.0
    return (exit_ - entry) / entry * 100.0


def pnl_amount_of(entry: float, exit_: Optional[float], size: float, side: str) -> float:
    if exit_ is None or size <= 0:
        return 0.0
    diff = (exit_ - entry) if side != "short" else (entry - exit_)
    return diff * size


def timeframe_bars_per_kline(timeframe: str) -> int:
    """1m→1、4h→240、1d→1440（klines_processed 按周期换算）。"""
    m = re.fullmatch(r"(\d+)([A-Za-z]+)", (timeframe or "").strip().lower())
    if not m:
        return 1
    n, unit = int(m.group(1)), m.group(2)
    factor = {"s": 1 / 60, "m": 1, "h": 60, "d": 1440, "w": 10080}.get(unit)
    if not factor:
        return 1
    return max(1, int(round(n * factor)))


def yaml_scalar(text: str, key: str) -> Optional[str]:
    m = re.search(rf"^\s*{re.escape(key)}\s*:\s*([^\s#]+)", text, re.M)
    if not m:
        return None
    return m.group(1).strip().strip("'\"")


def yaml_params(text: str) -> Dict[str, Any]:
    """解析顶层 `params:` 块的两级键值（快照配置为简单两级结构）。"""
    params: Dict[str, Any] = {}
    m = re.search(r"^params:\s*$((?:[ \t]+\S.*(?:\n|$))*)", text, re.M)
    if not m:
        return params
    for line in m.group(1).splitlines():
        km = re.match(r"^\s+([A-Za-z_][\w.]*)\s*:\s*([^#]*)", line)
        if km:
            raw = km.group(2).strip().strip("'\"")
            for cast in (int, float):
                try:
                    params[km.group(1)] = cast(raw)
                    break
                except ValueError:
                    continue
            else:
                params[km.group(1)] = raw if raw else None
    return params


# ────────────────────────────────────────────────────────────────────
# 实盘侧：replay_data/{day}
# ────────────────────────────────────────────────────────────────────
@dataclass
class LivePosition:
    position_id: str
    runtime: str
    symbol: str
    side: str                              # long / short
    entry_time: datetime
    exit_time: Optional[datetime]
    entry_price: float
    exit_price: Optional[float]
    qty: float
    max_pnl_pct: float
    min_pnl_pct: float
    pnl_pct: Optional[float]
    pnl_amount: Optional[float]
    exit_reason: str = ""
    trading_mode: str = "live"

    @property
    def is_closed(self) -> bool:
        return self.exit_time is not None


@dataclass
class LiveBundle:
    strategy: str
    symbol: str
    mode: str
    runtime: str
    source_strategy: str
    positions: Dict[str, LivePosition] = field(default_factory=dict)
    signals: List[Dict[str, Any]] = field(default_factory=list)

    def add_position(self, pos: LivePosition) -> None:
        old = self.positions.get(pos.position_id)
        if old is None:
            self.positions[pos.position_id] = pos
        elif pos.is_closed and not old.is_closed:
            self.positions[pos.position_id] = pos
        elif pos.is_closed and old.is_closed:
            if (pos.exit_time or pos.entry_time) >= (old.exit_time or old.entry_time):
                self.positions[pos.position_id] = pos


def _mk_closed_pos(payload: Dict[str, Any], runtime_hint: str = "") -> Optional[LivePosition]:
    """history_position（扁平行或 payload_json）→ 已平仓仓位。"""
    runtime = payload.get("strategy_name") or runtime_hint
    symbol = (payload.get("symbol") or "").upper()
    entry_time = parse_dt(payload.get("entry_time"))
    exit_time = parse_dt(payload.get("exit_time"))
    entry_price = to_float(payload.get("entry_price"))
    if not runtime or not symbol or entry_time is None or entry_price is None:
        return None
    side = (payload.get("position_type") or payload.get("side") or "").lower()
    if side not in ("long", "short"):
        side = "long" if side in ("buy", "1", "") else "short"
    pid = payload.get("position_id") or f"{runtime}_{symbol}_{int(entry_time.timestamp())}"
    entry_size = to_float(payload.get("entry_size"), 0.0) or 0.0
    exit_size = to_float(payload.get("exit_size"))
    size = exit_size if exit_size else entry_size
    exit_price = to_float(payload.get("exit_price"))
    pnl_pct = to_float(payload.get("pnl_pct"))
    if pnl_pct is None and exit_price is not None:
        pnl_pct = pnl_pct_of(entry_price, exit_price, side)
    pnl_amount = to_float(payload.get("pnl"))
    if pnl_amount is None and exit_price is not None:
        pnl_amount = pnl_amount_of(entry_price, exit_price, size, side)
    return LivePosition(
        position_id=pid, runtime=runtime, symbol=symbol, side=side,
        entry_time=entry_time, exit_time=exit_time, entry_price=entry_price,
        exit_price=exit_price, qty=size,
        max_pnl_pct=to_float(payload.get("max_pnl_pct"), 0.0) or 0.0,
        min_pnl_pct=to_float(payload.get("min_pnl_pct"), 0.0) or 0.0,
        pnl_pct=pnl_pct, pnl_amount=pnl_amount,
        exit_reason=str(payload.get("exit_reason") or ""),
        trading_mode=(payload.get("trading_mode") or "live").lower(),
    )


def _mk_open_pos(payload: Dict[str, Any], runtime_hint: str = "") -> Optional[LivePosition]:
    """state/{day}/position.csv deleted=0：日终仍在场的仓位。"""
    state = payload.get("state") or {}
    runtime = payload.get("strategy_name") or runtime_hint
    symbol = (state.get("symbol") or "").upper()
    entry_time = parse_dt(state.get("entry_time"))
    entry_price = to_float(state.get("entry_price"))
    if not runtime or not symbol or entry_time is None or entry_price is None:
        return None
    side = (state.get("side") or "").lower()
    if side not in ("long", "short"):
        side = "long" if side in ("buy", "1", "") else "short"
    pid = state.get("position_id") or f"{runtime}_{symbol}_{int(entry_time.timestamp())}"
    size = to_float(state.get("total_size"), 0.0) or to_float(state.get("remaining_size"), 0.0) or 0.0
    return LivePosition(
        position_id=pid, runtime=runtime, symbol=symbol, side=side,
        entry_time=entry_time, exit_time=None, entry_price=entry_price, exit_price=None,
        qty=size,
        max_pnl_pct=to_float(state.get("max_pnl_pct"), 0.0) or 0.0,
        min_pnl_pct=to_float(state.get("min_pnl_pct"), 0.0) or 0.0,
        pnl_pct=None, pnl_amount=None, trading_mode="live",
    )


def _live_signal(row: Dict[str, str], payload: Dict[str, Any], day: str,
                 include_unfilled: bool) -> Optional[Dict[str, Any]]:
    status = (payload.get("status") or "").lower()
    if not include_unfilled and status not in ("", "filled"):
        return None
    intent = payload.get("intent") or {}
    ts = parse_dt(intent.get("created_event_time")) or parse_dt(row.get("created_at_ms"))
    if ts is None or day_of(ts) != day:
        return None
    side, action = action_from(intent.get("kind") or "", intent.get("direction") or "")
    if not action:
        return None
    filled_price = to_float(payload.get("filled_price"))
    price = filled_price if filled_price else to_float(intent.get("price"), 0.0) or 0.0
    qty = to_float(payload.get("filled_quantity"))
    if qty is None:
        qty = to_float(payload.get("order_quantity"))
    if qty is None:
        qty = to_float(intent.get("size"), 0.0) or 0.0
    return {
        "raw_id": row.get("id") or intent.get("id") or "",
        "timestamp": ts,
        "symbol": (intent.get("symbol") or "").upper(),
        "side": side,
        "action": action,
        "direction": (intent.get("direction") or "").lower() or direction_for_action(side, action),
        "price": price,
        "qty": qty,
        "status": "filled" if status in ("", "filled") else status,
        "filled_price": filled_price if filled_price else price,
        "filled_qty": qty,
        "reason": "",
        "strategy_id": intent.get("strategy_id") or "",
    }


def collect_live(day: str, replay_data: Path, active_only: bool,
                 include_unfilled: bool) -> Dict[Tuple[str, str], LiveBundle]:
    """扫描 replay_data/{day}，按 (strategy, symbol) 聚合运行实例。"""
    day_root = replay_data / day
    if not day_root.is_dir():
        return {}
    raw: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
        "positions": {}, "signals": [], "symbols": Counter(), "strategies": Counter(),
    })

    for project_dir in sorted(p for p in day_root.iterdir() if p.is_dir()):
        state_root = project_dir / "data" / "state"
        if not state_root.is_dir():
            continue
        state_day = state_root / day

        # 1) history_positions/{runtime}/{day}.csv —— 当日平仓明细（扁平列）
        hist_root = state_root / "history_positions"
        if hist_root.is_dir():
            for runtime_dir in sorted(p for p in hist_root.iterdir() if p.is_dir()):
                runtime = runtime_dir.name
                if not active_only:
                    raw[runtime]
                for row in read_csv_rows(runtime_dir / f"{day}.csv"):
                    payload = dict(row)
                    payload.setdefault("strategy_name", runtime)
                    pos = _mk_closed_pos(payload)
                    if pos is not None:
                        raw[runtime]["positions"][pos.position_id] = pos
                        raw[runtime]["symbols"][pos.symbol] += 1

        # 2) state/{day}/history_position.csv —— 聚合快照（payload_json），仅当日平仓
        for row in read_csv_rows(state_day / "history_position.csv"):
            payload = parse_payload(row)
            if not payload:
                continue
            runtime = payload.get("strategy_name") or ""
            if runtime and not active_only:
                raw[runtime]
            exit_time = parse_dt(payload.get("exit_time"))
            if exit_time is None or day_of(exit_time) != day:
                continue
            pos = _mk_closed_pos(payload)
            if pos is not None and runtime:
                bundle = raw[runtime]
                old = bundle["positions"].get(pos.position_id)
                if old is None or (pos.is_closed and not old.is_closed):
                    bundle["positions"][pos.position_id] = pos
                bundle["symbols"][pos.symbol] += 1

        # 3) state/{day}/position.csv deleted=0 —— 日终在场仓位
        for row in read_csv_rows(state_day / "position.csv"):
            payload = parse_payload(row)
            if not payload:
                continue
            runtime = payload.get("strategy_name") or ""
            if runtime and not active_only:
                raw[runtime]
            if str(row.get("deleted", "0")) != "0":
                continue
            pos = _mk_open_pos(payload)
            if pos is None or not runtime:
                continue
            existing = raw[runtime]["positions"].get(pos.position_id)
            if existing is None or not existing.is_closed:
                raw[runtime]["positions"][pos.position_id] = pos
            raw[runtime]["symbols"][pos.symbol] += 1

        # 4) state/{day}/signal.csv —— 当日信号
        for row in read_csv_rows(state_day / "signal.csv"):
            payload = parse_payload(row)
            if not payload:
                continue
            runtime = payload.get("strategy_name") or ""
            if runtime and not active_only:
                raw[runtime]
            sig = _live_signal(row, payload, day, include_unfilled)
            if sig is None or not runtime:
                continue
            raw[runtime]["signals"].append(sig)
            raw[runtime]["symbols"][sig["symbol"]] += 1
            if sig.get("strategy_id"):
                raw[runtime]["strategies"][sig["strategy_id"]] += 1

        # 5) cooldown.csv —— 运行实例兜底登记
        if not active_only:
            for row in read_csv_rows(state_day / "cooldown.csv"):
                payload = parse_payload(row)
                runtime = payload.get("strategy_name") or row.get("id") or ""
                if runtime:
                    raw[runtime]

    bundles: Dict[Tuple[str, str], LiveBundle] = {}
    for runtime in sorted(raw):
        data = raw[runtime]
        if not runtime:
            continue
        symbol = data["symbols"].most_common(1)[0][0] if data["symbols"] else ""
        prefix, parsed_symbol, mode = parse_runtime(runtime, symbol)
        symbol = symbol or parsed_symbol
        if not symbol:
            log(f"  [warn] 无法解析 symbol，跳过 runtime: {runtime}")
            continue
        mode = mode or "live"
        key = (prefix, symbol.upper())
        bundle = bundles.get(key)
        if bundle is None:
            bundle = LiveBundle(
                strategy=prefix, symbol=symbol.upper(), mode=mode, runtime=runtime,
                source_strategy=data["strategies"].most_common(1)[0][0] if data["strategies"] else prefix,
            )
            bundles[key] = bundle
        else:
            bundle.runtime = min(bundle.runtime, runtime)
        for pos in data["positions"].values():
            bundle.add_position(pos)
        seen_ids = {s["raw_id"] for s in bundle.signals}
        for sig in data["signals"]:
            if sig["raw_id"] not in seen_ids:
                bundle.signals.append(sig)
                seen_ids.add(sig["raw_id"])

    # 空闲实例沿用同策略已带出的 source_strategy
    resolved: Dict[str, str] = {}
    for bundle in bundles.values():
        if bundle.source_strategy != bundle.strategy:
            resolved.setdefault(bundle.strategy, bundle.source_strategy)
    for bundle in bundles.values():
        if bundle.source_strategy == bundle.strategy:
            bundle.source_strategy = resolved.get(bundle.strategy, bundle.source_strategy)

    for bundle in bundles.values():
        bundle.signals.sort(key=lambda s: s["timestamp"])
    return bundles


# ────────────────────────────────────────────────────────────────────
# 回测侧：replay_outputs/{day}
# ────────────────────────────────────────────────────────────────────
@dataclass
class Run:
    strategy: str
    symbol: str
    run_date: str          # YYYYMMDD（run_day）
    run_stamp: str         # YYYYMMDDTHHMMSS
    dir: Path
    result: Dict[str, Any]
    config_text: str = ""
    batch_id: str = ""
    sweep: int = 0
    source_strategy: str = ""   # 配置策略名（strategy 为 runtime 族名时保留来源）


def assign_batches(runs: List[Run], gap_seconds: int) -> None:
    """同 (strategy, run_day) 内聚类批次并分配 batch_id / sweep。

    规则（对齐样例 README 第 4 节）：
      * 真实回放逐标的串行启动，同批 run_stamp 相差数秒~数分钟；
        与上一个 run 间隔 > gap_seconds 视为下一批（sweep + 1）。
      * 若同批内出现重复 symbol（同秒重跑），顺延开新批，保证每批 symbol 唯一。
      * batch_id = {run_date}-{HHMM}，HHMM 取该批第一个 run 的发起时刻，
        与样例 `{day}-{HHMM}` 形态一致。
    """
    groups: Dict[Tuple[str, str], List[Run]] = defaultdict(list)
    for run in runs:
        groups[(run.strategy, run.run_date)].append(run)

    for items in groups.values():
        items.sort(key=lambda r: r.run_stamp)
        sweep = 0
        prev_ts: Optional[datetime] = None
        seen_symbols: set = set()
        batch_first_stamp: str = items[0].run_stamp
        for run in items:
            ts = parse_dt(run.run_stamp)
            new_batch = False
            if prev_ts is not None and ts is not None and (ts - prev_ts).total_seconds() > gap_seconds:
                new_batch = True
            if run.symbol in seen_symbols:
                new_batch = True
            if new_batch:
                sweep += 1
                seen_symbols = set()
                batch_first_stamp = run.run_stamp
            seen_symbols.add(run.symbol)
            if ts is not None:
                prev_ts = ts
            run.sweep = sweep
            run.batch_id = f"{run.run_date}-{batch_first_stamp[-6:-2]}"


def discover_runs(day: str, replay_outputs: Path) -> List[Run]:
    """扫描 {day}/{项目}/…/{strategy}/{run_date}/{HHMMSS}/{SYMBOL}/backtest_result.json。"""
    base = replay_outputs / day
    runs: List[Run] = []
    if not base.is_dir():
        return runs
    seen: set = set()
    for result_path in sorted(base.rglob("backtest_result.json")):
        symbol_dir = result_path.parent
        symbol = symbol_dir.name.upper()
        try:
            parts = list(symbol_dir.relative_to(base).parts[:-1])
        except ValueError:
            parts = []
        dates = [p for p in parts if DATE_RE.match(p)]
        times = [t for t in parts if HHMMSS_RE.match(t) or RUN_STAMP_RE.match(t)]
        non_date = [p for p in parts if not DATE_RE.match(p) and not HHMMSS_RE.match(p)
                    and not RUN_STAMP_RE.match(p)]
        source_strategy = non_date[-1] if non_date else (parts[0] if parts else symbol_dir.parent.name)
        strategy = source_strategy
        # engine 产物带 runtime 目录（{strategy}_{tf}_{lev}_{SYMBOL}_BACKTEST）时，
        # 用解析出的族名作为 strategy，与实盘侧 runtime 族名（..._LIVE）对齐。
        # 无成交的 run 不会生成 history_positions，故依次尝试：
        #   engine/<runtime>/ → engine/signals/<runtime>/ → engine/state/history_positions/
        engine_dir = symbol_dir / "engine"
        candidates: List[str] = []
        if engine_dir.is_dir():
            candidates += [p.name for p in sorted(engine_dir.iterdir())
                           if p.is_dir() and "BACKTEST" in p.name.upper()]
            signals_dir = engine_dir / "signals"
            if signals_dir.is_dir():
                candidates += [p.name for p in sorted(signals_dir.iterdir())
                               if p.is_dir() and "BACKTEST" in p.name.upper()]
            hist_root = engine_dir / "state" / "history_positions"
            if hist_root.is_dir():
                candidates += [p.name for p in sorted(hist_root.iterdir()) if p.is_dir()]
        for runtime_name in candidates:
            family, _sym, mode = parse_runtime(runtime_name, symbol)
            if family and mode:
                strategy = family
                break
        run_date = dates[-1] if dates else day
        run_time = times[-1] if times else ""
        if RUN_STAMP_RE.match(run_time or ""):
            run_stamp = run_time
        elif run_time:
            run_stamp = f"{run_date}T{run_time}"
        else:
            run_stamp = run_date
        key = (strategy, symbol, run_stamp)
        if key in seen:
            continue
        seen.add(key)
        result = load_json(result_path, {})
        if not isinstance(result, dict):
            continue
        config_text = ""
        cfg = symbol_dir / "config.yaml"
        if cfg.is_file():
            try:
                config_text = cfg.read_text(encoding="utf-8")
            except OSError:
                pass
        runs.append(Run(strategy=strategy, symbol=symbol, run_date=run_date,
                        run_stamp=run_stamp, dir=symbol_dir, result=result,
                        config_text=config_text, source_strategy=source_strategy))
    # 无成交的 run 可能拿不到任何 runtime 目录（engine/ 只有 state/），
    # 用同一 source_strategy 下已解析出的族名回填，避免出现
    # 配置名与 runtime 族名两个策略目录。
    family_by_source: Dict[str, str] = {}
    for run in runs:
        if run.strategy != getattr(run, "source_strategy", run.strategy):
            family_by_source.setdefault(run.source_strategy, run.strategy)
    for run in runs:
        if run.strategy == run.source_strategy:
            run.strategy = family_by_source.get(run.source_strategy, run.strategy)

    runs.sort(key=lambda r: (r.strategy, r.run_stamp, r.symbol))
    return runs


def read_run_positions(run: Run) -> List[Dict[str, Any]]:
    """回测全区间已平仓仓位（engine/state/history_positions/**/*.csv 扁平列）。"""
    rows: List[Dict[str, Any]] = []
    seen: set = set()
    hist_root = run.dir / "engine" / "state" / "history_positions"
    files: List[Path] = sorted(p for p in hist_root.rglob("*.csv")) if hist_root.is_dir() else []
    for path in files:
        for row in read_csv_rows(path):
            entry_time = parse_dt(row.get("entry_time"))
            exit_time = parse_dt(row.get("exit_time"))
            if entry_time is None or exit_time is None:
                continue
            pid = row.get("position_id") or ""
            key = pid or (entry_time, exit_time, row.get("entry_price"), row.get("exit_price"))
            if key in seen:
                continue
            seen.add(key)
            side = (row.get("position_type") or "").lower()
            if side not in ("long", "short"):
                side = "long" if side in ("buy", "1", "") else "short"
            entry_price = to_float(row.get("entry_price"), 0.0) or 0.0
            exit_price = to_float(row.get("exit_price"), 0.0) or 0.0
            size = to_float(row.get("exit_size")) or to_float(row.get("entry_size"), 0.0) or 0.0
            pnl_pct = to_float(row.get("pnl_pct"))
            if pnl_pct is None:
                pnl_pct = pnl_pct_of(entry_price, exit_price, side)
            rows.append({
                "position_id": pid, "side": side, "entry_time": entry_time,
                "entry_price": entry_price, "exit_time": exit_time,
                "exit_price": exit_price, "qty": size,
                "realized_pnl": pnl_amount_of(entry_price, exit_price, size, side),
                "pnl_pct": pnl_pct,
                "max_pnl_pct": to_float(row.get("max_pnl_pct"), 0.0) or 0.0,
                "min_pnl_pct": to_float(row.get("min_pnl_pct"), 0.0) or 0.0,
                "exit_reason": str(row.get("exit_reason") or ""),
            })
    rows.sort(key=lambda r: r["entry_time"])
    return rows


def read_run_signals(run: Run) -> List[Dict[str, Any]]:
    """回测引擎信号（engine/signals/*/signal.csv，全区间，扁平列）。

    去重键用成交语义 (time, side, action, price)，而非 signal_id：
    同一信号的多轮状态更新会在 CSV 里重复出现。
    """
    out: List[Dict[str, Any]] = []
    seen: set = set()
    files: List[Path] = []
    signals_dir = run.dir / "engine" / "signals"
    if signals_dir.is_dir():
        files.extend(sorted(signals_dir.glob("*/signal.csv")))
    for path in files:
        for row in read_csv_rows(path):
            sid = row.get("signal_id") or ""
            ts = parse_dt(row.get("timestamp"))
            action = (row.get("signal_action") or "").lower()
            if ts is None or not action:
                continue
            long_ = action in ("buy", "buy_close")
            side = "BUY" if long_ else "SELL"
            action_kind = "close" if action.endswith("_close") else "open"
            price = to_float(row.get("trigger_price"), 0.0) or 0.0
            qty = to_float(row.get("quantity"), 0.0) or 0.0
            key = (ts, side, action_kind, price, qty)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "raw_id": sid, "timestamp": ts, "side": side, "action": action_kind,
                "direction": direction_for_action(side, action_kind),
                "price": price, "qty": qty, "reason": "",
            })
    out.sort(key=lambda s: s["timestamp"])
    return out


def signals_from_positions(positions: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """engine/signals 缺失时由仓位推导（每仓一开一平，同样例语义）。"""
    out: List[Dict[str, Any]] = []
    for pos in positions:
        out.append({
            "raw_id": f"pos-{pos['position_id']}-open", "timestamp": pos["entry_time"],
            "side": "BUY" if pos["side"] == "long" else "SELL", "action": "open",
            "direction": pos["side"], "price": pos["entry_price"], "qty": pos["qty"],
            "reason": "",
        })
        out.append({
            "raw_id": f"pos-{pos['position_id']}-close", "timestamp": pos["exit_time"],
            "side": "SELL" if pos["side"] == "long" else "BUY", "action": "close",
            "direction": pos["side"], "price": pos["exit_price"], "qty": pos["qty"],
            "reason": pos["exit_reason"],
        })
    out.sort(key=lambda s: s["timestamp"])
    return out


# ────────────────────────────────────────────────────────────────────
# 指标 / 元信息
# ────────────────────────────────────────────────────────────────────
def metrics_of(result: Dict[str, Any]) -> Dict[str, Any]:
    metrics = result.get("metrics") or {}
    accounts = result.get("accounts") or []
    account = accounts[0] if accounts and isinstance(accounts[0], dict) else {}
    cfg = result.get("config") or {}
    return {
        "status": str(result.get("status") or "success"),
        "signals_processed": int(to_float(result.get("signals_processed"), 0.0) or 0),
        "trades_count": int(to_float(result.get("trades_count"), 0.0) or 0),
        "annualized_return": to_float(metrics.get("annualized_return"), 0.0) or 0.0,
        "roe": to_float(metrics.get("roe"), 0.0) or 0.0,
        "total_return": to_float(metrics.get("total_return"), 0.0) or 0.0,
        "max_drawdown": to_float(metrics.get("max_drawdown"),
                                 to_float(account.get("max_drawdown"), 0.0)) or 0.0,
        "win_rate": to_float(metrics.get("win_rate"), 0.0) or 0.0,
        "total_trades": int(to_float(metrics.get("total_trades"), 0.0) or 0),
        "sharpe_ratio": to_float(metrics.get("sharpe_ratio"), 0.0) or 0.0,
        "source_strategy": str(account.get("strategy_id") or ""),
        "initial_cash": to_float(cfg.get("initial_cash"), None) or DEFAULT_INITIAL_CASH,
        "start_date": str(cfg.get("start_date") or ""),
        "end_date": str(cfg.get("end_date") or ""),
    }


def meta_from_run(run: Run, engine: str, day: str, display_name: str,
                  strategy_version: str, description: str = "") -> Dict[str, Any]:
    text = run.config_text
    timeframe = (yaml_scalar(text, "timeframe") or "").lower()
    params = yaml_params(text) if text else {}
    warmup = to_float(yaml_scalar(text, "warmup_days"), None) if text else None
    m = metrics_of(run.result)
    return {
        "schema_version": SCHEMA_VERSION,
        "day": day,
        "strategy": run.strategy,
        "source_strategy": run.source_strategy or m["source_strategy"] or run.strategy,
        "display_name": display_name,
        "description": description or str((run.result.get("config") or {}).get("name")
                                          or f"{run.strategy} 回放策略"),
        "version": strategy_version,
        "engine": engine,
        "timeframe": timeframe,
        "leverage": int(to_float(yaml_scalar(text, "leverage"), 1.0) or 1),
        "warmup_days": int(warmup) if warmup else None,
        "indicators": sorted({re.sub(r"_[a-z0-9]+$", "", k).upper() for k in params}),
        "indicator_params": params,
        "logic": {},
        "params": params,
        "captured_at": fmt_z(parse_dt(run.result.get("end_time"))
                             or parse_dt(run.result.get("start_time"))),
    }


def meta_from_snapshot(strategy: str, engine: str, day: str, display_name: str,
                      args: argparse.Namespace) -> Dict[str, Any]:
    """纯实盘策略（当日无回放 run）的 meta.json：读快照配置，读不到给默认。"""
    timeframe = leverage = warmup = None
    params: Dict[str, Any] = {}
    snap_day = Path(args.snapshot) / day
    if snap_day.is_dir():
        for project in sorted(p for p in snap_day.iterdir() if p.is_dir()):
            cfg_dir = project / "config" / strategy
            text = ""
            if cfg_dir.is_dir():
                for f in sorted(cfg_dir.glob("*.yaml")):
                    try:
                        text = f.read_text(encoding="utf-8")
                    except OSError:
                        continue
                    break
            elif (project / "config" / f"{strategy}.yaml").is_file():
                try:
                    text = (project / "config" / f"{strategy}.yaml").read_text(encoding="utf-8")
                except OSError:
                    text = ""
            if text:
                timeframe = (yaml_scalar(text, "timeframe") or "").lower() or None
                leverage = to_float(yaml_scalar(text, "leverage"))
                warmup = to_float(yaml_scalar(text, "warmup_days"))
                params = yaml_params(text)
                break
    return {
        "schema_version": SCHEMA_VERSION,
        "day": day,
        "strategy": strategy,
        "source_strategy": strategy,
        "display_name": display_name,
        "description": f"{strategy} 实盘策略",
        "version": day,
        "engine": engine,
        "timeframe": timeframe or "",
        "leverage": int(leverage or 1),
        "warmup_days": int(warmup) if warmup else None,
        "indicators": sorted({re.sub(r"_[a-z0-9]+$", "", k).upper() for k in params}),
        "indicator_params": params,
        "logic": {},
        "params": params,
        "captured_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def load_display_names(path: Optional[str]) -> Dict[str, str]:
    if not path:
        return {}
    data = load_json(Path(path), {}) or {}
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


# ────────────────────────────────────────────────────────────────────
# 输出工具
# ────────────────────────────────────────────────────────────────────
def write_json(path: Path, obj: Any, pretty: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2 if pretty else None,
                  separators=None if pretty else (",", ":"))
    os.replace(tmp, path)


def write_csv(path: Path, columns: Sequence[str], rows: Iterable[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(columns), extrasaction="ignore",
                               lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in columns})
    os.replace(tmp, path)


# ────────────────────────────────────────────────────────────────────
# 一天 = 一棵目录树
# ────────────────────────────────────────────────────────────────────
class DayBuilder:
    def __init__(self, day: str, args: argparse.Namespace):
        self.day = day
        self.args = args
        self.out_day = Path(args.out) / day
        self.now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._mark_cache: Dict[str, Optional[float]] = {}
        self._live_sig_index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._run_pos_cache: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
        self._run_pos_rows: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}
        self._run_sig_rows: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = {}

    # ── 行情收盘价（OPEN 仓位浮动盈亏的 mark 价） ──
    def mark_price(self, symbol: str, day_end: datetime) -> Optional[float]:
        """取 < day_end 的最后一根 1m K 线 close。

        K 线 CSV 时间升序、timestamp 形如 "YYYY-MM-DD HH:MM:SS+00:00"：
        按行前缀字符串比较，扫到首个 日期前缀 >= day_end 当日 即停，取前一行。
        纯线性 + 硬行数上限，无二分/回溯，不存在不收敛路径。
        """
        cache_key = f"{symbol}|{day_end.strftime('%Y%m%d')}"
        if cache_key in self._mark_cache:
            return self._mark_cache[cache_key]
        close: Optional[float] = None
        kfile = Path(self.args.klines) / "1m" / f"{symbol}_1m.csv"
        if kfile.is_file():
            stop_prefix = day_end.strftime("%Y-%m-%d")
            try:
                with open(kfile, "r", encoding="utf-8", errors="ignore") as f:
                    header = f.readline().strip().split(",")
                    if "timestamp" not in header or "close" not in header:
                        raise ValueError("kline header missing columns")
                    ts_i, close_i = header.index("timestamp"), header.index("close")
                    prev_line = ""
                    scanned = 0
                    if ts_i == 0:
                        # 快速路径：按日期前缀比较，无需逐行解析时间
                        for line in f:
                            scanned += 1
                            if line[:10] >= stop_prefix:
                                break
                            prev_line = line
                            if scanned >= 20_000_000:
                                break
                    else:
                        # 兼容路径：timestamp 不在第一列时逐行解析
                        for line in f:
                            scanned += 1
                            parts = line.rstrip("\r\n").split(",")
                            if len(parts) <= ts_i:
                                continue
                            ts = parse_dt(parts[ts_i])
                            if ts is None or ts >= day_end:
                                break
                            prev_line = line
                            if scanned >= 5_000_000:
                                break
                    if prev_line:
                        parts = prev_line.rstrip("\r\n").split(",")
                        if len(parts) > close_i:
                            close = to_float(parts[close_i])
            except (OSError, ValueError):
                close = None
        self._mark_cache[cache_key] = close
        return close

    # ── 引擎检测（对齐 sync-exee/replay 的 detect_lang 规则） ──
    def detect_engine(self) -> str:
        roots = [Path(self.args.snapshot) / self.day,
                 Path(self.args.replay_data) / self.day]
        for root in roots:
            if not root.is_dir():
                continue
            for project in sorted(p for p in root.iterdir() if p.is_dir()):
                if (project / "Cargo.toml").is_file():
                    return "rust"
                if (project / "requirements.txt").is_file() or (project / "strategy_core").is_dir():
                    return "python"
        return "rust"

    def leverage_for(self, strategy: str, runtime: str) -> int:
        snap_day = Path(self.args.snapshot) / self.day
        if snap_day.is_dir():
            for project in sorted(p for p in snap_day.iterdir() if p.is_dir()):
                for cfg_dir in (project / "config" / strategy, project / "config" / runtime):
                    if cfg_dir.is_dir():
                        for f in sorted(cfg_dir.glob("*.yaml")):
                            try:
                                lev = to_float(yaml_scalar(f.read_text(encoding="utf-8"), "leverage"))
                            except OSError:
                                continue
                            if lev:
                                return int(lev)
                flat = project / "config" / f"{strategy}.yaml"
                if flat.is_file():
                    lev = to_float(yaml_scalar(flat.read_text(encoding="utf-8"), "leverage"))
                    if lev:
                        return int(lev)
        return self.args.leverage

    # ── 主入口 ──
    def build(self) -> Counter:
        stats: Counter = Counter()
        args = self.args
        day_begin, day_end = day_start_end(self.day)

        bundles = collect_live(self.day, Path(args.replay_data), args.active_only,
                               args.include_unfilled)
        runs = discover_runs(self.day, Path(args.replay_outputs))
        if args.run == "latest":
            best: Dict[Tuple[str, str], Run] = {}
            for run in runs:
                cur = best.get((run.strategy, run.symbol))
                if cur is None or run.run_stamp > cur.run_stamp:
                    best[(run.strategy, run.symbol)] = run
            runs = sorted(best.values(), key=lambda r: (r.strategy, r.run_stamp, r.symbol))
        assign_batches(runs, args.batch_gap)
        latest: Dict[Tuple[str, str], Run] = {}
        for run in runs:
            cur = latest.get((run.strategy, run.symbol))
            if cur is None or run.run_stamp > cur.run_stamp:
                latest[(run.strategy, run.symbol)] = run

        engine = self.detect_engine()
        display_map = load_display_names(args.display_names)
        per_strategy_runs: Dict[str, List[Run]] = defaultdict(list)
        for run in runs:
            per_strategy_runs[run.strategy].append(run)

        row_keys = set(bundles.keys()) | {(r.strategy, r.symbol) for r in runs}
        if not row_keys:
            log(f"  [{self.day}] 无实盘 bundle 且无回放 run，跳过")
            return stats

        # 预构造回测明细行（缓存供 comparison 使用）
        for run in runs:
            self._backtest_detail_rows(run, engine, display_map, latest)

        rows: List[Dict[str, Any]] = []
        strategy_rows: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for strategy, symbol in sorted(row_keys):
            bundle = bundles.get((strategy, symbol))
            symbol_runs = sorted(
                (r for r in per_strategy_runs.get(strategy, []) if r.symbol == symbol),
                key=lambda r: r.run_stamp,
            )
            latest_run = latest.get((strategy, symbol))
            m = metrics_of(latest_run.result) if latest_run else {}
            display_name = (display_map.get(strategy)
                            or (bundle.source_strategy if bundle and bundle.source_strategy != strategy else None)
                            or m.get("source_strategy")
                            or strategy)
            has_live = 1 if bundle and (bundle.positions or bundle.signals) else 0
            has_bt = 1 if symbol_runs else 0

            total_trades = winning = losing = open_count = 0
            total_pnl_amount = floating_amount = 0.0
            if bundle:
                for pos in bundle.positions.values():
                    if pos.is_closed:
                        total_trades += 1
                        amt = pos.pnl_amount
                        if amt is None:
                            amt = (pos.pnl_pct or 0.0) / 100.0 * pos.entry_price * pos.qty
                        total_pnl_amount += amt
                        if amt > 0:
                            winning += 1
                        elif amt < 0:
                            losing += 1
                    else:
                        open_count += 1
                        mark = self.mark_price(pos.symbol, day_end)
                        floating_amount += pnl_amount_of(pos.entry_price, mark, pos.qty, pos.side)

            initial_cash = m.get("initial_cash", DEFAULT_INITIAL_CASH) if latest_run else DEFAULT_INITIAL_CASH
            row = {
                "schema_version": SCHEMA_VERSION, "data_day": self.day,
                "strategy": strategy,
                "source_strategy": bundle.source_strategy if bundle else m.get("source_strategy") or strategy,
                "strategy_display_name": display_name,
                "strategy_version": self.day,
                "symbol": symbol,
                "runtime_name": bundle.runtime if bundle else "",
                "engine": engine,
                "trading_mode": bundle.mode if bundle else "backtest",
                "status": m.get("status", "success") if latest_run else "success",
                "has_live": has_live, "has_backtest": has_bt,
                "total_trades": total_trades, "winning_trades": winning,
                "losing_trades": losing,
                "win_rate": round(winning / total_trades, 6) if total_trades else 0,
                "total_pnl": round(total_pnl_amount / initial_cash, 6),
                "open_positions": open_count,
                "floating_pnl": round(floating_amount / initial_cash, 6),
                "latest_run_id": f"{strategy}-{latest_run.run_stamp}" if latest_run else "",
                "latest_annualized_return": num(m["annualized_return"]) if latest_run else "",
                "latest_roe": num(m["roe"]) if latest_run else "",
                "latest_max_drawdown": num(m["max_drawdown"]) if latest_run else "",
                "strategy_path": f"{self.day}/{strategy}",
                "_lev": self.leverage_for(strategy, bundle.runtime if bundle else ""),
                "_display": display_name,
            }
            if not row["has_live"] and not row["has_backtest"]:
                continue  # 双 0 行违反样例第 6 节存在规则，不落盘
            rows.append(row)
            strategy_rows[strategy].append(row)
            stats["rows"] += 1

        if not args.dry_run:
            self._write_all(rows, strategy_rows, per_strategy_runs, bundles,
                            latest, engine, display_map, stats)
        else:
            log(f"  [{self.day}] dry-run: rows={len(rows)} strategies={len(strategy_rows)} "
                f"runs={len(runs)} bundles={len(bundles)}")
        return stats

    # ── 回测 positions / signals 行 ──
    def _backtest_detail_rows(self, run: Run, engine: str, display_map, latest):
        strategy, symbol = run.strategy, run.symbol
        m = metrics_of(run.result)
        display = display_map.get(strategy) or m["source_strategy"] or strategy
        run_id = f"{strategy}-{run.run_stamp}"
        sweep = run.sweep
        is_latest = 1 if latest.get((strategy, symbol)) is run else 0
        completed = fmt_z(parse_dt(run.result.get("end_time"))
                          or parse_dt(run.result.get("start_time")))
        leverage = int(to_float(yaml_scalar(run.config_text, "leverage"), 1.0) or 1)

        positions = read_run_positions(run)
        self._run_pos_cache[(strategy, run.run_stamp, symbol)] = positions
        pos_rows: List[Dict[str, Any]] = []
        for i, pos in enumerate(positions, 1):
            pos_rows.append({
                "schema_version": SCHEMA_VERSION, "source": "replay", "data_day": self.day,
                "strategy": strategy, "source_strategy": m["source_strategy"] or strategy,
                "strategy_display_name": display, "strategy_version": self.day,
                "symbol": symbol, "run_id": run_id, "batch_id": run.batch_id,
                "run_day": run.run_date, "run_stamp": run.run_stamp, "sweep": sweep,
                "is_latest": is_latest, "engine": engine, "trading_mode": "backtest",
                "position_id": f"{run_id}-{symbol}-P{i}",
                "side": pos["side"], "status": "CLOSED", "qty": num(pos["qty"]),
                "entry_time": fmt_z(pos["entry_time"]), "entry_price": num(pos["entry_price"]),
                "exit_time": fmt_z(pos["exit_time"]), "exit_price": num(pos["exit_price"]),
                "realized_pnl": num(pos["realized_pnl"]), "pnl_pct": num(pos["pnl_pct"]),
                "max_pnl_pct": num(pos["max_pnl_pct"]), "min_pnl_pct": num(pos["min_pnl_pct"]),
                "leverage": leverage, "exit_reason": pos["exit_reason"],
                "updated_at": completed or fmt_z(pos["exit_time"]),
            })
        self._run_pos_rows[(strategy, run.run_stamp, symbol)] = pos_rows

        signals = read_run_signals(run) or signals_from_positions(positions)
        sig_rows: List[Dict[str, Any]] = []
        seq_by_key = {}
        for idx, pos in enumerate(positions):
            seq_by_key[("open", pos["entry_time"], pos["side"])] = idx + 1
            seq_by_key[("close", pos["exit_time"], pos["side"])] = idx + 1
        for i, sig in enumerate(signals, 1):
            seq = seq_by_key.get((sig["action"], sig["timestamp"], sig["direction"]))
            sig_rows.append({
                "schema_version": SCHEMA_VERSION, "source": "replay", "data_day": self.day,
                "strategy": strategy, "source_strategy": m["source_strategy"] or strategy,
                "strategy_display_name": display, "strategy_version": self.day,
                "symbol": symbol, "run_id": run_id, "batch_id": run.batch_id,
                "run_day": run.run_date, "run_stamp": run.run_stamp, "sweep": sweep,
                "is_latest": is_latest, "engine": engine, "trading_mode": "backtest",
                "signal_id": f"{run_id}-{symbol}-BS{seq if seq else i}",
                "signal_time": fmt_z(sig["timestamp"]),
                "side": sig["side"], "action": sig["action"], "direction": sig["direction"],
                "price": num(sig["price"]), "qty": num(sig["qty"]),
                "status": "filled", "filled_price": num(sig["price"]),
                "filled_qty": num(sig["qty"]), "reason": sig.get("reason", ""),
                "_ts": sig["timestamp"],
            })
        self._run_sig_rows[(strategy, run.run_stamp, symbol)] = sig_rows

    # ── 全部文件写入 ──
    def _write_all(self, rows, strategy_rows, per_strategy_runs, bundles, latest,
                   engine, display_map, stats: Counter) -> None:
        args = self.args
        if args.prune and self.out_day.is_dir():
            keep = set(strategy_rows.keys())
            for child in sorted(self.out_day.iterdir()):
                if child.is_dir() and child.name not in keep:
                    log(f"  [prune] 删除过期策略目录: {self.day}/{child.name}")
                    shutil.rmtree(child)

        write_csv(self.out_day / "manifest.csv", DAY_MANIFEST_COLUMNS, rows)

        all_runs = [r for s in sorted(per_strategy_runs) for r in per_strategy_runs[s]]
        if all_runs:
            write_csv(self.out_day / "backtest_runs.csv", RUNS_COLUMNS,
                      self._run_rows(all_runs, latest, engine, display_map))

        for strategy, srows in sorted(strategy_rows.items()):
            sdir = self.out_day / strategy
            write_csv(sdir / "manifest.csv", STRATEGY_MANIFEST_COLUMNS,
                      [{k: r[k] for k in STRATEGY_MANIFEST_COLUMNS} for r in srows])

            runs = sorted(per_strategy_runs.get(strategy, []),
                          key=lambda r: (r.run_stamp, r.symbol))
            display = next((r["_display"] for r in srows), strategy)
            if runs:
                write_csv(sdir / "backtest_runs.csv", RUNS_COLUMNS,
                          self._run_rows(runs, latest, engine, display_map))
                for run in runs:
                    write_json(sdir / "backtest_results" / run.run_stamp / f"{run.symbol}.json",
                               run.result, args.pretty)
                latest_overall = max(runs, key=lambda r: r.run_stamp)
                write_json(sdir / "meta.json",
                           meta_from_run(latest_overall, engine, self.day, display,
                                         self.day),
                           True)
            else:
                write_json(sdir / "meta.json",
                           meta_from_snapshot(strategy, engine, self.day, display, args),
                           True)
            if runs:

                non_empty = [r for r in runs
                             if metrics_of(r.result)["signals_processed"] > 0]
                pos_all = [row for r in non_empty
                           for row in self._run_pos_rows.get(
                               (strategy, r.run_stamp, r.symbol), [])]
                sig_all = [row for r in non_empty
                           for row in self._run_sig_rows.get((strategy, r.run_stamp, r.symbol), [])]
                if pos_all:
                    write_csv(sdir / "backtest_positions.csv", BACKTEST_POSITIONS_COLUMNS, pos_all)
                    stats["bt_positions"] += len(pos_all)
                if sig_all:
                    write_csv(sdir / "backtest_signals.csv", BACKTEST_SIGNALS_COLUMNS, sig_all)
                    stats["bt_signals"] += len(sig_all)

            # live 文件
            if any(r["has_live"] for r in srows):
                self._write_live_files(strategy, sdir, bundles, engine, stats)

            # signal_comparison.csv
            self._write_comparison(strategy, sdir, srows, runs, latest, stats)
            stats["strategies"] += 1

        self._update_catalog(strategy_rows.keys(), rows)

    def _run_rows(self, runs: List[Run], latest, engine, display_map):
        out: List[Dict[str, Any]] = []
        for run in runs:
            m = metrics_of(run.result)
            display = display_map.get(run.strategy) or m["source_strategy"] or run.strategy
            out.append({
                "schema_version": SCHEMA_VERSION, "source": "replay",
                "data_day": self.day, "batch_id": run.batch_id,
                "run_id": f"{run.strategy}-{run.run_stamp}",
                "run_day": run.run_date, "run_stamp": run.run_stamp,
                "sweep": run.sweep,
                "strategy": run.strategy, "source_strategy": m["source_strategy"] or run.strategy,
                "strategy_display_name": display, "strategy_version": self.day,
                "config_version": yaml_scalar(run.config_text, "version") or "",
                "symbol": run.symbol, "start_date": m["start_date"], "end_date": m["end_date"],
                "status": m["status"],
                "completed_at": fmt_z(parse_dt(run.result.get("end_time"))
                                      or parse_dt(run.result.get("start_time"))),
                "signals_processed": m["signals_processed"],
                "trades_count": m["trades_count"],
                "annualized_return": num(m["annualized_return"]), "roe": num(m["roe"]),
                "total_return": num(m["total_return"]), "max_drawdown": num(m["max_drawdown"]),
                "win_rate": num(m["win_rate"]), "total_trades": m["total_trades"],
                "sharpe_ratio": num(m["sharpe_ratio"]),
                "is_latest": 1 if latest.get((run.strategy, run.symbol)) is run else 0,
            })
        return out

    def _write_live_files(self, strategy: str, sdir: Path, bundles, engine,
                          stats: Counter) -> None:
        day_begin, day_end = day_start_end(self.day)
        updated = fmt_z(day_end - timedelta(seconds=1))
        items = [(s, b) for (st, s), b in bundles.items() if st == strategy]
        pos_rows: List[Dict[str, Any]] = []
        sig_rows: List[Dict[str, Any]] = []
        for symbol in sorted(x[0] for x in items):
            bundle = next(b for s_, b in items if s_ == symbol)
            lev = self.leverage_for(strategy, bundle.runtime)
            display = bundle.source_strategy if bundle.source_strategy != strategy else strategy
            positions = sorted(bundle.positions.values(), key=lambda p: p.entry_time)
            for i, pos in enumerate(positions, 1):
                row: Dict[str, Any] = {
                    "schema_version": SCHEMA_VERSION, "data_day": self.day,
                    "strategy": strategy, "source_strategy": bundle.source_strategy,
                    "strategy_display_name": display, "strategy_version": self.day,
                    "symbol": symbol, "runtime_name": bundle.runtime, "engine": engine,
                    "trading_mode": bundle.mode,
                    "position_id": f"{strategy}-{symbol}-LIVE-P{i}",
                    "side": pos.side, "status": "CLOSED" if pos.is_closed else "OPEN",
                    "qty": num(pos.qty),
                    "entry_time": fmt_z(pos.entry_time), "entry_price": num(pos.entry_price),
                    "exit_time": fmt_z(pos.exit_time) if pos.exit_time else "",
                    "exit_price": num(pos.exit_price) if pos.exit_price is not None else "",
                    "realized_pnl": num(pos.pnl_amount) if pos.is_closed else 0,
                    "pnl_pct": "", "max_pnl_pct": num(pos.max_pnl_pct),
                    "min_pnl_pct": num(pos.min_pnl_pct), "leverage": lev,
                    "exit_reason": pos.exit_reason, "updated_at": updated,
                }
                if pos.is_closed:
                    row["pnl_pct"] = num(pos.pnl_pct if pos.pnl_pct is not None
                                         else pnl_pct_of(pos.entry_price, pos.exit_price, pos.side))
                else:
                    mark = self.mark_price(pos.symbol, day_end)
                    if mark is not None:
                        row["pnl_pct"] = num(pnl_pct_of(pos.entry_price, mark, pos.side))
                pos_rows.append(row)

            for i, sig in enumerate(bundle.signals, 1):
                sig_rows.append({
                    "schema_version": SCHEMA_VERSION, "data_day": self.day,
                    "strategy": strategy, "source_strategy": bundle.source_strategy,
                    "strategy_display_name": display, "strategy_version": self.day,
                    "symbol": symbol, "runtime_name": bundle.runtime, "engine": engine,
                    "trading_mode": bundle.mode,
                    "signal_id": f"{strategy}-{bundle.runtime}-{symbol}-LS{i}",
                    "signal_time": fmt_z(sig["timestamp"]), "side": sig["side"],
                    "action": sig["action"], "direction": sig["direction"],
                    "price": num(sig["price"]), "qty": num(sig["qty"]),
                    "status": sig["status"], "filled_price": num(sig["filled_price"]),
                    "filled_qty": num(sig["filled_qty"]), "reason": sig["reason"],
                    "_ts": sig["timestamp"],
                })
        if pos_rows:
            write_csv(sdir / "live_positions.csv", LIVE_POSITIONS_COLUMNS, pos_rows)
            stats["live_positions"] += len(pos_rows)
        if sig_rows:
            write_csv(sdir / "live_signals.csv", LIVE_SIGNALS_COLUMNS, sig_rows)
            stats["live_signals"] += len(sig_rows)
        self._live_sig_index[strategy] = sig_rows

    def _write_comparison(self, strategy: str, sdir: Path, srows, runs: List[Run],
                          latest, stats: Counter) -> None:
        args = self.args
        rows_out: List[Dict[str, Any]] = []
        for r in srows:
            symbol = r["symbol"]
            display = r["_display"]
            live_sigs = [s for s in self._live_sig_index.get(strategy, [])
                         if s["symbol"] == symbol]
            # 无实盘信号的标的（纯回测）不产对比行，符合样例第 6 节存在规则
            if not live_sigs:
                continue
            run = latest.get((strategy, symbol))
            bt_sigs = self._run_sig_rows.get((strategy, run.run_stamp, symbol), []) if run else []
            run_id = f"{strategy}-{run.run_stamp}" if run else ""
            batch_id = run.batch_id if run else ""

            def base(rec_type, match_type, action, live_id, bt_id, live_time, bt_time,
                     diff, lp, bp, pdiff, status):
                return {
                    "schema_version": SCHEMA_VERSION, "data_day": self.day,
                    "strategy": strategy, "source_strategy": r["source_strategy"],
                    "strategy_display_name": display, "symbol": symbol,
                    "run_id": run_id, "batch_id": batch_id,
                    "record_type": rec_type, "match_type": match_type,
                    "signal_action": action, "live_signal_id": live_id,
                    "backtest_signal_id": bt_id, "live_time": live_time,
                    "backtest_time": bt_time, "time_diff_seconds": diff,
                    "live_price": num(lp), "backtest_price": num(bp),
                    "price_diff_pct": pdiff, "status": status,
                }

            matched_l: set = set()
            matched_b: set = set()
            pairs: List[Tuple[int, int, str]] = []
            # 1) 同时间戳 + 同 side/action 精确
            for i, l in enumerate(live_sigs):
                for j, b in enumerate(bt_sigs):
                    if j in matched_b:
                        continue
                    if l["_ts"] == b["_ts"] and l["side"] == b["side"] and l["action"] == b["action"]:
                        pairs.append((i, j, "exact"))
                        matched_l.add(i)
                        matched_b.add(j)
                        break
            # 2) 时间窗口内最近邻（同 side/action）
            for i, l in enumerate(live_sigs):
                if i in matched_l:
                    continue
                best_j, best_diff = None, float("inf")
                for j, b in enumerate(bt_sigs):
                    if j in matched_b or b["side"] != l["side"] or b["action"] != l["action"]:
                        continue
                    d = abs((b["_ts"] - l["_ts"]).total_seconds())
                    if d <= args.time_window and d < best_diff:
                        best_j, best_diff = j, d
                if best_j is None:
                    continue
                pairs.append((i, best_j, "time_window"))
                matched_l.add(i)
                matched_b.add(best_j)

            for i, j, kind in pairs:
                l, b = live_sigs[i], bt_sigs[j]
                diff = abs((b["_ts"] - l["_ts"]).total_seconds())
                lp, bp = l["price"], b["price"]
                pdiff = round(abs(lp - bp) / lp, 4) if lp else 0
                rows_out.append(base("matched", kind, l["action"], l["signal_id"],
                                     b["signal_id"], fmt_z(l["_ts"]), fmt_z(b["_ts"]),
                                     int(diff), lp, bp, pdiff, "matched"))
            for i, l in enumerate(live_sigs):
                if i in matched_l:
                    continue
                rows_out.append(base("unmatched_live", "none", l["action"], l["signal_id"],
                                     "", fmt_z(l["_ts"]), "", "", l["price"], None, None,
                                     "unmatched"))
            for j, b in enumerate(bt_sigs):
                if j in matched_b:
                    continue
                rows_out.append(base("unmatched_backtest", "none", b["action"], "",
                                     b["signal_id"], "", fmt_z(b["_ts"]), "", None, b["price"],
                                     None, "missed"))

        if rows_out:
            rows_out.sort(key=lambda x: (x["symbol"], x["live_time"] or x["backtest_time"],
                                         x["record_type"]))
            write_csv(sdir / "signal_comparison.csv", COMPARISON_COLUMNS, rows_out)
            stats["comparison"] += len(rows_out)

    def _update_catalog(self, strategies, rows) -> None:
        catalog_path = Path(self.args.out) / "catalog.csv"
        entries: Dict[str, Dict[str, Any]] = {}
        for row in read_csv_rows(catalog_path):
            if row.get("day"):
                entries[row["day"]] = {k: row.get(k, "") for k in CATALOG_COLUMNS}
        entries[self.day] = {
            "schema_version": SCHEMA_VERSION, "day": self.day,
            "strategies": "|".join(sorted(set(strategies))),
            "has_live": 1 if any(r["has_live"] for r in rows) else 0,
            "has_backtest": 1 if any(r["has_backtest"] for r in rows) else 0,
            "updated_at": self.now_iso,
        }
        write_csv(catalog_path, CATALOG_COLUMNS,
                  [entries[d] for d in sorted(entries)])


# ────────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────────
ENV_WORKSPACE = os.environ.get("REPLAY_WORKSPACE")
# 默认工作区 = REPLAY_WORKSPACE 环境变量；未设置则用当前目录。
# replay.py 调用本脚本时会显式传入所有路径，不依赖此默认值。
DEFAULT_WORKSPACE = Path(ENV_WORKSPACE) if ENV_WORKSPACE else Path.cwd()


def list_replay_dates(replay_root: Path) -> List[str]:
    if not replay_root.is_dir():
        return []
    return sorted(p.name for p in replay_root.iterdir() if p.is_dir() and DATE_RE.match(p.name))


def resolve_dates(args: argparse.Namespace) -> List[str]:
    dates = list_replay_dates(Path(args.replay_data))
    if args.all:
        return dates
    if args.start or args.end:
        if not (args.start and args.end):
            raise SystemExit("错误：--start 与 --end 必须同时指定")
        cur = datetime.strptime(args.start, "%Y%m%d")
        end = datetime.strptime(args.end, "%Y%m%d")
        out = []
        while cur <= end:
            out.append(cur.strftime("%Y%m%d"))
            cur += timedelta(days=1)
        return out
    if args.date:
        return [args.date]
    return [dates[-1]] if dates else []


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="把 replay_data + replay_outputs 转换成 strategy-kanban frontend-data v2（CSV）布局",
    )
    g = p.add_mutually_exclusive_group()
    g.add_argument("--date", type=normalize_day, help="处理单日 YYYYMMDD（默认 replay_data 最新一天）")
    g.add_argument("--all", action="store_true", help="处理 replay_data 下所有日期")
    p.add_argument("--start", type=normalize_day, help="起始日期（与 --end 配合）")
    p.add_argument("--end", type=normalize_day, help="结束日期（与 --start 配合）")

    p.add_argument("--replay-data", default=str(DEFAULT_WORKSPACE / "replay_data"),
                   help="实盘快照根目录（默认 REPLAY_WORKSPACE/replay_data）")
    p.add_argument("--replay-outputs", default=str(DEFAULT_WORKSPACE / "replay_outputs"),
                   help="回测输出根目录")
    p.add_argument("--snapshot", default=str(DEFAULT_WORKSPACE / "snapshot"),
                   help="代码快照根目录（引擎/杠杆/meta 来源）")
    p.add_argument("--klines", default=str(DEFAULT_WORKSPACE / "data" / "klines"),
                   help="K线根目录（OPEN 仓位浮动盈亏 mark 价）")
    p.add_argument("--out", default=str(DEFAULT_WORKSPACE / "frontend-data"),
                   help="frontend-data 输出根目录")

    p.add_argument("--display-names", default=None,
                   help="策略显示名映射 JSON：{\"strategy\": \"中文名\"}")
    p.add_argument("--run", choices=["latest", "all"], default="all",
                   help="同日多次回测保留全部批次（all，默认，样例即如此）或仅最新（latest）")
    p.add_argument("--time-window", type=int, default=600,
                   help="信号时间窗口匹配容差（秒），默认 600")
    p.add_argument("--batch-gap", type=int, default=1800,
                   help="同策略回放批次聚簇间隔（秒），默认 1800；批次间 sweep 递增")
    p.add_argument("--leverage", type=int, default=1, help="快照读不到杠杆时的默认值")
    p.add_argument("--include-unfilled", action="store_true", help="非 filled 的实盘信号也纳入")
    p.add_argument("--active-only", action="store_true", help="只输出当日有仓位/信号的运行实例")
    p.add_argument("--prune", action="store_true", help="删除目标日下不在本次清单里的旧策略目录")
    p.add_argument("--pretty", action="store_true", help="回测结果 JSON 缩进输出（默认紧凑）")
    p.add_argument("--dry-run", action="store_true", help="只打印统计，不写文件")
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    dates = resolve_dates(args)
    if not dates:
        log(f"未找到待处理日期（replay_data={args.replay_data}）")
        return 1

    log(f"待处理 {len(dates)} 天: {', '.join(dates)}")
    log(f"输入: replay_data={args.replay_data} replay_outputs={args.replay_outputs}")
    log(f"输出: {args.out}")

    total: Counter = Counter()
    for day in dates:
        log(f"\n[{day}] 开始")
        total.update(DayBuilder(day, args).build())

    log(f"\n完成：{len(dates)} 天 | rows={total['rows']} strategies={total['strategies']} "
        f"live_positions={total['live_positions']} live_signals={total['live_signals']} "
        f"bt_positions={total['bt_positions']} bt_signals={total['bt_signals']} "
        f"comparison_rows={total['comparison']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
