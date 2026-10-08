#!/usr/bin/env python3
"""
配置加载器 - 只读取配置，不修改、不删除

保留的函数（legacy 双格式路径解析函数已删除）：
- load_main_config: 加载 YAML 配置文件（通用）
- load_profile: 加载 run-profile（config/<name>.yaml）
- verify_data_dir_consistency: 校验 profile.data_dir 与 settings.csv_dir 一致
- parse_date: 解析日期（YYYYMMDD / YYYY-MM-DD / 时间戳）
- merge_config_with_overrides: 深度合并配置与覆盖字段
"""

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Tuple

import yaml

PROFILES_DIR = Path("config")

# config/ 下不是 run-profile 的文件：它们是系统层与编排层配置，结构完全不同。
# 若允许 `--profile settings`，会把系统配置当 profile 解析，得到一堆字段缺失的
# 怪错误而非"参数不合法"。profile 与它们同目录（回测本来就要读 settings.yaml，
# 分开放反而割裂），因此改用保留名单显式拦截。
RESERVED_CONFIG_NAMES = frozenset({
    "settings", "settings.example",
    "strategies", "strategies.example",
})


def load_main_config(path: str) -> Dict:
    """读取 YAML 配置文件（只读）。

    Args:
        path: 配置文件路径

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


def load_profile(profile: str) -> Dict:
    """加载 run-profile（config/<name>.yaml）。

    run-profile 承载回测的运行方式（时间范围/资金/费率/输出/并发），绝不含策略参数。
    缺失或内容为空都视为错误——静默回退默认值会让"这次跑的是哪套参数"变得不可知，
    与配置收敛的目的相悖。

    Args:
        profile: profile 名（如 backtest）

    Returns:
        profile 配置字典（保证非空）

    Raises:
        FileNotFoundError: profile 文件不存在
        ValueError: profile 名含路径分隔符、是保留名，或文件内容为空
    """
    # profile 是文件名而非路径：拦住 "../etc/hostname" 这类穿越。
    if "/" in profile or "\\" in profile or profile.startswith("."):
        raise ValueError(f"profile 名不合法（不能含路径分隔符）: {profile!r}")

    # settings / strategies 与 profile 同在 config/ 下但不是 profile，显式拦截。
    if profile in RESERVED_CONFIG_NAMES:
        raise ValueError(
            f"{profile!r} 不是 run-profile，而是{'系统层' if 'settings' in profile else '编排层'}配置。"
            f"可用 profile 见 config/ 下非保留名的 yaml（如 backtest）。"
        )

    profile_path = PROFILES_DIR / f"{profile}.yaml"
    if not profile_path.exists():
        raise FileNotFoundError(f"profile 文件不存在: {profile_path}")

    with open(profile_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    if not cfg:
        raise ValueError(f"profile 文件内容为空: {profile_path}")
    return cfg


def verify_data_dir_consistency(profile_data_dir: str, settings_csv_dir) -> bool:
    """校验 profile.data_dir 与 settings.data_manager.csv_dir 指向同一目录。

    回测的配置来源是【两份】：config/settings.yaml（与实盘共用，提供
    顶层 use_bar_high_low_for_exit 等影响成交判定的字段）+ config/backtest.yaml
    （回测运行方式）。data_dir 与 csv_dir 是二者间唯一的语义重复。

    只靠注释约定维持不住：一旦有人只改一处，实盘往 A 目录写数据、回测从 B 目录读，
    回测结果基于过时数据却没有任何提示。这属于回测失真，必须在启动时拦住而不是
    留给使用者自己发现。

    settings_csv_dir 为 None（settings.yaml 不存在或未配置该键）时视为通过：
    此时回测仍可跑，但注意顶层的 use_bar_high_low_for_exit 会退回代码默认值 True，
    与 settings.yaml 中显式的 false 不同，止损判定行为会变化。

    Args:
        profile_data_dir: profile 的 data_dir
        settings_csv_dir: settings.yaml 的 data_manager.csv_dir，可为 None

    Returns:
        True（一致或无从比较）

    Raises:
        ValueError: 两者指向不同目录
    """
    if not settings_csv_dir:
        return True

    # "./data/klines" / "data/klines" / "data/klines/" 是同一目录，
    # 按写法直接比字符串会误报，故先归一化。
    if Path(profile_data_dir) == Path(settings_csv_dir):
        return True

    raise ValueError(
        "数据目录配置分叉：\n"
        f"  profile data_dir            = {profile_data_dir!r}\n"
        f"  settings.yaml csv_dir       = {settings_csv_dir!r}\n"
        "二者必须指向同一目录，否则实盘写入与回测读取会落在不同位置，"
        "回测将基于过时数据得出结论。"
    )


def parse_date(value: str) -> Tuple[str, datetime]:
    """解析日期输入，返回 (YYYYMMDD, datetime对象)。

    支持:
    - YYYYMMDD
    - YYYY-MM-DD
    - 秒时间戳(10位)
    - 毫秒时间戳(13位)
    """
    if value.isdigit() and len(value) in (10, 13):
        ts = int(value)
        if len(value) == 13:
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        else:
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
        return dt.strftime("%Y%m%d"), dt

    if "-" in value:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.strftime("%Y%m%d"), dt

    dt = datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
    return value, dt


def merge_config_with_overrides(base_config: Dict, overrides: Dict) -> Dict:
    """深度合并基础配置与覆盖字段。

    合并规则：
    - 嵌套字典：深度合并，只替换指定字段
    - 数组：直接替换（不合并）
    - None 值：删除该字段
    - 新字段：添加到结果
    """
    import copy

    result = copy.deepcopy(base_config)

    for key, value in overrides.items():
        if value is None:
            if key in result:
                del result[key]
        elif (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = merge_config_with_overrides(result[key], value)
        else:
            result[key] = copy.deepcopy(value)

    return result
