"""FVG (Fair Value Gap) 指标"""

from typing import Any, Dict, List

import pandas as pd

from .base import BaseIndicator


class FVGIndicator(BaseIndicator):
    """FVG (Fair Value Gap) 公允价值缺口指标"""

    name = "FVG"
    yaxis = "y"  # 与K线共享Y轴
    domain = None  # 不占独立区域

    def __init__(self, extend_bars: int = None):
        """
        Args:
            extend_bars: FVG 向后延伸K线数量，默认从配置读取
        """
        self.extend_bars = extend_bars

    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """检测 FVG 区域"""
        df = df.copy()

        # 从配置获取延伸数量
        extend_bars = self.extend_bars or 10

        # Bullish FVG: 第1根K线高点 < 第3根K线低点（向上跳空）
        # Bearish FVG: 第1根K线低点 > 第3根K线高点（向下跳空）
        fvg_bullish = []  # [{start_time, end_time, low, high}, ...]
        fvg_bearish = []

        for i in range(2, len(df)):
            # Bullish FVG: K1高点 < K3低点（向上跳空）
            # 区域从K2开始，向后延伸10根
            if df.iloc[i - 2]["high"] < df.iloc[i]["low"]:
                end_idx = min(i + extend_bars, len(df) - 1)
                fvg_bullish.append({
                    "start_time": df.iloc[i - 1]["timestamp"].strftime("%Y-%m-%d %H:%M") if hasattr(df.iloc[i - 1]["timestamp"], 'strftime') else str(df.iloc[i - 1]["timestamp"]),
                    "end_time": df.iloc[end_idx]["timestamp"].strftime("%Y-%m-%d %H:%M") if hasattr(df.iloc[end_idx]["timestamp"], 'strftime') else str(df.iloc[end_idx]["timestamp"]),
                    "low": float(df.iloc[i - 2]["high"]),   # 下边界：K1高点
                    "high": float(df.iloc[i]["low"]),       # 上边界：K3低点
                })

            # Bearish FVG: K1低点 > K3高点（向下跳空）
            # 区域从K2开始，向后延伸10根
            if df.iloc[i - 2]["low"] > df.iloc[i]["high"]:
                end_idx = min(i + extend_bars, len(df) - 1)
                fvg_bearish.append({
                    "start_time": df.iloc[i - 1]["timestamp"].strftime("%Y-%m-%d %H:%M") if hasattr(df.iloc[i - 1]["timestamp"], 'strftime') else str(df.iloc[i - 1]["timestamp"]),
                    "end_time": df.iloc[end_idx]["timestamp"].strftime("%Y-%m-%d %H:%M") if hasattr(df.iloc[end_idx]["timestamp"], 'strftime') else str(df.iloc[end_idx]["timestamp"]),
                    "low": float(df.iloc[i]["high"]),       # 下边界：K3高点
                    "high": float(df.iloc[i - 2]["low"]),   # 上边界：K1低点
                })

        # 将 FVG 列表作为属性存储，不作为 DataFrame 列
        df.attrs["fvg_bullish"] = fvg_bullish
        df.attrs["fvg_bearish"] = fvg_bearish
        return df

    def get_traces(self, data: Dict[str, Any], colors: Dict[str, str]) -> List[Dict]:
        """返回 FVG 区域的形状"""
        traces = []

        # Bullish FVG (绿色区域)
        for fvg in data.get("fvg_bullish", []):
            traces.append({
                "type": "rect",
                "x0": fvg["start_time"],
                "x1": fvg["end_time"],
                "y0": fvg["low"],
                "y1": fvg["high"],
                "fillcolor": colors.get("fvg_bullish_fill", "rgba(76, 175, 80, 0.2)"),
                "line": {"width": 0},
                "xref": "x",
                "yref": "y",
            })

        # Bearish FVG (红色区域)
        for fvg in data.get("fvg_bearish", []):
            traces.append({
                "type": "rect",
                "x0": fvg["start_time"],
                "x1": fvg["end_time"],
                "y0": fvg["low"],
                "y1": fvg["high"],
                "fillcolor": colors.get("fvg_bearish_fill", "rgba(244, 67, 54, 0.2)"),
                "line": {"width": 0},
                "xref": "x",
                "yref": "y",
            })

        return traces
