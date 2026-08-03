#!/usr/bin/env python3
"""仓位状态持久化工具"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class PositionPersistence:
    """仓位状态持久化工具

    将策略的仓位状态保存到 JSON 文件，支持进程重启后恢复。

    文件位置: data/positions/{strategy_name}.json
    """

    def __init__(self, base_path: Path = Path("data/positions")):
        self.base_path = base_path
        self.base_path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def generate_position_id(
        strategy_name: str, symbol: str, entry_timestamp: int
    ) -> str:
        """
        生成仓位唯一标识

        Args:
            strategy_name: 策略名称
            symbol: 交易标的
            entry_timestamp: 开仓时的 K 线时间戳（秒）

        Returns:
            position_id: {strategy_name}_{symbol}_{timestamp}
        """
        return f"{strategy_name}_{symbol}_{entry_timestamp}"

    def save_on_entry(
        self, strategy_name: str, position_id: str, state: Dict[str, Any],
        trading_mode: str = "live",
    ) -> None:
        """
        开仓时立即持久化

        Args:
            strategy_name: 策略名称
            position_id: 仓位唯一标识
            state: 仓位状态字典
            trading_mode: 运行模式 (live / paper_trading / smoking)
        """
        state["position_id"] = position_id
        state["entry_saved_at"] = int(datetime.now(timezone.utc).timestamp())
        state["trading_mode"] = trading_mode
        filepath = self.base_path / f"{strategy_name}.json"
        with open(filepath, "w") as f:
            json.dump(state, f, indent=2, default=str)
        logger.info(f"仓位持久化: {position_id}")

    def update_state(
        self, strategy_name: str, position_id: str, updates: Dict[str, Any]
    ) -> None:
        """
        更新仓位状态（peak_price、stop_price 等）

        Args:
            strategy_name: 策略名称
            position_id: 仓位唯一标识
            updates: 更新字段
        """
        saved = self.load(strategy_name)
        if saved and saved.get("position_id") == position_id:
            saved.update(updates)
            saved["updated_at"] = int(datetime.now(timezone.utc).timestamp())
            filepath = self.base_path / f"{strategy_name}.json"
            with open(filepath, "w") as f:
                json.dump(saved, f, indent=2, default=str)

    def clear_on_exit(self, strategy_name: str, position_id: str) -> None:
        """
        平仓时清除持久化（校验 position_id）

        Args:
            strategy_name: 策略名称
            position_id: 仓位唯一标识
        """
        saved = self.load(strategy_name)
        if saved and saved.get("position_id") == position_id:
            self.clear(strategy_name)
            logger.info(f"仓位持久化已清除: {position_id}")
        elif saved:
            logger.warning(
                f"position_id 不匹配，跳过清除: "
                f"期望={position_id}, 实际={saved.get('position_id')}"
            )

    def save(self, strategy_name: str, state: Dict[str, Any], trading_mode: str = "live") -> None:
        """保存仓位状态

        Args:
            strategy_name: 策略名称（用于生成文件名）
            state: 仓位状态字典
            trading_mode: 运行模式 (live / paper_trading / smoking)
        """
        state["trading_mode"] = trading_mode
        filepath = self.base_path / f"{strategy_name}.json"
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        with open(filepath, "w") as f:
            json.dump(state, f, indent=2, default=str)
        logger.debug(f"仓位状态已保存: {filepath}")

    def load(self, strategy_name: str) -> Optional[Dict[str, Any]]:
        """加载仓位状态

        Args:
            strategy_name: 策略名称

        Returns:
            仓位状态字典，文件不存在或损坏时返回 None
        """
        filepath = self.base_path / f"{strategy_name}.json"
        if not filepath.exists():
            return None
        try:
            with open(filepath, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"加载仓位状态失败: {filepath}, 错误: {e}")
            return None

    def clear(self, strategy_name: str) -> None:
        """清除仓位状态（平仓后）

        Args:
            strategy_name: 策略名称
        """
        filepath = self.base_path / f"{strategy_name}.json"
        if filepath.exists():
            filepath.unlink()
            logger.debug(f"仓位状态已清除: {filepath}")