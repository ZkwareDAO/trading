#!/usr/bin/env python3
"""
每日定时回测脚本 - thin wrapper around batch_runner.py

只负责：计算日期范围，调用 batch_runner CLI

使用方式：
    python3 backtest/daily_backtest.py                    # 回测当天
    python3 backtest/daily_backtest.py --yesterday        # 回测昨天
    python3 backtest/daily_backtest.py --days 30          # 回测最近30天
    python3 backtest/daily_backtest.py --start 20260612   # 回测指定日期

Crontab 配置示例：
    0 8 * * * cd /path/to/cta-strategy-code && python3 backtest/daily_backtest.py >> logs/daily_backtest.log 2>&1
"""

import argparse
import subprocess
import sys
from datetime import datetime, timedelta, timezone


def parse_args():
    """解析参数，返回 (start_date, end_date, remaining_args)"""
    parser = argparse.ArgumentParser(
        description="每日定时回测脚本",
        add_help=False,
    )
    # 日期参数
    parser.add_argument("--yesterday", action="store_true")
    parser.add_argument("--days", type=int, default=0)
    parser.add_argument("--start")
    parser.add_argument("--end")
    # 透传参数
    parser.add_argument("--config")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

    args, remaining = parser.parse_known_args(sys.argv[1:])

    today = datetime.now(timezone.utc)
    today_str = today.strftime("%Y%m%d")

    # 日期计算（优先级：--start > --yesterday > --days > 默认当天）
    if args.start:
        start_date = args.start
        end_date = args.end or today_str
    elif args.yesterday:
        yesterday = today - timedelta(days=1)
        start_date = yesterday.strftime("%Y%m%d")
        end_date = start_date
    elif args.days > 0:
        start = today - timedelta(days=args.days)
        start_date = start.strftime("%Y%m%d")
        end_date = today_str
    else:
        start_date = today_str
        end_date = today_str

    # 构建透传参数（--config 和 --log-level 已被解析，需手动加入）
    passthrough = remaining.copy()
    passthrough.extend(
        ["--config", args.config] if args.config else []
    )
    passthrough.extend(
        ["--log-level", args.log_level] if args.log_level else []
    )

    return start_date, end_date, passthrough


def main():
    start_date, end_date, remaining_args = parse_args()

    cmd = ["python3", "-m", "backtest.batch_runner"]
    cmd.extend(["--start", start_date, "--end", end_date])
    cmd.extend(remaining_args)

    result = subprocess.run(cmd)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
