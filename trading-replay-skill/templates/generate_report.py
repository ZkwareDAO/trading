#!/usr/bin/env python3
"""generate_report.py — Discovery/Replay 回测对比报告生成

从回测输出目录读取所有 backtest_result.json，生成对比报告。

产物目录结构（模板 backtest/backtest_reporter.py）:
    {output_dir}/{strategy}/{date}/{time}/{symbol}/backtest_result.json
指标位于 JSON 的 "metrics" 段（不是顶层）。

用法:
    python3 generate_report.py --output-dir ./discovery_outputs --start 20260601 --end 20260701
"""

import argparse
import json
import os
import sys
from pathlib import Path

# 结果文件名（backtest_reporter.py 的 prefix 固定为 backtest）
RESULT_FILENAME = "backtest_result.json"


def _num(v, default=0.0) -> float:
    """把 JSON 值安全转成 float（None / 字符串 / NaN 占位都兜住）"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    if f != f:  # NaN
        return default
    return f


def collect_results(output_dir: str) -> list:
    """递归查找所有 backtest_result.json，从路径反推 strategy/date/time/symbol。

    用 rglob 而非固定层级 glob：即使目录层级微调也不会静默漏结果。
    """
    base = Path(output_dir)
    if not base.is_dir():
        return []

    summary = []
    for result_file in sorted(base.rglob(RESULT_FILENAME)):
        try:
            with open(result_file, "r", encoding="utf-8") as f:
                r = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"WARN: 跳过无法解析的结果文件 {result_file}: {e}",
                  file=sys.stderr)
            continue

        # 相对路径反推: {strategy}/{date}/{time}/{symbol}/backtest_result.json
        try:
            rel_parts = result_file.relative_to(base).parts
        except ValueError:
            rel_parts = ()

        symbol = rel_parts[-2] if len(rel_parts) >= 2 else "?"
        strategy = rel_parts[0] if len(rel_parts) >= 4 else "?"
        run_date = rel_parts[1] if len(rel_parts) >= 4 else ""
        run_time = rel_parts[2] if len(rel_parts) >= 4 else ""

        # v3.7: 指标在 metrics 段；兼容极早期把指标放顶层的产物
        metrics = r.get("metrics")
        if not isinstance(metrics, dict):
            metrics = r

        summary.append({
            "strategy": strategy,
            "symbol": symbol,
            "run_at": f"{run_date}/{run_time}".strip("/"),
            "total_return": _num(metrics.get("total_return")),
            "roe": _num(metrics.get("roe")),
            "max_drawdown": _num(metrics.get("max_drawdown")),
            "win_rate": _num(metrics.get("win_rate")),
            "total_trades": int(_num(metrics.get("total_trades"))),
            "sharpe_ratio": _num(metrics.get("sharpe_ratio")),
            "profit_factor": _num(metrics.get("profit_factor")),
            "path": str(result_file),
        })

    return summary


def _dedupe_latest(summary: list) -> list:
    """同一 (strategy, symbol) 多次运行时只保留最新一次（按 run_at 排序）"""
    latest = {}
    for s in summary:
        key = (s["strategy"], s["symbol"])
        prev = latest.get(key)
        if prev is None or s["run_at"] >= prev["run_at"]:
            latest[key] = s
    return sorted(latest.values(), key=lambda x: (x["strategy"], x["symbol"]))


def generate_report(output_dir: str, start_date: str, end_date: str,
                    title: str = "Discovery 回测对比报告") -> str:
    """生成对比报告"""
    all_results = collect_results(output_dir)
    summary = _dedupe_latest(all_results)

    lines = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"时间范围: {start_date} - {end_date}")
    lines.append(f"结果数: {len(summary)}（扫描到 {len(all_results)} 次运行，同组合取最新）")
    lines.append("")

    if not summary:
        lines.append(f"⚠ 未在 `{output_dir}` 下找到任何 {RESULT_FILENAME}")
        lines.append("")
        lines.append("排查方向:")
        lines.append("- 确认 run-profile 的 `output_dir` 指向该目录")
        lines.append("- 确认 batch_runner 实际执行成功（查看 logs/backtest/ 下日志）")
        return "\n".join(lines)

    strategies = sorted(set(s["strategy"] for s in summary))
    symbols = sorted(set(s["symbol"] for s in summary))

    lines.append("## 按策略对比")
    lines.append("")
    for st in strategies:
        lines.append(f"**{st}:**")
        lines.append("")
        lines.append("| 代币 | 收益 | ROE | 回撤 | 胜率 | 交易数 | 夏普 | 盈亏比 |")
        lines.append("|------|------|-----|------|------|--------|------|--------|")
        for s in summary:
            if s["strategy"] != st:
                continue
            lines.append(
                f"| {s['symbol']} "
                f"| {s['total_return'] * 100:+.2f}% "
                f"| {s['roe'] * 100:+.2f}% "
                f"| {s['max_drawdown'] * 100:.2f}% "
                f"| {s['win_rate'] * 100:.1f}% "
                f"| {s['total_trades']} "
                f"| {s['sharpe_ratio']:.2f} "
                f"| {s['profit_factor']:.2f} |"
            )
        lines.append("")

    lines.append("## 按代币对比")
    lines.append("")
    for sym in symbols:
        sym_results = [(s["strategy"], s["total_return"])
                       for s in summary if s["symbol"] == sym]
        sym_results.sort(key=lambda x: x[1], reverse=True)
        ranking = " > ".join(f"{st} ({ret * 100:+.2f}%)" for st, ret in sym_results)
        lines.append(f"- **{sym}**: {ranking}")
    lines.append("")

    # 零交易的组合单独点出来：多数"收益 0%"其实是没成交，不是策略没赚钱
    zero_trade = [s for s in summary if s["total_trades"] == 0]
    if zero_trade:
        lines.append("## ⚠ 零交易组合")
        lines.append("")
        lines.append("以下组合回测期内未产生任何交易（数据不足 / 信号未触发 / 周期过长）:")
        for s in zero_trade:
            lines.append(f"- {s['strategy']} × {s['symbol']}")
        lines.append("")

    traded = [s for s in summary if s["total_trades"] > 0]
    if traded:
        best = max(traded, key=lambda x: x["total_return"])
        lines.append("## 最佳组合")
        lines.append(
            f"- 策略x代币: {best['strategy']} x {best['symbol']} "
            f"({best['total_return'] * 100:+.2f}%, "
            f"{best['total_trades']} 笔, 夏普 {best['sharpe_ratio']:.2f})"
        )
        lines.append(f"- 结果文件: `{best['path']}`")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="回测对比报告生成")
    parser.add_argument("--output-dir", required=True, help="回测产物根目录")
    parser.add_argument("--start", required=True, help="回测开始日期 (YYYYMMDD)")
    parser.add_argument("--end", required=True, help="回测结束日期 (YYYYMMDD)")
    parser.add_argument("--report-name", default="",
                        help="报告文件名（默认 discovery-report-{start}-{end}.md）")
    parser.add_argument("--title", default="Discovery 回测对比报告",
                        help="报告标题")
    args = parser.parse_args()

    report = generate_report(args.output_dir, args.start, args.end, args.title)

    name = args.report_name or f"discovery-report-{args.start}-{args.end}.md"
    os.makedirs(args.output_dir, exist_ok=True)
    report_file = os.path.join(args.output_dir, name)
    with open(report_file, "w", encoding="utf-8") as f:
        f.write(report)

    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
