#!/usr/bin/env python3
"""
策略基类

包含所有策略共有的功能，新增策略只需实现入场逻辑和出场逻辑
"""

from abc import ABC, abstractmethod
from datetime import datetime, timezone, date
from typing import Optional, Any, Dict, List
import logging

from data_manager import DataManager
from strategy_core.signal_logging import Signal, SignalType
from strategy_core.position_persistence import PositionPersistence
from strategy_core.stop_loss_cooldown_persistence import StopLossCoolDownPersistence
from strategy_core.base.risk_config import RiskControlConfig
from strategy_core.constants import (
    TF_MINUTES,
    DEFAULT_MIN_BARS_REQUIRED,
    INDICATOR_WARMUP_BARS,
)

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """
    策略基类 - 包含所有策略共有的功能

    新增策略只需:
    1. 设置类属性: STRATEGY_TYPE, DEFAULT_TIMEFRAME
    2. 实现 _create_core() 创建核心逻辑实例
    3. 实现 _get_indicator_timeframes() 返回指标周期
    4. (可选) 重写 State 类添加特有字段

    回测兼容性:
    - 基类自动处理 backtest_mode 判断
    - 仓位持久化回测时自动禁用
    """

    # ========== 子类必须设置的类属性 ==========
    STRATEGY_TYPE: str = ""       # 策略类型名称 (目录名)
    DEFAULT_TIMEFRAME: str = "1h"  # 默认主周期

    def __init__(
        self,
        data_manager: DataManager,
        config: Optional[Dict[str, Any]] = None,
        strategy_name: Optional[str] = None,
        trading_mode: str = "live",
    ):
        # 配置必须由入口注入（来自 per-symbol overrides），不再回退读共享层 config.yaml
        self.config = config or {}
        self.data_manager = data_manager

        # 外部传入的标准化策略名称
        self._external_strategy_name = strategy_name

        # 运行模式
        self._trading_mode = trading_mode
        self._paper_trading_mode = (trading_mode == "paper_trading")

        # 解析通用配置
        self._parse_common_config()

        # 运行状态
        self._running = False
        self._paused = False
        self._last_exit_signal_time: Dict[str, datetime] = {}  # 防止平仓信号重复
        self._current_kline_timestamp: Optional[datetime] = None
        self._current_price: Optional[float] = None
        self._backtest_mode = False

        # 创建核心逻辑
        self._core = self._create_core()

    def _parse_common_config(self) -> None:
        """解析通用配置 - 所有策略相同"""
        self.version = self.config.get("version", "1")

        # symbols
        symbols = self.config.get("symbols", ["BTCUSDT"])
        if isinstance(symbols, str):
            symbols = [symbols]
        self.symbols = symbols

        # timeframes
        timeframes = self.config.get("timeframes", [self.DEFAULT_TIMEFRAME])
        if isinstance(timeframes, str):
            timeframes = [timeframes]
        self.timeframes = timeframes
        self.main_timeframe = timeframes[0] if timeframes else self.DEFAULT_TIMEFRAME

        self.direction = self.config.get("direction", "neutral")
        # 转换为小写，确保一致性
        self.direction = self.direction.lower() if isinstance(self.direction, str) else "neutral"

        self.params = self.config.get("params", {})
        # 将顶层 direction 传入 params，确保 Core 能正确获取
        self.params["direction"] = self.direction

        # signal 配置
        signal_config = self.config.get("signal", {})
        self.min_strength = signal_config.get("min_strength", 0.5)
        self.cooldown_ms = signal_config.get("cooldown_ms", 60000)

        # capital 配置
        capital = self.config.get("capital", {})
        self.strategy_cash = capital.get("max_cash", 100)
        self.strategy_parts = capital.get("max_parts", 1)

        # leverage 配置
        # 优先级：config.yaml > 默认值
        # 实盘默认 5 倍，冒烟(paper_trading) 默认 1 倍
        default_leverage = 1 if self._paper_trading_mode else 5
        self.leverage = capital.get("leverage", default_leverage)

        # 风控配置
        risk_config = self.config.get('risk', {})
        self.risk_config = RiskControlConfig.from_dict(risk_config)

    # ========== 抽象方法（子类实现）==========

    @abstractmethod
    def _create_core(self):
        """
        创建核心逻辑实例

        实现示例:
        def _create_core(self):
            return MyStrategyCore(
                symbols=self.symbols,
                timeframes=self.timeframes,
                params=self.params,
            )
        """
        pass

    def _get_indicator_timeframes(self) -> set:
        """
        收集所有指标使用的 K 线周期集合

        实现示例:
        def _get_indicator_timeframes(self) -> set:
            tf_set = set(self.timeframes)
            p = self.params or {}
            tf_set.add(p.get("my_indicator_timeframes", "1h"))
            return tf_set
        """
        pass

    def _get_global_config(self) -> Dict[str, Any]:
        """
        获取全局系统配置（从 settings.yaml）

        子类可在 _create_core() 中调用，将全局配置传递给 Core。

        Returns:
            全局配置字典
        """
        import yaml
        try:
            with open("config/settings.yaml", "r", encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"加载全局配置失败: {e}")
            return {}

    # ========== 通用属性（基类实现）==========

    @property
    def strategy_name(self) -> str:
        """标准化策略 ID（入口算一次传入，直接复用，无回退）

        格式: {PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}_{MODE}
        由 run_strategy.py / run_strategies_manager.py 通过
        build_strategy_id_from_overrides 生成后传入。
        """
        return self._external_strategy_name

    @property
    def name(self) -> str:
        """策略类型名称（目录名）"""
        return self.STRATEGY_TYPE

    @property
    def subscribed_symbols(self) -> set:
        return set(self.symbols)

    @property
    def poll_timeframes(self) -> List[str]:
        return ["1m"]

    @property
    def signal_fields(self) -> Dict[str, Any]:
        return {
            "strategy_name": self.strategy_name,
            "symbols": self.symbols,
            "timeframes": self.timeframes,
            "strategy_type": self.name,
            "version": self.version,
            "main_timeframe": self.main_timeframe,
            "strategy_cash": self.strategy_cash,
            "strategy_parts": self.strategy_parts,
            "leverage": self.leverage,
        }

    # ========== 生命周期方法（基类实现）==========

    def on_start(self) -> None:
        """策略启动"""
        logger.info(f"策略 {self.strategy_name} 启动，标的：{self.symbols}")
        self._running = True
        self._paused = False
        self._auto_load_data_if_needed()

        if self.data_manager:
            for symbol in self.symbols:
                self.data_manager.register_timeframes(symbol, list(self._get_indicator_timeframes()))
                self.data_manager.reset_kline_tracking(symbol, "1m")

        # 判断回测模式（支持两种设置方式）
        # 1. 回测模式：bt_strategy.py 在 on_start() 后设置 _bt_backtest_mode 属性
        #    此时需要先检查是否已设置该属性
        # 2. 实盘模式：从 data_manager.config 读取
        if hasattr(self, '_bt_backtest_mode') and self._bt_backtest_mode:
            # 回测模式：属性已被 bt_strategy.py 设置
            self._backtest_mode = True
        else:
            # 实盘模式或首次启动：从配置读取
            self._backtest_mode = (
                getattr(self.data_manager.config, "backtest_mode", False)
                if self.data_manager else False
            )

        # 注入配置到 core
        self._core.set_strategy_name(self.strategy_name)
        self._core.set_backtest_mode(self._backtest_mode)
        self._core.set_risk_controller(self.risk_config)

        # 实盘模式：设置仓位回调并恢复状态
        if not self._backtest_mode:
            self._core.set_position_callbacks(
                on_enter=self._on_position_enter,
                on_exit=self._on_position_exit,
                on_update=self._on_position_update,
            )
            self._restore_position_state()

    def on_stop(self) -> None:
        """策略停止"""
        logger.info(f"策略 {self.strategy_name} 停止")
        self._running = False

    def on_pause(self) -> None:
        """策略暂停"""
        self._paused = True

    def on_resume(self) -> None:
        """策略恢复"""
        self._paused = False

    # ========== 仓位持久化（基类实现，回测时自动跳过）==========

    def _restore_position_state(self) -> None:
        """恢复仓位状态和止损冷却"""
        persistence = PositionPersistence()
        cooldown_persistence = StopLossCoolDownPersistence()

        for symbol in self.symbols:
            key = self._external_strategy_name
            state = self._core._get_state(symbol)

            # 恢复仓位状态
            saved = persistence.load(key)
            if saved and saved.get("position"):
                state.restore_from_dict(saved)
                logger.info(f"恢复 {symbol} 仓位: {state.position_id} @ {state.entry_price}")

            # 恢复止损冷却
            stop_loss_date = cooldown_persistence.load(key)
            if stop_loss_date:
                state.stop_loss_date = stop_loss_date
                # 检查是否过期
                if stop_loss_date < date.today():
                    cooldown_persistence.clear(key)
                    state.stop_loss_date = None
                    logger.info(f"[{symbol}] 止损冷却已过期（{stop_loss_date}），已清除")
                else:
                    logger.info(f"[{symbol}] 恢复止损冷却: stop_loss_date={stop_loss_date}")

    def _on_position_enter(self, symbol: str, state) -> None:
        """开仓时持久化"""
        persistence = PositionPersistence()
        key = self._external_strategy_name
        persistence.save_on_entry(
            strategy_name=key,
            position_id=state.position_id,
            state=state.to_persist_dict(),
            trading_mode=self._trading_mode,
        )
        logger.info(f"[{symbol}] 仓位持久化: {state.position_id} @ {state.entry_price}")

    def _on_position_exit(
        self,
        symbol: str,
        position_id: str,
        state: Any,
        exit_price: float,
        exit_reason: str,
        is_stop_loss: bool,
        exit_time: Optional[Any] = None,
    ) -> None:
        """平仓时：记录历史 + 清除持久化"""
        from strategy_core.history_position_logger import HistoryPositionLogger

        strategy_id = self._external_strategy_name
        exit_ts = exit_time or datetime.now(timezone.utc)
        exit_timestamp = (
            int(exit_ts.timestamp())
            if isinstance(exit_ts, datetime)
            else int(exit_ts)
        )

        # 1. 记录历史仓位
        HistoryPositionLogger().log_position_exit(
            strategy_name=strategy_id,
            symbol=symbol,
            position_id=position_id,
            position_type=state.position,
            entry_price=state.entry_price,
            exit_price=exit_price,
            entry_time=state.entry_time,
            exit_time=exit_ts,
            entry_timestamp=state.entry_timestamp,
            exit_timestamp=exit_timestamp,
            peak_price=state.peak_price,
            stop_price=state.stop_price,
            max_pnl_pct=state.max_pnl_pct,
            min_pnl_pct=state.min_pnl_pct,
            exit_reason=exit_reason,
            is_stop_loss=is_stop_loss,
            atr_at_entry=getattr(state, 'atr_at_entry', 0.0),
            trail_activated=getattr(state, 'trail_activated', False),
            trading_mode=self._trading_mode,
        )

        # 2. 清除当前仓位持久化
        PositionPersistence().clear_on_exit(
            strategy_name=strategy_id,
            position_id=position_id,
        )
        logger.info(f"[{symbol}] 仓位持久化已清除: {position_id}")

    def _on_position_update(self, symbol: str, state) -> None:
        """状态更新时持久化"""
        updates = {
            "peak_price": state.peak_price,
            "stop_price": state.stop_price,
        }
        # 持久化 trail_activated（如果存在）
        if hasattr(state, "trail_activated"):
            updates["trail_activated"] = state.trail_activated
        PositionPersistence().update_state(
            strategy_name=self._external_strategy_name,
            position_id=state.position_id,
            updates=updates,
        )

    # ========== on_kline 核心框架（基类实现）==========

    def on_kline(self, kline: Any) -> Optional[Signal]:
        """
        K 线处理 - 通用框架

        执行流程:
        1. 检查运行状态
        2. 解析 K 线信息
        3. 有持仓 → 调用 check_realtime_exit()
        4. 无持仓 → 调用 analyze()
        5. 信号强度过滤
        6. 创建信号
        """
        if not self._running or self._paused:
            return None

        # 解析 K 线信息
        trigger_symbol = self._parse_kline_symbol(kline)
        if trigger_symbol and trigger_symbol not in self.symbols:
            return None
        if not trigger_symbol:
            trigger_symbol = self.symbols[0]

        self._update_kline_info(kline)
        current_price = self._parse_kline_price(kline)
        bar_high = self._parse_kline_high(kline)
        bar_low = self._parse_kline_low(kline)

        # 同步价格到 core
        if current_price and current_price > 0:
            self._current_price = current_price
            self._core._current_price = current_price

        state = self._core._get_state(trigger_symbol)

        # 有持仓 → 检查出场
        if state.is_in_position():
            if current_price and current_price > 0:
                position_snapshot = self._snapshot_position(state)
                trail_before = getattr(state, "trail_activated", False)
                signal = self._check_exit(trigger_symbol, current_price, bar_high, bar_low)
                self._log_position_diagnostic(trigger_symbol, state, signal, current_price,
                                              position_snapshot=position_snapshot)
                if signal:
                    return signal
                # 未出场：若移动止损状态被推进，落盘持久化。
                # 必须在 signal 判空之后 —— 出场路径已由 _notify_position_exit
                # 清理持久化，此处再写会把清空后的状态覆盖回磁盘。
                self._persist_position_update_if_changed(
                    trigger_symbol, state, position_snapshot, trail_before
                )
            return None

        # 无持仓 → 入场分析
        klines_data = self._fetch_multi_timeframe_data(trigger_symbol)
        if not klines_data:
            return None

        result = self._core.analyze(
            trigger_symbol,
            klines_data,
            current_time=self._current_kline_timestamp,
            realtime_price=current_price,  # 传入实时价格（来自 1m K 线）
            current_cash=self.strategy_cash,  # 传入当前可用资金
        )

        if not result:
            return None

        action = result["action"]
        price = result["price"]
        strength = result.get("strength", 0.5)
        reason = result.get("metadata", {}).get("reason", "")

        # 输出入场诊断日志
        self._log_entry_diagnostic(trigger_symbol, action, price, strength, reason)

        if strength < self.min_strength:
            return None

        return self._create_signal(trigger_symbol, action, price, strength, result.get("metadata", {}))

    def _log_entry_diagnostic(
        self,
        symbol: str,
        action: str,
        price: float,
        strength: float,
        reason: str,
    ) -> None:
        """输出入场诊断日志"""
        ts = self._current_kline_timestamp or datetime.now(timezone.utc)
        price_str = f"{price:.2f}" if price else "0"

        log_msg = (
            f"[Signal] {self.strategy_name} | {symbol} {self.main_timeframe} "
            f"@ {ts} | {action} | close={price_str} | "
            f"direction={self.direction} | position=none | "
            f"strength={strength:.2f} | reason={reason}"
        )

        if action == "hold":
            logger.debug(log_msg)
        else:
            logger.info(log_msg)

    @staticmethod
    def _snapshot_position(state: Any) -> Dict[str, Any]:
        """快照持仓关键字段（check_realtime_exit 内部会清空 state）"""
        return {
            "position": state.position,
            "entry_price": state.entry_price,
            "stop_price": state.stop_price,
            "peak_price": state.peak_price,
        }

    def _persist_position_update_if_changed(
        self,
        symbol: str,
        state: Any,
        snapshot: Dict[str, Any],
        trail_before: bool,
    ) -> None:
        """移动止损状态发生变化时触发持久化

        peak_price / stop_price / trail_activated 会在持仓期间被推进
        （risk_control 的回落止盈、策略的 SAR 跟踪止损等）。这些字段会被
        state.from_persist_dict() 读回，但此前没有任何写回路径 ——
        进程重启后峰值归零、已抬高的止损位丢失。

        仅在字段真实变化时写盘，避免每根 K 线都产生 IO。
        回测模式由 _notify_position_update 内部的 backtest_mode 判据拦下。
        """
        if not state.is_in_position():
            return
        changed = (
            state.peak_price != snapshot.get("peak_price")
            or state.stop_price != snapshot.get("stop_price")
            or getattr(state, "trail_activated", False) != trail_before
        )
        if changed:
            self._core._notify_position_update(symbol, state)

    def _log_position_diagnostic(
        self,
        symbol: str,
        state: Any,
        signal: Optional[Signal],
        current_price: float,
        position_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
        """输出持仓诊断日志

        Args:
            symbol: 交易对
            state: 当前状态对象（check_realtime_exit 后可能已清空）
            signal: 出场信号（None 表示未触发出场）
            current_price: 当前价格
            position_snapshot: check_realtime_exit 前的状态快照，
                              用于在 state 被清空后仍有正确的日志数据
        """
        ts = self._current_kline_timestamp or datetime.now(timezone.utc)

        action = "hold"
        reason = ""
        if signal:
            action = signal.signal_type.value.lower()
            reason = signal.metadata.get("reason", "")

        # 优先用快照（check_realtime_exit 可能已清空 state），回退到 state 字段
        snap_position = position_snapshot.get("position") if position_snapshot else None
        snap_entry = position_snapshot.get("entry_price", 0.0) if position_snapshot else 0.0
        snap_stop = position_snapshot.get("stop_price", 0.0) if position_snapshot else 0.0
        snap_peak = position_snapshot.get("peak_price", 0.0) if position_snapshot else 0.0

        log_position = snap_position or state.position or 'none'
        log_entry = snap_entry if snap_entry > 0 else state.entry_price
        log_stop = snap_stop if snap_stop > 0 else state.stop_price
        log_peak = snap_peak if snap_peak > 0 else state.peak_price

        # 计算 ROI
        roi = 0.0
        if log_entry > 0 and current_price:
            if log_position == "long":
                roi = (current_price - log_entry) / log_entry
            elif log_position == "short":
                roi = (log_entry - current_price) / log_entry

        price_str = f"{current_price:.2f}" if current_price else "0"

        log_msg = (
            f"[Signal] {self.strategy_name} | {symbol} 1m "
            f"@ {ts} | {action} | close={price_str} | "
            f"position={log_position} | entry={log_entry:.2f} | "
            f"ROI={roi*100:.2f}% | stop={log_stop:.2f} | "
            f"peak={log_peak:.2f} | reason={reason}"
        )

        if action == "hold":
            logger.debug(log_msg)
        else:
            logger.info(log_msg)

    # ========== 辅助方法（基类实现）==========

    def _check_exit(
        self,
        symbol: str,
        current_price: float,
        bar_high: Optional[float],
        bar_low: Optional[float],
    ) -> Optional[Signal]:
        """检查出场 - 策略特有逻辑优先，统一风控作为兜底"""
        # 检查是否在平仓冷却期内（防止同一 K 线重复发送）
        # 使用 K 线时间而非真实时间，确保回测和实盘行为一致
        last_exit_time = self._last_exit_signal_time.get(symbol)
        if last_exit_time and self._current_kline_timestamp:
            # 如果上次平仓时间和当前 K 线时间相同，跳过（同一根 K 线）
            if last_exit_time == self._current_kline_timestamp:
                logger.debug(f"[{symbol}] 同一根 K 线内，跳过出场检查")
                return None

        # 1. 先检查策略特有出场逻辑
        exit_result = self._core.check_realtime_exit(
            symbol,
            current_price,
            current_time=self._current_kline_timestamp,
            bar_high=bar_high,
            bar_low=bar_low,
        )
        action = exit_result.get("action", "hold")
        if action in ("buy_close", "sell_close"):
            # 记录平仓时间（使用 K 线时间）
            self._last_exit_signal_time[symbol] = self._current_kline_timestamp
            return self._create_signal(
                symbol,
                exit_result["action"],
                exit_result["price"],
                exit_result.get("strength", 0.8),
                exit_result.get("metadata", {}),
            )

        # 2. 策略未触发时，检查统一风控（作为兜底）
        risk_exit = self._core.check_risk_control(symbol, current_price)
        if risk_exit:
            state = self._core._get_state(symbol)
            action = self._core._notify_exit_and_clear(
                symbol=symbol,
                state=state,
                exit_price=current_price,
                exit_reason=risk_exit.reason,
                is_stop_loss=risk_exit.is_stop_loss,
                exit_time=self._current_kline_timestamp,
            )
            # 记录平仓时间（使用 K 线时间）
            self._last_exit_signal_time[symbol] = self._current_kline_timestamp
            return self._create_signal(
                symbol,
                action,
                current_price,
                0.8,
                {"reason": risk_exit.reason, "is_stop_loss": risk_exit.is_stop_loss},
            )

        return None

    def _fetch_multi_timeframe_data(self, symbol: str) -> Dict[str, Any]:
        """获取多周期 K 线数据

        支持通过 params.kline_limits 配置每个周期的 K 线数量：
        params:
          kline_limits:
            1d: 30
            4h: 50
            15m: 100
        """
        klines_data = {}
        kline_limits = self.params.get("kline_limits", {})

        for tf in self._get_indicator_timeframes():
            # 优先使用配置的 limit，否则默认 200
            limit = kline_limits.get(tf, 200)
            df = self.data_manager.get_dataframe_cached(symbol=symbol, interval=tf, limit=limit)
            if df is not None and not df.empty:
                klines_data[tf] = df
        return klines_data
    def _create_signal(
        self,
        symbol: str,
        action: str,
        price: float,
        strength: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Signal]:
        """创建信号"""
        action_map = {
            "buy": SignalType.BUY,
            "sell": SignalType.SELL,
            "buy_close": SignalType.BUY_CLOSE,
            "sell_close": SignalType.SELL_CLOSE,
        }

        signal_type = action_map.get(action)
        if not signal_type:
            return None

        direction = "long" if action in ("buy", "sell_close") else "short"

        return Signal(
            strategy_id=self._external_strategy_name,
            strategy_type=self.name,
            signal_type=signal_type,
            symbol=symbol,
            price=price,
            strength=strength,
            direction=direction,
            timestamp=self._current_kline_timestamp or datetime.now(timezone.utc),
            metadata=metadata or {},
        )

    def _calc_required_history_days(self) -> int:
        """
        计算策略所需的历史数据天数，子类可重写。

        默认实现：基于最大时间周期，按 INDICATOR_WARMUP_BARS 根 K 线 + 5 天缓冲。
        子类可根据具体技术指标需求重写此方法。

        为什么不是 15 根：ADX 的 MIN_ROWS = 100，RSI/ATR 是 period*3
        （period=14 时 42 根）。原先固定 15 根导致 4h 只补 42 根、8h 只补
        30 根、1d 只补 20 根 —— 全部低于 ADX 阈值。指标层只 `warnings.warn`
        不阻断，于是策略拿着不准确的 ADX 照常发信号，且日志里只有一行
        UserWarning。补齐天数必须以最苛刻的指标为准。

        未登记到 TF_MINUTES 的周期会让 max_minutes=0 而静默退回 7 天，
        见 constants.py 中的说明。

        Returns:
            所需历史数据天数（最小 7 天）
        """
        timeframes = self._get_indicator_timeframes()
        if not timeframes:
            return 7

        # 取最大周期
        max_minutes = 0
        for tf in timeframes:
            minutes = TF_MINUTES.get(tf.lower(), 0)
            if minutes > max_minutes:
                max_minutes = minutes

        if max_minutes == 0:
            return 7

        # 预热根数对应的天数 + 5 天缓冲
        days = (INDICATOR_WARMUP_BARS * max_minutes) / 1440 + 5

        return max(int(days), 7)

    def _auto_load_data_if_needed(self) -> None:
        """自动加载缺失数据或数据量不足时补齐"""
        if not self.data_manager:
            return

        timeframes_to_load = list(self._get_indicator_timeframes())
        if "1m" not in timeframes_to_load:
            timeframes_to_load.append("1m")

        # 使用策略声明的历史天数
        required_days = self._calc_required_history_days()

        for symbol in self.symbols:
            for timeframe in timeframes_to_load:
                # 检查是否需要加载/补齐数据
                need_load, reason = self._check_data_needed(symbol, timeframe)
                if need_load:
                    self._load_data(symbol, timeframe, required_days, reason)

    def _check_data_needed(self, symbol: str, timeframe: str) -> tuple[bool, str]:
        """检查是否需要加载或补齐数据，返回 (need_load, reason)"""
        filepath = self.data_manager._get_file_path(symbol, timeframe)

        # 文件不存在
        if not filepath.exists():
            return True, "文件不存在"

        # 检查数据量是否足够
        df = self.data_manager.get_dataframe_cached(symbol=symbol, interval=timeframe, limit=500)
        current_bars = len(df) if df is not None and not df.empty else 0
        min_bars = self._get_min_bars_for_timeframe(timeframe)

        if current_bars < min_bars:
            return True, f"数据不足 ({current_bars}/{min_bars} 根)"

        return False, ""

    def _load_data(self, symbol: str, timeframe: str, days: int, reason: str) -> None:
        """加载或补齐数据"""
        try:
            logger.info(f"{symbol} {timeframe}: {reason}，加载 {days} 天数据")
            self.data_manager.auto_load_missing_data(
                symbol=symbol,
                intervals=[timeframe],
                days=days
            )
        except Exception as e:
            logger.error(f"自动加载数据失败：{e}")

    def _get_min_bars_for_timeframe(self, timeframe: str) -> int:
        """获取指定时间框架需要的最小 K 线数量，子类可重写"""
        return DEFAULT_MIN_BARS_REQUIRED

    # K线解析方法
    def _parse_kline_symbol(self, kline: Any) -> Optional[str]:
        if hasattr(kline, "symbol"):
            return kline.symbol
        elif isinstance(kline, dict) and "symbol" in kline:
            return kline.get("symbol")
        return None

    def _parse_kline_price(self, kline: Any) -> Optional[float]:
        price = float(kline.close) if hasattr(kline, "close") else None
        if price is None and isinstance(kline, dict):
            price = float(kline.get("close", 0))
        return price if price and price > 0 else None

    def _parse_kline_high(self, kline: Any) -> Optional[float]:
        if hasattr(kline, "high"):
            return float(kline.high)
        elif isinstance(kline, dict):
            return float(kline.get("high", 0))
        return None

    def _parse_kline_low(self, kline: Any) -> Optional[float]:
        if hasattr(kline, "low"):
            return float(kline.low)
        elif isinstance(kline, dict):
            return float(kline.get("low", 0))
        return None

    def _update_kline_info(self, kline: Any) -> None:
        if hasattr(kline, "timestamp"):
            self._current_kline_timestamp = kline.timestamp
        elif isinstance(kline, dict) and "timestamp" in kline:
            self._current_kline_timestamp = kline.get("timestamp")

    def get_status(self) -> Dict[str, Any]:
        """获取策略状态"""
        return {
            "strategy_name": self.strategy_name,
            "name": self.name,
            "running": self._running,
            "paused": self._paused,
            "symbols": self.symbols,
            "timeframes": self.timeframes,
            "core_status": self._core.get_status(),
            "signal_fields": self.signal_fields,
        }
