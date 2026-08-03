#!/usr/bin/env python3
"""
技术指标计算模块

基于 ta-lib 库实现（主要），pandas 辅助 ewm 方法：
- ADX / DI+ / DI-（趋势强度）
- EMA / SMA（移动平均线）
- RSI（相对强弱指标）
- MACD（指数平滑异同移动平均线）
- BOLL（布林带）
- ATR（平均真实波幅）
- KD / KDJ（随机指标）
- Envelope（均线包络通道）
- VPVR（可见区成交量分布）

ta-lib 优势：
- C 语言实现，性能优异
- 支持所有 Python 版本（无 numba 依赖）
- 行业标准，交易所广泛使用
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import warnings

import numpy as np
import pandas as pd
import talib


def _empty_result(columns: List[str]) -> pd.DataFrame:
    """返回空 DataFrame"""
    return pd.DataFrame(columns=columns)


def _as_float(arr: np.ndarray) -> np.ndarray:
    """确保数组为 float 类型（ta-lib 要求）"""
    return arr.astype(float)


def _dropna_rows(df: pd.DataFrame) -> pd.DataFrame:
    """移除全为 NaN 的行，保留部分 NaN 的行"""
    return df.dropna(how="all")


def _warn_insufficient_data(indicator: str, min_rows: int, actual: int) -> None:
    """发出数据量不足警告"""
    warnings.warn(
        f"{indicator} 计算建议至少需要 {min_rows} 根 K 线，"
        f"当前仅有 {actual} 根，计算值可能与交易所不一致",
        UserWarning,
        stacklevel=3,
    )


def compute_adx(
    df: pd.DataFrame, period: int = 14, method: str = "wilder"
) -> pd.DataFrame:
    """
    计算 ADX 指标

    **重要**: ADX 需要足够长的历史数据才能收敛到正确值。
    建议至少传入 100+ 根 K 线，理想情况下应使用完整历史数据。
    只传最近 N 根 K 线会导致 ADX 值严重偏离实际值。

    Args:
        df: 包含 high, low, close 列的 DataFrame（建议使用完整历史数据）
        period: 计算周期，默认 14
        method: 平滑方法，可选 "wilder"（默认）或 "ewm"

    Returns:
        包含 adx, di_plus, di_minus 列的 DataFrame

    Raises:
        ValueError: 数据量不足（建议最少 100 根 K 线）
    """
    if method not in ("wilder", "ewm"):
        raise ValueError(f"无效的 method '{method}'，可选: 'wilder', 'ewm'")

    # 最小数据量检查（技术指标需要足够历史数据才能收敛）
    MIN_ROWS = 100
    if df.empty:
        return _empty_result(["adx", "di_plus", "di_minus"])

    if len(df) < MIN_ROWS:
        _warn_insufficient_data("ADX", MIN_ROWS, len(df))

    if len(df) < period + 1:
        return _empty_result(["adx", "di_plus", "di_minus"])

    high = _as_float(df["high"].values)
    low = _as_float(df["low"].values)
    close = _as_float(df["close"].values)

    adx = talib.ADX(high, low, close, timeperiod=period)
    plus_di = talib.PLUS_DI(high, low, close, timeperiod=period)
    minus_di = talib.MINUS_DI(high, low, close, timeperiod=period)

    if method == "ewm":
        adx = pd.Series(adx).ewm(span=period, adjust=False).mean().values

    result = pd.DataFrame({"adx": adx, "di_plus": plus_di, "di_minus": minus_di})
    result = _dropna_rows(result)
    return result if not result.empty else _empty_result(["adx", "di_plus", "di_minus"])


def compute_ema(df: pd.DataFrame, column: str = "close", period: int = 20) -> pd.Series:
    """计算 EMA"""
    return pd.Series(talib.EMA(_as_float(df[column].values), timeperiod=period), index=df.index)


def compute_sma(df: pd.DataFrame, column: str = "close", period: int = 20) -> pd.Series:
    """计算 SMA"""
    return pd.Series(talib.SMA(_as_float(df[column].values), timeperiod=period), index=df.index)


def compute_rsi(
    df: pd.DataFrame, column: str = "close", period: int = 14, method: str = "wilder"
) -> pd.Series:
    """
    计算 RSI

    **重要**: RSI 需要足够长的历史数据才能收敛。
    建议至少传入 period*3 根 K 线，理想情况下使用完整历史数据。
    数据量不足会导致 RSI 值偏离实际值。

    Args:
        df: 包含价格列的 DataFrame（建议使用完整历史数据）
        column: 价格列名，默认 close
        period: 计算周期，默认 14
        method: 平滑方法，可选 "wilder"（默认）或 "ewm"

    Returns:
        RSI 序列
    """
    if method not in ("wilder", "ewm"):
        raise ValueError(f"无效的 method '{method}'，可选: 'wilder', 'ewm'")

    # 数据量警告
    MIN_ROWS = period * 3
    if len(df) < MIN_ROWS:
        _warn_insufficient_data("RSI", MIN_ROWS, len(df))

    close = _as_float(df[column].values)

    if method == "wilder":
        result = talib.RSI(close, timeperiod=period)
    else:
        delta = pd.Series(close).diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(span=period, adjust=False).mean()
        avg_loss = loss.ewm(span=period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.inf)
        result = (100 - (100 / (1 + rs))).values

    return pd.Series(result, index=df.index)


def compute_macd(
    df: pd.DataFrame, column: str = "close", fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """计算 MACD，返回包含 macd, signal, histogram 列的 DataFrame"""
    close = _as_float(df[column].values)
    macd, signal_line, histogram = talib.MACD(close, fastperiod=fast, slowperiod=slow, signalperiod=signal)
    return _dropna_rows(pd.DataFrame({"macd": macd, "signal": signal_line, "histogram": histogram}))


def compute_boll(
    df: pd.DataFrame, column: str = "close", period: int = 20, std_dev: float = 2.0
) -> pd.DataFrame:
    """计算布林带，返回包含 upper, middle, lower 列的 DataFrame"""
    close = _as_float(df[column].values)
    upper, middle, lower = talib.BBANDS(close, timeperiod=period, nbdevup=std_dev, nbdevdn=std_dev)
    return _dropna_rows(pd.DataFrame({"upper": upper, "middle": middle, "lower": lower}))


def _compute_kdj_ema(high: np.ndarray, low: np.ndarray, close: np.ndarray,
                      k_period: int, d_period: int, j_period: int) -> pd.DataFrame:
    """EMA 平滑方式计算 KDJ（交易所标准）"""
    length = len(close)
    rsv = np.full(length, 50.0)

    for i in range(k_period - 1, length):
        hh = max(high[i - k_period + 1 : i + 1])
        ll = min(low[i - k_period + 1 : i + 1])
        if hh != ll:
            rsv[i] = (close[i] - ll) / (hh - ll) * 100

    # K = EMA(RSV, d_period)
    alpha = 1.0 / d_period
    k = np.zeros(length)
    k[0] = rsv[0]
    for i in range(1, length):
        k[i] = alpha * rsv[i] + (1 - alpha) * k[i - 1]

    # D = EMA(K, d_period)
    d = np.zeros(length)
    d[0] = k[0]
    for i in range(1, length):
        d[i] = alpha * k[i] + (1 - alpha) * d[i - 1]

    j = j_period * k - (j_period - 1) * d
    result = pd.DataFrame({"k": k, "d": d, "j": j})
    return result.iloc[k_period - 1 :]


def compute_kd(
    df: pd.DataFrame, k_period: int = 9, d_period: int = 3, j_period: int = 3, smooth: str = "ema"
) -> pd.DataFrame:
    """
    计算 KD 随机指标

    **重要**: 交易所使用 EMA 平滑 (smooth="ema")，而非 SMA。
    EMA 平滑结果与交易所完全一致。

    Args:
        df: 包含 high, low, close 列的 DataFrame
        k_period: %K 周期，默认 9（交易所标准）
        d_period: %D 平滑周期，默认 3
        j_period: %J 系数，默认 3
        smooth: 平滑方式，"ema"（交易所标准）或 "sma"

    Returns:
        包含 k, d, j 列的 DataFrame
    """
    high = _as_float(df["high"].values)
    low = _as_float(df["low"].values)
    close = _as_float(df["close"].values)

    if smooth == "ema":
        result = _compute_kdj_ema(high, low, close, k_period, d_period, j_period)
        return result if not result.empty else _empty_result(["k", "d", "j"])

    # SMA 平滑 - ta-lib 默认方式
    k, d = talib.STOCH(
        high, low, close,
        fastk_period=k_period,
        slowk_period=d_period,
        slowk_matype=0,
        slowd_period=d_period,
        slowd_matype=0,
    )
    j = j_period * k - (j_period - 1) * d
    return _dropna_rows(pd.DataFrame({"k": k, "d": d, "j": j}))


def compute_envelope(
    df: pd.DataFrame, column: str = "close", period: int = 26,
    upper_pct: float = 0.618, lower_pct: float = 0.618
) -> pd.DataFrame:
    """
    计算均线通道（Envelope）

    Args:
        df: 包含价格列的 DataFrame
        column: 价格列名
        period: 均线周期
        upper_pct: 上轨偏移百分比，如 0.618 表示 0.618%（即 middle * 1.00618）
        lower_pct: 下轨偏移百分比，如 0.618 表示 0.618%（即 middle * 0.99382）

    Returns:
        包含 upper, middle, lower 列的 DataFrame

    Note:
        参数使用百分比格式，例如：
        - upper_pct=0.618 表示 0.618% 偏移
        - upper_pct=5 表示 5% 偏移
    """
    values = _as_float(df[column].values)
    middle = talib.SMA(values, timeperiod=period)
    return pd.DataFrame({
        "upper": middle * (1 + upper_pct / 100),
        "middle": middle,
        "lower": middle * (1 - lower_pct / 100)
    })


def compute_obv(df: pd.DataFrame) -> pd.Series:
    """计算 OBV"""
    return pd.Series(
        talib.OBV(_as_float(df["close"].values), _as_float(df["volume"].values)),
        index=df.index
    )


def compute_atr(
    df: pd.DataFrame, period: int = 14, method: str = "wilder"
) -> pd.Series:
    """
    计算 ATR

    **重要**: ATR 需要足够长的历史数据才能收敛。
    建议至少传入 period*3 根 K 线，理想情况下使用完整历史数据。
    数据量不足会导致 ATR 值偏离实际值。

    Args:
        df: 包含 high, low, close 列的 DataFrame（建议使用完整历史数据）
        period: 计算周期，默认 14
        method: 平滑方法，可选 "wilder"（默认）或 "ewm"

    Returns:
        ATR 序列
    """
    if method not in ("wilder", "ewm"):
        raise ValueError(f"无效的 method '{method}'，可选: 'wilder', 'ewm'")

    # 数据量警告
    MIN_ROWS = period * 3
    if len(df) < MIN_ROWS:
        _warn_insufficient_data("ATR", MIN_ROWS, len(df))

    high = _as_float(df["high"].values)
    low = _as_float(df["low"].values)
    close = _as_float(df["close"].values)

    if method == "wilder":
        result = talib.ATR(high, low, close, timeperiod=period)
    else:
        prev_close = np.roll(close, 1)
        prev_close[0] = close[0]
        tr = np.maximum(high - low, np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
        result = pd.Series(tr).ewm(span=period, adjust=False).mean().values

    return pd.Series(result, index=df.index)


# 注册表：指标名 -> 计算函数 + 默认参数
_INDICATOR_REGISTRY: Dict[str, dict] = {
    "adx": {
        "fn": compute_adx,
        "params": {"period": 14, "method": "wilder"},
        "requires": ["high", "low", "close"],
    },
    "ema": {
        "fn": compute_ema,
        "params": {"period": 20, "column": "close"},
        "requires": ["close"],
    },
    "sma": {
        "fn": compute_sma,
        "params": {"period": 20, "column": "close"},
        "requires": ["close"],
    },
    "rsi": {
        "fn": compute_rsi,
        "params": {"period": 14, "column": "close", "method": "wilder"},
        "requires": ["close"],
    },
    "macd": {
        "fn": compute_macd,
        "params": {"fast": 12, "slow": 26, "signal": 9, "column": "close"},
        "requires": ["close"],
    },
    "boll": {
        "fn": compute_boll,
        "params": {"period": 20, "std_dev": 2.0, "column": "close"},
        "requires": ["close"],
    },
    "atr": {
        "fn": compute_atr,
        "params": {"period": 14, "method": "wilder"},
        "requires": ["high", "low", "close"],
    },
    "kd": {
        "fn": compute_kd,
        "params": {"k_period": 9, "d_period": 3, "j_period": 3, "smooth": "ema"},
        "requires": ["high", "low", "close"],
    },
    "envelope": {
        "fn": compute_envelope,
        "params": {"period": 26, "upper_pct": 0.618, "lower_pct": 0.618, "column": "close"},
        "requires": ["close"],
    },
    "obv": {
        "fn": compute_obv,
        "params": {},
        "requires": ["close", "volume"],
    },
}


def get_available_indicators() -> List[str]:
    """获取所有可用指标名称"""
    return list(_INDICATOR_REGISTRY.keys())


def compute_indicator(
    name: str,
    df: pd.DataFrame,
    params: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """
    计算指定技术指标

    Args:
        name: 指标名称（adx, ema, sma, rsi, macd, boll, atr）
        df: K 线数据，须包含 high, low, close, volume 等列
        params: 可选参数，覆盖默认值

    Returns:
        指标结果的 DataFrame 或 Series

    Raises:
        ValueError: 指标不存在或缺少必要列
    """
    name = name.lower()
    if name not in _INDICATOR_REGISTRY:
        available = ", ".join(get_available_indicators())
        raise ValueError(
            f"未知指标 '{name}'。可用指标: {available}"
        )

    info = _INDICATOR_REGISTRY[name]

    # 验证必要列
    for col in info["requires"]:
        if col not in df.columns:
            raise ValueError(
                f"指标 '{name}' 需要列 '{col}'，但 DataFrame 中不存在"
            )

    # 合并参数
    kwargs = {**info["params"], **(params or {})}

    # 调用计算函数
    result = info["fn"](df, **kwargs)

    if isinstance(result, pd.Series):
        return result.to_frame(name=result.name if hasattr(result, 'name') else name)
    return result


# =============================================================================
# VPVR (Volume Profile Visible Range)
# =============================================================================


@dataclass
class VPVRProfile:
    """VPVR 成交量分布结果"""
    poc_price: float           # Point of Control：成交量最大的价格位
    vah: float                 # Value Area High
    val: float                 # Value Area Low
    high_prices: List[float]   # HVN 价格区间列表 [low, high, ...]
    low_prices: List[float]    # LVN 价格区间列表 [low, high, ...]
    all_bins: pd.Series        # 每个价格 bin 的成交量，index 为 bin 下限


def compute_volume_profile(
    df: pd.DataFrame,
    bin_count: int = 50,
    value_area_pct: float = 0.70,
) -> VPVRProfile:
    """
    计算 Volume Profile（可见区成交量分布）

    将价格范围划分为 bin_count 个区间，按成交量聚合，
    返回 POC、VAH、VAL、HVN/LVN 分布。

    Args:
        df: 包含 high, low, close, volume 列的 DataFrame
        bin_count: 价格区间分 bin 数
        value_area_pct: 价值区域百分比（默认 0.70 即 70%）

    Returns:
        VPVRProfile 实例

    Raises:
        ValueError: DataFrame 为空或缺少必要列
    """
    if df.empty or "close" not in df.columns or "volume" not in df.columns:
        raise ValueError("compute_volume_profile: 需要非空 DataFrame 且包含 close, volume 列")

    close = df["close"].values.astype(float)
    volume = df["volume"].values.astype(float)

    price_min = float(close.min())
    price_max = float(close.max())

    if price_max == price_min:
        price_max = price_min + 1e-8

    # 使用 numpy histogram 按价格分 bin，同时加权成交量
    bin_edges = np.linspace(price_min, price_max, bin_count + 1)
    bin_volumes = np.zeros(bin_count)

    for i in range(len(close)):
        price = close[i]
        # digitize 返回 bin 索引（从 1 开始），price_max 会返回 bin_count（越界）
        idx = int(np.digitize(price, bin_edges)) - 1
        idx = max(0, min(bin_count - 1, idx))
        bin_volumes[idx] += volume[i]

    all_bins = pd.Series(bin_volumes, index=pd.RangeIndex(0, bin_count))

    # POC：成交量最大的 bin 的中心价格
    poc_idx = int(all_bins.idxmax())
    poc_price = (bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2

    # 按成交量降序排序，累积计算价值区域
    sorted_indices = all_bins.sort_values(ascending=False).index.tolist()
    total_volume = float(all_bins.sum())

    if total_volume == 0:
        return VPVRProfile(
            poc_price=poc_price,
            vah=price_max,
            val=price_min,
            high_prices=[],
            low_prices=[],
            all_bins=all_bins,
        )

    cumulative = 0.0
    va_indices = set()
    for idx in sorted_indices:
        cumulative += all_bins.iloc[idx]
        va_indices.add(idx)
        if cumulative / total_volume >= value_area_pct:
            break

    # VAH / VAL：价值区域内价格的上下界
    va_prices = [(bin_edges[i] + bin_edges[i + 1]) / 2 for i in va_indices]
    vah = max(va_prices)
    val = min(va_prices)

    # HVN：成交量超过中位数 1.5 倍的 bin
    median_vol = float(all_bins.median())
    hvn_threshold = median_vol * 1.5 if median_vol > 0 else 0
    high_prices = []
    for i in range(bin_count):
        if all_bins.iloc[i] >= hvn_threshold:
            p = (bin_edges[i] + bin_edges[i + 1]) / 2
            high_prices.append(p)

    # LVN：成交量低于中位数 0.5 倍且成交量 > 0 的 bin
    lvn_threshold = median_vol * 0.5
    low_prices = []
    for i in range(bin_count):
        v = all_bins.iloc[i]
        if 0 < v < lvn_threshold:
            p = (bin_edges[i] + bin_edges[i + 1]) / 2
            low_prices.append(p)

    return VPVRProfile(
        poc_price=poc_price,
        vah=vah,
        val=val,
        high_prices=high_prices,
        low_prices=low_prices,
        all_bins=all_bins,
    )
