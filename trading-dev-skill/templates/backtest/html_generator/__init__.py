#!/usr/bin/env python3
"""
回测结果 HTML 可视化生成器

将回测结果转换为交互式 HTML 图表
"""

import argparse
import logging
from pathlib import Path

from .config import DEFAULT_KLINE_DIR, DISPLAY_CONFIG
from .data_loader import load_kline_data, load_trade_data
from .html_builder import generate_html

__all__ = ["generate_html", "load_kline_data", "load_trade_data"]


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="回测结果 HTML 可视化生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m backtest.html_generator --symbol ETHUSDT --interval 15m --start 2026-01-01 --end 2026-07-09

  python -m backtest.html_generator --symbol BNBUSDT --interval 15m --start 20260101 --end 20260709 \\
      --backtest-dir ./backtest_output/obv_atr_v2/20260710/030118/SOLUSDT \\
      --output ./charts/BNBUSDT.html
        """,
    )
    parser.add_argument("--symbol", required=True, help="交易对 (如 ETHUSDT)")
    parser.add_argument("--interval", default="15m", help="K 线周期 (默认: 15m)")
    parser.add_argument("--start", required=True, help="开始日期 (YYYY-MM-DD 或 YYYYMMDD)")
    parser.add_argument("--end", required=True, help="结束日期 (YYYY-MM-DD 或 YYYYMMDD)")
    parser.add_argument("--kline-dir", default=DEFAULT_KLINE_DIR, help="K 线数据目录")
    parser.add_argument("--backtest-dir", help="回测结果目录 (包含 backtest_trades.csv)")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--display-count", type=int, default=DISPLAY_CONFIG["default_count"], help="默认显示 K 线数量")
    parser.add_argument("--title", help="自定义页面标题")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    output_path = args.output or f"charts/{args.symbol}_indicators.html"

    # 加载 K 线数据
    kline_period = load_kline_data(args.symbol, args.kline_dir, args.start, args.end, args.interval)

    # 加载交易数据
    trade_pairs = []
    if args.backtest_dir:
        trade_pairs = load_trade_data(args.backtest_dir, args.start, args.end)

    # 生成 HTML
    generate_html(args.symbol, kline_period, trade_pairs, output_path, args.display_count, args.title)

    print(f"\n✅ HTML 已生成: {output_path}")


if __name__ == "__main__":
    main()
