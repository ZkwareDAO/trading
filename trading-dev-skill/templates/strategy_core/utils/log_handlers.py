"""
日志工具模块

提供自定义日志处理器
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class DailyDirectoryFileHandler(logging.FileHandler):
    """
    按日期目录存储日志文件的处理器

    日志路径格式: {base_dir}/{YYYY-MM-DD}/{filename}.log
    每天自动创建新目录，使用 UTC 时间

    Args:
        base_dir: 日志基础目录
        filename: 日志文件名（不含扩展名）
        encoding: 文件编码
        date_override: 日期覆盖（YYYYMMDD 格式），用于回测模式
    """

    def __init__(
        self,
        base_dir: str,
        filename: str,
        encoding: str = "utf-8",
        date_override: str | None = None,
    ):
        self.base_dir = Path(base_dir)
        self.filename = filename
        self._current_date: Optional[str] = None
        self._date_override = date_override
        super().__init__(self._get_log_path(), encoding=encoding)

    def _get_log_path(self) -> str:
        """获取当前日期的日志路径"""
        if self._date_override:
            # 回测模式：使用指定的日期（YYYYMMDD -> YYYY-MM-DD）
            day_str = f"{self._date_override[:4]}-{self._date_override[4:6]}-{self._date_override[6:8]}"
        else:
            day_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        day_dir = self.base_dir / day_str
        day_dir.mkdir(parents=True, exist_ok=True)
        return str(day_dir / f"{self.filename}.log")

    def emit(self, record: logging.LogRecord) -> None:
        """写入日志，检查日期变化"""
        # 回测模式：不检查日期变化，始终使用固定日期
        if self._date_override:
            super().emit(record)
            return

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        if self._current_date != today:
            self._current_date = today
            # 刷新并关闭旧文件，打开新日期的文件
            if self.stream:
                self.flush()
            self.close()
            self.stream = open(self._get_log_path(), "a", encoding=self.encoding)

        super().emit(record)