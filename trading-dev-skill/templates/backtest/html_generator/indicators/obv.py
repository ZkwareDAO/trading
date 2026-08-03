"""OBV 指标"""

from typing import Any, Dict, List

import numpy as np
import pandas as pd

from .base import BaseIndicator


class OBVIndicator(BaseIndicator):
    """OBV (On-Balance Volume) 指标"""

    name = "OBV"
    yaxis = "y2"
    domain = [0.30, 0.48]

    def __init__(self, ma_period: int = 20):
        self.ma_period = ma_period

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        obv = (np.sign(df["close"].diff()) * df["volume"]).fillna(0).cumsum()
        df["obv"] = obv
        df["obv_ma"] = obv.rolling(window=self.ma_period).mean()
        return df

    def get_traces(self, data: Dict[str, Any], colors: Dict[str, str]) -> List[Dict]:
        return [
            {
                "x": data["timestamps"],
                "y": data["obv"],
                "type": "scatter",
                "mode": "lines",
                "name": "OBV",
                "line": {"color": colors.get("obv_line", "purple"), "width": 1},
                "xaxis": "x",
                "yaxis": self.yaxis,
            },
            {
                "x": data["timestamps"],
                "y": data["obv_ma"],
                "type": "scatter",
                "mode": "lines",
                "name": f"OBV MA({self.ma_period})",
                "line": {"color": colors.get("ma_line", "orange"), "width": 1.5, "dash": "dash"},
                "xaxis": "x",
                "yaxis": self.yaxis,
            },
            # 多头填充
            {
                "x": data["timestamps"],
                "y": [v if v > data["obv_ma"][i] else data["obv_ma"][i] for i, v in enumerate(data["obv"])],
                "type": "scatter",
                "mode": "lines",
                "fill": "tonexty",
                "fillcolor": colors.get("obv_bullish_fill", "rgba(76, 175, 80, 0.3)"),
                "line": {"width": 0},
                "xaxis": "x",
                "yaxis": self.yaxis,
                "showlegend": False,
                "hoverinfo": "skip",
            },
            # 空头填充
            {
                "x": data["timestamps"],
                "y": [v if v < data["obv_ma"][i] else data["obv_ma"][i] for i, v in enumerate(data["obv"])],
                "type": "scatter",
                "mode": "lines",
                "fill": "tonexty",
                "fillcolor": colors.get("obv_bearish_fill", "rgba(244, 67, 54, 0.3)"),
                "line": {"width": 0},
                "xaxis": "x",
                "yaxis": self.yaxis,
                "showlegend": False,
                "hoverinfo": "skip",
            },
        ]
