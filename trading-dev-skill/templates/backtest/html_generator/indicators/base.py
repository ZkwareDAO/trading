"""技术指标基类"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import pandas as pd


class BaseIndicator(ABC):
    """指标基类"""

    name: str = ""
    yaxis: str = "y"  # y, y2, y3, y4...
    domain: Optional[List[float]] = None  # [start, end] 或 None（与K线共享）

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.DataFrame:
        """计算指标，返回添加了指标列的 DataFrame"""
        pass

    @abstractmethod
    def get_traces(self, data: Dict[str, Any], colors: Dict[str, str]) -> List[Dict]:
        """返回 Plotly traces 列表"""
        pass

    def get_yaxis_config(self) -> Optional[Dict]:
        """返回 Y 轴配置"""
        if self.domain is None:
            return None
        return {
            "domain": self.domain,
            "title": self.name,
            "fixedrange": False,
        }