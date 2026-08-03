"""RSI 指标"""

from typing import Any, Dict, List

import pandas as pd

from .base import BaseIndicator


class RSIndicator(BaseIndicator):
    """RSI (Relative Strength Index) 相对强弱指标"""

    name = "RSI"
    yaxis = "y4"
    domain = [0.08, 0.22]

    def __init__(self, period: int = 14):
        self.period = period

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.rolling(window=self.period).mean()
        avg_loss = loss.rolling(window=self.period).mean()
        rs = avg_gain / avg_loss
        df["rsi"] = 100 - (100 / (1 + rs))
        return df

    def get_traces(self, data: Dict[str, Any], colors: Dict[str, str]) -> List[Dict]:
        return [
            {
                "x": data["timestamps"],
                "y": data["rsi"],
                "type": "scatter",
                "mode": "lines",
                "name": f"RSI({self.period})",
                "line": {"color": colors.get("rsi_line", "purple"), "width": 1.5},
                "xaxis": "x",
                "yaxis": self.yaxis,
            },
            {
                "x": data["timestamps"],
                "y": [70] * len(data["timestamps"]),
                "type": "scatter",
                "mode": "lines",
                "name": "Overbought",
                "line": {"color": "red", "width": 1, "dash": "dash"},
                "xaxis": "x",
                "yaxis": self.yaxis,
                "hoverinfo": "skip",
            },
            {
                "x": data["timestamps"],
                "y": [30] * len(data["timestamps"]),
                "type": "scatter",
                "mode": "lines",
                "name": "Oversold",
                "line": {"color": "green", "width": 1, "dash": "dash"},
                "xaxis": "x",
                "yaxis": self.yaxis,
                "hoverinfo": "skip",
            },
        ]