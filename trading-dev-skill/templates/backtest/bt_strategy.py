"""BacktestBTStrategy — 将真实 CTA 策略封装到 backtrader 中."""

import logging
from dataclasses import dataclass
from datetime import timezone, timedelta, datetime
from typing import Optional, Dict
from pathlib import Path
import csv

import backtrader as bt

from data_manager import Kline
from backtest.signal_mapper import SignalMapper
from strategy_core.constants import (
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TRAILING_PROFIT_ACTIVATION,
    DEFAULT_TRAILING_PROFIT_DRAWDOWN,
)

logger = logging.getLogger(__name__)


def generate_signal_csv_filename(strategy_name: str) -> str:
    """生成信号 CSV 文件名，包含时间戳以区分同日多次运行."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{strategy_name}_{timestamp}_signals.csv"


@dataclass
class SimPosition:
    size: float = 0.0
    price: float = 0.0
    side: str = ""
    entry_commission: float = 0.0


class BacktestBTStrategy(bt.Strategy):
    """
    封装真实 CTA 策略到 backtrader 中。

    手动跟踪持仓和 PnL，以信号价格直接成交，不依赖 backtrader broker 撮合。
    支持多 symbol 联合回测（共用资金池，等分资金）。
    """

    params = dict(
        cta_strategy=None,
        signal_mapper=None,
        data_manager=None,
        bt_first_day_kline=None,
        signal_csv_dir=None,
        strategy_type=None,  # 策略类型，用于输出目录
        strategy_config=None,  # 策略配置，用于 CtaSignalCSV
        signal_start_dt=None,  # 只有超过此时间才生成信号（预热期间不生成）
    )

    def __init__(self):
        self.cta_strategy = self.p.cta_strategy
        self.signal_mapper: SignalMapper = self.p.signal_mapper or SignalMapper()
        self.data_manager = self.p.data_manager
        self.signal_csv_dir = self.p.signal_csv_dir
        self.strategy_type = self.p.strategy_type  # 策略类型
        self.strategy_config = self.p.strategy_config or {}  # 策略配置
        self.signals_generated = []
        self.order_count = 0
        self.equity_history = []
        self.trades_completed: list[dict] = []
        self.klines_processed = 0
        self._trade_counter = 0
        self._daily_equity: dict[str, dict] = {}
        self._tf_equity: dict[str, dict] = {}  # 按配置周期记录权益
        self._tf_key: str = None  # 配置的最小周期（用于权益记录）
        self._bt_daily_ohlc: dict[str, dict] = {}
        self._bt_last_date = None
        self._signal_csv_path = None
        self._signal_csv_writer = None

        # 从 strategy_config 获取最小周期用于权益记录
        self._tf_key = self._extract_min_timeframe(self.strategy_config)

        self._sim_cash: float = 0.0
        self._sim_positions: Dict[str, SimPosition] = {}
        self._num_symbols: int = max(len(self.datas), 1)
        self._data_by_name: Dict[str, bt.AbstractDataBase] = {}

    def start(self):
        super().start()
        self._sim_cash = self.broker.getcash()
        self._num_symbols = max(len(self.datas), 1)

        for data in self.datas:
            name = getattr(data, "_name", "UNKNOWN")
            self._data_by_name[name] = data

        # 初始化信号 CSV 写入（使用 CtaSignalCSV 格式）
        if self.signal_csv_dir and self.cta_strategy:
            strategy_name = self.cta_strategy.strategy_name if hasattr(self.cta_strategy, 'strategy_name') else 'unknown'
            # 输出目录：直接使用传入的目录（回测结果目录）
            output_dir = Path(self.signal_csv_dir)
            # 文件名：backtest_signals.csv（简化命名）
            self._signal_csv_path = output_dir / "backtest_signals.csv"
            # 写入 CSV header（CtaSignalCSV 格式）
            from strategy_core.signal_logging.csv_adapter import SignalCsvWriter
            with open(self._signal_csv_path, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=SignalCsvWriter.FIELDNAMES)
                writer.writeheader()
            logger.info(f"[BacktestBTStrategy] 信号 CSV 已初始化: {self._signal_csv_path}")

        if self.cta_strategy:
            # 先设置回测模式标记，再启动策略
            self.cta_strategy._bt_backtest_mode = True
            self.cta_strategy.on_start()
            logger.info(f"[BacktestBTStrategy] 策略 {self.cta_strategy.strategy_name} 已启动")
            if self.p.bt_first_day_kline:
                kline = self.p.bt_first_day_kline
                for sym in self.cta_strategy.symbols:
                    if hasattr(self.cta_strategy, '_initialize_from_data'):
                        self.cta_strategy._initialize_from_data(sym, prev_kline=kline)
                        if hasattr(self.cta_strategy, '_prev_daily_kline'):
                            self.cta_strategy._prev_daily_kline[sym] = kline
                        logger.info(
                            f"[BacktestBTStrategy] 已注入 {sym} 价格线: "
                            f"H={kline.high:.2f}, L={kline.low:.2f}, C={kline.close:.2f}"
                        )

    def stop(self):
        if self.cta_strategy:
            self.cta_strategy.on_stop()
            logger.info(f"[BacktestBTStrategy] 策略 {self.cta_strategy.strategy_name} 已停止")
        super().stop()

    def prenext(self):
        self._process_all_bars()

    def next(self):
        self._process_all_bars()

    def _process_all_bars(self):
        """遍历所有 data feed，为每个 symbol 构造 Kline 并调用策略。"""
        for data in self.datas:
            kline = self._make_kline(data)
            if kline is None:
                continue

            if self.data_manager:
                ts = kline.timestamp
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                self.data_manager.set_backtest_timestamp(ts)
                # 将 K 线推入缓存（模拟 WS 推送）
                self.data_manager._on_kline_received(kline)

            self._handle_day_change(kline)

            # 预热期间不调用策略，避免产生信号和状态变化
            if self.p.signal_start_dt and kline.timestamp < self.p.signal_start_dt:
                self.klines_processed += 1
                continue

            signal = self.cta_strategy.on_kline(kline)

            if signal and self.signal_mapper:
                self.order_count += 1
                self.signals_generated.append(signal)
                self._write_signal_to_csv(signal)
                self.signal_mapper.apply(signal, self)
                logger.info(
                    f"[BacktestBTStrategy] 信号: {signal.signal_type.value} "
                    f"{signal.symbol} @ {signal.price:.2f}"
                )

            self.klines_processed += 1

        self._record_equity()

    def _record_equity(self):
        """记录当前时间点的 equity 快照。"""
        dt = self.datas[0].datetime.datetime(0)
        current_prices = {}
        for data in self.datas:
            name = getattr(data, "_name", "UNKNOWN")
            current_prices[name] = float(data.close[0])

        value = self._sim_equity(current_prices)

        self.equity_history.append({
            "date": dt,
            "value": value,
            "cash": self._sim_cash,
        })

        date_key = dt.strftime("%Y-%m-%d")
        self._daily_equity[date_key] = {
            "date": date_key,
            "equity": round(value, 2),
            "cash": round(self._sim_cash, 2),
        }

        # 按配置周期记录权益
        if self._tf_key:
            tf_fmt = self._get_tf_datetime_format(self._tf_key)
            tf_key = dt.strftime(tf_fmt)
            self._tf_equity[tf_key] = {
                "datetime": tf_key,
                "equity": round(value, 2),
                "cash": round(self._sim_cash, 2),
            }

    # 周期时间格式映射
    TF_DATETIME_FORMATS = {
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
    TF_ORDER = list(TF_DATETIME_FORMATS.keys())

    def _extract_min_timeframe(self, config: dict) -> str | None:
        """从配置中提取最小周期"""
        if not config:
            return None
        timeframes = config.get("timeframes", [])
        if isinstance(timeframes, str):
            timeframes = [timeframes]
        valid_tfs = [tf for tf in timeframes if tf in self.TF_ORDER]
        return min(valid_tfs, key=self.TF_ORDER.index) if valid_tfs else None

    def _get_tf_datetime_format(self, tf: str) -> str:
        """根据周期返回日期时间格式"""
        return self.TF_DATETIME_FORMATS.get(tf, "%Y-%m-%d")

    def _sim_equity(self, current_prices: Dict[str, float]) -> float:
        equity = self._sim_cash
        for symbol, pos in self._sim_positions.items():
            if pos.size == 0:
                continue
            price = current_prices.get(symbol)
            if price is None:
                continue
            if pos.side == "long":
                equity += (price - pos.price) * pos.size
            else:
                equity += (pos.price - price) * pos.size
        return equity

    def execute_signal(self, signal, action: str) -> None:
        """以信号价格直接成交，按等分资金计算仓位。"""
        dt = self.datas[0].datetime.datetime(0)
        self._trade_counter += 1
        trade_id = f"T{self._trade_counter:08d}"
        strategy_id = self.cta_strategy.strategy_name if self.cta_strategy else ""
        symbol = signal.symbol

        if action in ("buy", "sell"):
            # 使用信号中的 adjusted_cash（支持资金递减逻辑）
            adjusted_cash = signal.metadata.get('adjusted_cash', self._sim_cash)
            config = getattr(self, "strategy_config", {})
            if not isinstance(config, dict):
                config = {}
            leverage = float(
                signal.metadata.get(
                    "leverage",
                    config.get("capital", {}).get("leverage", 1),
                )
            )
            target_notional = signal.metadata.get("target_notional")
            alloc = (
                float(target_notional)
                if target_notional is not None
                else float(adjusted_cash) * leverage / self._num_symbols
            )
            size = alloc / signal.price
            side = "long" if action == "buy" else "short"
            entry_commission = self._calculate_commission(symbol, size, signal.price)
            self._sim_cash -= entry_commission
            self._sim_positions[symbol] = SimPosition(
                size=size,
                price=signal.price,
                side=side,
                entry_commission=entry_commission,
            )

            if self.cta_strategy and hasattr(self.cta_strategy, 'strategy_cash'):
                self.cta_strategy.strategy_cash = self._sim_cash

            self.trades_completed.append({
                "trade_id": trade_id,
                "strategy_id": strategy_id,
                "symbol": symbol,
                "side": "BUY" if action == "buy" else "SELL",
                "quantity": round(size, 6),
                "price": signal.price,
                "commission": round(entry_commission, 8),
                "slippage": 0.0,
                "pnl": 0.0,
                "timestamp": dt.isoformat() if hasattr(dt, 'isoformat') else str(dt),
                "comment": action,
            })
            logger.debug(f"[BacktestBTStrategy] {action.upper()} {symbol} {size:.6f} @ {signal.price:.2f}")

        elif action == "close":
            pos = self._sim_positions.pop(symbol, None)
            if not pos or pos.size == 0:
                return

            if pos.side == "long":
                gross_pnl = (signal.price - pos.price) * pos.size
                side = "SELL_CLOSE"
            else:
                gross_pnl = (pos.price - signal.price) * pos.size
                side = "BUY_CLOSE"

            exit_commission = self._calculate_commission(symbol, pos.size, signal.price)
            net_pnl = gross_pnl - pos.entry_commission - exit_commission
            # 开仓手续费已经在开仓时扣除，此处只加入毛盈亏并扣除平仓手续费。
            self._sim_cash += gross_pnl - exit_commission

            # 同步更新策略的可用资金（用于动态资金计算）
            if self.cta_strategy and hasattr(self.cta_strategy, 'strategy_cash'):
                self.cta_strategy.strategy_cash = self._sim_cash

            self.trades_completed.append({
                "trade_id": trade_id,
                "strategy_id": strategy_id,
                "symbol": symbol,
                "side": side,
                "quantity": round(pos.size, 6),
                "price": signal.price,
                "commission": round(exit_commission, 8),
                "slippage": 0.0,
                "pnl": round(net_pnl, 2),
                "timestamp": dt.isoformat() if hasattr(dt, 'isoformat') else str(dt),
                "comment": "sell_close" if side == "SELL_CLOSE" else "buy_close",
            })
            logger.debug(
                f"[BacktestBTStrategy] {side} {symbol} {pos.size:.6f} @ {signal.price:.2f} "
                f"gross={gross_pnl:.2f} commission={pos.entry_commission + exit_commission:.2f} "
                f"net={net_pnl:.2f}"
            )

    def _calculate_commission(self, symbol: str, size: float, price: float) -> float:
        """使用 Cerebro broker 的手续费配置计算单边手续费。"""
        data = self._data_by_name.get(symbol) if hasattr(self, '_data_by_name') else None
        if data is None:
            for candidate in getattr(self, 'datas', []):
                if getattr(candidate, '_name', None) == symbol:
                    data = candidate
                    break
        if data is None:
            return 0.0

        try:
            commission_info = self.broker.getcommissioninfo(data)
            commission = commission_info.getcommission(abs(size), price)
            if not isinstance(commission, (int, float)):
                return 0.0
            return max(float(commission), 0.0)
        except (AttributeError, TypeError, ValueError):
            return 0.0

    def _handle_day_change(self, kline: Kline) -> None:
        ts = kline.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        current_date = ts.date()

        if not hasattr(self.cta_strategy, '_prev_daily_kline'):
            return

        if self._bt_last_date is None:
            self._bt_last_date = current_date
            return

        if current_date <= self._bt_last_date:
            for sym in self.cta_strategy.symbols:
                if kline.symbol.upper() == sym:
                    self._update_daily_ohlc(sym, kline, current_date)
            return

        for sym in self.cta_strategy.symbols:
            if sym in self._bt_daily_ohlc and sym in self.cta_strategy._prev_daily_kline:
                ohlc = self._bt_daily_ohlc[sym]
                prev_kline = type('FakeKline', (), {
                    'symbol': sym,
                    'interval': '1d',
                    'timestamp': ts.replace(tzinfo=timezone.utc) - timedelta(days=1),
                    'open': ohlc['open'],
                    'high': ohlc['high'],
                    'low': ohlc['low'],
                    'close': ohlc['close'],
                    'volume': ohlc['volume'],
                })()
                self.cta_strategy._prev_daily_kline[sym] = prev_kline
                if hasattr(self.cta_strategy, '_initialize_from_data'):
                    self.cta_strategy._initialize_from_data(sym, prev_kline=prev_kline)
                logger.info(
                    f"[BacktestBTStrategy] 日期变化 {self._bt_last_date} -> {current_date}，"
                    f"{sym} 价格线已更新: H={ohlc['high']:.2f}, L={ohlc['low']:.2f}, C={ohlc['close']:.2f}"
                )
            self._bt_daily_ohlc[sym] = {
                'open': kline.open if kline.symbol.upper() == sym else 0,
                'high': kline.high if kline.symbol.upper() == sym else 0,
                'low': kline.low if kline.symbol.upper() == sym else float('inf'),
                'close': kline.close if kline.symbol.upper() == sym else 0,
                'volume': kline.volume if kline.symbol.upper() == sym else 0,
            }

        self._bt_last_date = current_date

    def _update_daily_ohlc(self, sym: str, kline: Kline, date) -> None:
        if sym not in self._bt_daily_ohlc:
            self._bt_daily_ohlc[sym] = {
                'open': kline.open,
                'high': kline.high,
                'low': kline.low,
                'close': kline.close,
                'volume': kline.volume,
            }
        else:
            ohlc = self._bt_daily_ohlc[sym]
            ohlc['high'] = max(ohlc['high'], kline.high)
            ohlc['low'] = min(ohlc['low'], kline.low)
            ohlc['close'] = kline.close
            ohlc['volume'] += kline.volume

    def _make_kline(self, data: bt.AbstractDataBase) -> Optional[Kline]:
        try:
            dt = data.datetime.datetime(0)
            # 添加 UTC 时区，与 DataFrame 中的 timestamp 一致
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            name = getattr(data, "_name", "UNKNOWN")
            # 始终使用 1m 周期，与实盘 WS 推送一致
            symbol = name
            interval = "1m"
            return Kline(
                symbol=symbol,
                interval=interval,
                timestamp=dt,
                open=float(data.open[0]),
                high=float(data.high[0]),
                low=float(data.low[0]),
                close=float(data.close[0]),
                volume=float(data.volume[0]),
            )
        except Exception as e:
            logger.error(f"[BacktestBTStrategy] 构造 Kline 失败: {e}")
            return None

    def get_daily_equity(self) -> list[dict]:
        return [self._daily_equity[k] for k in sorted(self._daily_equity.keys())]

    def get_tf_equity(self) -> list[dict]:
        """获取按配置周期记录的权益曲线"""
        return [self._tf_equity[k] for k in sorted(self._tf_equity.keys())]

    def get_tf_key(self) -> str:
        """获取配置的最小周期"""
        return self._tf_key

    def _write_signal_to_csv(self, signal):
        """将信号写入 CSV 文件（使用 CtaSignalCSV 格式）"""
        if not self._signal_csv_path:
            return

        from strategy_core.signal_logging.csv_adapter import CtaSignalCSV, SignalCsvWriter

        # 从策略配置获取参数
        config = self.strategy_config or {}
        capital = config.get('capital', {})
        signal_cfg = config.get('signal', {})
        risk = config.get('risk', {})

        # 构建 CtaSignalCSV
        # 从统一 risk 配置获取风控参数
        trailing = risk.get('trailing_profit', {})

        # 使用信号中的 adjusted_cash（支持资金递减逻辑）
        adjusted_cash = signal.metadata.get('adjusted_cash', capital.get('max_cash', 100))

        cta_signal = CtaSignalCSV.from_signal(
            signal=signal,
            strategy_name=self.cta_strategy.strategy_name if self.cta_strategy else '',
            strategy_version=config.get('version', '1'),
            interval='1m',
            strategy_params=config.get('params', {}),
            strategy_cash=adjusted_cash,
            strategy_parts=capital.get('max_parts', 1),
            strategy_type=config.get('strategy_type', 'CTAFutureFactory'),
            strategy_type_name=config.get('strategy', {}).get('name', ''),
            risk_strategy_type=config.get('risk_strategy_type', 'cta_intraday'),
            user_id=config.get('user_id', 1),
            signal_exchange=signal_cfg.get('exchange', 'binance'),
            signal_order_type=signal_cfg.get('order_type', 1),
            leverage=capital.get(
                'leverage',
                getattr(self.cta_strategy, 'leverage', 5),
            ),
            risk_stop_loss_pct=risk.get('fixed_stop_loss_pct', DEFAULT_STOP_LOSS_PCT),
            risk_trailing_profit_activation=trailing.get('activation_pct', DEFAULT_TRAILING_PROFIT_ACTIVATION),
            risk_trailing_profit_drawdown=trailing.get('drawdown_pct', DEFAULT_TRAILING_PROFIT_DRAWDOWN),
        )

        # 写入 CSV
        with open(self._signal_csv_path, 'a', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=SignalCsvWriter.FIELDNAMES)
            writer.writerow(cta_signal.to_csv_row())
