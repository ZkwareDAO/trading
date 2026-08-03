"""
通用 CSV → Markdown 转换器

将任意 CSV 文件转换为 Markdown 表格格式。
"""

import csv
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class CsvFormatter:
    """通用 CSV 转 Markdown 转换器"""

    @staticmethod
    def to_markdown(
        csv_path: Path,
        title: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        将 CSV 文件转换为 Markdown 格式

        Args:
            csv_path: CSV 文件路径
            title: 标题（默认使用文件名）
            context: 上下文变量（strategy, date 等）

        Returns:
            Markdown 格式字符串
        """
        context = context or {}

        if not csv_path.exists():
            raise FileNotFoundError(f"CSV file not found: {csv_path}")

        # 读取 CSV 数据
        rows = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

        # 生成标题
        if not title:
            title = csv_path.stem

        # 构建 Markdown
        lines = []

        # 标题
        lines.append(f"# {title}")
        lines.append("")

        # 元信息
        if context:
            if context.get("strategy"):
                lines.append(f"**策略**: {context['strategy']}")
            if context.get("date"):
                lines.append(f"**日期**: {context['date']}")

        lines.append(f"**记录数**: {len(rows)}")
        lines.append("")

        if not rows:
            return "\n".join(lines)

        # 表格
        headers = list(rows[0].keys())

        # 表头
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("| " + " | ".join(["---"] * len(headers)) + " |")

        # 数据行（限制每列最大宽度）
        for row in rows:
            values = []
            for h in headers:
                val = str(row.get(h, ""))
                # 截断过长的值
                if len(val) > 50:
                    val = val[:47] + "..."
                values.append(val)
            lines.append("| " + " | ".join(values) + " |")

        lines.append("")

        # 统计摘要
        stats = CsvFormatter._generate_stats(rows)
        if stats:
            lines.append("## 统计")
            lines.append("")
            for key, value in stats.items():
                lines.append(f"- **{key}**: {value}")

        return "\n".join(lines)

    @staticmethod
    def _generate_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        生成统计摘要

        Args:
            rows: 数据行列表

        Returns:
            统计摘要字典
        """
        if not rows:
            return {}

        stats = {}

        # 数值列统计
        numeric_cols = []
        for key in rows[0].keys():
            try:
                float(rows[0].get(key, "nan"))
                numeric_cols.append(key)
            except (ValueError, TypeError):
                pass

        for col in numeric_cols:
            values = []
            for row in rows:
                try:
                    values.append(float(row.get(col, 0)))
                except (ValueError, TypeError):
                    pass

            if values:
                stats[f"{col} 总和"] = f"{sum(values):.2f}"
                stats[f"{col} 平均"] = f"{sum(values) / len(values):.2f}"

        return stats