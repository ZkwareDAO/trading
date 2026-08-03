#!/usr/bin/env python3
"""
为 ETHUSDT 和 SOLUSDT 生成市场状态图表

时间范围：2026-01-01 到 2026-03-31
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_manager.market_chart import MarketChartGenerator
from strategies.cta_market_research.market_judgment import MarketJudgment
from data_manager.backtest_data_loader import BacktestDataLoader
from data_manager.klines_loader import resample_ohlcv
from strategies.cta_market_research.indicator_calculator import IndicatorCalculator

# 配置
SYMBOLS = ["ETHUSDT", "SOLUSDT"]
START_DATE = datetime(2026, 1, 1, tzinfo=timezone.utc)
END_DATE = datetime(2026, 3, 31, 23, 59, tzinfo=timezone.utc)
DATE_RANGE_STR = "20260101-20260331"
TIMEFRAMES = ["15m", "1h", "4h", "1d"]
DATA_DIR = Path("./data/klines")
OUTPUT_BASE_DIR = Path("./data/charts")

# 图表参数
MAX_CANDLES = {
    "15m": 200,  # 15m 数据显示最近 200 根（约 2 天）
    "1h": 200,   # 1h 数据显示最近 200 根（约 8 天）
    "4h": 200,   # 4h 数据显示最近 200 根（约 33 天）
    "1d": 90,    # 1d 数据显示 Q1 全部 90 天
}

ADX_TREND_THRESHOLD = 25


def load_and_prepare_data(symbol: str, timeframe: str) -> Optional[pd.DataFrame]:
    """
    加载并准备数据（包含技术指标和市场状态）
    """
    print(f"  加载 {symbol} {timeframe} 数据...")

    loader = BacktestDataLoader(str(DATA_DIR))
    df = loader.load_data_for_backtest(
        symbol=symbol,
        timeframe=timeframe,
        start_date=START_DATE,
        end_date=END_DATE,
        source_timeframe="1m"
    )

    if df is None or df.empty:
        print(f"    无法加载数据")
        return None

    print(f"    数据量：{len(df):,} 条")
    return df


def compute_market_state_for_df(
    df: pd.DataFrame,
    judgment: MarketJudgment,
    adx_col: str = "adx",
    plus_di_col: str = "plus_di",
    minus_di_col: str = "minus_di",
) -> pd.DataFrame:
    """
    为 DataFrame 添加 market state 字段
    """
    result = df.copy()
    trend_market_list = []
    direction_list = []

    for idx, row in result.iterrows():
        adx = row.get(adx_col)
        plus_di = row.get(plus_di_col)
        minus_di = row.get(minus_di_col)

        if pd.isna(adx) or pd.isna(plus_di) or pd.isna(minus_di):
            trend_market_list.append("ranging_market")
            direction_list.append("ranging")
            continue

        is_trend = adx >= ADX_TREND_THRESHOLD
        trend_market_list.append("trend_market" if is_trend else "ranging_market")

        if plus_di > minus_di:
            direction_list.append("bullish")
        elif minus_di > plus_di:
            direction_list.append("bearish")
        else:
            direction_list.append("ranging")

    result["trend_market"] = trend_market_list
    result["direction"] = direction_list

    # 格式化时间戳
    result["timestamp"] = pd.to_datetime(result["timestamp"], utc=True)

    return result


def generate_charts_for_symbol(symbol: str) -> List[str]:
    """
    为单个交易对生成所有时间框架的图表
    """
    print(f"\n{'='*60}")
    print(f"处理 {symbol}...")
    print(f"{'='*60}")

    output_dir = OUTPUT_BASE_DIR / symbol
    output_dir.mkdir(parents=True, exist_ok=True)

    generator = MarketChartGenerator(figsize=(14, 10))
    output_paths = []

    for timeframe in TIMEFRAMES:
        print(f"\n  时间框架：{timeframe}")

        # 加载并准备数据
        df = load_and_prepare_data(symbol, timeframe)
        if df is None:
            continue

        # 计算市场状态
        print(f"    计算市场状态...")
        judgment = MarketJudgment(
            primary_timeframes=[timeframe],
            adx_trend_threshold=ADX_TREND_THRESHOLD,
        )
        df_with_state = compute_market_state_for_df(df, judgment)

        # 生成图表
        output_file = output_dir / f"{symbol}-{timeframe}-{DATE_RANGE_STR}-market.png"
        print(f"    生成图表：{output_file}")

        try:
            generator.plot_market_state(
                df=df_with_state,
                symbol=symbol,
                timeframe=timeframe,
                output_path=str(output_file),
                adx_threshold=ADX_TREND_THRESHOLD,
                max_candles=MAX_CANDLES.get(timeframe, 200),
            )
            output_paths.append(str(output_file))
            print(f"    完成")
        except Exception as e:
            print(f"    生成失败：{e}")

    return output_paths


def main():
    """主函数"""
    print("=" * 60)
    print("ETHUSDT & SOLUSDT 市场状态图表生成")
    print(f"时间范围：{DATE_RANGE_STR}")
    print(f"时间框架：{TIMEFRAMES}")
    print("=" * 60)

    all_paths = []

    for symbol in SYMBOLS:
        paths = generate_charts_for_symbol(symbol)
        all_paths.extend(paths)

    # 输出结果
    print("\n" + "=" * 60)
    print("生成的图表")
    print("=" * 60)

    for path in all_paths:
        p = Path(path)
        if p.exists():
            size_kb = p.stat().st_size / 1024
            print(f"  [OK] {p.relative_to(OUTPUT_BASE_DIR.parent)} ({size_kb:.1f} KB)")
        else:
            print(f"  [FAIL] {p.relative_to(OUTPUT_BASE_DIR.parent)}")

    print(f"\n共生成 {len(all_paths)} 个图表")
    return len(all_paths) > 0


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
