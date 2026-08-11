#!/usr/bin/env python3
"""analyze_snapshot.py — Replay 策略分析 CLI

Phase 2.5: 分析 snapshot 目录下的策略配置、代码完整性、K线数据可用性。
供 replay.sh 调用，输出分析报告 + JSON 文件。

用法:
  python3 analyze_snapshot.py --snapshot-dir ./snapshot/20260801 --start 20260702 --end 20260801
  python3 analyze_snapshot.py --snapshot-dir ./snapshot/20260801 --strategy ema_rsi --model product
"""

import argparse
import json
import os
import sys

# 同目录导入 strategy_analyzer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy_analyzer import (
    analyze_snapshot,
    format_analysis_report,
    format_analysis_json,
)


def main():
    parser = argparse.ArgumentParser(description="Replay 策略分析 (Phase 2.5)")
    parser.add_argument("--snapshot-dir", required=True,
                        help="snapshot/{date}/ 目录路径")
    parser.add_argument("--start", default="", help="回测开始日期 (YYYYMMDD)")
    parser.add_argument("--end", default="", help="回测结束日期 (YYYYMMDD)")
    parser.add_argument("--kline-data-dir", default="./data/strategies/1m",
                        help="K线数据目录 (默认: ./data/strategies/1m)")
    parser.add_argument("--output", default="",
                        help="JSON 输出路径 (默认: logs/analysis-{date}.json)")
    parser.add_argument("--strategy-filter", default="",
                        help="只分析指定策略")
    parser.add_argument("--model-filter", default="",
                        help="只分析指定模型")

    args = parser.parse_args()

    # 执行分析
    results = analyze_snapshot(
        snapshot_day_dir=args.snapshot_dir,
        start_date=args.start,
        end_date=args.end,
        kline_data_dir=args.kline_data_dir,
        strategy_filter=args.strategy_filter,
        model_filter=args.model_filter,
    )

    # 打印报告
    report = format_analysis_report(
        results,
        source="replay",
        source_path=args.snapshot_dir,
        start_date=args.start,
        end_date=args.end,
        kline_data_dir=args.kline_data_dir,
    )
    print(report)

    # 写 JSON
    output_path = args.output
    if not output_path:
        snapshot_date = os.path.basename(args.snapshot_dir.rstrip('/'))
        logs_dir = os.path.join(os.path.dirname(args.snapshot_dir.rstrip('/')), '..', 'logs')
        output_path = os.path.join(logs_dir, f"analysis-{snapshot_date}.json")

    json_data = format_analysis_json(
        results,
        source="replay",
        source_path=args.snapshot_dir,
        start_date=args.start,
        end_date=args.end,
        kline_data_dir=args.kline_data_dir,
    )

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(json_data, f, indent=2, ensure_ascii=False)

    print(f"\nJSON output: {output_path}")

    # 返回码: 0=有可回测策略, 1=全部 skip
    can_proceed = sum(1 for r in results if r.status in ("ready", "partial"))
    if can_proceed == 0:
        print("\n⚠ 无可回测策略 (全部 skip)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
