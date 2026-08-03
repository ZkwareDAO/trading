"""策略参数加载器 — 通过 AST + config.yaml 静态读取策略命名参数

为 build_strategy_name() 提供与信号端 BaseStrategy 一致的数据来源：
- prefix:  通过 AST 解析 strategy.py 读取 STRATEGY_PREFIX 类属性（不执行导入）
- version: 加载 strategies/{name}/config.yaml 的 version 字段
- interval: 加载 strategies/{name}/config.yaml 的 timeframes[0]
"""

import ast
import logging
from pathlib import Path
from typing import Dict, Optional

import yaml

from strategy_core.utils.strategy_naming import extract_name_prefix

logger = logging.getLogger(__name__)

# 策略目录基路径（project_root/strategies/）
_STRATEGIES_DIR = Path(__file__).parent.parent.parent / "strategies"


def get_strategy_name_params(name: str) -> Dict[str, str]:
    """
    动态读取策略命名参数（与信号端 BaseStrategy 一致）

    - prefix:  通过 AST 解析 strategy.py 读取 STRATEGY_PREFIX
    - version: config.yaml 的 version 字段
    - interval: config.yaml 的 timeframes[0]

    Args:
        name: 策略目录名 (如 "cta_ict_v3", "dolphin_trading_v2")

    Returns:
        {"prefix": str, "version": str, "interval": str}
    """
    strategy_dir = _STRATEGIES_DIR / name

    version, interval, user_id = _load_config_params(strategy_dir, name)
    prefix = _extract_prefix_from_ast(strategy_dir, name)

    return {
        "prefix": prefix,
        "version": version,
        "interval": interval,
        "user_id": user_id,
    }


def _load_config_params(strategy_dir: Path, name: str) -> tuple[str, str, str]:
    """从 config.yaml 加载 version、timeframes[0] 和 user_id"""
    config_path = strategy_dir / "config.yaml"
    if not config_path.exists():
        logger.warning(f"策略配置不存在: {config_path}，使用默认值")
        return ("1", "1h", "")

    with open(config_path, "r", encoding="utf-8") as f:
        full_config = yaml.safe_load(f) or {}

    strategy_config = full_config.get(name, {})

    version = strategy_config.get("version", "1")
    timeframes = strategy_config.get("timeframes", ["1h"])
    interval = timeframes[0] if timeframes else "1h"
    user_id = str(strategy_config.get("user_id", ""))

    return (str(version), str(interval), user_id)


def _extract_prefix_from_ast(strategy_dir: Path, name: str) -> str:
    """
    通过 AST 解析 strategy.py，读取 Strategy.STRATEGY_PREFIX 类属性

    不执行任何导入，避免触发依赖链问题。
    """
    strategy_py = strategy_dir / "strategy.py"
    if not strategy_py.exists():
        logger.warning(f"策略文件不存在: {strategy_py}，回退到 extract_name_prefix")
        return extract_name_prefix(name)

    try:
        source = strategy_py.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(strategy_py))
    except SyntaxError as e:
        logger.warning(f"AST 解析失败 {strategy_py}: {e}，回退到 extract_name_prefix")
        return extract_name_prefix(name)

    prefix = _find_strategy_prefix_in_ast(tree)
    if prefix:
        return prefix

    logger.warning(f"未找到 STRATEGY_PREFIX，回退到 extract_name_prefix")
    return extract_name_prefix(name)


def _find_strategy_prefix_in_ast(tree: ast.AST) -> Optional[str]:
    """在 AST 中搜索 class Strategy 的 STRATEGY_PREFIX 类属性"""
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        # 找名为 Strategy 或包含 Strategy 的类
        if "Strategy" not in node.name:
            continue

        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            for target in item.targets:
                if isinstance(target, ast.Name) and target.id == "STRATEGY_PREFIX":
                    if isinstance(item.value, ast.Constant) and isinstance(item.value.value, str):
                        return item.value.value
    return None
