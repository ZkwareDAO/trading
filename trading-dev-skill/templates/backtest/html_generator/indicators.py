"""技术指标计算"""

from typing import Tuple

import numpy as np
import pandas as pd

from .config import INDICATOR_PARAMS


def compute_obv(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series]:
    """计算 OBV 指标，返回 (obv, obv_ma)"""
    period = INDICATOR_PARAMS["obv_ma_period"]
    obv = (np.sign(df["close"].diff()) * df["volume"]).fillna(0).cumsum()
    obv_ma = obv.rolling(window=period).mean()
    return obv, obv_ma


def compute_adx(df: pd.DataFrame) -> pd.Series:
    """计算 ADX 指标"""
    period = INDICATOR_PARAMS["adx_period"]
    high, low, close = df["high"], df["low"], df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0

    tr = pd.concat([high - low, abs(high - close.shift(1)), abs(low - close.shift(1))], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
    minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)
    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
    return dx.rolling(window=period).mean()


def compute_price_ma(df: pd.DataFrame) -> pd.Series:
    """计算价格均线"""
    return df["close"].rolling(window=INDICATOR_PARAMS["price_ma_period"]).mean()


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """添加所有技术指标到 DataFrame"""
    df = df.copy()
    df["obv"], df["obv_ma"] = compute_obv(df)
    df["adx"] = compute_adx(df)
    df["price_ma"] = compute_price_ma(df)
    return df