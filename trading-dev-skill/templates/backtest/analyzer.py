#!/usr/bin/env python3
"""
回测分析器 - 分析权益曲线，生成图表和报告

功能：
- 加载权益 CSV 数据
- 加载日线 K 线数据
- 计算关键指标（收益率、最大回撤等）
- 生成图表（权益曲线、回撤图）
- 生成 Markdown 分析报告
"""

import logging
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any

import matplotlib.pyplot as plt
import matplotlib.dates as mdates

logger = logging.getLogger(__name__)


class BacktestAnalyzer:
    """回测分析器"""

    def __init__(
        self,
        equity_csv: str,
        symbol: str,
        data_dir: str = "./data/strategies",
    ):
        """
        初始化分析器

        Args:
            equity_csv: 权益 CSV 文件路径
            symbol: 交易对
            data_dir: K 线数据目录
        """
        if not symbol:
            raise ValueError("symbol 参数必填")

        self.equity_csv = equity_csv
        self.symbol = symbol
        self.data_dir = data_dir
        self._equity_df: Optional[pd.DataFrame] = None
        self._klines_df: Optional[pd.DataFrame] = None
        self._metrics: Dict[str, Any] = {}

    def load_equity_data(self) -> pd.DataFrame:
        """
        加载权益 CSV 数据

        Returns:
            权益 DataFrame

        Raises:
            FileNotFoundError: 文件不存在
        """
        path = Path(self.equity_csv)
        if not path.exists():
            raise FileNotFoundError(f"权益文件不存在: {self.equity_csv}")

        self._equity_df = pd.read_csv(self.equity_csv)
        self._equity_df["date"] = pd.to_datetime(self._equity_df["date"])
        return self._equity_df

    def load_daily_klines(self) -> Optional[pd.DataFrame]:
        """
        加载日线 K 线数据，并过滤到权益数据的时间范围

        Returns:
            日线 DataFrame 或 None（文件不存在）
        """
        # 先加载权益数据获取时间范围
        if self._equity_df is None:
            self.load_equity_data()

        klines_path = Path(self.data_dir) / "1d" / f"{self.symbol}_1d.csv"
        if not klines_path.exists():
            logger.warning(f"日线数据不存在: {klines_path}")
            return None

        self._klines_df = pd.read_csv(klines_path)
        self._klines_df["timestamp"] = pd.to_datetime(self._klines_df["timestamp"]).dt.tz_localize(None)

        # 过滤到权益数据的时间范围
        start_date = self._equity_df["date"].min()
        end_date = self._equity_df["date"].max()
        self._klines_df = self._klines_df[
            (self._klines_df["timestamp"] >= start_date) &
            (self._klines_df["timestamp"] <= end_date)
        ]

        if self._klines_df.empty:
            logger.warning(f"日线数据在回测时间范围内为空: {start_date} ~ {end_date}")
            return None

        logger.info(f"日线数据已加载: {len(self._klines_df)} 行, 时间范围: {start_date} ~ {end_date}")
        return self._klines_df

    def calculate_metrics(self) -> Dict[str, Any]:
        """
        计算关键指标

        Returns:
            指标字典
        """
        if self._equity_df is None:
            self.load_equity_data()

        equity = self._equity_df["equity"]
        initial = equity.iloc[0]
        final = equity.iloc[-1]

        # 总收益率
        total_return = (final - initial) / initial * 100

        # 最大回撤
        peak = equity.max()
        trough = equity.min()
        max_drawdown = (peak - trough) / peak * 100 if peak > 0 else 0

        # 找到峰值和谷值时间
        peak_idx = equity.idxmax()
        trough_idx = equity.idxmin()
        peak_date = self._equity_df["date"].iloc[peak_idx]
        trough_date = self._equity_df["date"].iloc[trough_idx]

        self._metrics = {
            "total_return": round(total_return, 2),
            "max_drawdown": round(max_drawdown, 2),
            "peak_equity": round(peak, 2),
            "trough_equity": round(trough, 2),
            "peak_date": peak_date.strftime("%Y-%m-%d"),
            "trough_date": trough_date.strftime("%Y-%m-%d"),
            "initial_equity": round(initial, 2),
            "final_equity": round(final, 2),
            "days": len(self._equity_df),
        }

        return self._metrics

    def generate_charts(self, output_dir: str, prefix: str = "") -> Dict[str, str]:
        """
        生成图表

        Args:
            output_dir: 输出目录
            prefix: 文件名前缀（如 backtest_strategy_symbol_timestamp）

        Returns:
            图表路径字典
        """
        if self._equity_df is None:
            self.load_equity_data()

        # 加载日线 K 线数据
        if self._klines_df is None:
            self.load_daily_klines()

        output_path = Path(output_dir)
        charts_dir = output_path / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)

        # 设置图表样式
        plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        # 图1: 权益曲线 + 价格对比
        fig, ax1 = plt.subplots(figsize=(12, 6))

        # 绘制权益曲线（左 Y 轴）
        color1 = "tab:blue"
        ax1.plot(self._equity_df["date"], self._equity_df["equity"], "b-", linewidth=1.5, label="Equity")
        ax1.axhline(y=self._equity_df["equity"].iloc[0], color="gray", linestyle="--", alpha=0.5, label="Initial")
        ax1.fill_between(
            self._equity_df["date"],
            self._equity_df["equity"].iloc[0],
            self._equity_df["equity"],
            where=self._equity_df["equity"] >= self._equity_df["equity"].iloc[0],
            alpha=0.3,
            color="green",
        )
        ax1.fill_between(
            self._equity_df["date"],
            self._equity_df["equity"].iloc[0],
            self._equity_df["equity"],
            where=self._equity_df["equity"] < self._equity_df["equity"].iloc[0],
            alpha=0.3,
            color="red",
        )
        ax1.set_xlabel("Date")
        ax1.set_ylabel("Equity (USDT)", color=color1)
        ax1.tick_params(axis="y", labelcolor=color1)
        ax1.grid(True, alpha=0.3)

        # 如果有 K 线数据，叠加价格曲线（右 Y 轴）
        if self._klines_df is not None and not self._klines_df.empty:
            ax2 = ax1.twinx()
            color2 = "tab:orange"
            ax2.plot(self._klines_df["timestamp"], self._klines_df["close"], color=color2, linewidth=1.2, alpha=0.7, label="Price")
            ax2.set_ylabel("Price (USDT)", color=color2)
            ax2.tick_params(axis="y", labelcolor=color2)

            # 合并图例
            lines1, labels1 = ax1.get_legend_handles_labels()
            lines2, labels2 = ax2.get_legend_handles_labels()
            ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")
        else:
            ax1.legend(loc="upper left")

        ax1.set_title(f"{self.symbol} Backtest Equity Curve", fontsize=14, fontweight="bold")
        ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        plt.tight_layout()

        equity_chart_name = f"{prefix}_equity_curve.png" if prefix else "equity_curve.png"
        equity_chart = charts_dir / equity_chart_name
        plt.savefig(equity_chart, dpi=150, bbox_inches="tight")
        plt.close()

        # 图2: 回撤图
        fig, ax = plt.subplots(figsize=(12, 4))
        # 计算回撤
        rolling_peak = self._equity_df["equity"].expanding().max()
        drawdown = (self._equity_df["equity"] - rolling_peak) / rolling_peak * 100
        ax.plot(self._equity_df["date"], drawdown, "r-", linewidth=1.5)
        ax.fill_between(self._equity_df["date"], 0, drawdown, alpha=0.3, color="red")
        ax.set_title(f"{self.symbol} Drawdown", fontsize=14, fontweight="bold")
        ax.set_xlabel("Date")
        ax.set_ylabel("Drawdown (%)")
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        plt.tight_layout()

        drawdown_chart_name = f"{prefix}_drawdown.png" if prefix else "drawdown.png"
        drawdown_chart = charts_dir / drawdown_chart_name
        plt.savefig(drawdown_chart, dpi=150, bbox_inches="tight")
        plt.close()

        return {
            "equity_curve": str(equity_chart),
            "drawdown": str(drawdown_chart),
        }

    # 周期对应的横轴日期格式（matplotlib DateFormatter）
    TF_CHART_FORMATS = {
        "1m": "%Y-%m-%d %H:%M",
        "5m": "%Y-%m-%d %H:%M",
        "15m": "%Y-%m-%d %H:%M",
        "30m": "%Y-%m-%d %H:%M",
        "1h": "%Y-%m-%d %H:00",
        "4h": "%Y-%m-%d %H:00",
        "6h": "%Y-%m-%d %H:00",
        "8h": "%Y-%m-%d %H:00",
        "1d": "%Y-%m-%d",
    }

    def generate_tf_equity_chart(
        self,
        tf_equity_csv: str,
        output_dir: str,
        tf_key: str,
        prefix: str = "",
    ) -> str:
        """
        生成周期权益曲线图

        Args:
            tf_equity_csv: 周期权益 CSV 文件路径
            output_dir: 输出目录
            tf_key: 周期键值（如 "1h", "15m"）
            prefix: 文件名前缀

        Returns:
            图表路径
        """
        # 加载周期权益数据
        tf_df = pd.read_csv(tf_equity_csv)
        if tf_df.empty:
            logger.warning(f"周期权益文件为空: {tf_equity_csv}")
            return ""

        # 解析 datetime 列
        if "datetime" in tf_df.columns:
            tf_df["datetime"] = pd.to_datetime(tf_df["datetime"])
        elif "date" in tf_df.columns:
            tf_df["datetime"] = pd.to_datetime(tf_df["date"])
        else:
            logger.error(f"周期权益文件缺少 datetime 列: {tf_equity_csv}")
            return ""

        output_path = Path(output_dir)
        charts_dir = output_path / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)

        # 设置图表样式
        plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False

        # 绘制权益曲线
        fig, ax = plt.subplots(figsize=(12, 6))

        ax.plot(tf_df["datetime"], tf_df["equity"], "b-", linewidth=1.5, label="Equity")
        ax.axhline(y=tf_df["equity"].iloc[0], color="gray", linestyle="--", alpha=0.5, label="Initial")

        initial_equity = tf_df["equity"].iloc[0]
        ax.fill_between(
            tf_df["datetime"],
            initial_equity,
            tf_df["equity"],
            where=tf_df["equity"] >= initial_equity,
            alpha=0.3,
            color="green",
        )
        ax.fill_between(
            tf_df["datetime"],
            initial_equity,
            tf_df["equity"],
            where=tf_df["equity"] < initial_equity,
            alpha=0.3,
            color="red",
        )

        ax.set_xlabel("Datetime")
        ax.set_ylabel("Equity (USDT)")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper left")
        ax.set_title(f"{self.symbol} {tf_key} Equity Curve", fontsize=14, fontweight="bold")

        # 根据周期设置横轴格式
        date_fmt = self.TF_CHART_FORMATS.get(tf_key, "%Y-%m-%d")
        ax.xaxis.set_major_formatter(mdates.DateFormatter(date_fmt))

        plt.xticks(rotation=45, ha="right")
        plt.tight_layout()

        # 保存图表
        chart_name = f"{prefix}_{tf_key}_equity_curve.png" if prefix else f"{tf_key}_equity_curve.png"
        chart_path = charts_dir / chart_name
        plt.savefig(chart_path, dpi=150, bbox_inches="tight")
        plt.close()

        logger.info(f"[BacktestAnalyzer] 已生成周期权益曲线: {chart_path}")
        return str(chart_path)

    def generate_report(self, output_dir: str, prefix: str = "") -> str:
        """
        生成 Markdown 分析报告

        Args:
            output_dir: 输出目录
            prefix: 文件名前缀（如 backtest_strategy_symbol_timestamp）

        Returns:
            报告路径
        """
        if not self._metrics:
            self.calculate_metrics()

        output_path = Path(output_dir)
        report_name = f"{prefix}_analysis_report.md" if prefix else f"{self.symbol}_analysis_report.md"
        report_path = output_path / report_name

        # 生成报告内容
        content = f"""# 回测分析报告

**策略**: {self.symbol}
**生成时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

## 1. 概况

| 指标 | 值 |
|------|------|
| 回测天数 | {self._metrics["days"]} |
| 初始权益 | {self._metrics["initial_equity"]:,.2f} |
| 期末权益 | {self._metrics["final_equity"]:,.2f} |
| 总收益率 | {self._metrics["total_return"]:.2f}% |
| 最大回撤 | {self._metrics["max_drawdown"]:.2f}% |

---

## 2. 权益曲线

![权益曲线](charts/equity_curve.png)

---

## 3. 回撤分析

![回撤图](charts/drawdown.png)

| 指标 | 值 |
|------|------|
| 峰值权益 | {self._metrics["peak_equity"]:,.2f} |
| 峰值日期 | {self._metrics["peak_date"]} |
| 谷值权益 | {self._metrics["trough_equity"]:,.2f} |
| 谷值日期 | {self._metrics["trough_date"]} |

---

## 4. 分析结论

- **收益表现**: {self._metrics["total_return"] > 0 and "盈利" or "亏损"}
- **风险控制**: 最大回撤 {self._metrics["max_drawdown"]:.2f}%，{self._metrics["max_drawdown"] < 20 and "风险较低" or self._metrics["max_drawdown"] < 40 and "风险中等" or "风险较高"}

---

*报告由 BacktestAnalyzer 自动生成*
"""

        report_path.write_text(content, encoding="utf-8")
        logger.info(f"分析报告已生成: {report_path}")

        return str(report_path)