"""
信号格式转换器

将信号 CSV 文件转换为 OpenViking 友好的 Markdown 格式。
"""

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class SignalFormatter:
    """信号 CSV → Markdown 转换器"""

    # 动作类型映射
    ACTION_NAMES = {
        "buy": "买入",
        "sell": "卖出",
        "buy_close": "平多",
        "sell_close": "平空",
        "reverse_long": "反多",
        "reverse_short": "反空",
    }

    @staticmethod
    def csv_to_markdown(
        csv_path: str,
        strategy_name: str,
        date: datetime,
    ) -> str:
        """
        CSV 文件转 Markdown 格式

        Args:
            csv_path: CSV 文件路径
            strategy_name: 策略名称
            date: 日期

        Returns:
            Markdown 格式的信号文档
        """
        csv_path = Path(csv_path)
        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        # 读取 CSV 数据
        signals = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                signals.append(row)

        # 生成统计
        stats = SignalFormatter.generate_summary_stats(signals)

        # 获取策略信息（从第一条信号）
        signals[0].get("strategy_version", "v1") if signals else "v1"
        strategy_internal = signals[0].get("strategy_internal", "") if signals else ""
        strategy_params = signals[0].get("strategy_params", "{}") if signals else "{}"

        # 构建 Markdown
        lines = []

        # 标题
        lines.append(f"# CTA 交易信号 - {strategy_name} - {date.strftime('%Y-%m-%d')}")
        lines.append("")

        # 基本信息
        lines.append(f"**策略**: {strategy_name}")
        lines.append(f"**日期**: {date.strftime('%Y-%m-%d')}")
        if strategy_internal:
            lines.append(f"**K线周期**: {strategy_internal}")
        lines.append(f"**信号数量**: {stats['total']}")
        lines.append("")

        # 信号列表
        lines.append("## 信号列表")
        lines.append("")
        lines.append("| signal_id | 时间 | 标的 | 动作 | 价格 | 强度 | 原因 |")
        lines.append("|-----------|------|------|------|------|------|------|")

        for signal in signals:
            signal_id = signal.get("signal_id", "")[:16] + "..."
            time_str = SignalFormatter.timestamp_to_time(
                int(signal.get("signal_timestamp", 0))
            )
            symbol = signal.get("symbol", "")
            action = signal.get("signal_action", "")
            action_cn = SignalFormatter.ACTION_NAMES.get(action, action)
            price = signal.get("signal_trigger_price", "")
            strength = signal.get("strength", "")

            # 从 metadata 提取原因
            reason = ""
            try:
                metadata = json.loads(signal.get("metadata", "{}"))
                reason = metadata.get("reason", "")[:30]
            except (json.JSONDecodeError, TypeError):
                pass

            lines.append(
                f"| {signal_id} | {time_str} | {symbol} | {action_cn} | {price} | {strength} | {reason} |"
            )

        lines.append("")

        # 策略参数
        lines.append("## 策略参数")
        lines.append("")
        lines.append("```json")
        try:
            params = json.loads(strategy_params)
            lines.append(json.dumps(params, indent=2, ensure_ascii=False))
        except (json.JSONDecodeError, TypeError):
            lines.append(strategy_params)
        lines.append("```")
        lines.append("")

        # 统计信息
        lines.append("## 统计")
        lines.append("")
        lines.append(f"- **买入信号**: {stats['buy']}")
        lines.append(f"- **卖出信号**: {stats['sell']}")
        lines.append(f"- **平多信号**: {stats['buy_close']}")
        lines.append(f"- **平空信号**: {stats['sell_close']}")
        lines.append(f"- **涉及标的**: {', '.join(stats['symbols']) if stats['symbols'] else '无'}")
        if stats['avg_strength'] > 0:
            lines.append(f"- **平均信号强度**: {stats['avg_strength']:.2f}")

        return "\n".join(lines)

    @staticmethod
    def generate_summary_stats(csv_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        生成统计摘要

        Args:
            csv_data: CSV 数据列表

        Returns:
            统计摘要字典
        """
        stats = {
            "total": len(csv_data),
            "buy": 0,
            "sell": 0,
            "buy_close": 0,
            "sell_close": 0,
            "reverse_long": 0,
            "reverse_short": 0,
            "symbols": set(),
            "avg_strength": 0.0,
        }

        if not csv_data:
            stats["symbols"] = []
            return stats

        total_strength = 0.0
        strength_count = 0

        for row in csv_data:
            action = row.get("signal_action", "")
            if action in stats:
                stats[action] += 1

            symbol = row.get("symbol", "")
            if symbol:
                stats["symbols"].add(symbol)

            try:
                strength = float(row.get("strength", 0))
                if strength > 0:
                    total_strength += strength
                    strength_count += 1
            except (ValueError, TypeError):
                pass

        if strength_count > 0:
            stats["avg_strength"] = total_strength / strength_count

        stats["symbols"] = sorted(list(stats["symbols"]))

        return stats

    @staticmethod
    def timestamp_to_time(ts_ms: int) -> str:
        """
        毫秒时间戳转时间字符串

        Args:
            ts_ms: 毫秒时间戳

        Returns:
            时间字符串 (HH:MM)
        """
        if ts_ms <= 0:
            return "--:--"

        try:
            dt = datetime.fromtimestamp(ts_ms / 1000)
            return dt.strftime("%H:%M")
        except (ValueError, OSError):
            return "--:--"
