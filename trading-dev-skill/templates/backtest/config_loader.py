#!/usr/bin/env python3
"""
配置加载器 - 只读取配置，不修改、不删除

功能：
- load_main_config: 加载全局配置
- load_batch_config: 加载批量配置
- build_config_path: 组合配置路径
- resolve_config_path: 解析路径
- parse_date: 解析日期
- resolve_strategy_config_path: 解析策略配置路径（支持全局/策略级 config_path）
- merge_config_with_overrides: 深度合并配置与覆盖字段
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple

import yaml


def load_main_config(path: str) -> Dict:
    """
    读取全局配置（只读）

    Args:
        path: 配置文件路径，如 "backtest/config/main.yaml"

    Returns:
        配置字典

    Raises:
        FileNotFoundError: 配置文件不存在
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_batch_config(path: str) -> Dict:
    """
    读取批量配置（只读）

    配置文件格式：{strategy_name: {config}}
    返回第一个 key 的 value

    Args:
        path: 配置文件路径，如 "backtest/config/cta_rbreaker_v2/BTCUSDT.yaml"

    Returns:
        策略配置字典

    Raises:
        FileNotFoundError: 配置文件不存在
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {path}")

    with open(config_path, "r", encoding="utf-8") as f:
        full_config = yaml.safe_load(f)

    if full_config:
        strategy_name = list(full_config.keys())[0]
        return full_config[strategy_name]
    return {}


def build_config_path(config_dir: str, strategy_name: str, symbol: str) -> str:
    """
    组合配置文件路径

    Args:
        config_dir: 配置目录，如 "backtest/config" 或 "./backtest/config"
        strategy_name: 策略名称，如 "cta_rbreaker_v2"
        symbol: 交易对，如 "BTCUSDT"

    Returns:
        配置文件路径字符串，如 "backtest/config/cta_rbreaker_v2/BTCUSDT.yaml"
    """
    # 保留 ./ 前缀（如果存在）
    has_dot_slash = config_dir.startswith("./")

    # 使用 Path 组合路径
    config_path = Path(config_dir) / strategy_name / f"{symbol}.yaml"

    # 转换为字符串
    result = str(config_path)

    # 如果原始路径有 ./ 前缀，恢复它
    if has_dot_slash and not result.startswith("./"):
        result = "./" + result

    return result


def resolve_config_path(config_path: str) -> str:
    """
    解析配置路径，确保路径格式正确

    支持：
    - backtest/config/cta_rbreaker_v2/BTCUSDT.yaml
    - ./backtest/config/cta_rbreaker_v2/BTCUSDT.yaml
    - /absolute/path/backtest/config/cta_rbreaker_v2/BTCUSDT.yaml

    Args:
        config_path: 原始路径

    Returns:
        解析后的路径
    """
    path = Path(config_path)

    # 如果路径存在，返回绝对路径
    if path.exists():
        return str(path.resolve())

    # 尝试添加 ./ 前缀
    if not config_path.startswith("./") and not config_path.startswith("/"):
        alt_path = Path("./" + config_path)
        if alt_path.exists():
            return str(alt_path.resolve())

    # 返回原始路径（后续会报错文件不存在）
    return config_path


def parse_date(value: str) -> Tuple[str, datetime]:
    """
    解析日期输入，返回 (YYYYMMDD, datetime对象)

    支持:
    - YYYYMMDD
    - YYYY-MM-DD
    - 秒时间戳(10位)
    - 毫秒时间戳(13位)

    Args:
        value: 日期字符串

    Returns:
        (YYYYMMDD格式字符串, datetime对象)
    """
    # 时间戳格式
    if value.isdigit() and len(value) in (10, 13):
        ts = int(value)
        if len(value) == 13:
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        else:  # len == 10
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y%m%d"), dt

    # YYYY-MM-DD 格式
    if "-" in value:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y%m%d"), dt

    # YYYYMMDD 格式
    dt = datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
    return value, dt


def resolve_strategy_config_path(
    strategy_name: str,
    symbol: str,
    global_config_path: str = "backtest/config",
    strategy_config_path: str | None = None,
) -> str:
    """
    解析策略配置文件路径

    优先级：strategy_config_path > global_config_path > 默认值

    Args:
        strategy_name: 策略名称，如 "cta_ict_v3"
        symbol: 交易对，如 "BTCUSDT"（自动转大写）
        global_config_path: 全局配置路径，默认 "config/strategies"
        strategy_config_path: 策略级配置路径，优先级最高

    Returns:
        配置文件路径，如 "backtest/config/cta_ict_v3/BTCUSDT.yaml"
    """
    # 确定基础路径（策略级优先）
    base_path = strategy_config_path if strategy_config_path else global_config_path

    # symbol 转大写
    symbol_upper = symbol.upper()

    # 保留 ./ 前缀（如果存在）
    has_dot_slash = base_path.startswith("./")

    # 组合路径
    config_path = Path(base_path) / strategy_name / f"{symbol_upper}.yaml"

    # 转换为字符串
    result = str(config_path)

    # 如果原始路径有 ./ 前缀，恢复它
    if has_dot_slash and not result.startswith("./"):
        result = "./" + result

    return result


def merge_config_with_overrides(base_config: Dict, overrides: Dict) -> Dict:
    """
    深度合并基础配置与覆盖字段

    合并规则：
    - 嵌套字典：深度合并，只替换指定字段
    - 数组：直接替换（不合并）
    - None 值：删除该字段
    - 新字段：添加到结果

    Args:
        base_config: 基础配置（从配置文件加载）
        overrides: 覆盖字段（优先级更高）

    Returns:
        合并后的配置（新字典，不修改原配置）
    """
    import copy

    # 深拷贝避免修改原配置
    result = copy.deepcopy(base_config)

    for key, value in overrides.items():
        if value is None:
            # None 值删除字段
            if key in result:
                del result[key]
        elif (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            # 嵌套字典：递归合并
            result[key] = merge_config_with_overrides(result[key], value)
        else:
            # 其他情况：直接覆盖
            result[key] = copy.deepcopy(value)

    return result
