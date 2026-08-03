#!/usr/bin/env python3
"""
为 ETHUSDT 和 SOLUSDT 生成完整数据并创建市场状态图表

时间范围：2026-01-01 到 2026-03-31
"""

import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Optional
import concurrent.futures

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from data_manager.market_chart import MarketChartGenerator
from strategies.cta_market_research.market_judgment import MarketJudgment
from data_manager.klines_loader import read_binance_klines_csv, transform_binance_klines, resample_ohlcv
from strategies.cta_market_research.indicator_calculator import IndicatorCalculator

# 配置
SYMBOLS = ["ETHUSDT", "SOLUSDT"]
PRELOAD_START = datetime(2025, 12, 1)  # 预加载开始日期（用于计算指标）
START_DATE = datetime(2026, 1, 1)       # 实际数据开始日期
END_DATE = datetime(2026, 3, 31)        # 实际数据结束日期
DATE_RANGE_STR = "20260101-20260331"
TIMEFRAMES = ["15m", "1h", "4h", "1d"]
DATA_DIR = Path("./data/klines")
OUTPUT_BASE_DIR = Path("./data/charts")

ADX_TREND_THRESHOLD = 25


def load_daily_file(filepath: Path) -> Optional[pd.DataFrame]:
    """加载单个每日文件"""
    try:
        df = read_binance_klines_csv(filepath)
        df = transform_binance_klines(df, "timestamp")
        return df
    except Exception as e:
        print(f"    加载失败 {filepath.name}: {e}")
        return None


def load_1m_data(symbol: str, preload_start: datetime, start_date: datetime, end_date: datetime) -> pd.DataFrame:
    """
    并行加载所有每日 1m 文件并合并（包含预热数据）
    """
    timeframe_dir = DATA_DIR / symbol / "1m"

    print(f"  扫描 {symbol} 1m 文件（{preload_start.date()} 到 {end_date.date()}）...")
    daily_files = []
    current = preload_start
    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")
        daily_file = timeframe_dir / f"{symbol}-1m-{date_str}.csv"
        if daily_file.exists():
            daily_files.append(daily_file)
        current += pd.Timedelta(days=1)

    print(f"    找到 {len(daily_files)} 个文件")

    # 并行加载
    all_dfs = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_file = {executor.submit(load_daily_file, f): f for f in daily_files}
        for future in concurrent.futures.as_completed(future_to_file):
            df = future.result()
            if df is not None and not df.empty:
                all_dfs.append(df)

    if not all_dfs:
        return pd.DataFrame()

    # 合并
    combined = pd.concat(all_dfs, ignore_index=True)
    combined = combined.sort_values('timestamp').drop_duplicates(subset=['timestamp'], keep='last')
    combined = combined.reset_index(drop=True)

    print(f"    合并后 {len(combined):,} 条记录")
    return combined


def save_dataframe(df: pd.DataFrame, symbol: str, timeframe: str, start_date: datetime, end_date: datetime) -> Path:
    """保存 DataFrame 到 CSV"""
    output_dir = DATA_DIR / symbol / timeframe
    output_dir.mkdir(parents=True, exist_ok=True)

    start_str = start_date.strftime("%Y%m%d")
    end_str = end_date.strftime("%Y%m%d")
    filename = f"{symbol}-{timeframe}-{start_str}-{end_str}.csv"
    filepath = output_dir / filename

    df_copy = df.copy()
    df_copy['timestamp'] = df_copy['timestamp'].dt.strftime("%Y-%m-%d %H:%M:%S+00:00")
    df_copy.to_csv(filepath, index=False)

    return filepath


def compute_market_state(df: pd.DataFrame) -> pd.DataFrame:
    """计算市场状态"""
    result = df.copy()
    trend_market_list = []
    direction_list = []

    for idx, row in result.iterrows():
        adx = row.get('adx')
        plus_di = row.get('plus_di')
        minus_di = row.get('minus_di')

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
    return result


def generate_data_and_charts(symbol: str) -> List[str]:
    """为单个交易对生成数据和图表"""
    print(f"\n{'='*60}")
    print(f"处理 {symbol}...")
    print(f"{'='*60}")

    output_dir = OUTPUT_BASE_DIR / symbol
    output_dir.mkdir(parents=True, exist_ok=True)

    # 步骤 1: 加载 1m 源数据（包含预热数据）
    print(f"\n步骤 1: 加载 1m 源数据（含预热）...")
    df_1m = load_1m_data(symbol, PRELOAD_START, START_DATE, END_DATE)

    if df_1m.empty:
        print(f"  错误：无法加载 1m 数据")
        return []

    # 步骤 2: 为每个时间框架生成数据和图表
    output_paths = []
    generator = MarketChartGenerator(figsize=(14, 10))

    for timeframe in TIMEFRAMES:
        print(f"\n  时间框架：{timeframe}")

        if timeframe == "1m":
            df_full = df_1m.copy()
        else:
            # 从重采样到目标时间框架（使用完整数据包括预热）
            print(f"    重采样到 {timeframe}...")
            df_full = resample_ohlcv(df_1m, timeframe, datetime_column="timestamp")
            print(f"    重采样后 {len(df_full):,} 条（含预热）")

        # 计算指标（使用完整数据）
        print(f"    计算技术指标...")
        calculator = IndicatorCalculator()
        df_full = calculator.calculate(df_full)

        # 筛选出实际需要的日期范围（2026-01-01 开始）
        df = df_full[
            (df_full['timestamp'] >= pd.Timestamp(START_DATE, tz='UTC')) &
            (df_full['timestamp'] <= pd.Timestamp(END_DATE, tz='UTC'))
        ].copy()

        print(f"    筛选后 {len(df):,} 条（{START_DATE.date()} 到 {END_DATE.date()}）")

        # 计算市场状态
        print(f"    计算市场状态...")
        df_with_state = compute_market_state(df)

        # 保存数据（包含市场状态字段）
        filepath = save_dataframe(df_with_state, symbol, timeframe, START_DATE, END_DATE)
        print(f"    已保存：{filepath}")

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
                max_candles=len(df_with_state),  # 显示全部数据
            )
            output_paths.append(str(output_file))
            print(f"    完成")
        except Exception as e:
            print(f"    生成失败：{e}")

    return output_paths


def main():
    """主函数"""
    print("=" * 60)
    print("ETHUSDT & SOLUSDT 数据生成和图表")
    print(f"时间范围：2026-01-01 到 2026-03-31")
    print(f"时间框架：{TIMEFRAMES}")
    print("=" * 60)

    all_paths = []

    for symbol in SYMBOLS:
        paths = generate_data_and_charts(symbol)
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
