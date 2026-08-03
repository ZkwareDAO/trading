"""BacktestReporter — 生成回测输出文件到 backtest_output/."""

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

TRADES_CSV_COLUMNS = [
    "trade_id", "strategy_id", "symbol", "side", "quantity",
    "price", "commission", "slippage", "pnl", "timestamp", "comment",
]


class BacktestReporter:
    """生成 4 个标准输出文件到 backtest_output/{策略名称}/{YYYYMMDD}/{HHMMSS}/."""

    def __init__(self, output_dir: str = "./backtest_output"):
        self.base_output_dir = Path(output_dir)
        self._current_run_dir: Path = None

    def create_run_dir(
        self,
        strategy_name: str,
        symbol: str = "",
        backtest_date: str | None = None,
    ) -> Path:
        """
        提前创建回测运行目录，供 signals.csv 等使用。

        Args:
            strategy_name: 策略名称
            symbol: 交易标的（可选，用于创建 {symbol} 子目录）
            backtest_date: 回测日期 (YYYYMMDD)，用于目录命名。
                           通常为回测结束日期，若不传则使用 UTC 当前日期。

        Returns:
            运行目录路径
        """
        date_dir = backtest_date or datetime.now(timezone.utc).strftime("%Y%m%d")
        time_dir = datetime.now(timezone.utc).strftime("%H%M%S")

        # 目录结构: {strategy}/{date}/{time}/{symbol}/
        if symbol:
            run_dir = self.base_output_dir / strategy_name / date_dir / time_dir / symbol
        else:
            run_dir = self.base_output_dir / strategy_name / date_dir / time_dir
        run_dir.mkdir(parents=True, exist_ok=True)

        self._current_run_dir = run_dir
        self._current_prefix = "backtest"

        logger.info(f"[BacktestReporter] 创建回测目录: {run_dir}")
        return run_dir

    def get_current_run_dir(self) -> Path:
        """获取当前运行目录"""
        return self._current_run_dir

    def get_current_prefix(self) -> str:
        """获取当前文件名前缀"""
        return self._current_prefix or "backtest"

    def generate(
        self,
        strategy_name: str,
        symbol: str,
        config: Dict[str, Any],
        accounts: List[Dict[str, Any]],
        daily_equity: List[Dict[str, Any]],
        trades: List[Dict[str, Any]],
        klines_processed: int,
        signals_processed: int,
        start_time: datetime,
        end_time: datetime,
        tf_equity: List[Dict[str, Any]] = None,
        tf_key: str = None,
    ) -> Dict[str, Path]:
        """生成全部 4 个输出文件（+可选周期权益文件）."""
        # 使用已创建的目录（如果存在）
        if self._current_run_dir:
            output_dir = self._current_run_dir
            prefix = self._current_prefix or "backtest"
        else:
            now = datetime.now(timezone.utc)
            date_dir = now.strftime("%Y%m%d")
            time_dir = now.strftime("%H%M%S")
            # 如果没有预创建目录，则根据 symbol 创建
            if symbol:
                output_dir = self.base_output_dir / strategy_name / date_dir / time_dir / symbol
            else:
                output_dir = self.base_output_dir / strategy_name / date_dir / time_dir
            output_dir.mkdir(parents=True, exist_ok=True)
            prefix = "backtest"

        metrics = self._compute_metrics(config, daily_equity, trades)
        duration = (end_time - start_time).total_seconds()

        paths: Dict[str, Path] = {}
        paths["equity"] = self._write_equity(output_dir, prefix, daily_equity)

        # 写入周期权益文件（如果有）
        if tf_equity and tf_key:
            paths[f"{tf_key}_equity"] = self._write_tf_equity(output_dir, tf_key, tf_equity)

        paths["trades"] = self._write_trades(output_dir, prefix, trades)
        paths["result"] = self._write_result(
            output_dir, prefix, config, accounts, daily_equity, trades,
            metrics, klines_processed, signals_processed,
            start_time, end_time, duration,
        )
        paths["report"] = self._write_report(
            output_dir, prefix, config, accounts, trades, metrics,
            klines_processed, signals_processed, duration,
        )

        # 新增：生成分析图表和报告
        try:
            from backtest.analyzer import BacktestAnalyzer
            analyzer = BacktestAnalyzer(
                equity_csv=str(paths["equity"]),
                symbol=symbol,
                data_dir=config.get("data_dir", "./data/klines"),
            )
            analyzer.load_equity_data()
            analyzer.load_daily_klines()  # 显式加载日线数据
            analyzer.calculate_metrics()
            chart_paths = analyzer.generate_charts(str(output_dir), prefix=prefix)
            report_path = analyzer.generate_report(str(output_dir), prefix=prefix)
            paths["charts"] = chart_paths
            paths["analysis_report"] = Path(report_path)
            logger.info(f"[BacktestReporter] 已生成分析报告: {report_path}")

            # 生成周期权益曲线图（如果有）
            if tf_equity and tf_key and f"{tf_key}_equity" in paths:
                tf_chart_path = analyzer.generate_tf_equity_chart(
                    tf_equity_csv=str(paths[f"{tf_key}_equity"]),
                    output_dir=str(output_dir),
                    tf_key=tf_key,
                    prefix=prefix,
                )
                if tf_chart_path:
                    chart_paths[f"{tf_key}_equity_curve"] = tf_chart_path
        except Exception as e:
            logger.warning(f"[BacktestReporter] 分析报告生成失败: {e}")

        logger.info(f"[BacktestReporter] 已生成 {len(paths)} 个文件到 {output_dir}")
        return paths

    def _write_equity(self, output_dir: Path, prefix: str,
                      daily_equity: List[Dict]) -> Path:
        path = output_dir / f"{prefix}_equity.csv"
        with open(path, "w", encoding="utf-8") as f:
            f.write("date,equity,cash\n")
            for row in daily_equity:
                f.write(f"{row['date']},{row['equity']},{row['cash']}\n")
        return path

    def _write_tf_equity(self, output_dir: Path, tf_key: str,
                         tf_equity: List[Dict]) -> Path:
        """写入周期权益曲线文件"""
        path = output_dir / f"{tf_key}_equity.csv"
        with open(path, "w", encoding="utf-8") as f:
            f.write("datetime,equity,cash\n")
            for row in tf_equity:
                f.write(f"{row['datetime']},{row['equity']},{row['cash']}\n")
        logger.info(f"[BacktestReporter] 已写入周期权益: {path}")
        return path

    def _write_trades(self, output_dir: Path, prefix: str,
                      trades: List[Dict]) -> Path:
        path = output_dir / f"{prefix}_trades.csv"
        with open(path, "w", encoding="utf-8") as f:
            f.write(",".join(TRADES_CSV_COLUMNS) + "\n")
            for t in trades:
                row = [str(t.get(col, "")) for col in TRADES_CSV_COLUMNS]
                f.write(",".join(row) + "\n")
        return path

    def _write_result(
        self, output_dir: Path, prefix: str,
        config: Dict, accounts: List[Dict], daily_equity: List[Dict],
        trades: List[Dict], metrics: Dict,
        klines_processed: int, signals_processed: int,
        start_time: datetime, end_time: datetime, duration: float,
    ) -> Path:
        path = output_dir / f"{prefix}_result.json"
        perf_summary = self._format_performance_summary(metrics)

        result = {
            "config": config,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": duration,
            "accounts": accounts,
            "metrics": metrics,
            "daily_equity": daily_equity,
            "trades_count": len(trades),
            "klines_processed": klines_processed,
            "signals_processed": signals_processed,
            "status": "success",
            "performance_summary": perf_summary,
        }

        result = _sanitize(result)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        return path

    def _write_report(
        self, output_dir: Path, prefix: str,
        config: Dict, accounts: List[Dict], trades: List[Dict],
        metrics: Dict, klines_processed: int, signals_processed: int,
        duration: float,
    ) -> Path:
        path = output_dir / f"{prefix}_report.txt"
        name = config.get("name", prefix)
        start_date = config.get("start_date", "")
        end_date = config.get("end_date", "")
        initial_cash = config.get("initial_cash", 0)
        bt_symbols = config.get("symbols", [])

        total_return = metrics.get("total_return", 0) * 100
        annualized = metrics.get("annualized_return", 0) * 100
        sharpe = metrics.get("sharpe_ratio", 0)
        sortino = metrics.get("sortino_ratio", 0)
        max_dd = metrics.get("max_drawdown", 0) * 100
        total_trades = metrics.get("total_trades", 0)
        winning = metrics.get("winning_trades", 0)
        losing = metrics.get("losing_trades", 0)
        win_rate = metrics.get("win_rate", 0) * 100
        profit_factor = metrics.get("profit_factor", 0)
        avg_pnl = metrics.get("avg_trade_pnl", 0)
        avg_win = metrics.get("avg_win", 0)
        avg_loss = metrics.get("avg_loss", 0)
        largest_win = metrics.get("largest_win", 0)
        largest_loss = metrics.get("largest_loss", 0)
        profit_total = metrics.get("profit_trades_pnl", 0)
        loss_total = metrics.get("loss_trades_pnl", 0)

        lines = []
        sep = "=" * 80
        dash = "-" * 40

        lines.append(sep)
        lines.append("CTA 策略回测报告")
        lines.append(sep)
        lines.append("")

        lines.append("回测概况")
        lines.append(dash)
        lines.append(f"  回测名称：    {name}")
        lines.append(f"  回测区间：    {start_date} 至 {end_date}")
        lines.append(f"  初始资金：    {initial_cash:,.2f}")
        if len(bt_symbols) > 1:
            lines.append(f"  交易币对：    {', '.join(bt_symbols)} ({len(bt_symbols)} 个)")
            lines.append(f"  资金分配：    等分（每币对 {initial_cash / len(bt_symbols):,.2f}）")
        lines.append(f"  耗时：        {duration:.2f} 秒")
        lines.append(f"  处理 K 线数：   {klines_processed}")
        lines.append(f"  处理信号数：  {signals_processed}")
        lines.append("")

        lines.append("账户摘要")
        lines.append(dash)
        for acc in accounts:
            sid = acc.get("strategy_id", "")
            lines.append(f"  策略：{sid}")
            lines.append(f"    期末权益：    {acc.get('total_equity', 0):,.2f}")
            lines.append(f"    可用现金：    {acc.get('cash', 0):,.2f}")
            lines.append(f"    持仓保证金：  {acc.get('frozen_cash', 0):.2f}")
            lines.append(f"    最大回撤：    {acc.get('max_drawdown', 0) * 100:.2f}%")
            lines.append(f"    交易次数：    {acc.get('trade_count', 0)}")
        lines.append("")

        lines.append("绩效指标")
        lines.append(dash)
        lines.append(f"  总收益率：            {total_return:.2f}%")
        lines.append(f"  年化收益率：          {annualized:.2f}%")
        lines.append(f"  夏普比率：              {sharpe:.2f}")
        lines.append(f"  索提诺比率：            {sortino:.2f}")
        lines.append(f"  最大回撤：            {max_dd:.2f}%")
        lines.append("")

        lines.append("交易统计")
        lines.append(dash)
        lines.append(f"  总交易次数：               {total_trades}")
        lines.append(f"  盈利次数：                 {winning}")
        lines.append(f"  亏损次数：                 {losing}")
        lines.append(f"  胜率：                {win_rate:.2f}%")
        lines.append(f"  盈亏比：               {profit_factor:.2f}")
        lines.append("")

        # 多 symbol 分币对统计
        if len(bt_symbols) > 1:
            lines.append("分币对交易统计")
            lines.append(dash)
            for sym in bt_symbols:
                sym_trades = [t for t in trades if t.get("symbol", "") == sym and t.get("pnl", 0) != 0]
                sym_wins = [t for t in sym_trades if t["pnl"] > 0]
                sym_losses = [t for t in sym_trades if t["pnl"] < 0]
                sym_total_pnl = sum(t["pnl"] for t in sym_trades)
                sym_wr = len(sym_wins) / len(sym_trades) * 100 if sym_trades else 0
                lines.append(f"  {sym}:")
                lines.append(f"    交易次数: {len(sym_trades)}  盈利: {len(sym_wins)}  亏损: {len(sym_losses)}  胜率: {sym_wr:.1f}%  总盈亏: {sym_total_pnl:.2f}")
            lines.append("")

        lines.append("盈亏分析")
        lines.append(dash)
        lines.append(f"  平均盈亏：           {avg_pnl:.2f}")
        lines.append(f"  平均盈利：          {avg_win:.2f}")
        lines.append(f"  平均亏损：           {avg_loss:.2f}")
        lines.append(f"  最大盈利：          {largest_win:.2f}")
        lines.append(f"  最大亏损：          {largest_loss:.2f}")
        lines.append(f"  盈利总额：          {profit_total:.2f}")
        lines.append(f"  亏损总额：          {loss_total:.2f}")
        lines.append("")

        lines.append("期末持仓")
        lines.append(dash)
        has_position = any(acc.get("position_count", 0) > 0 for acc in accounts)
        if not has_position:
            lines.append("  无持仓")
        lines.append("")

        lines.append("最近交易记录（最多 20 条）")
        lines.append(dash)
        recent = trades[-20:] if len(trades) > 20 else trades
        lines.append("  时间                  策略              标的         方向               数量         价格         盈亏")
        lines.append("  " + "-" * 85)
        for t in recent:
            ts_str = str(t.get("timestamp", ""))[:19].replace("T", " ")
            sid = t.get("strategy_id", "")
            sym = t.get("symbol", "")
            side = t.get("side", "")
            qty = t.get("quantity", 0)
            price = t.get("price", 0)
            pnl = t.get("pnl", 0)
            pnl_str = f"{pnl:.2f}" if pnl != 0 else "-"
            lines.append(
                f"  {ts_str} {sid:<20s} {sym:<12s} {side:<18s} {qty:>10.2f} {price:>12.2f} {pnl_str:>10s}"
            )
        lines.append("")

        lines.append(sep)
        lines.append(f"报告生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(sep)
        lines.append("")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        return path

    def _compute_metrics(
        self, config: Dict, daily_equity: List[Dict], trades: List[Dict],
    ) -> Dict[str, Any]:
        initial_cash = config.get("initial_cash", 0)
        if not initial_cash:
            initial_cash = daily_equity[0]["equity"] if daily_equity else 0

        final_equity = daily_equity[-1]["equity"] if daily_equity else initial_cash
        total_return = (final_equity - initial_cash) / initial_cash if initial_cash else 0

        trading_days = len(daily_equity) if daily_equity else 0
        annualized = 0.0
        if trading_days > 1 and initial_cash:
            annualized = (1 + total_return) ** (365 / trading_days) - 1

        daily_returns = []
        for i in range(1, len(daily_equity)):
            prev_eq = daily_equity[i - 1]["equity"]
            curr_eq = daily_equity[i]["equity"]
            if prev_eq > 0:
                daily_returns.append((curr_eq - prev_eq) / prev_eq)

        daily_mean = sum(daily_returns) / len(daily_returns) if daily_returns else 0
        daily_std = _std(daily_returns) if daily_returns else 0
        sharpe = (daily_mean / daily_std * math.sqrt(252)) if daily_std > 0 else 0

        neg_returns = [r for r in daily_returns if r < 0]
        neg_std = _std(neg_returns) if neg_returns else 0
        sortino = (daily_mean / neg_std * math.sqrt(252)) if neg_std > 0 else 0

        peak = initial_cash
        max_dd = 0.0
        for row in daily_equity:
            eq = row["equity"]
            if eq > peak:
                peak = eq
            dd = (peak - eq) / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd

        close_trades = [t for t in trades if t.get("pnl", 0) != 0]
        winning_trades = [t for t in close_trades if t["pnl"] > 0]
        losing_trades = [t for t in close_trades if t["pnl"] < 0]

        total_trades_count = len(close_trades)
        winning_count = len(winning_trades)
        losing_count = len(losing_trades)
        win_rate = winning_count / total_trades_count if total_trades_count > 0 else 0

        profit_pnl = sum(t["pnl"] for t in winning_trades)
        loss_pnl = sum(t["pnl"] for t in losing_trades)
        profit_factor = abs(profit_pnl / loss_pnl) if loss_pnl != 0 else 0

        avg_pnl = sum(t["pnl"] for t in close_trades) / total_trades_count if total_trades_count > 0 else 0
        avg_win = profit_pnl / winning_count if winning_count > 0 else 0
        avg_loss = abs(loss_pnl / losing_count) if losing_count > 0 else 0

        largest_win = max((t["pnl"] for t in winning_trades), default=0)
        largest_loss = min((t["pnl"] for t in losing_trades), default=0)

        return {
            "total_return": total_return,
            "roe": total_return,
            "annualized_return": annualized,
            "sharpe_ratio": sharpe,
            "sortino_ratio": sortino,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "total_trades": total_trades_count,
            "winning_trades": winning_count,
            "losing_trades": losing_count,
            "avg_trade_pnl": avg_pnl,
            "largest_win": largest_win,
            "largest_loss": largest_loss,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "profit_trades_pnl": profit_pnl,
            "loss_trades_pnl": loss_pnl,
            "trading_days": trading_days,
            "daily_return_mean": daily_mean,
            "daily_return_std": daily_std,
        }

    def _format_performance_summary(self, metrics: Dict) -> str:
        lines = []
        sep = "=" * 60
        lines.append(sep)
        lines.append("绩效分析摘要")
        lines.append(sep)
        lines.append("")
        lines.append("收益指标:")
        lines.append(f"  ROE (权益回报率):       {metrics['total_return'] * 100:.2f}%  (总收益率：{metrics['total_return'] * 100:.2f}%)")
        lines.append(f"  年化收益率：         {metrics['annualized_return'] * 100:.2f}%")
        lines.append("")
        lines.append("风险指标:")
        lines.append(f"  最大回撤：           {metrics['max_drawdown'] * 100:.2f}%")
        lines.append(f"  日波动率：            {metrics['daily_return_std'] * 100:.2f}%")
        lines.append("")
        lines.append("风险调整后收益:")
        lines.append(f"  夏普比率：             {metrics['sharpe_ratio']:.2f}")
        lines.append(f"  索提诺比率：           {metrics['sortino_ratio']:.2f}")
        lines.append("")
        lines.append("交易统计:")
        lines.append(f"  总交易次数：              {metrics['total_trades']}")
        lines.append(f"  盈利次数：                {metrics['winning_trades']}")
        lines.append(f"  亏损次数：                {metrics['losing_trades']}")
        lines.append(f"  胜率：               {metrics['win_rate'] * 100:.2f}%")
        lines.append(f"  盈亏比：              {metrics['profit_factor']:.2f}")
        lines.append("")
        lines.append("盈亏分析:")
        lines.append(f"  平均盈亏：          {metrics['avg_trade_pnl']:.2f}")
        lines.append(f"  平均盈利：         {metrics['avg_win']:.2f}")
        lines.append(f"  平均亏损：          {metrics['avg_loss']:.2f}")
        lines.append(f"  最大盈利：         {metrics['largest_win']:.2f}")
        lines.append(f"  最大亏损：         {metrics['largest_loss']:.2f}")
        lines.append("")
        lines.append(sep)
        return "\n".join(lines)


def _std(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    return math.sqrt(variance)


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    elif isinstance(obj, float):
        if obj != obj:
            return None
        return obj
    elif isinstance(obj, datetime):
        return obj.isoformat()
    return obj
