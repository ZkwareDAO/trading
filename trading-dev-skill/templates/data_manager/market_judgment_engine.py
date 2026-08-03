#!/usr/bin/env python3
"""
市场状态判断引擎 - Market Judgment Engine

功能:
根据多周期 (1d/4h/15m) 指标一致性，判断市场类型和方向

市场类型:
- trend_market: 多周期趋势一致
- ranging_market: 震荡市场

方向:
- bullish: 看涨
- bearish: 看跌
- ranging: 震荡
"""

from dataclasses import dataclass
from typing import Dict, Optional, List, Tuple
import pandas as pd


@dataclass
class MarketState:
    """
    市场状态数据类
    """
    market_type: str = "ranging_market"
    direction: str = "ranging"
    confidence: float = 0.0
    primary_timeframes: Optional[List[str]] = None
    details: Optional[Dict[str, Dict]] = None

    def __post_init__(self):
        if self.primary_timeframes is None:
            self.primary_timeframes = []
        if self.details is None:
            self.details = {}


class MarketJudgmentEngine:
    """
    市场状态判断引擎

    判断规则:
    - 1d/4h/15m 三者 ADX 都 > 阈值 且方向一致 → trend_market
    - 否则 → ranging_market
    """

    def __init__(
        self,
        primary_timeframes: Optional[List[str]] = None,
        adx_trend_threshold: float = 25.0,
        rsi_bullish_threshold: float = 50.0,
        rsi_bearish_threshold: float = 50.0,
    ):
        """
        初始化引擎

        Args:
            primary_timeframes: 用于判断的主要周期列表
            adx_trend_threshold: ADX 趋势阈值
            rsi_bullish_threshold: RSI 看涨阈值
            rsi_bearish_threshold: RSI 看跌阈值
        """
        self.primary_timeframes = primary_timeframes or ["1d", "4h", "15m"]
        self.adx_trend_threshold = adx_trend_threshold
        self.rsi_bullish_threshold = rsi_bullish_threshold
        self.rsi_bearish_threshold = rsi_bearish_threshold

    def judge_timeframe(
        self,
        adx: Optional[float],
        plus_di: Optional[float],
        minus_di: Optional[float],
        rsi: Optional[float],
    ) -> Dict[str, any]:
        """
        判断单个周期的状态

        Args:
            adx: ADX 值
            plus_di: +DI 值
            minus_di: -DI 值
            rsi: RSI 值

        Returns:
            {direction: str, is_trending: bool}
        """
        result = {"direction": "ranging", "is_trending": False}

        if adx is None or plus_di is None or minus_di is None:
            return result

        is_trending = adx > self.adx_trend_threshold
        result["is_trending"] = is_trending

        if not is_trending:
            return result

        if plus_di > minus_di:
            result["direction"] = "bullish"
        elif minus_di > plus_di:
            result["direction"] = "bearish"
        else:
            result["direction"] = "ranging"

        return result

    def judge(
        self,
        indicators_by_timeframe: Dict[str, Dict[str, Optional[float]]]
    ) -> MarketState:
        """
        判断市场状态

        Args:
            indicators_by_timeframe: {timeframe: {adx, plus_di, minus_di, rsi}}

        Returns:
            MarketState 市场状态
        """
        details = {}
        bullish_count = 0
        bearish_count = 0
        trending_count = 0

        for tf in self.primary_timeframes:
            if tf not in indicators_by_timeframe:
                continue

            indicators = indicators_by_timeframe[tf]
            adx = indicators.get("adx")
            plus_di = indicators.get("plus_di")
            minus_di = indicators.get("minus_di")
            rsi = indicators.get("rsi")

            tf_state = self.judge_timeframe(adx, plus_di, minus_di, rsi)
            details[tf] = {
                "adx": adx,
                "plus_di": plus_di,
                "minus_di": minus_di,
                "rsi": rsi,
                "direction": tf_state["direction"],
                "is_trending": tf_state["is_trending"],
            }

            if tf_state["direction"] == "bullish":
                bullish_count += 1
            elif tf_state["direction"] == "bearish":
                bearish_count += 1

            if tf_state["is_trending"]:
                trending_count += 1

        all_trending = trending_count == len(self.primary_timeframes)
        all_same_direction = bullish_count == len(self.primary_timeframes) or bearish_count == len(self.primary_timeframes)

        if all_trending and all_same_direction:
            market_type = "trend_market"
            direction = "bullish" if bullish_count > bearish_count else "bearish"
            confidence = 1.0
        else:
            market_type = "ranging_market"
            if bullish_count > bearish_count:
                direction = "bullish"
            elif bearish_count > bullish_count:
                direction = "bearish"
            else:
                direction = "ranging"
            confidence = trending_count / len(self.primary_timeframes) if self.primary_timeframes else 0.0

        return MarketState(
            market_type=market_type,
            direction=direction,
            confidence=confidence,
            primary_timeframes=self.primary_timeframes,
            details=details,
        )

    def calculate_market_state_for_row(
        self,
        row_ts: pd.Timestamp,
        df_1d: pd.DataFrame,
        df_4h: pd.DataFrame,
        df_15m: pd.DataFrame
    ) -> Tuple[str, str]:
        """
        为指定时间点计算市场状态

        Args:
            row_ts: 当前时间点
            df_1d: 1d 数据
            df_4h: 4h 数据
            df_15m: 15m 数据

        Returns:
            (market_type, direction) 元组
        """
        def get_latest_indicator(df: pd.DataFrame, ts: pd.Timestamp) -> dict:
            mask = df["timestamp"] <= ts
            df_filtered = df[mask]
            if df_filtered.empty:
                return {"adx": None, "plus_di": None, "minus_di": None, "rsi": None}
            last_row = df_filtered.iloc[-1]
            return {
                "adx": last_row.get("adx"),
                "plus_di": last_row.get("plus_di"),
                "minus_di": last_row.get("minus_di"),
                "rsi": last_row.get("rsi"),
            }

        indicators_1d = get_latest_indicator(df_1d, row_ts)
        indicators_4h = get_latest_indicator(df_4h, row_ts)
        indicators_15m = get_latest_indicator(df_15m, row_ts)

        indicators_by_timeframe = {
            "1d": indicators_1d,
            "4h": indicators_4h,
            "15m": indicators_15m,
        }

        state = self.judge(indicators_by_timeframe)
        return state.market_type, state.direction


def load_timeframe_data(
    symbol: str,
    timeframe: str,
    data_dir: str = "./data/strategies/market_research"
) -> pd.DataFrame:
    """
    加载时间框架数据

    Args:
        symbol: 交易对
        timeframe: 时间框架
        data_dir: 数据目录

    Returns:
        DataFrame with timestamp parsed
    """
    from pathlib import Path
    filepath = Path(data_dir) / f"{symbol}_{timeframe}.csv"
    df = pd.read_csv(filepath)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def update_csv_with_market_state(
    symbol: str,
    timeframe: str,
    df_1d: pd.DataFrame,
    df_4h: pd.DataFrame,
    df_15m: pd.DataFrame,
    data_dir: str = "./data/strategies/market_research",
    engine: Optional[MarketJudgmentEngine] = None,
) -> Dict[str, int]:
    """
    为 CSV 文件添加 market_type 和 direction 列

    Args:
        symbol: 交易对
        timeframe: 时间框架
        df_1d: 1d 数据（用于判断）
        df_4h: 4h 数据（用于判断）
        df_15m: 15m 数据（用于判断）
        data_dir: 数据目录
        engine: MarketJudgmentEngine 实例

    Returns:
        统计结果 {trend_market: count, bullish: count, ...}
    """
    from pathlib import Path

    if engine is None:
        engine = MarketJudgmentEngine()

    filepath = Path(data_dir) / f"{symbol}_{timeframe}.csv"
    if not filepath.exists():
        return {}

    df = pd.read_csv(filepath)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

    trend_markets = []
    directions = []

    for idx, row in df.iterrows():
        tm, d = engine.calculate_market_state_for_row(row["timestamp"], df_1d, df_4h, df_15m)
        trend_markets.append(tm)
        directions.append(d)

    df["trend_market"] = trend_markets
    df["direction"] = directions

    save_df = df.copy()
    if save_df["timestamp"].dt.tz is not None:
        save_df["timestamp"] = save_df["timestamp"].dt.tz_convert("UTC")
    else:
        save_df["timestamp"] = save_df["timestamp"].dt.tz_localize("UTC")
    save_df["timestamp"] = save_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S+00:00")
    save_df.to_csv(filepath, index=False)

    return {
        "trend_market": sum(1 for t in trend_markets if t == "trend_market"),
        "ranging_market": sum(1 for t in trend_markets if t == "ranging_market"),
        "bullish": sum(1 for d in directions if d == "bullish"),
        "bearish": sum(1 for d in directions if d == "bearish"),
        "ranging": sum(1 for d in directions if d == "ranging"),
        "total": len(df),
    }
