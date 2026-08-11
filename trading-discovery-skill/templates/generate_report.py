#!/usr/bin/env python3
"""generate_report.py — Discovery 回测对比报告生成

从 discovery_outputs 目录读取所有回测结果，生成对比报告。

用法:
    python3 generate_report.py --output-dir ./discovery_outputs --start 20260601 --end 20260701
"""

import argparse
import json
import os
import glob
import sys


def generate_report(output_dir: str, start_date: str, end_date: str) -> str:
    """生成对比报告"""
    summary = []

    for strategy_dir in sorted(glob.glob(os.path.join(output_dir, "*"))):
        strategy = os.path.basename(strategy_dir)
        if strategy.startswith("discovery-report"):
            continue
        for symbol_dir in sorted(glob.glob(os.path.join(strategy_dir, "*"))):
            symbol = os.path.basename(symbol_dir)
            for date_range_dir in sorted(glob.glob(os.path.join(symbol_dir, "*"))):
                date_range = os.path.basename(date_range_dir)
                result_file = os.path.join(date_range_dir, "backtest_result.json")
                if os.path.exists(result_file):
                    with open(result_file) as f:
                        r = json.load(f)
                    summary.append({
                        "strategy": strategy,
                        "symbol": symbol,
                        "date_range": date_range,
                        "total_return": r.get("total_return", 0),
                        "max_drawdown": r.get("max_drawdown", 0),
                        "win_rate": r.get("win_rate", 0),
                        "total_trades": r.get("total_trades", 0),
                        "sharpe_ratio": r.get("sharpe_ratio", 0),
                        "profit_factor": r.get("profit_factor", 0),
                    })

    lines = []
    lines.append("# Discovery 回测对比报告")
    lines.append("")
    lines.append(f"时间范围: {start_date} - {end_date}")
    lines.append("")

    strategies = sorted(set(s["strategy"] for s in summary))
    symbols = sorted(set(s["symbol"] for s in summary))

    lines.append("## 按策略对比")
    lines.append("")
    for st in strategies:
        lines.append(f"**{st}:**")
        lines.append("")
        lines.append("| 代币 | 收益 | 回撤 | 胜率 | 交易数 | 夏普 |")
        lines.append("|------|------|------|------|--------|------|")
        for s in summary:
            if s["strategy"] == st:
                ret = f"{s['total_return']*100:+.1f}%"
                dd = f"{s['max_drawdown']*100:.1f}%"
                wr = f"{s['win_rate']*100:.1f}%"
                lines.append(
                    f"| {s['symbol']} | {ret} | {dd} | {wr} | "
                    f"{s['total_trades']} | {s['sharpe_ratio']:.2f} |"
                )
        lines.append("")

    lines.append("## 按代币对比")
    lines.append("")
    for sym in symbols:
        sym_results = [(s["strategy"], s["total_return"]) for s in summary if s["symbol"] == sym]
        sym_results.sort(key=lambda x: x[1], reverse=True)
        ranking = " > ".join([f"{st} ({ret*100:+.1f}%)" for st, ret in sym_results])
        lines.append(f"- **{sym}**: {ranking}")
    lines.append("")

    if summary:
        best = max(summary, key=lambda x: x["total_return"])
        best_ret = f"{best['total_return']*100:+.1f}%"
        lines.append("## 最佳组合")
        lines.append(f"- 策略x代币: {best['strategy']} x {best['symbol']} ({best_ret})")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Discovery 回测对比报告生成")
    parser.add_argument("--output-dir", required=True, help="discovery_outputs 目录路径")
    parser.add_argument("--start", required=True, help="回测开始日期 (YYYYMMDD)")
    parser.add_argument("--end", required=True, help="回测结束日期 (YYYYMMDD)")
    args = parser.parse_args()

    report = generate_report(args.output_dir, args.start, args.end)

    report_file = os.path.join(
        args.output_dir, f"discovery-report-{args.start}-{args.end}.md"
    )
    with open(report_file, "w") as f:
        f.write(report)

    print(report)


if __name__ == "__main__":
    main()
