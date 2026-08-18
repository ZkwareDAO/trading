"""策略命名工具 — 唯一权威 strategy_id 生成

对外仅暴露 build_strategy_id_from_overrides。
prefix 由 strategy_dir 推导（内部 _extract_name_prefix），不再依赖 STRATEGY_PREFIX / AST。
"""

import re
from typing import Optional


def get_mode_suffix(trading_mode: str) -> str:
    """
    获取 trading_mode 的缩写后缀

    Args:
        trading_mode: 运行模式 (live / paper_trading / smoking / backtest)

    Returns:
        缩写后缀 (LIVE / PAPER / SMOKING / BACKTEST)
    """
    mode_map = {
        "live": "LIVE",
        "paper_trading": "PAPER",
        "smoking": "SMOKING",
        "backtest": "BACKTEST",
    }
    return mode_map.get(trading_mode.lower(), "LIVE")


def _extract_name_prefix(name: str) -> str:
    """
    从策略目录名提取前缀（私有，仅 build_strategy_id_from_overrides 调用）

    规则：
    - 去掉 cta_ 前缀
    - 去掉末尾版本后缀 (_trading_v\d+ / _v\d+)  —— 见源码正则 r'(_trading_v\d+|_v\d+)$'
    - 去掉所有下划线并大写
    - cta_ict_v3 → ICT
    - dolphin_trading_v2 → DOLPHIN
    - obv_atr_v2 → OBVATR
    - sar_snt3_v3 → SARSNT3
    - cta_rbreaker_v3 → RBREAKER
    """
    if name.startswith("cta_"):
        name = name[4:]

    name = re.sub(r'(_trading_v\d+|_v\d+)$', '', name)

    return name.replace("_", "").upper()


def _normalize_version(version: str) -> str:
    """版本号规范化：去 v/V 前缀后大写。v3/V3/3 → 3"""
    return str(version).lstrip("vV").upper()


def build_strategy_id_from_overrides(
    strategy_dir: str,
    symbol: str,
    trading_mode: str = "live",
    interval: Optional[str] = None,
    version: Optional[str] = None,
) -> str:
    """
    唯一权威 strategy_id 生成函数

    所有路径（日志文件名、信号 CSV 目录、仓位持久化、历史仓位、止损冷却）
    均收口到此函数。prefix 由 strategy_dir 推导，不依赖 STRATEGY_PREFIX 或 AST。

    Args:
        strategy_dir: 策略目录名 (如 "sar_snt3_v3", "obv_atr_v2")
        symbol: 交易对 (如 "BTCUSDT")
        trading_mode: 运行模式 (live / paper_trading / smoking)
        interval: 主周期 (如 "4h", "15m")，未传回退 "1h"
        version: 版本号 (如 "v2", "3")，未传回退 "1"

    Returns:
        标准化 strategy_id: {PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}_{MODE}
        例如: sar_snt3_v3/BTCUSDT/4h/3/paper_trading → SARSNT3_4H_3_BTCUSDT_PAPER
    """
    prefix = _extract_name_prefix(strategy_dir)
    tf = (interval or "1h").upper()
    ver = _normalize_version(version or "1")
    return f"{prefix}_{tf}_{ver}_{symbol.upper()}_{get_mode_suffix(trading_mode)}"
