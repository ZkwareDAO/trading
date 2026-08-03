"""ADX 指标"""

from typing import Any, Dict, List

import pandas as pd

from .base import BaseIndicator


class ADXIndicator(BaseIndicator):
    """ADX (Average Directional Index) 指标"""

    name = "ADX"
    yaxis = "y3"
    domain = [0.08, 0.25]

    def __init__(self, period: int = 14, threshold: int = 25):
        self.period = period
        self.threshold = threshold

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        high = df["high"]
        low = df["low"]
        close = df["close"]

        plus_dm = high.diff()
        minus_dm = -low.diff()
        plus_dm[plus_dm < 0] = 0
        minus_dm[minus_dm < 0] = 0

        tr = pd.concat(
            [high - low, abs(high - close.shift(1)), abs(low - close.shift(1))], axis=1
        ).max(axis=1)
        atr = tr.rolling(window=self.period).mean()
        plus_di = 100 * (plus_dm.rolling(window=self.period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=self.period).mean() / atr)
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        df["adx"] = dx.rolling(window=self.period).mean()
        df["plus_di"] = plus_di
        df["minus_di"] = minus_di
        return df

    def get_traces(self, data: Dict[str, Any], colors: Dict[str, str]) -> List[Dict]:
        return [
            {
                "x": data["timestamps"],
                "y": data["adx"],
                "type": "scatter",
                "mode": "lines",
                "name": "ADX",
                "line": {"color": colors.get("adx_line", "purple"), "width": 1.5},
                "xaxis": "x",
                "yaxis": self.yaxis,
            },
            {
                "x": data["timestamps"],
                "y": [self.threshold] * len(data["timestamps"]),
                "type": "scatter",
                "mode": "lines",
                "name": f"Threshold ({self.threshold})",
                "line": {"color": colors.get("adx_threshold", "red"), "width": 1, "dash": "dash"},
                "xaxis": "x",
                "yaxis": self.yaxis,
                "hoverinfo": "skip",
            },
        ]
