#!/usr/bin/env python3
"""
更新市场状态并生成可视化图表

命令行工具，用于：
1. 为 CSV 文件添加 trend_market 和 direction 列
2. 为每个时间周期生成可视化图表
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="更新市场状态并生成可视化图表"
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="BTCUSDT",
        help="交易对 (默认：BTCUSDT)"
    )
    parser.add_argument(
        "--data-dir",
        type=str,
        default="./data/strategies/market_research",
        help="数据目录 (默认：./data/strategies/market_research)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./data/charts/market_research",
        help="图表输出目录 (默认：./data/charts/market_research)"
    )
    parser.add_argument(
        "--timeframes",
        type=str,
        nargs="+",
        default=["1d", "1h", "4h", "15m"],
        help="要更新的时间框架列表 (默认：1d 1h 4h 15m)"
    )
    parser.add_argument(
        "--adx-threshold",
        type=float,
        default=25.0,
        help="ADX 趋势阈值 (默认：25.0)"
    )
    parser.add_argument(
        "--max-candles",
        type=int,
        default=200,
        help="图表中最大显示的 K 线数量 (默认：200)"
    )
    parser.add_argument(
        "--no-chart",
        action="store_true",
        help="不生成图表"
    )
    parser.add_argument(
        "--update-csv",
        action="store_true",
        default=True,
        help="更新 CSV 文件 (默认：True)"
    )

    return parser.parse_args()


def update_csv_files(
    symbol: str,
    timeframes: List[str],
    data_dir: str,
    adx_threshold: float,
) -> dict:
    """
    更新 CSV 文件，添加市场状态列

    Returns:
        统计结果字典
    """
    from data_manager.market_judgment_engine import (
        MarketJudgmentEngine,
        load_timeframe_data,
        update_csv_with_market_state,
    )

    print("\n=== 加载基准周期数据 ===")
    df_1d = load_timeframe_data(symbol, "1d", data_dir)
    df_4h = load_timeframe_data(symbol, "4h", data_dir)
    df_15m = load_timeframe_data(symbol, "15m", data_dir)

    print(f"  1d: {len(df_1d)} 行")
    print(f"  4h: {len(df_4h)} 行")
    print(f"  15m: {len(df_15m)} 行")

    # 创建引擎
    engine = MarketJudgmentEngine(adx_trend_threshold=adx_threshold)

    print("\n=== 更新 CSV 文件 ===")
    stats = {}

    for tf in timeframes:
        print(f"\n处理 {tf} ...")
        result = update_csv_with_market_state(
            symbol=symbol,
            timeframe=tf,
            df_1d=df_1d,
            df_4h=df_4h,
            df_15m=df_15m,
            data_dir=data_dir,
            engine=engine,
        )

        if result:
            stats[tf] = result
            print(
                f"  trend_market={result.get('trend_market', 0)}, "
                f"ranging_market={result.get('ranging_market', 0)}, "
                f"bullish={result.get('bullish', 0)}, "
                f"bearish={result.get('bearish', 0)}, "
                f"ranging={result.get('ranging', 0)}"
            )
        else:
            print(f"  跳过：文件不存在")

    return stats


def generate_charts(
    symbol: str,
    timeframes: List[str],
    data_dir: str,
    output_dir: str,
    max_candles: int,
) -> List[str]:
    """
    生成可视化图表

    Returns:
        图表文件路径列表
    """
    from data_manager.market_chart import generate_all_charts

    print("\n=== 生成可视化图表 ===")
    output_paths = generate_all_charts(
        symbol=symbol,
        timeframes=timeframes,
        data_dir=data_dir,
        output_dir=output_dir,
        max_candles=max_candles,
    )

    return output_paths


def main():
    """主函数"""
    args = parse_args()

    print("=" * 60)
    print("市场状态更新工具")
    print("=" * 60)
    print(f"交易对：{args.symbol}")
    print(f"数据目录：{args.data_dir}")
    print(f"时间框架：{', '.join(args.timeframes)}")
    print(f"ADX 阈值：{args.adx_threshold}")

    # 确保数据目录存在
    if not Path(args.data_dir).exists():
        print(f"错误：数据目录不存在：{args.data_dir}")
        sys.exit(1)

    # 更新 CSV 文件
    if args.update_csv:
        stats = update_csv_files(
            symbol=args.symbol,
            timeframes=args.timeframes,
            data_dir=args.data_dir,
            adx_threshold=args.adx_threshold,
        )

        # 打印汇总
        print("\n=== 汇总 ===")
        total_trend = sum(s.get("trend_market", 0) for s in stats.values())
        total_ranging = sum(s.get("ranging_market", 0) for s in stats.values())
        total_bullish = sum(s.get("bullish", 0) for s in stats.values())
        total_bearish = sum(s.get("bearish", 0) for s in stats.values())
        total_rows = sum(s.get("total", 0) for s in stats.values())

        print(f"  总行数：{total_rows}")
        print(f"  trend_market: {total_trend}")
        print(f"  ranging_market: {total_ranging}")
        print(f"  bullish: {total_bullish}")
        print(f"  bearish: {total_bearish}")

    # 生成图表
    if not args.no_chart:
        chart_paths = generate_charts(
            symbol=args.symbol,
            timeframes=args.timeframes,
            data_dir=args.data_dir,
            output_dir=args.output_dir,
            max_candles=args.max_candles,
        )

        print("\n=== 生成的图表 ===")
        for path in chart_paths:
            print(f"  {path}")

    print("\n" + "=" * 60)
    print("完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()
