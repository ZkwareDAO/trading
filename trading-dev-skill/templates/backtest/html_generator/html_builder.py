"""HTML 生成器"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import pandas as pd

from .config import (
    ASSETS_DIR,
    AVAILABLE_INDICATORS,
    CHART_LAYOUT,
    COLORS,
    DEFAULT_ENABLED_INDICATORS,
    DEFAULT_KLINE_DIR,
    DISPLAY_CONFIG,
    INDICATOR_PARAMS,
    PLOTLY_JS_FILENAME,
)
from .indicators import get_indicator, list_indicators
from .templates import CHART_HTML_TEMPLATE

logger = logging.getLogger(__name__)


def get_plotly_js() -> str:
    plotly_path = ASSETS_DIR / PLOTLY_JS_FILENAME
    if plotly_path.exists():
        with open(plotly_path, "r", encoding="utf-8") as f:
            return f.read()
    logger.warning(f"Plotly 库不存在: {plotly_path}")
    return ""


def get_price_precision(price: float) -> int:
    """根据价格大小自动判断精度"""
    if price == 0:
        return 2
    abs_price = abs(price)
    if abs_price >= 1000:
        return 2
    elif abs_price >= 1:
        return 4
    elif abs_price >= 0.01:
        return 6
    elif abs_price >= 0.0001:
        return 8
    else:
        return 10


def compute_all_indicators(df: pd.DataFrame, enabled_indicators: List[str] = None) -> pd.DataFrame:
    """计算所有指标数据"""
    df = df.copy()

    # 计算价格均线
    df["price_ma"] = df["close"].rolling(window=20).mean()

    # 计算所有可用指标（前端选择显示哪些）
    for indicator_name in list_indicators():
        # 获取指标参数配置
        params = INDICATOR_PARAMS.get(indicator_name, {})
        indicator = get_indicator(indicator_name, **params)
        df = indicator.compute(df)

    return df


def prepare_chart_data(
    kline_period: pd.DataFrame,
    trade_pairs: List[Dict[str, Any]],
    enabled_indicators: List[str] = None
) -> Dict[str, Any]:
    """准备图表数据"""
    avg_price = kline_period["close"].mean()
    precision = get_price_precision(avg_price)

    data = {
        "timestamps": kline_period["timestamp"].dt.strftime("%Y-%m-%d %H:%M").tolist(),
        "open": kline_period["open"].round(precision).tolist(),
        "high": kline_period["high"].round(precision).tolist(),
        "low": kline_period["low"].round(precision).tolist(),
        "close": kline_period["close"].round(precision).tolist(),
        "volume": kline_period["volume"].round(2).tolist(),
        "price_ma": kline_period["price_ma"].round(precision).tolist(),
        "trades": [{
            "entry_time": t["entry_time"].strftime("%Y-%m-%d %H:%M"),
            "entry_price": round(t["entry_price"], precision),
            "exit_time": t["exit_time"].strftime("%Y-%m-%d %H:%M"),
            "exit_price": round(t["exit_price"], precision),
            "pnl": round(t["pnl"], 2) if pd.notna(t["pnl"]) else 0,
            "type": t["type"],
        } for t in trade_pairs],
    }

    # 添加所有指标数据
    for indicator_name in list_indicators():
        indicator = get_indicator(indicator_name)

        if indicator_name == "OBV":
            data["obv"] = kline_period["obv"].round(2).tolist()
            data["obv_ma"] = kline_period["obv_ma"].round(2).tolist()
        elif indicator_name == "ADX":
            data["adx"] = kline_period["adx"].round(2).tolist()
        elif indicator_name == "ATR":
            data["atr"] = kline_period["atr"].round(4).tolist()
        elif indicator_name == "RSI":
            data["rsi"] = kline_period["rsi"].round(2).tolist()
        elif indicator_name == "MACD":
            data["macd"] = kline_period["macd"].round(4).tolist()
            data["macd_signal"] = kline_period["macd_signal"].round(4).tolist()
            data["macd_hist"] = kline_period["macd_hist"].round(4).tolist()
        elif indicator_name == "BB":
            data["bb_upper"] = kline_period["bb_upper"].round(precision).tolist()
            data["bb_middle"] = kline_period["bb_middle"].round(precision).tolist()
            data["bb_lower"] = kline_period["bb_lower"].round(precision).tolist()
        elif indicator_name == "FVG":
            # FVG 区域数据（存储在 attrs 中）
            data["fvg_bullish"] = kline_period.attrs.get("fvg_bullish", [])
            data["fvg_bearish"] = kline_period.attrs.get("fvg_bearish", [])
        elif indicator_name == "Swing":
            # Swing Points 数据（存储在 attrs 中）
            data["swing_highs"] = kline_period.attrs.get("swing_highs", [])
            data["swing_lows"] = kline_period.attrs.get("swing_lows", [])

    return data


def generate_html(
    symbol: str,
    kline_period: pd.DataFrame,
    trade_pairs: List[Dict[str, Any]],
    output_path: str,
    display_count: Optional[int] = None,
    title: Optional[str] = None,
    enabled_indicators: Optional[List[str]] = None,
) -> str:
    """
    生成交互式 HTML 图表

    Args:
        symbol: 交易对
        kline_period: K 线数据
        trade_pairs: 配对交易列表
        output_path: 输出文件路径
        display_count: 默认显示 K 线数量
        title: 自定义标题
        enabled_indicators: 启用的指标列表，如 ['OBV', 'ADX']
    """
    # 默认不启用任何指标
    if enabled_indicators is None:
        enabled_indicators = DEFAULT_ENABLED_INDICATORS

    # 计算所有指标
    kline_period = compute_all_indicators(kline_period, enabled_indicators)
    logger.info(f"准备数据: {symbol}, {len(kline_period)} 条 K 线, 启用指标: {enabled_indicators}")

    plotly_js = get_plotly_js()
    if plotly_js:
        logger.info(f"嵌入 Plotly 库: {len(plotly_js)//1024}KB")

    all_data = prepare_chart_data(kline_period, trade_pairs, enabled_indicators)

    page_title = title or f"{symbol} Technical Indicators"
    display_count = display_count or DISPLAY_CONFIG["default_count"]

    html = CHART_HTML_TEMPLATE.format(
        title=page_title,
        plotly_js=plotly_js,
        total_klines=len(kline_period),
        long_cnt=sum(1 for p in trade_pairs if p["type"] == "LONG"),
        short_cnt=sum(1 for p in trade_pairs if p["type"] == "SHORT"),
        display_count=display_count,
        min_count=DISPLAY_CONFIG["min_count"],
        max_count=DISPLAY_CONFIG["max_count"],
        default_count=DISPLAY_CONFIG["default_count"],
        data_json=json.dumps(all_data),
        adaptive_config_json=json.dumps(DISPLAY_CONFIG["adaptive"]),
        colors_json=json.dumps(COLORS),
        chart_height=CHART_LAYOUT["height"],
        margin_l=CHART_LAYOUT["margin"]["l"],
        margin_r=CHART_LAYOUT["margin"]["r"],
        margin_t=CHART_LAYOUT["margin"]["t"],
        margin_b=CHART_LAYOUT["margin"]["b"],
        available_indicators_json=json.dumps(AVAILABLE_INDICATORS),
        enabled_indicators_json=json.dumps(enabled_indicators),
    )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    logger.info(f"HTML 已生成: {output_path} ({len(html)//1024}KB)")
    return output_path