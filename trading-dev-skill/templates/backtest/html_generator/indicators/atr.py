"""ATR 指标"""

from typing import Any, Dict, List

import pandas as pd

from .base import BaseIndicator


class ATRIndicator(BaseIndicator):
    """ATR (Average True Range) 指标 - 波动率指标"""

    name = "ATR"
    yaxis = "y_atr"
    domain = None  # 动态分配

    def __init__(self, period: int = 14):
        self.period = period

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        high = df["high"]
        low = df["low"]
        close = df["close"]

        # True Range = max(H-L, |H-C_prev|, |L-C_prev|)
        tr = pd.concat(
            [high - low, abs(high - close.shift(1)), abs(low - close.shift(1))], axis=1
        ).max(axis=1)

        # ATR = SMA(TR, period)
        df["atr"] = tr.rolling(window=self.period).mean()
        return df

    def get_traces(self, data: Dict[str, Any], colors: Dict[str, str]) -> List[Dict]:
        return [
            {
                "x": data["timestamps"],
                "y": data["atr"],
                "type": "scatter",
                "mode": "lines",
                "name": f"ATR({self.period})",
                "line": {"color": colors.get("atr_line", "#FF6B00"), "width": 1.5},
                "xaxis": "x",
                "yaxis": self.yaxis,
            },
        ]