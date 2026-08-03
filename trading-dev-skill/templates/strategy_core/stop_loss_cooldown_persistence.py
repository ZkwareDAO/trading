#!/usr/bin/env python3
"""止损冷却持久化工具

独立存储 stop_loss_date，不依赖仓位持久化文件。
策略重启后可正确恢复止损冷却状态。
"""

import json
import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class StopLossCoolDownPersistence:
    """止损冷却持久化工具

    文件位置: data/stop_loss_cool_down/{strategy_id}.json
    内容: {"stop_loss_date": "2026-06-26", "updated_at": "2026-06-26T15:30:00+00:00"}
    """

    def __init__(self, base_path: Path = Path("data/stop_loss_cool_down")):
        self.base_path = base_path
        self.base_path.mkdir(parents=True, exist_ok=True)

    def save(self, strategy_id: str, stop_loss_date: date) -> None:
        """
        保存止损日期

        Args:
            strategy_id: 策略 ID（如 OBVATR_4H_2_DOGEUSDT_LIVE）
            stop_loss_date: 止损日期
        """
        data = {
            "stop_loss_date": stop_loss_date.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        filepath = self.base_path / f"{strategy_id}.json"
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(f"[{strategy_id}] 止损冷却已保存: stop_loss_date={stop_loss_date}")

    def load(self, strategy_id: str) -> Optional[date]:
        """
        加载止损日期

        Args:
            strategy_id: 策略 ID

        Returns:
            止损日期，文件不存在或损坏时返回 None
        """
        filepath = self.base_path / f"{strategy_id}.json"
        if not filepath.exists():
            return None

        try:
            with open(filepath, "r") as f:
                data = json.load(f)
                stop_loss_date_str = data.get("stop_loss_date")
                if stop_loss_date_str:
                    return date.fromisoformat(stop_loss_date_str)
                return None
        except (json.JSONDecodeError, IOError, ValueError) as e:
            logger.error(f"加载止损冷却失败: {filepath}, 错误: {e}")
            return None

    def clear(self, strategy_id: str) -> None:
        """
        清除止损冷却（新的一天开始时）

        Args:
            strategy_id: 策略 ID
        """
        filepath = self.base_path / f"{strategy_id}.json"
        if filepath.exists():
            filepath.unlink()
            logger.info(f"[{strategy_id}] 止损冷却已清除")
