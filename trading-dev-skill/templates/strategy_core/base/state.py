#!/usr/bin/env python3
"""
策略状态基类

包含所有策略共有的状态字段，遵循 docs/strategy/DEVELOPMENT_GUIDE.md 规范
"""

from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional, Dict, Any


@dataclass
class BaseState:
    """
    策略状态基类 - 包含所有策略共有的状态字段

    子类可以添加特有字段，但必须重写 to_persist_dict() 和 restore_from_dict()
    以确保特有字段被正确持久化和恢复。

    Attributes:
        position: 当前仓位 ('long', 'short', None)
        position_id: 仓位唯一标识
        entry_timestamp: 开仓时的 K 线时间戳（秒）
        entry_price: 开仓价格
        entry_time: 开仓时间
        peak_price: 持仓期间峰值价格（用于 trailing stop）
        stop_price: 止损价格
        stop_loss_date: 止损日期（用于日内止损冷却）
    """

    # ========== 必需字段 ==========
    position: Optional[str] = None           # 'long', 'short', None
    position_id: Optional[str] = None
    entry_timestamp: Optional[int] = None    # 秒级时间戳
    entry_price: float = 0.0
    entry_time: Optional[datetime] = None
    peak_price: float = 0.0
    stop_price: float = 0.0

    # ========== 止损日冷却 ==========
    stop_loss_date: Optional[date] = None

    # ========== 盈亏极值记录 ==========
    max_pnl_pct: float = 0.0  # 最大盈利百分比（>0）
    min_pnl_pct: float = 0.0  # 最大亏损百分比（<0）

    # ========== 回落止盈状态 ==========
    trail_activated: bool = False          # 是否已激活
    trail_trigger_pct: float = 0.0         # 触发百分比

    # ========== 通用方法 ==========

    def is_in_position(self) -> bool:
        """是否有持仓"""
        return self.position is not None

    def clear_position(
        self,
        record_stop_loss: bool = False,
        current_time: Optional[datetime] = None
    ) -> None:
        """
        清除持仓状态

        Args:
            record_stop_loss: 是否记录止损日期
            current_time: 当前时间，用于记录止损日期
        """
        self.position = None
        self.position_id = None
        self.entry_timestamp = None
        self.entry_price = 0.0
        self.entry_time = None
        self.peak_price = 0.0
        self.stop_price = 0.0
        self.max_pnl_pct = 0.0
        self.min_pnl_pct = 0.0
        self.trail_activated = False
        self.trail_trigger_pct = 0.0

        if record_stop_loss and current_time:
            self.stop_loss_date = current_time.date()

    def to_persist_dict(self) -> Dict[str, Any]:
        """
        转换为持久化字典

        子类重写以添加特有字段：

        def to_persist_dict(self):
            data = super().to_persist_dict()
            data.update({
                "my_custom_field": self.my_custom_field,
            })
            return data
        """
        return {
            "position": self.position,
            "position_id": self.position_id,
            "entry_timestamp": self.entry_timestamp,
            "entry_price": self.entry_price,
            "entry_time": self.entry_time.isoformat() if self.entry_time else None,
            "peak_price": self.peak_price,
            "stop_price": self.stop_price,
            "max_pnl_pct": self.max_pnl_pct,
            "min_pnl_pct": self.min_pnl_pct,
            "trail_activated": self.trail_activated,
            "trail_trigger_pct": self.trail_trigger_pct,
        }

    def restore_from_dict(self, data: Dict[str, Any]) -> None:
        """
        从字典恢复状态

        子类重写以恢复特有字段：

        def restore_from_dict(self, data):
            super().restore_from_dict(data)
            self.my_custom_field = data.get("my_custom_field", 0.0)
        """
        self.position = data.get("position")
        self.position_id = data.get("position_id")
        self.entry_timestamp = data.get("entry_timestamp")
        self.entry_price = data.get("entry_price", 0.0)
        self.peak_price = data.get("peak_price", 0.0)
        self.stop_price = data.get("stop_price", 0.0)
        self.max_pnl_pct = data.get("max_pnl_pct", 0.0)
        self.min_pnl_pct = data.get("min_pnl_pct", 0.0)
        self.trail_activated = data.get("trail_activated", False)
        self.trail_trigger_pct = data.get("trail_trigger_pct", 0.0)

        if data.get("entry_time"):
            try:
                self.entry_time = datetime.fromisoformat(data["entry_time"])
            except ValueError:
                self.entry_time = None

    def update_pnl_extremes(self, current_price: float) -> None:
        """
        更新盈亏极值

        Args:
            current_price: 当前价格
        """
        if not self.is_in_position() or self.entry_price <= 0:
            return

        # 计算当前盈亏百分比
        if self.position == "long":
            pnl_pct = (current_price - self.entry_price) / self.entry_price * 100
        else:  # short
            pnl_pct = (self.entry_price - current_price) / self.entry_price * 100

        # 更新极值
        if pnl_pct > self.max_pnl_pct:
            self.max_pnl_pct = pnl_pct
        if pnl_pct < self.min_pnl_pct:
            self.min_pnl_pct = pnl_pct
