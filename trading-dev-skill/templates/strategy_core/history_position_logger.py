#!/usr/bin/env python3
"""历史仓位记录器

每次平仓时记录历史仓位信息，便于查询和对比回测。
存储位置: data/history_positions/{strategy_name}/{YYYYMMDD}.csv
"""

import csv
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class HistoryPositionLogger:
    """历史仓位记录器

    存储位置: data/history_positions/{strategy_name}/{YYYYMMDD}.csv
    """

    FIELDNAMES = [
        "position_id", "strategy_name", "symbol", "position_type",
        "entry_price", "exit_price", "entry_time", "exit_time",
        "entry_timestamp", "exit_timestamp", "peak_price", "stop_price",
        "max_pnl_pct", "min_pnl_pct",  # 新增：盈亏极值
        "exit_reason", "is_stop_loss",
        "price_diff", "pnl_pct", "duration_seconds",  # pnl -> price_diff
        "atr_at_entry", "trail_activated",
        "trading_mode",  # 运行模式 (live / paper_trading / smoking)
    ]

    DEFAULT_BASE_PATH = Path("data/history_positions")

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = base_path or self.DEFAULT_BASE_PATH

    def log_position_exit(
        self,
        strategy_name: str,
        symbol: str,
        position_id: str,
        position_type: str,
        entry_price: float,
        exit_price: float,
        entry_time: Optional[datetime],
        exit_time: Optional[datetime],
        entry_timestamp: Optional[int],
        exit_timestamp: int,
        peak_price: float,
        stop_price: float,
        max_pnl_pct: float = 0.0,  # 新增：最大盈利百分比
        min_pnl_pct: float = 0.0,  # 新增：最大亏损百分比
        exit_reason: str = "",
        is_stop_loss: bool = False,
        atr_at_entry: float = 0.0,
        trail_activated: bool = False,
        trading_mode: str = "live",  # 运行模式
    ) -> None:
        """记录平仓信息到 CSV

        Args:
            strategy_name: 策略名称
            symbol: 交易标的
            position_id: 仓位唯一标识
            position_type: 'long' 或 'short'
            entry_price: 开仓价格
            exit_price: 平仓价格
            entry_time: 开仓时间
            exit_time: 平仓时间
            entry_timestamp: 开仓时间戳（秒）
            exit_timestamp: 平仓时间戳（秒）
            peak_price: 持仓期间最高/最低价
            stop_price: 止损价格
            max_pnl_pct: 最大盈利百分比（>0）
            min_pnl_pct: 最大亏损百分比（<0）
            exit_reason: 平仓原因
            is_stop_loss: 是否止损
            atr_at_entry: 入场时 ATR
            trail_activated: 是否触发移动止盈
        """
        # 计算价格差（改名为 price_diff）
        if position_type == "long":
            price_diff = exit_price - entry_price
        else:
            price_diff = entry_price - exit_price

        # 计算价格变动百分比（避免除零）
        if entry_price > 0:
            pnl_pct = price_diff / entry_price * 100
        else:
            pnl_pct = 0.0

        # 计算持仓时长
        duration = 0
        if entry_timestamp and exit_timestamp:
            duration = exit_timestamp - entry_timestamp

        # 确定日期文件
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        strategy_dir = self.base_path / strategy_name
        strategy_dir.mkdir(parents=True, exist_ok=True)
        filepath = strategy_dir / f"{date_str}.csv"

        # 写入 CSV
        write_header = not filepath.exists()
        row = {
            "position_id": position_id,
            "strategy_name": strategy_name,
            "symbol": symbol,
            "position_type": position_type,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "entry_time": entry_time.isoformat() if entry_time else "",
            "exit_time": exit_time.isoformat() if exit_time else "",
            "entry_timestamp": entry_timestamp or 0,
            "exit_timestamp": exit_timestamp,
            "peak_price": peak_price,
            "stop_price": stop_price,
            "max_pnl_pct": max_pnl_pct,
            "min_pnl_pct": min_pnl_pct,
            "exit_reason": exit_reason,
            "is_stop_loss": is_stop_loss,
            "price_diff": round(price_diff, 4),
            "pnl_pct": round(pnl_pct, 4),
            "atr_at_entry": atr_at_entry,
            "trail_activated": trail_activated,
            "duration_seconds": duration,
            "trading_mode": trading_mode,
        }

        with open(filepath, "a", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
            if write_header:
                writer.writeheader()
            writer.writerow(row)

        logger.info(f"历史仓位记录: {position_id} price_diff={price_diff:.2f} ({pnl_pct:.2f}%) max={max_pnl_pct:.2f}% min={min_pnl_pct:.2f}%")