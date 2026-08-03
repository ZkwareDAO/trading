#!/usr/bin/env python3
"""
通用技术指标计算工具

提供策略共享的指标计算函数，避免各策略重复实现。
"""

import logging
from typing import Dict, List, Optional

import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

# 尝试导入 TA-Lib
try:
    import talib
    TALIB_AVAILABLE = True
except ImportError:
    TALIB_AVAILABLE = False


def calculate_adx(
    df: pd.DataFrame,
    period: int = 14,
    fallback_state: Optional[Dict[str, Optional[float]]] = None,
) -> Optional[float]:
    """
    计算 ADX 值

    优先使用 TA-Lib，不可用时回退到手动 EMA 计算。

    Args:
        df: 包含 high/low/close 列的 DataFrame
        period: ADX 周期
        fallback_state: 手动 ADX 的 EMA 中间状态字典（含 tr_ema, plus_dm_ema, minus_dm_ema, dx_ema）
            传入时会被更新并用于增量计算。

    Returns:
        ADX 值，数据不足返回 None
    """
    if len(df) < period + 10:
        return None

    # 优先使用 TA-Lib
    if TALIB_AVAILABLE:
        try:
            highs = df["high"].values[-50:]
            lows = df["low"].values[-50:]
            closes = df["close"].values[-50:]

            adx = talib.ADX(highs, lows, closes, timeperiod=period)

            if len(adx) > 0 and not np.isnan(adx[-1]):
                return float(adx[-1])
        except Exception as e:
            logger.debug(f"ADX 计算失败 (TA-Lib): {e}")

    # 回退到手动计算
    return _calculate_adx_manual(df, period, fallback_state)


def _calculate_adx_manual(
    df: pd.DataFrame,
    period: int,
    state: Optional[Dict[str, Optional[float]]] = None,
) -> Optional[float]:
    """手动计算 ADX（EMA 平滑）"""
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values
    n = len(closes)

    if n < period + 1:
        return None

    alpha = 2.0 / (period + 1)
    tr_vals = []
    plus_dm_vals = []
    minus_dm_vals = []

    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]

        plus_dm = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm = down_move if (down_move > up_move and down_move > 0) else 0.0

        tr_vals.append(tr)
        plus_dm_vals.append(plus_dm)
        minus_dm_vals.append(minus_dm)

    if len(tr_vals) < period:
        return None

    # 初始化 EMA
    tr_ema = sum(tr_vals[:period]) / period
    plus_dm_ema = sum(plus_dm_vals[:period]) / period
    minus_dm_ema = sum(minus_dm_vals[:period]) / period

    dx_vals = []
    for i in range(period, len(tr_vals)):
        tr_ema = alpha * tr_vals[i] + (1 - alpha) * tr_ema
        plus_dm_ema = alpha * plus_dm_vals[i] + (1 - alpha) * plus_dm_ema
        minus_dm_ema = alpha * minus_dm_vals[i] + (1 - alpha) * minus_dm_ema

        if tr_ema > 0:
            di_plus = plus_dm_ema / tr_ema * 100
            di_minus = minus_dm_ema / tr_ema * 100
            di_sum = di_plus + di_minus
            dx = abs(di_plus - di_minus) / di_sum * 100 if di_sum > 0 else 0.0
            dx_vals.append(dx)

    if not dx_vals:
        return None

    # 平滑 DX 得到 ADX
    if len(dx_vals) >= period:
        dx_ema = sum(dx_vals[:period]) / period
        for dx in dx_vals[period:]:
            dx_ema = alpha * dx + (1 - alpha) * dx_ema
    else:
        dx_ema = sum(dx_vals) / len(dx_vals)

    # 更新外部状态（如果提供）
    if state is not None:
        state["tr_ema"] = tr_ema
        state["plus_dm_ema"] = plus_dm_ema
        state["minus_dm_ema"] = minus_dm_ema
        state["dx_ema"] = dx_ema

    return dx_ema


def calculate_bollinger(
    closes: List[float],
    period: int = 20,
    multiplier: float = 2.0,
) -> tuple:
    """
    计算 Bollinger Bands

    Args:
        closes: 收盘价列表
        period: 周期
        multiplier: 标准差倍数

    Returns:
        (upper, middle, lower) 或 (0, 0, 0) 数据不足时
    """
    n = len(closes)
    if n < period:
        return 0.0, 0.0, 0.0

    from math import sqrt

    recent = closes[-period:]
    mean = sum(recent) / period
    variance = sum((c - mean) ** 2 for c in recent) / period
    std = sqrt(variance)

    return mean + multiplier * std, mean, mean - multiplier * std
