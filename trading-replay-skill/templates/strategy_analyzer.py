#!/usr/bin/env python3
"""strategy_analyzer.py — 策略分析共享模块

共享模块，与 trading-discovery-skill/templates/strategy_analyzer.py 保持同步。
任何修改需同步到另一份。

分析策略配置、代码完整性、K线数据可用性，输出结构化分析结果。
供 analyze_snapshot.py (replay) 和 analyze_strategies.py (discovery) 调用。
"""

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# YAML 解析：优先 PyYAML，fallback 纯文本解析
try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


# ===== 数据结构 =====

@dataclass
class KlineDataStatus:
    """单个 symbol 的 K线数据状态"""
    csv_exists: bool = False
    row_count: int = 0
    first_date: Optional[str] = None
    last_date: Optional[str] = None
    covers_range: bool = False
    missing_range: Optional[str] = None


@dataclass
class CodeChecks:
    """策略代码文件检查"""
    strategy_py: bool = False
    core_py: str = ""  # 找到的 core 文件名，空=未找到


@dataclass
class StrategyAnalysisResult:
    """单个策略的分析结果"""
    strategy_name: str = ""
    model: str = ""
    config_path: str = ""
    symbols: list = field(default_factory=list)
    timeframes: list = field(default_factory=list)
    direction: str = ""
    params: dict = field(default_factory=dict)
    code_checks: CodeChecks = field(default_factory=CodeChecks)
    kline_data: dict = field(default_factory=dict)  # {SYMBOL: KlineDataStatus}
    status: str = "skip"  # ready / partial / skip
    issues: list = field(default_factory=list)


# ===== Config 解析 =====

def _parse_yaml_file(path: str) -> dict:
    """解析 YAML 配置文件，返回顶层 dict"""
    if HAS_YAML:
        with open(path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else {}
    else:
        return _simple_yaml_parse(path)


def _simple_yaml_parse(path: str) -> dict:
    """简易 YAML 解析 fallback（无 PyYAML 时使用）"""
    result = {}
    current_key = None
    current_sub = {}

    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.rstrip()
            if not stripped or stripped.lstrip().startswith('#'):
                continue

            indent = len(line) - len(line.lstrip())

            if indent == 0 and ':' in stripped:
                if current_key and current_sub:
                    result[current_key] = current_sub
                elif current_key:
                    val = stripped.split(':', 1)[1].strip()
                    result[current_key] = _parse_simple_value(val)

                current_key = stripped.split(':')[0].strip()
                val = stripped.split(':', 1)[1].strip()
                if val:
                    result[current_key] = _parse_simple_value(val)
                    current_key = None
                    current_sub = {}
                else:
                    current_sub = {}
            elif indent > 0 and current_key:
                sub_stripped = stripped.strip()
                if ':' in sub_stripped:
                    sub_key = sub_stripped.split(':')[0].strip()
                    sub_val = sub_stripped.split(':', 1)[1].strip()
                    current_sub[sub_key] = _parse_simple_value(sub_val)

    if current_key and current_sub:
        result[current_key] = current_sub

    return result


def _parse_simple_value(val: str):
    """解析简单 YAML 值"""
    val = val.strip()
    if not val:
        return ""
    if (val.startswith('"') and val.endswith('"')) or \
       (val.startswith("'") and val.endswith("'")):
        return val[1:-1]
    if val.lower() in ('true', 'yes'):
        return True
    if val.lower() in ('false', 'no'):
        return False
    try:
        return int(val)
    except ValueError:
        pass
    try:
        return float(val)
    except ValueError:
        pass
    if val.startswith('[') and val.endswith(']'):
        items = val[1:-1].split(',')
        return [item.strip().strip("'\"") for item in items if item.strip()]
    return val


def _extract_strategy_config(config_data: dict, strategy_name: str) -> dict:
    """从配置数据中提取指定策略的配置

    配置格式: 顶层 key 为策略名，value 为策略配置 dict
    """
    if strategy_name in config_data:
        cfg = config_data[strategy_name]
        return cfg if isinstance(cfg, dict) else {}

    for key, val in config_data.items():
        if key.lower() == strategy_name.lower() and isinstance(val, dict):
            return val

    return {}


def list_override_symbols(strategy_dir: str) -> list:
    """列出 strategies/<name>/overrides/ 下所有 per-symbol 配置对应的 symbol。

    v3.7 起每个 (策略, 代币) 的参数各自独立成文件，overrides/ 的文件名
    即该策略实际可运行的 symbol 全集。
    """
    odir = Path(strategy_dir) / "overrides"
    if not odir.is_dir():
        return []
    return sorted(
        f.stem for f in odir.glob("*.yaml")
        if f.is_file() and not f.name.startswith(".")
    )


def resolve_config(strategy_dir: str, strategy_name: str, symbol: str = "") -> Optional[str]:
    """解析策略参数配置路径（v3.7 单一事实来源）。

    唯一来源: strategies/<name>/overrides/<SYMBOL>.yaml
    —— 与实盘 run_strategy.py 和回测 run_backtest.py 读的是同一份文件，
    这正是"回测不失真"的前提。

    symbol 为空时取 overrides/ 下第一个文件作为代表（仅用于读 symbols/
    timeframes 等元信息，不用于实际回测）。

    Returns: 配置文件绝对路径，未找到返回 None
    """
    sdir = Path(strategy_dir)
    odir = sdir / "overrides"

    if symbol:
        cfg = odir / f"{symbol}.yaml"
        return str(cfg.resolve()) if cfg.is_file() else None

    for name in list_override_symbols(strategy_dir):
        cfg = odir / f"{name}.yaml"
        if cfg.is_file():
            return str(cfg.resolve())

    return None


# 向后兼容别名：两种模式现在读同一份 overrides，不再有 replay/discovery 之分
def resolve_config_replay(strategy_dir: str, strategy_name: str) -> Optional[str]:
    """已统一为 resolve_config()，保留名字避免调用方断裂"""
    return resolve_config(strategy_dir, strategy_name)


def resolve_config_discovery(strategy_dir: str, strategy_name: str, symbol: str = "") -> Optional[str]:
    """已统一为 resolve_config()，保留名字避免调用方断裂"""
    return resolve_config(strategy_dir, strategy_name, symbol)


# ===== K线数据检查 =====

def _find_kline_csv(data_dir: Path, symbol: str, timeframe: str = "") -> Optional[Path]:
    """定位某 symbol 的 K 线 CSV。

    模板实际布局是按周期分目录: {csv_dir}/{tf}/{SYMBOL}_{tf}.csv
    （如 data/klines/8h/BTCUSDT_8h.csv），所以优先按 timeframe 精确命中；
    否则退回扁平布局与全局 rglob。

    传入 timeframe 很重要：不传时 rglob 会拿到任意周期的文件，
    而不同周期的起止日期不同，覆盖范围判断会跟着抖。
    """
    if not data_dir.is_dir():
        return None

    candidates = []
    if timeframe:
        candidates.extend([
            data_dir / timeframe / f"{symbol}_{timeframe}.csv",
            data_dir / timeframe / f"{symbol}.csv",
        ])
    candidates.extend([
        data_dir / f"{symbol}.csv",
    ])

    for c in candidates:
        if c.is_file():
            return c

    # 扁平布局的带后缀命名: BTCUSDT_8h.csv
    for pattern in [f"{symbol}_*.csv"]:
        matches = sorted(data_dir.glob(pattern))
        if matches:
            return matches[0]

    # 独立子目录: {data_dir}/{SYMBOL}/*.csv
    symbol_dir = data_dir / symbol
    if symbol_dir.is_dir():
        matches = sorted(symbol_dir.glob("*.csv"))
        if matches:
            return matches[0]

    # 兜底全局搜索
    for f in sorted(data_dir.rglob(f"{symbol}*.csv")):
        if f.is_file():
            return f

    return None


def check_kline_data(symbol: str, kline_data_dir: str, start_date: str = "",
                     end_date: str = "", timeframe: str = "") -> KlineDataStatus:
    """检查单个 symbol 的 K线数据

    纯 Python file I/O，不依赖 pandas。
    读 CSV 首行+末行获取日期范围。
    """
    status = KlineDataStatus()

    data_dir = Path(kline_data_dir)
    csv_file = _find_kline_csv(data_dir, symbol, timeframe)

    if not csv_file:
        return status

    status.csv_exists = True

    try:
        with open(csv_file, 'r', encoding='utf-8') as f:
            header = f.readline()
            first_line = f.readline().strip()

            f.seek(0, 2)
            file_size = f.tell()
            seek_pos = max(0, file_size - 4096)
            f.seek(seek_pos)
            tail = f.read()
            lines = [l.strip() for l in tail.split('\n') if l.strip()]
            last_line = lines[-1] if lines else ""

        avg_line_len = 80
        status.row_count = max(0, file_size // avg_line_len - 1)

        status.first_date = _extract_date(first_line)
        status.last_date = _extract_date(last_line)

        if start_date and end_date and status.first_date and status.last_date:
            try:
                sd = _parse_date_str(start_date)
                ed = _parse_date_str(end_date)
                fd = _parse_date_str(status.first_date)
                ld = _parse_date_str(status.last_date)

                if fd and ld and sd and ed:
                    covers = (fd <= sd) and (ld >= ed)
                    status.covers_range = covers
                    if not covers:
                        gaps = []
                        if fd > sd:
                            gaps.append(f"{sd.strftime('%Y%m%d')}-{fd.strftime('%Y%m%d')}")
                        if ld < ed:
                            gaps.append(f"{ld.strftime('%Y%m%d')}-{ed.strftime('%Y%m%d')}")
                        status.missing_range = ", ".join(gaps)
            except (ValueError, TypeError):
                pass

    except (IOError, OSError):
        pass

    return status


def _extract_date(csv_line: str) -> Optional[str]:
    """从 CSV 行提取日期（第一列），统一返回 YYYYMMDD

    支持格式:
      - YYYYMMDD
      - YYYY-MM-DD
      - YYYY-MM-DD HH:MM:SS[+00:00]  ← 模板 K 线 CSV 的实际格式
      - Unix timestamp（秒/毫秒）
    """
    if not csv_line:
        return None

    parts = csv_line.split(',')
    if not parts:
        return None

    date_str = parts[0].strip().strip('"')
    if not date_str:
        return None

    # ISO 日期或 ISO datetime：取前 10 字符的日期部分。
    # 模板 CSV 首列形如 "2026-06-02 00:00:00+00:00"，长度 25，
    # 早期版本只判 len==10 会漏掉它，然后 fallback 到 date_str[:8]
    # 得到 "2026-06-" 这种非法值，导致后续所有日期比较静默失效。
    if len(date_str) >= 10 and date_str[4] == '-' and date_str[7] == '-':
        head = date_str[:10]
        if head[:4].isdigit() and head[5:7].isdigit() and head[8:10].isdigit():
            return head.replace('-', '')

    if len(date_str) == 8 and date_str.isdigit():
        return date_str

    try:
        ts = int(date_str)
        if ts > 1e12:
            ts = ts // 1000
        dt = datetime.fromtimestamp(ts)
        return dt.strftime('%Y%m%d')
    except (ValueError, OSError):
        pass

    return None


def _parse_date_str(date_str: str) -> Optional[datetime]:
    """解析日期字符串为 datetime"""
    if not date_str:
        return None

    if len(date_str) == 8 and date_str.isdigit():
        try:
            return datetime.strptime(date_str, '%Y%m%d')
        except ValueError:
            return None

    if len(date_str) >= 10 and date_str[4] == '-' and date_str[7] == '-':
        try:
            return datetime.strptime(date_str[:10], '%Y-%m-%d')
        except ValueError:
            return None

    try:
        ts = int(date_str)
        if ts > 1e12:
            ts = ts // 1000
        return datetime.fromtimestamp(ts)
    except (ValueError, OSError):
        return None


# ===== 核心分析函数 =====

def analyze_strategy(strategy_dir: str, strategy_name: str, model: str = "",
                     start_date: str = "", end_date: str = "",
                     kline_data_dir: str = "./data/klines",
                     config_mode: str = "replay") -> StrategyAnalysisResult:
    """分析单个策略

    Args:
        strategy_dir: 策略目录路径 (含 strategy.py, overrides/ 等)
        strategy_name: 策略名称
        model: 模型标识 (replay 用)
        start_date: 回测开始日期
        end_date: 回测结束日期
        kline_data_dir: K线数据目录
        config_mode: 已废弃且不再生效。v3.7 起 replay 与 discovery
            读同一份 strategies/<name>/overrides/<SYMBOL>.yaml，
            不再有两套配置解析路径。参数保留仅为兼容旧调用方。

    Returns:
        StrategyAnalysisResult
    """
    result = StrategyAnalysisResult(
        strategy_name=strategy_name,
        model=model,
    )

    sdir = Path(strategy_dir)
    if not sdir.is_dir():
        result.issues.append(f"策略目录不存在: {strategy_dir}")
        result.status = "skip"
        return result

    # 1. 检查代码文件
    strategy_py = sdir / "strategy.py"
    result.code_checks.strategy_py = strategy_py.is_file()

    for f in sdir.glob("*_core.py"):
        if f.is_file():
            result.code_checks.core_py = f.name
            break

    if not result.code_checks.strategy_py:
        result.issues.append("strategy.py 缺失")

    # 2. 解析配置文件（v3.7: strategies/<name>/overrides/<SYMBOL>.yaml）
    config_path = resolve_config(strategy_dir, strategy_name)

    if not config_path:
        result.issues.append(
            "无 per-symbol 配置（缺 overrides/<SYMBOL>.yaml）"
        )
        result.status = "skip"
        return result

    result.config_path = config_path

    try:
        config_data = _parse_yaml_file(config_path)
        strategy_cfg = _extract_strategy_config(config_data, strategy_name)

        if not strategy_cfg:
            if 'enabled' in config_data or 'symbols' in config_data:
                strategy_cfg = config_data
            else:
                result.issues.append(f"配置文件中未找到策略 '{strategy_name}' 的配置段")
                strategy_cfg = {}

        # symbols 来自 overrides/ 目录的文件名，而不是某一份配置里的 symbols 字段。
        # v3.7 每份 overrides/<SYM>.yaml 只描述自己那个 symbol，读单份的
        # symbols 字段只会看到一个代币，会漏掉该策略其余已配好的标的。
        result.symbols = list_override_symbols(strategy_dir)
        if not result.symbols:
            fallback = strategy_cfg.get('symbols', [])
            if isinstance(fallback, str):
                fallback = [s.strip() for s in fallback.split(',') if s.strip()]
            result.symbols = fallback

        result.timeframes = strategy_cfg.get('timeframes', [])
        if isinstance(result.timeframes, str):
            result.timeframes = [tf.strip() for tf in result.timeframes.split(',')]

        result.direction = strategy_cfg.get('direction', '')
        result.params = strategy_cfg.get('params', {})

        enabled = strategy_cfg.get('enabled', None)
        if enabled is False:
            result.issues.append("策略已禁用 (enabled: false)")

    except Exception as e:
        result.issues.append(f"配置解析失败: {e}")
        result.status = "skip"
        return result

    # 3. 检查 K线数据
    if not result.symbols:
        result.issues.append("overrides/ 下无 per-symbol 配置，无可回测标的")
    else:
        # 用策略主周期定位 CSV：数据按 {csv_dir}/{tf}/{SYM}_{tf}.csv 分目录存放
        main_tf = result.timeframes[0] if result.timeframes else ""
        all_ok = True
        for symbol in result.symbols:
            kline_status = check_kline_data(
                symbol, kline_data_dir, start_date, end_date, timeframe=main_tf
            )
            result.kline_data[symbol] = kline_status
            if not kline_status.csv_exists:
                result.issues.append(f"{symbol} 无K线数据")
                all_ok = False
            elif not kline_status.covers_range and start_date and end_date:
                result.issues.append(f"{symbol} 数据不覆盖回测范围: {kline_status.missing_range}")
                all_ok = False

        if not result.issues:
            result.status = "ready"
        elif all_ok and any("disabled" in i for i in result.issues):
            result.status = "partial"
        elif any(s for s in result.kline_data.values() if s.csv_exists):
            result.status = "partial"
        else:
            result.status = "skip"

    if result.status == "skip" and result.code_checks.strategy_py and result.config_path:
        if any(s for s in result.kline_data.values() if s.csv_exists):
            result.status = "partial"

    return result


def analyze_snapshot(snapshot_day_dir: str, start_date: str = "", end_date: str = "",
                     kline_data_dir: str = "./data/klines",
                     strategy_filter: str = "", model_filter: str = "") -> list:
    """分析 snapshot 目录下所有策略

    Args:
        snapshot_day_dir: snapshot/{date}/ 目录
        start_date: 回测开始日期
        end_date: 回测结束日期
        kline_data_dir: K线数据目录
        strategy_filter: 策略名过滤
        model_filter: 模型过滤

    Returns:
        list[StrategyAnalysisResult]
    """
    results = []
    snap_dir = Path(snapshot_day_dir)

    if not snap_dir.is_dir():
        return results

    for item in sorted(snap_dir.iterdir()):
        if not item.is_dir():
            continue

        basename = item.name

        if '-' in basename:
            strategy_name = basename.rsplit('-', 1)[0]
            model = basename.rsplit('-', 1)[1]
        else:
            strategy_name = basename
            model = ""

        if strategy_filter and strategy_name != strategy_filter:
            continue
        if model_filter and model != model_filter:
            continue

        strategy_dir = item / "strategies" / strategy_name
        if not strategy_dir.is_dir():
            strategy_dir = item

        result = analyze_strategy(
            strategy_dir=str(strategy_dir),
            strategy_name=strategy_name,
            model=model,
            start_date=start_date,
            end_date=end_date,
            kline_data_dir=kline_data_dir,
            config_mode="replay",
        )
        results.append(result)

    return results


def analyze_strategy_list(strategies: list, strategies_dir: str,
                          symbols: list = None, start_date: str = "",
                          end_date: str = "", kline_data_dir: str = "./data/klines") -> list:
    """分析策略列表（discovery 模式）

    Args:
        strategies: 策略名列表
        strategies_dir: 策略根目录
        symbols: 指定的 symbol 列表（可选，覆盖配置中的 symbols）
        start_date: 回测开始日期
        end_date: 回测结束日期
        kline_data_dir: K线数据目录

    Returns:
        list[StrategyAnalysisResult]
    """
    results = []
    sdir = Path(strategies_dir)

    for strategy_name in strategies:
        strategy_dir = sdir / strategy_name
        result = analyze_strategy(
            strategy_dir=str(strategy_dir),
            strategy_name=strategy_name,
            start_date=start_date,
            end_date=end_date,
            kline_data_dir=kline_data_dir,
            config_mode="discovery",
        )

        if symbols:
            # 用户指定的 symbols 与该策略实际配好的 overrides 求交集。
            # 不做交集会把没有 overrides 的组合报成 ready，等到 batch_runner
            # 才因显式清单里的文件缺失而整批报错。
            available = set(list_override_symbols(str(strategy_dir)))
            requested = list(symbols)
            usable = [s for s in requested if s in available] if available else []
            missing = [s for s in requested if s not in available]

            result.symbols = usable
            result.kline_data = {}
            result.issues = [
                i for i in result.issues
                if "无K线数据" not in i
                and "数据不覆盖" not in i
                and "无可回测标的" not in i
            ]
            for symbol in missing:
                result.issues.append(f"{symbol} 缺 overrides/{symbol}.yaml")

            main_tf = result.timeframes[0] if result.timeframes else ""
            for symbol in usable:
                kline_status = check_kline_data(
                    symbol, kline_data_dir, start_date, end_date, timeframe=main_tf
                )
                result.kline_data[symbol] = kline_status
                if not kline_status.csv_exists:
                    result.issues.append(f"{symbol} 无K线数据")
                elif not kline_status.covers_range and start_date and end_date:
                    result.issues.append(f"{symbol} 数据不覆盖回测范围: {kline_status.missing_range}")

            if not usable:
                result.status = "skip"
            elif not result.issues:
                result.status = "ready"
            elif result.code_checks.strategy_py and result.config_path:
                result.status = "partial"
            else:
                result.status = "skip"

        results.append(result)

    return results


# ===== 报告格式化 =====

def format_analysis_report(results: list, source: str = "", source_path: str = "",
                           start_date: str = "", end_date: str = "",
                           kline_data_dir: str = "") -> str:
    """格式化分析报告（人类可读终端输出）"""
    lines = []
    lines.append("=" * 60)
    lines.append("  Strategy Analysis Report")
    lines.append("=" * 60)

    if source:
        lines.append(f"  Source: {source}")
    if source_path:
        lines.append(f"  Path:   {source_path}")
    if start_date or end_date:
        lines.append(f"  Range:  {start_date or '?'} ~ {end_date or '?'}")
    if kline_data_dir:
        lines.append(f"  Data:   {kline_data_dir}")
    lines.append("")

    ready_count = 0
    partial_count = 0
    skip_count = 0

    for r in results:
        if r.status == "ready":
            ready_count += 1
            tag = "[READY]   "
        elif r.status == "partial":
            partial_count += 1
            tag = "[PARTIAL] "
        else:
            skip_count += 1
            tag = "[SKIP]    "

        model_str = f" ({r.model})" if r.model else ""
        lines.append(f"{tag}{r.strategy_name}{model_str}")

        # 显式标注运行模式
        if r.model:
            model_labels = {"product": "实盘", "smoking": "模拟盘", "paper": "纸上交易"}
            model_label = model_labels.get(r.model, r.model)
            lines.append(f"  Model: {r.model} ({model_label})")

        if r.config_path:
            lines.append(f"  Config: {r.config_path}")
        if r.symbols:
            lines.append(f"  Symbols: {', '.join(r.symbols)}")
        if r.timeframes:
            tf_str = ', '.join(r.timeframes) if isinstance(r.timeframes, list) else str(r.timeframes)
            dir_str = f" | Direction: {r.direction}" if r.direction else ""
            lines.append(f"  Timeframes: {tf_str}{dir_str}")
        if r.params:
            param_parts = [f"{k}={v}" for k, v in r.params.items()]
            lines.append(f"  Params: {', '.join(param_parts)}")

        code_parts = []
        code_parts.append(f"strategy.py {'OK' if r.code_checks.strategy_py else 'MISSING'}")
        if r.code_checks.core_py:
            code_parts.append(f"{r.code_checks.core_py} OK")
        elif not r.code_checks.core_py and r.code_checks.strategy_py:
            code_parts.append("no *_core.py")
        lines.append(f"  Code: {' | '.join(code_parts)}")

        if r.kline_data:
            data_parts = []
            for sym, ks in r.kline_data.items():
                if ks.csv_exists:
                    if ks.covers_range:
                        data_parts.append(f"{sym} OK")
                    elif ks.missing_range:
                        data_parts.append(f"{sym} GAP({ks.missing_range})")
                    else:
                        data_parts.append(f"{sym} EXISTS")
                else:
                    data_parts.append(f"{sym} MISSING")
            lines.append(f"  Data: {' | '.join(data_parts)}")

        if r.issues:
            lines.append(f"  Issues: {'; '.join(r.issues)}")

        lines.append("")

    total = len(results)
    can_proceed = ready_count + partial_count
    lines.append("-" * 60)
    lines.append(f"Summary: {ready_count} ready, {partial_count} partial, {skip_count} skip | "
                 f"{can_proceed} of {total} can proceed")
    lines.append("=" * 60)

    return '\n'.join(lines)


def format_analysis_json(results: list, source: str = "", source_path: str = "",
                         start_date: str = "", end_date: str = "",
                         kline_data_dir: str = "") -> dict:
    """格式化分析结果为 JSON 结构"""
    ready_count = sum(1 for r in results if r.status == "ready")
    partial_count = sum(1 for r in results if r.status == "partial")
    skip_count = sum(1 for r in results if r.status == "skip")

    strategies_json = []
    for r in results:
        r_dict = asdict(r)
        strategies_json.append(r_dict)

    return {
        "analysis_version": "1.0",
        "timestamp": datetime.now().isoformat(),
        "source": source,
        "source_path": source_path,
        "start_date": start_date,
        "end_date": end_date,
        "kline_data_dir": kline_data_dir,
        "strategies": strategies_json,
        "summary": {
            "ready": ready_count,
            "partial": partial_count,
            "skip": skip_count,
            "total": len(results),
        }
    }


# ===== CLI 入口（用于独立测试） =====

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="策略分析工具")
    parser.add_argument("--strategy-dir", help="策略目录路径")
    parser.add_argument("--strategy-name", help="策略名称")
    parser.add_argument("--snapshot-dir", help="snapshot/{date}/ 目录 (replay 模式)")
    parser.add_argument("--strategies", help="策略列表，逗号分隔 (discovery 模式)")
    parser.add_argument("--strategies-dir", help="策略根目录 (discovery 模式)")
    parser.add_argument("--symbols", help="代币列表，逗号分隔")
    parser.add_argument("--start", help="回测开始日期")
    parser.add_argument("--end", help="回测结束日期")
    parser.add_argument("--kline-data-dir", default="./data/klines", help="K线数据目录")
    parser.add_argument("--output", help="JSON 输出路径")
    parser.add_argument("--mode", choices=["replay", "discovery"], default="replay")

    args = parser.parse_args()

    start_date = args.start or ""
    end_date = args.end or ""
    symbols = [s.strip() for s in args.symbols.split(',')] if args.symbols else None

    if args.snapshot_dir:
        results = analyze_snapshot(
            snapshot_day_dir=args.snapshot_dir,
            start_date=start_date,
            end_date=end_date,
            kline_data_dir=args.kline_data_dir,
        )
        source = "replay"
        source_path = args.snapshot_dir
    elif args.strategies and args.strategies_dir:
        strategy_list = [s.strip() for s in args.strategies.split(',')]
        results = analyze_strategy_list(
            strategies=strategy_list,
            strategies_dir=args.strategies_dir,
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            kline_data_dir=args.kline_data_dir,
        )
        source = "discovery"
        source_path = args.strategies_dir
    elif args.strategy_dir and args.strategy_name:
        result = analyze_strategy(
            strategy_dir=args.strategy_dir,
            strategy_name=args.strategy_name,
            start_date=start_date,
            end_date=end_date,
            kline_data_dir=args.kline_data_dir,
            config_mode=args.mode,
        )
        results = [result]
        source = args.mode
        source_path = args.strategy_dir
    else:
        parser.print_help()
        sys.exit(1)

    report = format_analysis_report(
        results, source=source, source_path=source_path,
        start_date=start_date, end_date=end_date,
        kline_data_dir=args.kline_data_dir,
    )
    print(report)

    if args.output:
        json_data = format_analysis_json(
            results, source=source, source_path=source_path,
            start_date=start_date, end_date=end_date,
            kline_data_dir=args.kline_data_dir,
        )
        os.makedirs(os.path.dirname(args.output) or '.', exist_ok=True)
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(json_data, f, indent=2, ensure_ascii=False)
        print(f"\nJSON output: {args.output}")
