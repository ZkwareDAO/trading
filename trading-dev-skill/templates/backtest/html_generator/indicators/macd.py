"""MACD 指标"""

from typing import Any, Dict, List

import pandas as pd

from .base import BaseIndicator


class MACDIndicator(BaseIndicator):
    """MACD (Moving Average Convergence Divergence) 指标"""

    name = "MACD"
    yaxis = "y5"
    domain = [0.08, 0.22]

    def __init__(self, fast: int = 12, slow: int = 26, signal: int = 9):
        self.fast = fast
        self.slow = slow
        self.signal = signal

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        ema_fast = df["close"].ewm(span=self.fast).mean()
        ema_slow = df["close"].ewm(span=self.slow).mean()
        df["macd"] = ema_fast - ema_slow
        df["macd_signal"] = df["macd"].ewm(span=self.signal).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]
        return df

    def get_traces(self, data: Dict[str, Any], colors: Dict[str, str]) -> List[Dict]:
        return [
            {
                "x": data["timestamps"],
                "y": data["macd"],
                "type": "scatter",
                "mode": "lines",
                "name": "MACD",
                "line": {"color": colors.get("macd_line", "blue"), "width": 1.5},
                "xaxis": "x",
                "yaxis": self.yaxis,
            },
            {
                "x": data["timestamps"],
                "y": data["macd_signal"],
                "type": "scatter",
                "mode": "lines",
                "name": "Signal",
                "line": {"color": colors.get("macd_signal", "orange"), "width": 1.5},
                "xaxis": "x",
                "yaxis": self.yaxis,
            },
            {
                "x": data["timestamps"],
                "y": data["macd_hist"],
                "type": "bar",
                "name": "Histogram",
                "marker": {
                    "color": [
                        colors.get("macd_hist_pos", "green") if v >= 0 else colors.get("macd_hist_neg", "red")
                        for v in data["macd_hist"]
                    ]
                },
                "xaxis": "x",
                "yaxis": self.yaxis,
            },
        ]