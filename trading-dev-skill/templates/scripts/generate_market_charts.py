#!/usr/bin/env python3
"""
K 线数据可视化图表生成器 - 命令行版本

功能:
1. 从 strategies/market_research/timeframe/symbol/ 加载 CSV 数据
2. 支持指定时间范围、交易对、时间框架
3. 生成包含市场状态可视化的图表

数据源：strategies/market_research/{timeframe}/{symbol}/{symbol}_{timeframe}.csv
"""

import sys
import argparse
from pathlib import Path
from typing import List, Dict, Optional

import pandas as pd

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_manager.market_chart import MarketChartGenerator
from strategies.cta_market_research.market_judgment import MarketJudgment
from strategies.cta_market_research.indicator_calculator import IndicatorCalculator


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description='Market Research 图表生成器 - 从 strategies/market_research 目录加载数据生成可视化图表'
    )
    parser.add_argument('--symbol', type=str, default='BTCUSDT',
                        help='交易对 (默认：BTCUSDT)')
    parser.add_argument('--start', type=str,
                        help='起始时间 (YYYY-MM-DD)，如 2026-01-01')
    parser.add_argument('--end', type=str,
                        help='结束时间 (YYYY-MM-DD)，如 2026-03-31')
    parser.add_argument('--timeframe', type=str, default='1h',
                        choices=['1m', '5m', '15m', '1h', '4h', '1d'],
                        help='时间框架 (默认：1h)')
    parser.add_argument('--data-dir', type=str,
                        default='data/strategies/market_research',
                        help='数据目录 (默认：data/strategies/market_research)')
    parser.add_argument('--output', type=str,
                        default='data/charts/market_research',
                        help='输出目录 (默认：data/charts/market_research)')
    parser.add_argument('--max-candles', type=int, default=200,
                        help='最大显示 K 线数 (默认：200)')
    parser.add_argument('--adx-threshold', type=float, default=25.0,
                        help='ADX 趋势阈值 (默认：25.0)')

    return parser.parse_args()

# 图表参数 - 各时间框架最大显示数量
MAX_CANDLES = {
    "1m": 500,   # 1m 数据显示最近 500 根（约 8 小时）
    "5m": 300,   # 5m 数据显示最近 300 根（约 25 小时）
    "15m": 200,  # 15m 数据显示最近 200 根（约 2 天）
    "1h": 200,   # 1h 数据显示最近 200 根（约 8 天）
    "4h": 200,   # 4h 数据显示最近 200 根（约 33 天）
    "1d": 128,   # 1d 数据显示全部 128 天
}


def load_csv(filepath: Path, start: Optional[str] = None, end: Optional[str] = None) -> pd.DataFrame:
    """
    加载 CSV 文件并应用时间过滤

    Args:
        filepath: CSV 文件路径
        start: 起始时间 (YYYY-MM-DD)
        end: 结束时间 (YYYY-MM-DD)

    Returns:
        过滤后的 DataFrame
    """
    df = pd.read_csv(filepath, index_col='timestamp', parse_dates=True)
    df = df.sort_index()

    # 时间范围过滤
    if start:
        df = df[df.index >= pd.to_datetime(start, utc=True)]
    if end:
        df = df[df.index <= pd.to_datetime(end, utc=True)]

    # 重置索引
    df = df.reset_index(drop=False)

    return df


def compute_market_state_for_df(
    df: pd.DataFrame,
    adx_threshold: float = 25.0,
) -> pd.DataFrame:
    """
    为 DataFrame 添加 market state 字段

    判断标准:
    - trending_market: ADX >= 25
    - bullish: +DI > -DI
    - bearish: +DI < -DI

    Args:
        df: 包含 OHLCV + 指标的 DataFrame
        adx_threshold: ADX 趋势阈值

    Returns:
        添加了 market_type 和 direction 列的 DataFrame
    """
    result = df.copy()

    # 初始化列
    market_type_list = []
    direction_list = []

    for idx, row in result.iterrows():
        adx = row.get("adx")
        plus_di = row.get("plus_di")
        minus_di = row.get("minus_di")

        # 检查数据有效性
        if pd.isna(adx) or pd.isna(plus_di) or pd.isna(minus_di):
            market_type_list.append("ranging_market")
            direction_list.append("ranging")
            continue

        # 判断市场类型
        is_trend = adx >= adx_threshold
        market_type_list.append("trend_market" if is_trend else "ranging_market")

        # 判断方向
        if plus_di > minus_di:
            direction_list.append("bullish")
        elif minus_di > plus_di:
            direction_list.append("bearish")
        else:
            direction_list.append("ranging")

    result["market_type"] = market_type_list
    result["direction"] = direction_list

    return result


def generate_chart(
    symbol: str,
    timeframe: str,
    data_dir: Path,
    output_dir: Path,
    start: Optional[str] = None,
    end: Optional[str] = None,
    max_candles: int = 200,
    adx_threshold: float = 25.0,
) -> Optional[str]:
    """
    为单个时间框架生成市场状态图表

    Args:
        symbol: 交易对
        timeframe: 时间框架
        data_dir: 数据目录
        output_dir: 输出目录
        start: 起始时间
        end: 结束时间
        max_candles: 最大显示 K 线数
        adx_threshold: ADX 趋势阈值

    Returns:
        生成的图表文件路径，失败返回 None
    """
    # 创建输出目录
    output_dir.mkdir(parents=True, exist_ok=True)

    # 构建文件路径 - 新结构：strategies/market_research/{timeframe}/{symbol}/{symbol}_{timeframe}.csv
    # 兼容旧结构：strategies/market_research/{symbol}_{timeframe}.csv
    input_file = data_dir / f"{symbol}_{timeframe}.csv"

    if not input_file.exists():
        print(f"  文件不存在：{input_file}")
        return None

    # 加载数据
    print(f"  加载数据：{input_file}")
    df = load_csv(input_file, start=start, end=end)
    print(f"  数据量：{len(df):,} 条")

    if df.empty:
        print(f"  数据为空，跳过")
        return None

    # 检查是否需要计算 Bollinger Bands 和 KDJ
    if "bb_upper" not in df.columns or "kdj_k" not in df.columns:
        print(f"  计算缺失指标 (BB, KDJ)...")
        calculator = IndicatorCalculator()
        df = calculator.calculate(df)

    # 计算市场状态
    print(f"  计算市场状态...")
    df_with_state = compute_market_state_for_df(df, adx_threshold=adx_threshold)

    # 生成图表
    date_range = f"{start}-{end}" if start and end else "all"
    output_file = output_dir / f"{symbol}_{timeframe}_{date_range}_market.png"

    print(f"  生成图表：{output_file}")

    # 初始化图表生成器
    generator = MarketChartGenerator(figsize=(14, 10))

    try:
        generator.plot_market_state(
            df=df_with_state,
            symbol=symbol,
            timeframe=timeframe,
            output_path=str(output_file),
            adx_threshold=adx_threshold,
            max_candles=max_candles,
        )
        print(f"  完成")
        return str(output_file)
    except Exception as e:
        print(f"  生成失败：{e}")
        return None


def main():
    """主函数"""
    args = parse_args()

    print("=" * 60)
    print("Market Research 图表生成器")
    print("=" * 60)
    print(f"交易对：{args.symbol}")
    print(f"时间框架：{args.timeframe}")
    print(f"起始时间：{args.start or '全部'}")
    print(f"结束时间：{args.end or '全部'}")
    print(f"数据目录：{args.data_dir}")
    print(f"输出目录：{args.output}")
    print(f"ADX 阈值：{args.adx_threshold}")
    print("=" * 60)

    # 生成图表
    output_path = generate_chart(
        symbol=args.symbol,
        timeframe=args.timeframe,
        data_dir=Path(args.data_dir),
        output_dir=Path(args.output),
        start=args.start,
        end=args.end,
        max_candles=args.max_candles,
        adx_threshold=args.adx_threshold,
    )

    # 输出结果
    print("\n" + "=" * 60)
    print("生成的图表")
    print("=" * 60)

    if output_path:
        p = Path(output_path)
        if p.exists():
            size_kb = p.stat().st_size / 1024
            print(f"  [OK] {p} ({size_kb:.1f} KB)")
        else:
            print(f"  [FAIL] {p}")
            return False
    else:
        print("  没有生成图表")
        return False

    print("\n完成!")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
