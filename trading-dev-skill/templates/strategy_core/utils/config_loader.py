"""
策略配置加载器 - 支持多环境

加载策略配置文件:
- config.{env}.yaml (如 config.prod.yaml) - 通过 CTA_ENV 环境变量指定（可选）
- config.yaml (默认回退)

注意: 新架构中，策略运行配置在 settings.yaml 的 strategies 段指定。
此模块用于加载策略内部的参数配置（如指标参数等）。
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def load_config_with_env(
    strategy_name: str,
    config_dir: Optional[Path] = None,
    env: Optional[str] = None,
) -> Dict[str, Any]:
    """
    加载策略配置

    加载顺序:
    1. config.{env}.yaml (如 config.prod.yaml) - 如果指定了 env
    2. config.yaml (默认回退)

    Args:
        strategy_name: 策略名称 (如 "cta_rbreaker")
        config_dir: 配置目录路径 (默认自动推导)
        env: 环境名称 (如 "dev", "prod")，可选，默认从 CTA_ENV 读取

    Returns:
        策略配置字典
    """
    # 获取环境变量（可选）
    if env is None:
        env = os.environ.get("CTA_ENV", None)

    if config_dir is None:
        # 自动推导: strategy_core/utils -> strategy_core -> strategies/{strategy_name}
        config_dir = Path(__file__).parent.parent.parent / "strategies" / strategy_name

    # 如果指定了环境，优先加载环境配置
    if env:
        env_config_path = config_dir / f"config.{env}.yaml"
        if env_config_path.exists():
            try:
                with open(env_config_path, "r", encoding="utf-8") as f:
                    full_config = yaml.safe_load(f) or {}
                logger.debug(f"加载策略配置: {env_config_path} (env={env})")
                return full_config.get(strategy_name, {})
            except Exception as e:
                logger.warning(f"加载配置失败 {env_config_path}: {e}")

    # 回退到默认配置
    default_config_path = config_dir / "config.yaml"
    if default_config_path.exists():
        try:
            with open(default_config_path, "r", encoding="utf-8") as f:
                full_config = yaml.safe_load(f) or {}
            logger.debug(f"加载策略配置 (默认): {default_config_path}")
            return full_config.get(strategy_name, {})
        except Exception as e:
            logger.warning(f"加载配置失败 {default_config_path}: {e}")

    logger.warning(f"未找到策略配置: {strategy_name}" + (f" (env={env})" if env else ""))
    return {}
