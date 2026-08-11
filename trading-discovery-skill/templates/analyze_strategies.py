#!/usr/bin/env python3
"""analyze_strategies.py — Discovery 策略分析 CLI

Phase 1.5: 分析策略配置、代码完整性、K线数据可用性。
供 discover.sh 调用，输出分析报告 + JSON 文件。
当 --symbols 未指定时，从策略配置中读取默认 symbols。

用法:
  python3 analyze_strategies.py --strategies ema_rsi,ict_v4 --strategies-dir ./strategies --start 20260601 --end 20260701
  python3 analyze_strategies.py --strategies ema_rsi --strategies-dir ./strategies --symbols BTCUSDT,ETHUSDT --start 20260601
  python3 analyze_strategies.py --strategies ema_rsi --strategies-dir ./strategies --start 20260601  # symbols 从配置读取
"""

import argparse
import json
import os
import sys

# 同目录导入 strategy_analyzer
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from strategy_analyzer import (
    analyze_strategy_list,
    format_analysis_report,
    format_analysis_json,
)


def main():
    parser = argparse.ArgumentParser(description="Discovery 策略分析 (Phase 1.5)")
    parser.add_argument("--strategies", required=True,
                        help="策略列表，逗号分隔")
    parser.add_argument("--strategies-dir", required=True,
                        help="策略根目录路径")
    parser.add_argument("--symbols", default="",
                        help="代币列表，逗号分隔 (可选，不指定则从配置读取)")
    parser.add_argument("--start", default="", help="回测开始日期 (YYYYMMDD)")
    parser.add_argument("--end", default="", help="回测结束日期 (YYYYMMDD)")
    parser.add_argument("--kline-data-dir", default="./data/strategies/1m",
                        help="K线数据目录 (默认: ./data/strategies/1m)")
    parser.add_argument("--output", default="",
                        help="JSON 输出路径 (默认: logs/discovery-analysis-{date}.json)")

    args = parser.parse_args()

    strategy_list = [s.strip() for s in args.strategies.split(',')]
    symbols = [s.strip() for s in args.symbols.split(',') if s.strip()] if args.symbols else None

    # 执行分析
    results = analyze_strategy_list(
        strategies=strategy_list,
        strategies_dir=args.strategies_dir,
        symbols=symbols,
        start_date=args.start,
        end_date=args.end,
        kline_data_dir=args.kline_data_dir,
    )

    # 打印报告
    report = format_analysis_report(
        results,
        source="discovery",
        source_path=args.strategies_dir,
        start_date=args.start,
        end_date=args.end,
        kline_data_dir=args.kline_data_dir,
    )
    print(report)

    # 写 JSON
    output_path = args.output
    if not output_path:
        from datetime import datetime
        date_str = datetime.now().strftime('%Y%m%d')
        logs_dir = os.path.join(os.path.dirname(args.strategies_dir), 'logs')
        output_path = os.path.join(logs_dir, f"discovery-analysis-{date_str}.json")

    json_data = format_analysis_json(
        results,
        source="discovery",
        source_path=args.strategies_dir,
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
