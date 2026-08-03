#!/usr/bin/env python3
"""
策略核心逻辑基类

提供工具方法和回调机制，子类只需实现入场逻辑和出场逻辑
"""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Callable, TypeVar, Generic, List
import pandas as pd

from .state import BaseState
from .risk_config import RiskControlConfig
from .risk_control import RiskController, ExitSignal

StateType = TypeVar('StateType', bound=BaseState)


class BaseStrategyCore(ABC, Generic[StateType]):
    """
    策略核心逻辑基类

    子类只需实现:
    1. _get_state(symbol) - 获取状态
    2. analyze(symbol, klines_data, current_time) - 入场逻辑
    3. check_realtime_exit(symbol, current_price, ...) - 出场逻辑
    4. get_status() - 状态查询
    """

    def __init__(
        self,
        symbols: List[str],
        timeframes: List[str],
        params: Optional[Dict[str, Any]] = None,
        global_config: Optional[Dict[str, Any]] = None,
    ):
        self.symbols = symbols
        self.timeframes = timeframes
        self.params = params or {}

        # 方向过滤（从 params 中提取，Strategy 已确保是小写）
        self.direction = self.params.get("direction", "neutral")

        # 状态管理
        self._state: Dict[str, StateType] = {}

        # 策略信息（由 Strategy 类注入）
        self._strategy_name: str = ""
        self._backtest_mode: bool = False
        self._current_price: Optional[float] = None

        # 仓位回调（实盘模式）
        self._on_position_enter: Optional[Callable] = None
        self._on_position_exit: Optional[Callable] = None
        self._on_position_update: Optional[Callable] = None

        # 风控控制器（可选注入）
        self._risk_controller: Optional[RiskController] = None

        # 止损止盈检测模式（从全局配置读取）
        self._init_exit_detection_mode(global_config)

    def _init_exit_detection_mode(self, global_config: Optional[Dict[str, Any]]) -> None:
        """初始化止损止盈检测模式"""
        if global_config:
            engine_config = global_config.get("strategy_engine", {})
            self.use_bar_high_low_for_exit = engine_config.get("use_bar_high_low_for_exit", True)
        else:
            self.use_bar_high_low_for_exit = True

    def _get_exit_detection_prices(
        self,
        current_price: float,
        bar_high: Optional[float] = None,
        bar_low: Optional[float] = None,
    ) -> tuple:
        """获取止损止盈检测价格

        根据配置返回检测价格：
        - use_bar_high_low_for_exit=True 且 bar_high/bar_low 存在：返回 (bar_high, bar_low)
        - 否则：返回 (current_price, current_price)

        Returns:
            (check_high, check_low) 元组
        """
        if self.use_bar_high_low_for_exit and bar_high is not None and bar_low is not None:
            return bar_high, bar_low
        return current_price, current_price

    # ========== 配置注入方法（由 Strategy 类调用）==========

    def set_strategy_name(self, name: str) -> None:
        """设置策略名称"""
        self._strategy_name = name

    def set_backtest_mode(self, enabled: bool) -> None:
        """设置回测模式"""
        self._backtest_mode = enabled

    def set_position_callbacks(
        self,
        on_enter: Optional[Callable] = None,
        on_exit: Optional[Callable] = None,
        on_update: Optional[Callable] = None,
    ) -> None:
        """设置仓位回调函数"""
        self._on_position_enter = on_enter
        self._on_position_exit = on_exit
        self._on_position_update = on_update

    def set_risk_controller(self, config: RiskControlConfig) -> None:
        """设置风控控制器"""
        self._risk_controller = RiskController(config)

    def check_risk_control(self, symbol: str, current_price: float) -> Optional[ExitSignal]:
        """检查统一风控"""
        if not self._risk_controller:
            return None
        state = self._get_state(symbol)
        return self._risk_controller.check_exit(state, current_price)

    # ========== 回调触发方法 ==========

    def _notify_position_enter(self, symbol: str, state: StateType) -> None:
        """通知仓位进入"""
        if self._on_position_enter and not self._backtest_mode:
            self._on_position_enter(symbol, state)

    def _notify_position_exit(
        self,
        symbol: str,
        state: StateType,
        exit_price: float,
        exit_reason: str,
        is_stop_loss: bool,
        exit_time: Optional[Any] = None,
    ) -> None:
        """通知仓位退出

        Args:
            symbol: 交易标的
            state: 仓位状态对象
            exit_price: 平仓价格
            exit_reason: 平仓原因
            is_stop_loss: 是否止损
            exit_time: 平仓时间
        """
        if self._on_position_exit and not self._backtest_mode:
            self._on_position_exit(
                symbol=symbol,
                position_id=state.position_id,
                state=state,
                exit_price=exit_price,
                exit_reason=exit_reason,
                is_stop_loss=is_stop_loss,
                exit_time=exit_time,
            )

    def _notify_position_update(self, symbol: str, state: StateType) -> None:
        """通知仓位更新"""
        if self._on_position_update and not self._backtest_mode:
            self._on_position_update(symbol, state)

    # ========== 仓位操作通用方法 ==========

    def _on_before_exit_clear(
        self,
        symbol: str,
        state: StateType,
        is_stop_loss: bool,
    ) -> None:
        """
        平仓前钩子（在状态清除之前调用）

        子类可重写此方法，在平仓时执行特有逻辑（如更新递减状态）。
        无论平仓路径如何（策略特有/统一风控），都会触发此钩子。

        Args:
            symbol: 交易标的
            state: 仓位状态对象
            is_stop_loss: 是否止损平仓
        """
        pass  # 默认空实现，子类可选重写

    def _notify_exit_and_clear(
        self,
        symbol: str,
        state: StateType,
        exit_price: float,
        exit_reason: str,
        is_stop_loss: bool,
        exit_time: Optional[Any] = None,
    ) -> str:
        """
        执行平仓的核心逻辑：通知平仓 + 清除状态

        返回 action 字符串，让子类构建完整的返回结果。
        子类可以在调用此方法前后执行特有逻辑。

        Args:
            symbol: 交易标的
            state: 仓位状态
            exit_price: 平仓价格
            exit_reason: 平仓原因
            is_stop_loss: 是否止损
            exit_time: 平仓时间

        Returns:
            action: "sell_close" 或 "buy_close"
        """
        # 调用钩子（在通知和清除之前）
        self._on_before_exit_clear(symbol, state, is_stop_loss)

        is_long = state.position == "long"
        action = "sell_close" if is_long else "buy_close"

        # 通知平仓回调（在清除状态之前）
        if state.position_id:
            self._notify_position_exit(
                symbol=symbol,
                state=state,
                exit_price=exit_price,
                exit_reason=exit_reason,
                is_stop_loss=is_stop_loss,
                exit_time=exit_time,
            )

        # 清除状态
        state.clear_position(record_stop_loss=is_stop_loss, current_time=exit_time)

        return action

    # ========== K 线处理工具方法 ==========

    @staticmethod
    def parse_interval_to_minutes(interval: str) -> int:
        """
        解析时间周期为分钟数

        Args:
            interval: 时间周期字符串 (如 '1m', '15m', '1h', '4h', '1d')

        Returns:
            分钟数
        """
        interval = interval.lower()
        if interval.endswith("m"):
            try:
                return int(interval[:-1])
            except ValueError:
                return 1
        elif interval.endswith("h"):
            try:
                return int(interval[:-1]) * 60
            except ValueError:
                return 60
        elif interval.endswith("d"):
            try:
                return int(interval[:-1]) * 1440
            except ValueError:
                return 1440
        return 1

    @staticmethod
    def get_expected_last_closed_timestamp(
        current_time: datetime, interval_minutes: int
    ) -> datetime:
        """
        计算期望的最后一根闭合 K 线时间戳

        例如：
        - current_time=10:30, interval=60 → 09:00
        - current_time=10:59, interval=60 → 09:00
        - current_time=11:00, interval=60 → 10:00
        - current_time=09:30, interval=240 → 04:00

        Args:
            current_time: 当前时间
            interval_minutes: K 线周期分钟数

        Returns:
            期望的最后一根闭合 K 线时间戳
        """
        # 向下取整到周期边界
        total_minutes = current_time.hour * 60 + current_time.minute
        floored_minutes = (total_minutes // interval_minutes) * interval_minutes

        # 期望最后一根闭合 K 线 = 当前周期边界 - 一个周期
        expected_minutes = floored_minutes - interval_minutes

        # 处理跨天情况
        if expected_minutes < 0:
            expected_minutes += 24 * 60
            # 返回前一天的时间
            return (current_time - timedelta(days=1)).replace(
                hour=expected_minutes // 60,
                minute=expected_minutes % 60,
                second=0,
                microsecond=0
            )

        return current_time.replace(
            hour=expected_minutes // 60,
            minute=expected_minutes % 60,
            second=0,
            microsecond=0
        )

    @staticmethod
    def get_closed_data(
        klines_data: Dict[str, pd.DataFrame],
        timeframe: str,
        min_rows: int = 3,
        current_time: Optional[datetime] = None,
    ) -> pd.DataFrame:
        """
        获取已闭合的 K 线数据

        重要：入场判断必须使用已闭合 K 线，避免未来函数

        Args:
            klines_data: 多周期 K 线数据字典
            timeframe: 目标周期
            min_rows: 最小行数要求
            current_time: 当前 1m K 线时间，用于判断大周期是否闭合

        Returns:
            已闭合的 K 线 DataFrame，数据不足时返回空 DataFrame
        """
        df = klines_data.get(timeframe)
        if df is None or len(df) < min_rows:
            return pd.DataFrame()

        # 如果传入当前时间，使用时间查询筛选已闭合 bar
        if current_time is not None and "timestamp" in df.columns:
            interval_minutes = BaseStrategyCore.parse_interval_to_minutes(timeframe)

            # bar_end = bar开始时间 + 周期分钟数
            bar_end = df["timestamp"] + pd.Timedelta(minutes=interval_minutes)
            mask = bar_end <= current_time
            return df[mask]

        # 未传入时间，去掉最后一根（可能未闭合）
        return df.iloc[:-1]

    # ========== 抽象方法（子类必须实现）==========

    def _format_bar_ts(self, current_time: Optional[datetime]) -> str:
        """格式化当前 K 线时间戳用于诊断日志，None 时返回 'N/A'。"""
        return current_time.strftime("%Y-%m-%d %H:%M") if current_time else "N/A"

    @abstractmethod
    def _get_state(self, symbol: str) -> StateType:
        """
        获取 per-symbol 状态

        实现示例:
        def _get_state(self, symbol: str) -> MyState:
            if symbol not in self._state:
                self._state[symbol] = MyState()
            return self._state[symbol]
        """
        pass

    @abstractmethod
    def analyze(
        self,
        symbol: str,
        klines_data: Dict[str, pd.DataFrame],
        current_time: Optional[datetime] = None,
        realtime_price: Optional[float] = None,
        current_cash: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        入场分析

        实现要点:
        1. 检查已有持仓和止损日冷却
        2. 使用 get_closed_data() 获取已闭合 K 线
        3. 计算技术指标
        4. 判断入场条件
        5. 满足条件时设置状态并返回 buy/sell

        Args:
            symbol: 交易对
            klines_data: 多周期 K 线数据
            current_time: 当前时间（1m K 线时间）
            realtime_price: 实时价格（来自 1m K 线），优先使用此价格判断入场
            current_cash: 当前可用资金（用于动态资金计算，如连续盈利递减）

        Returns:
            {
                "action": "hold" | "buy" | "sell",
                "price": float,
                "strength": float,
                "metadata": {"reason": str, ...}
            }
        """
        pass

    @abstractmethod
    def check_realtime_exit(
        self,
        symbol: str,
        current_price: float,
        current_time: Optional[datetime] = None,
        bar_high: Optional[float] = None,
        bar_low: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        出场检查

        实现要点:
        1. 更新 peak_price
        2. 检查止损条件（止损时调用 state.clear_position(record_stop_loss=True)）
        3. 检查止盈条件（止盈时调用 state.clear_position(record_stop_loss=False)）
        4. 返回 buy_close/sell_close/hold

        Returns:
            {
                "action": "hold" | "buy_close" | "sell_close",
                "price": float,
                "strength": float,
                "metadata": {"reason": str, "is_stop_loss": bool}
            }
        """
        pass

    @abstractmethod
    def get_status(self) -> Dict[str, Any]:
        """获取策略状态"""
        pass