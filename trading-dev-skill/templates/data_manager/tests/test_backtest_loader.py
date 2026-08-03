#!/usr/bin/env python3
"""
测试智能数据加载功能

验证 BacktestDataLoader 是否能正确:
1. 查找覆盖文件
2. 加载并截取数据
3. 从源数据合成
"""

import sys
from pathlib import Path
from datetime import datetime, timezone

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_manager.backtest_data_loader import BacktestDataLoader, parse_date_range_from_filename, load_and_slice_data, is_file_covering_range


def test_parse_date_range():
    """测试文件名日期解析"""
    print("=" * 60)
    print("测试 1: 文件名日期解析")
    print("=" * 60)

    test_cases = [
        "BTCUSDT-1m-20251201-20260407.csv",
        "BTCUSDT_1m_20251201_20260407.csv",
        "BTCUSDT-15m-20251201-20260407.csv",
        "BTCUSDT_1m.csv",  # 无日期范围
    ]

    for filename in test_cases:
        result = parse_date_range_from_filename(filename)
        if result:
            print(f"  {filename} -> {result[0]} 到 {result[1]}")
        else:
            print(f"  {filename} -> 无法解析")

    print()


def test_find_covering_file():
    """测试查找覆盖文件"""
    print("=" * 60)
    print("测试 2: 查找覆盖文件")
    print("=" * 60)

    loader = BacktestDataLoader("./data/klines")

    # 测试案例：查找覆盖 2026-01-06 到 2026-03-19 的文件
    test_cases = [
        ("1m", datetime(2026, 1, 6, tzinfo=timezone.utc), datetime(2026, 3, 19, 23, 59, tzinfo=timezone.utc)),
        ("15m", datetime(2026, 1, 6, tzinfo=timezone.utc), datetime(2026, 3, 19, 23, 59, tzinfo=timezone.utc)),
        ("1h", datetime(2026, 1, 6, tzinfo=timezone.utc), datetime(2026, 3, 19, 23, 59, tzinfo=timezone.utc)),
    ]

    for timeframe, start, end in test_cases:
        result = loader.find_covering_file(timeframe, start, end)
        if result:
            print(f"  {timeframe}: 找到覆盖文件 {result.name}")
        else:
            print(f"  {timeframe}: 未找到覆盖文件")

    print()


def test_load_and_slice():
    """测试加载并截取数据"""
    print("=" * 60)
    print("测试 3: 加载并截取数据")
    print("=" * 60)

    from data_manager.backtest_data_loader import load_and_slice_data, is_file_covering_range

    # 测试加载 1m 数据
    filepath = Path("data/klines/BTCUSDT/1m/BTCUSDT-1m-20251201-20260407.csv")

    if filepath.exists():
        # 检查是否覆盖
        covers, date_range = is_file_covering_range(
            filepath,
            datetime(2026, 1, 6, tzinfo=timezone.utc),
            datetime(2026, 3, 19, 23, 59, tzinfo=timezone.utc),
            "1m"
        )
        print(f"  文件覆盖检查：{covers}")
        print(f"  文件日期范围：{date_range}")

        # 加载并截取
        start_date = datetime(2026, 1, 6, tzinfo=timezone.utc)
        end_date = datetime(2026, 3, 19, 23, 59, tzinfo=timezone.utc)

        df = load_and_slice_data(filepath, start_date, end_date, "1m")
        if df is not None:
            print(f"  加载成功：{len(df):,} 条记录")
            print(f"  时间范围：{df['timestamp'].min()} 到 {df['timestamp'].max()}")
        else:
            print(f"  加载失败")
    else:
        print(f"  文件不存在：{filepath}")

    print()


def test_synthesize_data():
    """测试数据合成"""
    print("=" * 60)
    print("测试 4: 数据合成（从 1m 重采样到 15m）")
    print("=" * 60)

    loader = BacktestDataLoader("./data/klines")

    start_date = datetime(2026, 1, 6, tzinfo=timezone.utc)
    end_date = datetime(2026, 3, 19, 23, 59, tzinfo=timezone.utc)

    # 测试合成 15m 数据
    df = loader.synthesize_data("15m", start_date, end_date, "1m")

    if df is not None:
        print(f"  合成成功：{len(df):,} 条记录")
        print(f"  时间范围：{df['timestamp'].min()} 到 {df['timestamp'].max()}")
        print(f"  列：{list(df.columns)}")
    else:
        print(f"  合成失败")

    print()


def test_full_load():
    """测试完整加载流程"""
    print("=" * 60)
    print("测试 5: 完整加载流程")
    print("=" * 60)

    loader = BacktestDataLoader("./data/klines")

    start_date = datetime(2026, 1, 6, tzinfo=timezone.utc)
    end_date = datetime(2026, 3, 19, 23, 59, tzinfo=timezone.utc)

    # 测试加载 1m 数据
    print("  加载 1m 数据...")
    df_1m = loader.load_data_for_backtest("BTCUSDT", "1m", start_date, end_date, "1m")
    if df_1m is not None:
        print(f"    成功：{len(df_1m):,} 条记录")
    else:
        print(f"    失败")

    # 测试加载 15m 数据
    print("  加载 15m 数据...")
    df_15m = loader.load_data_for_backtest("BTCUSDT", "15m", start_date, end_date, "1m")
    if df_15m is not None:
        print(f"    成功：{len(df_15m):,} 条记录")
    else:
        print(f"    失败")

    # 测试加载 1h 数据
    print("  加载 1h 数据...")
    df_1h = loader.load_data_for_backtest("BTCUSDT", "1h", start_date, end_date, "1m")
    if df_1h is not None:
        print(f"    成功：{len(df_1h):,} 条记录")
    else:
        print(f"    失败")

    print()


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("智能数据加载功能测试")
    print("=" * 60 + "\n")

    # 运行所有测试
    test_parse_date_range()
    test_find_covering_file()
    test_load_and_slice()
    test_synthesize_data()
    test_full_load()

    print("=" * 60)
    print("测试完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
