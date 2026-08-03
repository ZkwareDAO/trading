#!/usr/bin/env python3
"""
K 线数据处理脚本

功能:
1. 从 data/klines/BTCUSDT/1m 目录合并每日 CSV 文件
2. 重采样到 5m, 15m, 1h, 4h, 1d 周期
3. 计算并添加 ADX, MACD, RSI 指标

时间范围：2025-12-01 到 2026-04-07
"""

import sys
from pathlib import Path
from datetime import date
from typing import List, Optional

import pandas as pd
import numpy as np

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_manager.klines_loader import (
    read_binance_klines_csv,
    transform_binance_klines,
    resample_ohlcv,
)
from strategies.cta_market_research.indicator_calculator import IndicatorCalculator

# 配置
SYMBOL = "BTCUSDT"
START_DATE = date(2025, 12, 1)
END_DATE = date(2026, 4, 7)
RAW_FREQUENCY = "1m"
TARGET_FREQUENCIES = ["5m", "15m", "1h", "4h", "1d"]
DATA_DIR = Path("./data/klines")

# TA-Lib 默认参数
ADX_PERIOD = 14
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
RSI_PERIOD = 14


def get_date_range_files(
    source_dir: Path, start: date, end: date
) -> List[Path]:
    """获取指定日期范围内的 CSV 文件列表"""
    files = []
    current = start
    while current <= end:
        filename = f"{SYMBOL}-{RAW_FREQUENCY}-{current.strftime('%Y-%m-%d')}.csv"
        filepath = source_dir / filename
        if filepath.exists():
            files.append(filepath)
        else:
            print(f"  文件不存在：{filepath}")
        current += pd.Timedelta(days=1)
    return files


def merge_1m_data(files: List[Path]) -> pd.DataFrame:
    """合并多个 1m CSV 文件"""
    print(f"\n=== 第一步：合并 {len(files)} 个 1m CSV 文件 ===")

    all_dfs = []
    for i, filepath in enumerate(files, 1):
        if i % 20 == 0:
            print(f"  读取进度：{i}/{len(files)}")

        try:
            df = read_binance_klines_csv(filepath)
            df = transform_binance_klines(df, datetime_column="timestamp")

            # 只保留标准 OHLCV 列
            columns_to_keep = ["timestamp", "open", "high", "low", "close", "volume"]
            df = df[columns_to_keep]
            all_dfs.append(df)

        except Exception as e:
            print(f"  读取失败 {filepath}: {e}")

    if not all_dfs:
        raise ValueError("没有成功加载任何数据")

    print(f"  合并 {len(all_dfs)} 个 DataFrame...")
    combined = pd.concat(all_dfs, ignore_index=True)

    print(f"  排序并去重...")
    combined = combined.sort_values("timestamp").drop_duplicates(
        subset=["timestamp"], keep="last"
    ).reset_index(drop=True)

    print(f"  合并完成：{len(combined):,} 条记录")
    print(f"  时间范围：{combined['timestamp'].min()} 到 {combined['timestamp'].max()}")

    return combined


def save_with_indicators(df: pd.DataFrame, filepath: Path, calculator: IndicatorCalculator):
    """计算指标并保存 CSV"""
    print(f"  计算技术指标...")
    df_with_indicators = calculator.calculate(df)

    # 确保时间戳格式正确
    if df_with_indicators["timestamp"].dt.tz is None:
        df_with_indicators = df_with_indicators.copy()
        df_with_indicators["timestamp"] = df_with_indicators["timestamp"].dt.tz_localize("UTC")
    else:
        df_with_indicators = df_with_indicators.copy()
        df_with_indicators["timestamp"] = df_with_indicators["timestamp"].dt.tz_convert("UTC")

    # 转换为字符串格式
    df_with_indicators["timestamp"] = df_with_indicators["timestamp"].dt.strftime(
        "%Y-%m-%d %H:%M:%S+00:00"
    )

    # 确保目录存在
    filepath.parent.mkdir(parents=True, exist_ok=True)

    # 保存
    df_with_indicators.to_csv(filepath, index=False)

    # 统计有值的指标
    adx_count = df_with_indicators["adx"].notna().sum() if "adx" in df_with_indicators.columns else 0
    print(f"  保存完成：{filepath}")
    print(f"  记录数：{len(df_with_indicators):,} 条")
    print(f"  ADX 有效值：{adx_count:,} 条 ({adx_count/len(df_with_indicators)*100:.1f}%)")


def main():
    print("=" * 60)
    print("K 线数据处理")
    print(f"标的：{SYMBOL}")
    print(f"时间范围：{START_DATE} 到 {END_DATE}")
    print(f"周期：{RAW_FREQUENCY} -> {TARGET_FREQUENCIES}")
    print("=" * 60)

    # 源目录
    source_dir = DATA_DIR / SYMBOL / RAW_FREQUENCY
    print(f"\n源目录：{source_dir}")

    # 第一步：获取文件列表
    print(f"\n扫描 {START_DATE} 到 {END_DATE} 的文件...")
    files = get_date_range_files(source_dir, START_DATE, END_DATE)
    print(f"找到 {len(files)} 个文件")

    if not files:
        print("错误：没有找到任何文件")
        return False

    # 第二步：合并 1m 数据
    df_1m = merge_1m_data(files)

    # 生成输出文件名
    date_range_str = START_DATE.strftime("%Y%m%d") + "-" + END_DATE.strftime("%Y%m%d")
    output_1m = DATA_DIR / SYMBOL / RAW_FREQUENCY / f"{SYMBOL}-{RAW_FREQUENCY}-{date_range_str}.csv"

    # 初始化指标计算器
    calculator = IndicatorCalculator(
        adx_period=ADX_PERIOD,
        macd_fast=MACD_FAST,
        macd_slow=MACD_SLOW,
        macd_signal=MACD_SIGNAL,
        rsi_period=RSI_PERIOD,
    )

    # 第三步：保存 1m 数据（带指标）
    print(f"\n=== 保存 1m 数据（带指标） ===")
    save_with_indicators(df_1m, output_1m, calculator)

    # 第四步：重采样并保存其他周期
    print(f"\n=== 第二步 + 第三步：重采样并计算指标 ===")
    for freq in TARGET_FREQUENCIES:
        print(f"\n处理 {freq}...")

        # 重采样
        print(f"  重采样从 {RAW_FREQUENCY} -> {freq}...")
        df_resampled = resample_ohlcv(df_1m, freq, datetime_column="timestamp")
        print(f"  重采样完成：{len(df_resampled):,} 条记录")

        # 保存（带指标）
        output_path = DATA_DIR / SYMBOL / freq / f"{SYMBOL}-{freq}-{date_range_str}.csv"
        save_with_indicators(df_resampled, output_path, calculator)

    print("\n" + "=" * 60)
    print("处理完成!")
    print("=" * 60)

    # 输出文件列表
    print(f"\n生成的文件:")
    all_outputs = [output_1m] + [
        DATA_DIR / SYMBOL / freq / f"{SYMBOL}-{freq}-{date_range_str}.csv"
        for freq in TARGET_FREQUENCIES
    ]
    for filepath in all_outputs:
        if filepath.exists():
            size_mb = filepath.stat().st_size / 1024 / 1024
            print(f"  [OK] {filepath.relative_to(DATA_DIR)} ({size_mb:.2f} MB)")
        else:
            print(f"  [FAIL] {filepath.relative_to(DATA_DIR)} (生成失败)")

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
