#!/usr/bin/env python3
"""
市场状态可视化模块 - Market Chart Generator

功能:
- 绘制 K 线价格走势图
- 用背景色标注 trend_market/ranging_market
- 用 K 线颜色标注 direction (bullish/bearish/ranging)
- 显示 ADX 和 DI 指标副图
"""

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.axes import Axes
from matplotlib.figure import Figure
import pandas as pd
import numpy as np
from typing import Optional, List, Tuple
from pathlib import Path


class MarketChartGenerator:
    """
    市场状态图表生成器
    """

    def __init__(
        self,
        figsize: Tuple[int, int] = (14, 10),
        style: str = "default",
    ):
        """
        初始化图表生成器

        Args:
            figsize: 图表尺寸 (宽，高)
            style: matplotlib 样式
        """
        self.figsize = figsize
        self.style = style

        # 颜色配置
        self.colors = {
            # trend_market 背景色
            "trend_market_bg": "#C8E6C9",  # 浅绿色
            "ranging_market_bg": "#EEEEEE",  # 浅灰色

            # K 线颜色
            "bullish_candle": "#26A69A",  # 深绿色
            "bearish_candle": "#EF5350",  # 红色
            "ranging_candle": "#BDBDBD",  # 灰色

            # 边框颜色
            "bullish_edge": "#00897B",
            "bearish_edge": "#C62828",
            "ranging_edge": "#757575",

            # ADX 线颜色
            "adx_line": "#42A5F5",  # 蓝色
            "plus_di_line": "#66BB6A",  # 绿色
            "minus_di_line": "#EF5350",  # 红色

            # 阈值线颜色
            "threshold_line": "#FF9800",  # 橙色

            # MACD 颜色
            "macd_line": "#42A5F5",  # 蓝色
            "macd_signal": "#FF9800",  # 橙色
            "macd_hist_positive": "#26A69A",  # 深绿色
            "macd_hist_negative": "#EF5350",  # 红色

            # RSI 颜色
            "rsi_line": "#AB47BC",  # 紫色
            "rsi_overbought": "#EF5350",  # 红色
            "rsi_oversold": "#26A69A",  # 绿色

            # Bollinger Bands 颜色
            "bb_upper": "#66BB6A",  # 绿色
            "bb_middle": "#42A5F5",  # 蓝色
            "bb_lower": "#EF5350",  # 红色
            "bb_fill": "#42A5F5",  # 蓝色填充
        }

    def plot_market_state(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        output_path: str,
        adx_threshold: float = 25.0,
        max_candles: int = 200,
    ) -> str:
        """
        绘制市场状态图

        Args:
            df: 包含 OHLCV、trend_market、direction 的数据
            symbol: 交易对
            timeframe: 时间框架
            output_path: 输出文件路径
            adx_threshold: ADX 阈值
            max_candles: 最大显示的 K 线数量

        Returns:
            输出文件路径
        """
        df = df.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

        # 只显示最后 max_candles 条数据
        if len(df) > max_candles:
            df = df.iloc[-max_candles:].reset_index(drop=True)

        # 创建图表
        fig = plt.figure(figsize=self.figsize)

        # 配置字体，避免中文乱码
        plt.rcParams['font.sans-serif'] = ['Arial', 'DejaVu Sans', 'sans-serif']
        plt.rcParams['axes.unicode_minus'] = False

        fig.suptitle(f"{symbol} {timeframe} Market State Analysis", fontsize=16, fontweight='bold')

        # 创建子图布局 - 5 个子图：价格 + BB, MACD, RSI, ADX, DI
        gs = plt.GridSpec(
            nrows=5,
            ncols=1,
            height_ratios=[3, 1, 1, 1, 1],
            hspace=0.1
        )

        ax_price = plt.subplot(gs[0])
        ax_macd = plt.subplot(gs[1], sharex=ax_price)
        ax_rsi = plt.subplot(gs[2], sharex=ax_price)
        ax_adx = plt.subplot(gs[3], sharex=ax_price)
        ax_di = plt.subplot(gs[4], sharex=ax_price)

        # 绘制价格区域（含 Bollinger Bands）
        self._plot_price_section(ax_price, df)

        # 绘制 MACD 区域
        self._plot_macd_section(ax_macd, df)

        # 绘制 RSI 区域
        self._plot_rsi_section(ax_rsi, df)

        # 绘制 ADX 区域
        self._plot_adx_section(ax_adx, df, adx_threshold)

        # 绘制 DI 区域
        self._plot_di_section(ax_di, df)

        # 设置 X 轴标签
        self._setup_x_axis(ax_di, df)

        # 添加图例
        self._add_legends(fig)

        # 保存图表
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(output_path, dpi=150, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        return output_path

    def _plot_price_section(self, ax: Axes, df: pd.DataFrame):
        """绘制价格区域"""
        # 绘制背景色块表示 trend_market/ranging_market
        self._plot_market_type_background(ax, df)

        # 绘制 K 线
        self._plot_candlesticks(ax, df)

        # 绘制布林带
        self._plot_bollinger_bands(ax, df)

        ax.set_ylabel("Price")
        ax.grid(True, alpha=0.3)

    def _plot_market_type_background(self, ax: Axes, df: pd.DataFrame):
        """用背景色标注市场类型"""
        trend_market_regions = []
        ranging_market_regions = []

        current_region_start = None
        current_type = None

        # 使用 enumerate 确保索引与 K 线图一致
        for i, (_, row) in enumerate(df.iterrows()):
            # 支持 market_type 和 trend_market 两种列名
            market_type = row.get("market_type") or row.get("trend_market") or "ranging_market"

            if current_type is None:
                current_type = market_type
                current_region_start = i
            elif market_type != current_type:
                # 记录前一个区域
                if current_type == "trend_market":
                    trend_market_regions.append((current_region_start, i - 1))
                else:
                    ranging_market_regions.append((current_region_start, i - 1))
                current_type = market_type
                current_region_start = i

        # 记录最后一个区域
        if current_type is not None and current_region_start is not None:
            if current_type == "trend_market":
                trend_market_regions.append((current_region_start, len(df) - 1))
            else:
                ranging_market_regions.append((current_region_start, len(df) - 1))

        # 绘制背景矩形 - 先绘制 ranging_market（底层），再绘制 trend_market
        for start, end in ranging_market_regions:
            ax.axvspan(
                start - 0.5, end + 0.5,
                facecolor=self.colors["ranging_market_bg"],
                alpha=0.5,
                label="Ranging" if start == ranging_market_regions[0][0] else ""
            )

        for start, end in trend_market_regions:
            ax.axvspan(
                start - 0.5, end + 0.5,
                facecolor=self.colors["trend_market_bg"],
                alpha=0.5,
                label="Trend Market" if start == trend_market_regions[0][0] else ""
            )

    def _plot_candlesticks(self, ax: Axes, df: pd.DataFrame):
        """绘制 K 线图"""
        candle_width = 0.6

        for i, (idx, row) in enumerate(df.iterrows()):
            open_price = row["open"]
            close_price = row["close"]
            high = row["high"]
            low = row["low"]
            direction = row.get("direction", "ranging")

            # 根据方向选择颜色
            if direction == "bullish":
                body_color = self.colors["bullish_candle"]
                edge_color = self.colors["bullish_edge"]
            elif direction == "bearish":
                body_color = self.colors["bearish_candle"]
                edge_color = self.colors["bearish_edge"]
            else:
                body_color = self.colors["ranging_candle"]
                edge_color = self.colors["ranging_edge"]

            # 绘制影线
            ax.plot(
                [i, i], [low, high],
                color=edge_color,
                linewidth=1,
                alpha=0.8
            )

            # 绘制实体
            if open_price <= close_price:
                # 阳线
                rect = plt.Rectangle(
                    (i - candle_width / 2, open_price),
                    candle_width,
                    close_price - open_price,
                    facecolor=body_color,
                    edgecolor=edge_color,
                    linewidth=1,
                    label="Bullish" if i == 0 and direction == "bullish" else ""
                )
            else:
                # 阴线
                rect = plt.Rectangle(
                    (i - candle_width / 2, close_price),
                    candle_width,
                    open_price - close_price,
                    facecolor=body_color,
                    edgecolor=edge_color,
                    linewidth=1,
                    label="Bearish" if i == 0 and direction == "bearish" else ""
                )

            ax.add_patch(rect)

        ax.set_xlim(-1, len(df))

    def _plot_adx_section(self, ax: Axes, df: pd.DataFrame, threshold: float):
        """绘制 ADX 指标"""
        if "adx" in df.columns:
            ax.plot(
                range(len(df)), df["adx"],
                color=self.colors["adx_line"],
                linewidth=1.5,
                label="ADX"
            )

            # 绘制阈值线
            ax.axhline(
                y=threshold,
                color=self.colors["threshold_line"],
                linestyle="--",
                linewidth=1,
                label=f"Threshold ({threshold})"
            )

        ax.set_ylabel("ADX")
        ax.grid(True, alpha=0.3)
        ax.set_ylim(0, max(50, df["adx"].max() * 1.1) if "adx" in df.columns else 50)

    def _plot_di_section(self, ax: Axes, df: pd.DataFrame):
        """绘制 DI+ 和 DI- 指标"""
        if "plus_di" in df.columns:
            ax.plot(
                range(len(df)), df["plus_di"],
                color=self.colors["plus_di_line"],
                linewidth=1.5,
                label="+DI"
            )

        if "minus_di" in df.columns:
            ax.plot(
                range(len(df)), df["minus_di"],
                color=self.colors["minus_di_line"],
                linewidth=1.5,
                label="-DI"
            )

        ax.set_ylabel("DI")
        ax.set_xlabel("Time")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=9)
        ax.set_ylim(0, max(50, df["plus_di"].max() * 1.2, df["minus_di"].max() * 1.2) if "plus_di" in df.columns else 50)

    def _plot_macd_section(self, ax: Axes, df: pd.DataFrame):
        """绘制 MACD 指标"""
        has_macd = "macd" in df.columns
        has_signal = "macd_signal" in df.columns
        has_hist = "macd_hist" in df.columns

        if has_macd:
            ax.plot(
                range(len(df)), df["macd"],
                color=self.colors["macd_line"],
                linewidth=1.5,
                label="MACD"
            )

        if has_signal:
            ax.plot(
                range(len(df)), df["macd_signal"],
                color=self.colors["macd_signal"],
                linewidth=1.5,
                label="Signal"
            )

        if has_hist:
            # 柱状图 - 根据正负值使用不同颜色
            colors = [
                self.colors["macd_hist_positive"] if v > 0 else self.colors["macd_hist_negative"]
                for v in df["macd_hist"]
            ]
            ax.bar(
                range(len(df)), df["macd_hist"],
                color=colors,
                alpha=0.7,
                width=0.8,
                label="Histogram"
            )

        ax.set_ylabel("MACD")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=9)

    def _plot_rsi_section(self, ax: Axes, df: pd.DataFrame):
        """绘制 RSI 指标"""
        if "rsi" in df.columns:
            ax.plot(
                range(len(df)), df["rsi"],
                color=self.colors["rsi_line"],
                linewidth=1.5,
                label="RSI"
            )

            # 超买超卖线
            ax.axhline(
                y=70,
                color=self.colors["rsi_overbought"],
                linestyle="--",
                linewidth=1,
                alpha=0.7,
                label="Overbought (70)"
            )
            ax.axhline(
                y=30,
                color=self.colors["rsi_oversold"],
                linestyle="--",
                linewidth=1,
                alpha=0.7,
                label="Oversold (30)"
            )

        ax.set_ylabel("RSI")
        ax.set_ylim(-10, 110)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=9)

    def _plot_bollinger_bands(self, ax: Axes, df: pd.DataFrame):
        """绘制布林带"""
        if all(col in df.columns for col in ["bb_upper", "bb_middle", "bb_lower"]):
            # 上轨
            ax.plot(
                range(len(df)), df["bb_upper"],
                color=self.colors["bb_upper"],
                linewidth=1,
                linestyle="--",
                label="Upper BB"
            )
            # 中轨
            ax.plot(
                range(len(df)), df["bb_middle"],
                color=self.colors["bb_middle"],
                linewidth=1.5,
                label="Middle BB"
            )
            # 下轨
            ax.plot(
                range(len(df)), df["bb_lower"],
                color=self.colors["bb_lower"],
                linewidth=1,
                linestyle="--",
                label="Lower BB"
            )

            # 填充区域
            ax.fill_between(
                range(len(df)),
                df["bb_upper"],
                df["bb_lower"],
                alpha=0.1,
                color=self.colors["bb_fill"],
                label="BB Band"
            )

            ax.legend(loc="upper left", fontsize=8)

    def _setup_x_axis(self, ax: Axes, df: pd.DataFrame):
        """设置 X 轴"""
        num_ticks = min(10, len(df))
        if num_ticks > 0:
            step = max(1, len(df) // num_ticks)
            tick_positions = range(0, len(df), step)
            tick_labels = [
                df.iloc[i]["timestamp"].strftime("%m-%d") if len(df) > 60 else
                df.iloc[i]["timestamp"].strftime("%m-%d %H:%M")
                for i in tick_positions
            ]
            ax.set_xticks(tick_positions)
            ax.set_xticklabels(tick_labels, rotation=45, ha="right")

    def _add_legends(self, fig: Figure):
        """添加图例"""
        # 市场类型图例
        trend_patch = mpatches.Patch(
            facecolor=self.colors["trend_market_bg"],
            alpha=0.5,
            label="Trend Market"
        )
        ranging_patch = mpatches.Patch(
            facecolor=self.colors["ranging_market_bg"],
            alpha=0.3,
            label="Ranging Market"
        )

        # K 线颜色图例
        bullish_patch = mpatches.Patch(
            facecolor=self.colors["bullish_candle"],
            edgecolor=self.colors["bullish_edge"],
            label="Bullish"
        )
        bearish_patch = mpatches.Patch(
            facecolor=self.colors["bearish_candle"],
            edgecolor=self.colors["bearish_edge"],
            label="Bearish"
        )
        ranging_patch = mpatches.Patch(
            facecolor=self.colors["ranging_candle"],
            edgecolor=self.colors["ranging_edge"],
            label="Ranging"
        )

        # 指标图例
        macd_patch = mpatches.Patch(
            facecolor=self.colors["macd_line"],
            label="MACD"
        )
        rsi_patch = mpatches.Patch(
            facecolor=self.colors["rsi_line"],
            label="RSI"
        )
        bb_patch = mpatches.Patch(
            facecolor=self.colors["bb_middle"],
            label="Bollinger Bands"
        )

        # 添加两个图例框
        legend1 = fig.legend(
            handles=[trend_patch, ranging_patch],
            loc="upper center",
            bbox_to_anchor=(0.5, 0.98),
            ncol=2,
            frameon=True,
            fontsize=10
        )
        legend2 = fig.legend(
            handles=[bullish_patch, bearish_patch, ranging_patch],
            loc="lower center",
            bbox_to_anchor=(0.5, 0.02),
            ncol=3,
            frameon=True,
            fontsize=10
        )

        fig.add_artist(legend1)
        fig.add_artist(legend2)


def generate_all_charts(
    symbol: str,
    timeframes: List[str],
    data_dir: str = "./data/strategies/market_research",
    output_dir: str = "./data/charts/market_research",
    max_candles: int = 200,
) -> List[str]:
    """
    为所有时间框架生成图表

    Args:
        symbol: 交易对
        timeframes: 时间框架列表
        data_dir: 数据目录
        output_dir: 输出目录
        max_candles: 最大显示的 K 线数

    Returns:
        生成的图表文件路径列表
    """
    generator = MarketChartGenerator()
    output_paths = []

    for timeframe in timeframes:
        filepath = Path(data_dir) / f"{symbol}_{timeframe}.csv"
        if not filepath.exists():
            print(f"跳过 {timeframe}: 文件不存在")
            continue

        df = pd.read_csv(filepath)

        output_path = Path(output_dir) / f"{symbol}_{timeframe}_market.png"
        generator.plot_market_state(
            df=df,
            symbol=symbol,
            timeframe=timeframe,
            output_path=str(output_path),
            max_candles=max_candles,
        )
        output_paths.append(str(output_path))
        print(f"生成图表：{output_path}")

    return output_paths
