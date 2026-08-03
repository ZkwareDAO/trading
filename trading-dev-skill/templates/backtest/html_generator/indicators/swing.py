"""Swing Point 波段高低点指标"""

from typing import Any, Dict, List

import pandas as pd

from .base import BaseIndicator


class SwingIndicator(BaseIndicator):
    """Swing Point 波段高低点指标

    Swing High: K线高点 > 周围 lookback 根K线的高点
    Swing Low: K线低点 < 周围 lookback 根K线的低点
    """

    name = "Swing"
    yaxis = "y"  # 与K线共享Y轴
    domain = None  # 不占独立区域

    def __init__(self, lookback: int = 5):
        """
        Args:
            lookback: 回溯窗口，默认5
        """
        self.lookback = lookback

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """检测 Swing Points"""
        df = df.copy()

        swing_highs = []  # [{timestamp, price, bar_index}, ...]
        swing_lows = []

        lookback = self.lookback
        start_idx = lookback
        end_idx = len(df) - lookback

        for i in range(start_idx, end_idx):
            k = df.iloc[i]
            neighbors_h = [df.iloc[i + j]["high"] for j in range(-lookback, lookback + 1) if j != 0]
            neighbors_l = [df.iloc[i + j]["low"] for j in range(-lookback, lookback + 1) if j != 0]

            timestamp = k["timestamp"]
            ts_str = timestamp.strftime("%Y-%m-%d %H:%M") if hasattr(timestamp, 'strftime') else str(timestamp)

            if k["high"] > max(neighbors_h):
                swing_highs.append({
                    "time": ts_str,
                    "price": float(k["high"]),
                    "bar_index": i,
                })

            if k["low"] < min(neighbors_l):
                swing_lows.append({
                    "time": ts_str,
                    "price": float(k["low"]),
                    "bar_index": i,
                })

        df.attrs["swing_highs"] = swing_highs
        df.attrs["swing_lows"] = swing_lows
        return df

    def get_traces(self, data: Dict[str, Any], colors: Dict[str, str]) -> List[Dict]:
        """返回 Swing Points 标记"""
        traces = []

        # Swing Highs (向上三角形)
        for swing in data.get("swing_highs", []):
            traces.append({
                "x": [swing["time"]],
                "y": [swing["price"]],
                "type": "scatter",
                "mode": "markers",
                "name": "Swing High",
                "text": f"HH {swing['price']:.4f}",
                "hoverinfo": "text",
                "marker": {
                    "symbol": "triangle-up",
                    "size": 10,
                    "color": "green",
                    "line": {"width": 1, "color": "darkgreen"},
                },
                "xaxis": "x",
                "yaxis": "y",
                "showlegend": False,
            })

        # Swing Lows (向下三角形)
        for swing in data.get("swing_lows", []):
            traces.append({
                "x": [swing["time"]],
                "y": [swing["price"]],
                "type": "scatter",
                "mode": "markers",
                "name": "Swing Low",
                "text": f"LL {swing['price']:.4f}",
                "hoverinfo": "text",
                "marker": {
                    "symbol": "triangle-down",
                    "size": 10,
                    "color": "red",
                    "line": {"width": 1, "color": "darkred"},
                },
                "xaxis": "x",
                "yaxis": "y",
                "showlegend": False,
            })

        return traces
