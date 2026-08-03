"""HTML 生成器配置"""

import os
from pathlib import Path

# 目录配置
BASE_DIR = Path(__file__).parent
ASSETS_DIR = BASE_DIR / "assets"
TEMPLATES_DIR = BASE_DIR / "templates"

# 默认 K 线数据目录
DEFAULT_KLINE_DIR = os.getenv("DATA_PATH", "./data") + "/strategies/15m"

# Plotly 库文件名
PLOTLY_JS_FILENAME = "plotly.min.js"

# K 线显示配置
DISPLAY_CONFIG = {
    "default_count": 180,
    "min_count": 30,
    "max_count": 500,
    "adaptive": {
        "small": {"max_width": 600, "count": 60},
        "medium": {"max_width": 900, "count": 100},
        "large": {"max_width": 1400, "count": 140},
        "xlarge": {"max_width": float("inf"), "count": 180},
    },
}

# 可用技术指标列表
AVAILABLE_INDICATORS = ["OBV", "ADX", "ATR", "FVG", "RSI", "MACD", "BB", "Swing"]

# 默认不启用任何指标
DEFAULT_ENABLED_INDICATORS = []

# 颜色配置
COLORS = {
    # K线
    "bullish": "#26a69a",
    "bearish": "#ef5350",
    # OBV
    "obv_bullish_fill": "rgba(76, 175, 80, 0.3)",
    "obv_bearish_fill": "rgba(244, 67, 54, 0.3)",
    "obv_line": "purple",
    "ma_line": "orange",
    # ADX
    "adx_line": "purple",
    "adx_threshold": "red",
    # ATR
    "atr_line": "#FF6B00",
    # FVG
    "fvg_bullish_fill": "rgba(76, 175, 80, 0.2)",
    "fvg_bearish_fill": "rgba(244, 67, 54, 0.2)",
    # RSI
    "rsi_line": "purple",
    # MACD
    "macd_line": "blue",
    "macd_signal": "orange",
    "macd_hist_pos": "green",
    "macd_hist_neg": "red",
    # Bollinger
    "bb_line": "blue",
    # 交易
    "long_entry": "blue",
    "short_entry": "orange",
    "profit_exit": "green",
    "loss_exit": "red",
}

# 图表布局配置
CHART_LAYOUT = {
    "height": 900,
    "margin": {"l": 60, "r": 20, "t": 50, "b": 40},
}

# 指标参数配置
INDICATOR_PARAMS = {
    "FVG": {
        "extend_bars": 10,  # FVG 向后延伸K线数量
    },
    "OBV": {
        "ma_period": 20,  # OBV MA 周期（暂未实现）
    },
    "ADX": {
        "period": 14,  # ADX 周期（暂未实现）
    },
    "ATR": {
        "period": 14,  # ATR 周期
    },
    "RSI": {
        "period": 14,  # RSI 周期
    },
    "MACD": {
        "fast": 12,  # 快线周期
        "slow": 26,  # 慢线周期
        "signal": 9,  # 信号线周期
    },
    "BB": {
        "period": 20,  # 布林带周期
        "std_dev": 2.0,  # 标准差倍数
    },
    "Swing": {
        "lookback": 5,  # Swing 检测回溯窗口
    },
}