"""布林带指标"""

from typing import Any, Dict, List

import pandas as pd

from .base import BaseIndicator


class BollingerBandsIndicator(BaseIndicator):
    """布林带 (Bollinger Bands) 指标"""

    name = "BB"
    yaxis = "y"  # 与K线共享Y轴
    domain = None

    def __init__(self, period: int = 20, std_dev: float = 2.0):
        self.period = period
        self.std_dev = std_dev

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df["bb_middle"] = df["close"].rolling(window=self.period).mean()
        std = df["close"].rolling(window=self.period).std()
        df["bb_upper"] = df["bb_middle"] + self.std_dev * std
        df["bb_lower"] = df["bb_middle"] - self.std_dev * std
        return df

    def get_traces(self, data: Dict[str, Any], colors: Dict[str, str]) -> List[Dict]:
        return [
            {
                "x": data["timestamps"],
                "y": data["bb_upper"],
                "type": "scatter",
                "mode": "lines",
                "name": "BB Upper",
                "line": {"color": colors.get("bb_line", "blue"), "width": 1, "dash": "dot"},
                "xaxis": "x",
                "yaxis": "y",
            },
            {
                "x": data["timestamps"],
                "y": data["bb_middle"],
                "type": "scatter",
                "mode": "lines",
                "name": "BB Middle",
                "line": {"color": colors.get("bb_line", "blue"), "width": 1},
                "xaxis": "x",
                "yaxis": "y",
            },
            {
                "x": data["timestamps"],
                "y": data["bb_lower"],
                "type": "scatter",
                "mode": "lines",
                "name": "BB Lower",
                "line": {"color": colors.get("bb_line", "blue"), "width": 1, "dash": "dot"},
                "xaxis": "x",
                "yaxis": "y",
                "fill": "tonexty",
                "fillcolor": "rgba(0, 0, 255, 0.1)",
            },
        ]