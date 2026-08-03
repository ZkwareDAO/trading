"""策略命名工具 — 生成标准化 strategy_id"""

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


def extract_name_prefix(name: str) -> str:
    """
    从策略目录名提取前缀

    规则：
    - cta_ict_v2 → ICT
    - dolphin_trading_v2 → DOLPHIN
    - obv_atr_v2 → OBVATR
    - cta_rbreaker_v2 → RBREAKER
    """
    if name.startswith("cta_"):
        name = name[4:]

    name = re.sub(r'(_trading_v\d+|_v\d+)$', '', name)

    return name.replace("_", "").upper()


def build_strategy_name(
    prefix: str,
    version: str,
    interval: str,
    symbol: str,
) -> str:
    """
    生成策略名称（不含 trading_mode）

    格式: {PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}

    Args:
        prefix:   策略前缀 (如 "ICT", "RBREAKER")
        version:  版本号 (如 "v2", "3") - 会去掉 v/V 前缀
        interval: 时间周期 (如 "4h", "15m")
        symbol:   交易对 (如 "BTCUSDT")
    """
    version_num = version.lstrip("vV").upper()
    return f"{prefix.upper()}_{interval.upper()}_{version_num}_{symbol.upper()}"


def build_strategy_id(
    name: str,
    interval: str,
    version: str,
    symbol: str,
    trading_mode: str = "live",
) -> str:
    """
    生成标准化策略 ID（含 trading_mode）

    格式: {PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}_{MODE}
    例如: ICT_4H_2_BTCUSDT_LIVE

    Args:
        name: 策略目录名 (如 "cta_ict_v3")
        interval: 时间周期 (如 "4h", "1d")
        version: 版本号 (如 "v2", "3") - 会去掉 v/V 前缀
        symbol: 交易对 (如 "BTCUSDT")
        trading_mode: 运行模式 (live / paper_trading / smoking / backtest)
    """
    prefix = extract_name_prefix(name)
    mode_suffix = get_mode_suffix(trading_mode)
    version_num = version.lstrip("vV").upper()
    return f"{prefix}_{interval.upper()}_{version_num}_{symbol.upper()}_{mode_suffix}"
