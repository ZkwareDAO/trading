"""
统一同步器

配置驱动的通用数据同步器，支持：
- 多路径扫描
- include/exclude 过滤
- 格式转换（csv_to_md, signal_csv_to_md, raw）
- URI 模板变量替换
"""

import fnmatch
import json
import logging
import re
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from .base_sync import BaseSyncer, SyncResult
from .ov_client import OpenVikingClient, OpenVikingError
from .formatter.signal_formatter import SignalFormatter
from .formatter.csv_formatter import CsvFormatter

logger = logging.getLogger(__name__)

# 默认并发限制
DEFAULT_MAX_CONCURRENT = 5

# 路径变量正则：匹配 {var_name}
PATH_VAR_PATTERN = re.compile(r'\{(\w+)\}')


@dataclass
class UniversalSyncResult(SyncResult):
    """同步结果"""
    source_type: str = "universal"
    files_synced: int = 0


class UniversalSyncer(BaseSyncer):
    """统一同步器 - 配置驱动的通用数据同步"""

    def __init__(
        self,
        source_name: str,
        config: Dict[str, Any],
        ov_client: OpenVikingClient,
    ):
        """
        初始化统一同步器

        Args:
            source_name: 同步源名称
            config: 配置字典
            ov_client: OpenViking 客户端
        """
        super().__init__(source_name, config, ov_client)

        # 路径配置
        paths = config.get("paths", [])
        if isinstance(paths, str):
            paths = [paths]
        self.paths = [Path(p) for p in paths]

        # 文件匹配
        self.pattern = config.get("pattern", "*")
        self.include = config.get("include", [])
        self.exclude = config.get("exclude", [])

        # 格式转换
        self.formatter_name = config.get("formatter", "raw")
        self.formatter = self._get_formatter(self.formatter_name)

        # URI 模板
        self.uri_template = config.get(
            "uri_template",
            "trading_data/{year}/{month}/{day}/{source_name}"
        )

        # 路径变量提取规则
        self.path_vars = config.get("path_vars", {})

        # 日期过滤（从文件名提取日期，只同步匹配指定日期的文件）
        self.date_from = config.get("date_from", "")  # 如 "{stem}" 从文件名提取日期

        # 并发限制（避免文件句柄耗尽）
        self.max_concurrent = config.get("max_concurrent", DEFAULT_MAX_CONCURRENT)

        # 路径模式（智能提取变量）
        # 例如: "{strategy}/{date}/{time}/{symbol}/{filename}"
        # 自动从文件路径提取对应位置的变量
        self.path_pattern = config.get("path_pattern", "")
        self._path_var_positions = self._parse_path_pattern(self.path_pattern)

        # 空文件过滤（默认启用）
        self.skip_empty = config.get("skip_empty", True)

        # 哨兵文件：检查此文件是否为空，为空则跳过整个目录
        self.sentinel_file = config.get("sentinel_file", "")

    @staticmethod
    def _count_csv_data_rows(file_path: Path) -> int:
        """
        统计 CSV 数据行数（排除表头）

        Args:
            file_path: CSV 文件路径

        Returns:
            数据行数（总行数 - 1）
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                line_count = sum(1 for _ in f)
            return max(0, line_count - 1)  # 减去表头
        except Exception:
            return 0

    @staticmethod
    def _is_valid_json_data(file_path: Path) -> bool:
        """
        检查 JSON 文件是否包含有效数据

        Args:
            file_path: JSON 文件路径

        Returns:
            是否有有效数据
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                # 空对象或只有 null 值
                if not data:
                    return False
                # 持仓文件: position 有值，或其他字段有非 null 值
                return data.get("position") is not None or any(v is not None for v in data.values())

            if isinstance(data, list):
                return len(data) > 0

            return bool(data)

        except Exception:
            return False

    def _should_skip_file(self, file_path: Path) -> bool:
        """
        检查是否应该跳过该文件（空文件检测）

        Args:
            file_path: 文件路径

        Returns:
            True 表示跳过，False 表示上传
        """
        if not self.skip_empty:
            return False

        suffix = file_path.suffix.lower()

        if suffix == ".csv":
            rows = self._count_csv_data_rows(file_path)
            if rows == 0:
                logger.warning(f"跳过空 CSV 文件: {file_path.name} (0 行数据)")
                return True

        elif suffix == ".json":
            if not self._is_valid_json_data(file_path):
                logger.warning(f"跳过空 JSON 文件: {file_path.name} (无有效数据)")
                return True

        return False

    def _parse_path_pattern(self, pattern: str) -> Dict[str, int]:
        """
        解析路径模式，返回变量名到位置索引的映射

        例如: "{strategy}/{date}/{time}/{symbol}/{filename}"
        返回: {"strategy": -5, "date": -4, "time": -3, "symbol": -2, "filename": -1}
        """
        if not pattern:
            return {}

        parts = pattern.split("/")
        positions = {}
        for i, part in enumerate(parts):
            match = PATH_VAR_PATTERN.match(part)
            if match:
                var_name = match.group(1)
                # 使用负索引，从文件名开始计数
                positions[var_name] = i - len(parts)
        return positions

    def _get_formatter(self, name: str) -> Optional[Callable]:
        """获取格式转换器"""
        if name == "raw":
            return None

        if name == "csv_to_md":
            return lambda f, c: CsvFormatter.to_markdown(f, f.stem, c)

        if name == "signal_csv_to_md":
            return lambda f, c: SignalFormatter.csv_to_markdown(
                str(f), c.get("strategy", ""), c.get("date_obj", datetime.now())
            )

        return None

    def sync_daily(
        self,
        date: datetime,
        strategy_names: Optional[List[str]] = None,
        account: str = "",
    ) -> List[SyncResult]:
        """
        同步指定日期的数据

        Args:
            date: 日期
            strategy_names: 策略名称列表（可选）
            account: 账户名

        Returns:
            同步结果列表
        """
        results = []
        files = self._scan_files(date)

        # 哨兵文件过滤：按目录分组，检查哨兵文件是否为空
        if self.sentinel_file:
            files = self._filter_by_sentinel(files)

        for i, file_path in enumerate(files):
            result = self._sync_file(file_path, date, account)
            if result:
                results.append(result)

            # 并发控制：每上传 max_concurrent 个文件后暂停
            if (i + 1) % self.max_concurrent == 0:
                logger.info(f"Synced {i + 1}/{len(files)} files, pausing...")
                time.sleep(1)  # 等待 1 秒让服务器处理

        return results

    def _scan_files(self, date: datetime) -> List[Path]:
        """扫描匹配的文件"""
        files = []
        date_str = date.strftime("%Y%m%d")

        for base_path in self.paths:
            if not base_path.exists():
                continue

            for f in base_path.glob(self.pattern):
                if not f.is_file():
                    continue
                if not self._match_filters(f):
                    continue
                # 日期过滤：如果配置了 date_from，只同步当天文件
                if self.date_from and not self._match_date(f, date_str):
                    continue
                files.append(f)

        return sorted(files)

    def _filter_by_sentinel(self, files: List[Path]) -> List[Path]:
        """
        通过哨兵文件过滤：如果哨兵文件为空，跳过整个目录

        Args:
            files: 扫描到的文件列表

        Returns:
            过滤后的文件列表
        """
        # 按目录分组（symbol 级别）
        dir_files: Dict[Path, List[Path]] = {}
        for f in files:
            dir_files.setdefault(f.parent, []).append(f)

        # 检查每个目录的哨兵文件
        result = []
        for dir_path, dir_file_list in dir_files.items():
            sentinel_path = dir_path / self.sentinel_file

            # 哨兵文件存在且为空 → 跳过整个目录
            if sentinel_path.exists() and self._should_skip_file(sentinel_path):
                logger.warning(
                    f"跳过目录 {dir_path.name}: 哨兵文件 {self.sentinel_file} 为空"
                )
                continue

            # 其他情况：哨兵不存在或有数据，保留所有文件
            result.extend(dir_file_list)

        return result

    def _match_date(self, file_path: Path, date_str: str) -> bool:
        """
        检查文件是否匹配指定日期

        Args:
            file_path: 文件路径
            date_str: 目标日期字符串 (YYYYMMDD)

        Returns:
            是否匹配
        """
        if not self.date_from:
            return True

        # 使用 path_pattern 智能提取日期变量
        if self._path_var_positions:
            var_name = self.date_from.strip("{}")
            if var_name in self._path_var_positions:
                return self._match_date_from_path_position(file_path, date_str, var_name)

        # 兼容旧格式
        return self._match_date_legacy(file_path, date_str)

    def _match_date_from_path_position(self, file_path: Path, date_str: str, var_name: str) -> bool:
        """从路径位置提取并匹配日期"""
        pos = self._path_var_positions[var_name]
        parts = list(file_path.parts)
        try:
            value = parts[pos].replace("-", "")
            return value == date_str
        except IndexError:
            return False

    def _match_date_legacy(self, file_path: Path, date_str: str) -> bool:
        """兼容旧格式的日期匹配"""
        if self.date_from == "{stem}":
            return file_path.stem == date_str
        if self.date_from == "{filename}":
            return file_path.stem.startswith(date_str)
        if self.date_from == "{parent_dir}":
            return file_path.parent.name.replace("-", "") == date_str
        return True

    def _match_filters(self, file_path: Path) -> bool:
        """检查文件是否匹配过滤规则"""
        filename = file_path.name

        # exclude 优先
        for pattern in self.exclude:
            if fnmatch.fnmatch(filename, pattern):
                return False

        # include 匹配
        if self.include:
            for pattern in self.include:
                if fnmatch.fnmatch(filename, pattern):
                    return True
            return False

        return True

    def _sync_file(
        self,
        file_path: Path,
        date: datetime,
        account: str = "",
    ) -> Optional[SyncResult]:
        """同步单个文件"""
        # 空文件检查
        if self._should_skip_file(file_path):
            return None

        context = self._extract_context(file_path, date)
        target_uri = self._generate_uri(context, account)

        try:
            upload_path = self._prepare_upload_file(file_path, context)
            self.ov_client.add_resource(
                file_path=upload_path,
                target_uri=target_uri,
                reason=f"Sync: {self.source_name}",
                wait=False,
            )

            # 清理临时文件
            if self.formatter and upload_path != str(file_path):
                Path(upload_path).unlink(missing_ok=True)

            return UniversalSyncResult(
                success=True,
                source_name=self.source_name,
                uri=target_uri,
                items_count=1,
                files_synced=1,
            )

        except OpenVikingError as e:
            logger.error(f"Failed to sync {file_path}: {e}")
            return UniversalSyncResult(
                success=False,
                source_name=self.source_name,
                uri=target_uri,
                error=str(e),
            )

    def _prepare_upload_file(self, file_path: Path, context: dict) -> str:
        """准备上传文件（格式转换或直接返回原路径）"""
        if not self.formatter:
            return str(file_path)

        content = self.formatter(file_path, context)
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            return f.name

    def _extract_context(self, file_path: Path, date: datetime) -> dict:
        """从文件路径提取上下文变量"""
        context = {
            "year": date.year,
            "month": f"{date.month:02d}",
            "day": f"{date.day:02d}",
            "date": date.strftime("%Y%m%d"),
            "date_obj": date,
            "filename": file_path.name,
            "stem": file_path.stem,
            "source_name": self.source_name,
            "strategy": "",
            "symbol": "",
        }

        # 根据 path_vars 规则提取变量
        for var_name, pattern in self.path_vars.items():
            self._extract_by_pattern(file_path, context, var_name, pattern)

        # 根据 path_pattern 智能提取（优先级更高）
        if self._path_var_positions:
            parts = list(file_path.parts)
            for var_name, pos in self._path_var_positions.items():
                try:
                    context[var_name] = parts[pos]
                except IndexError:
                    context[var_name] = ""

        return context

    def _extract_by_pattern(self, file_path: Path, context: dict, var_name: str, pattern: str):
        """根据单个模式提取变量"""
        # 映射模式到提取逻辑
        extractors = {
            "{parent_dir}": lambda p: p.parent.name,
            "{parent}": lambda p: p.parent.name,
            "{stem}": lambda p: p.stem,
            "{filename}": lambda p: p.name,
        }

        extractor = extractors.get(pattern)
        if extractor:
            context[var_name] = extractor(file_path)

    def _generate_uri(self, context: dict, account: str) -> str:
        """生成目标 URI"""
        try:
            uri_path = self.uri_template.format(**context)
        except KeyError as e:
            logger.warning(f"Missing template variable {e}, using raw template")
            uri_path = self.uri_template

        base = "viking://resources/"
        if account:
            base += f"{account}/"

        return f"{base}{uri_path}"

    def discover_sources(self, date: datetime) -> List[str]:
        """发现可同步的源"""
        files = self._scan_files(date)
        return [f.name for f in files]