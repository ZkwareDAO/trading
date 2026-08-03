"""SignalMapper — 将 Signal 映射为回测交易操作."""

from typing import Optional, Any

from strategy_core.signal_logging.storage import Signal, SignalType


_SIGNAL_TO_ACTION = {
    SignalType.BUY: "buy",
    SignalType.SELL: "sell",
    SignalType.BUY_CLOSE: "close",
    SignalType.SELL_CLOSE: "close",
    SignalType.FLAT: "close",
    SignalType.REVERSE_LONG: "buy",
    SignalType.REVERSE_SHORT: "sell",
}


class SignalMapper:
    """将策略 Signal 映射为回测交易操作."""

    def map(self, signal: Signal) -> Optional[str]:
        return _SIGNAL_TO_ACTION.get(signal.signal_type)

    def apply(self, signal: Signal, bt_strategy: Any) -> None:
        action = self.map(signal)
        if action:
            if hasattr(bt_strategy, 'execute_signal'):
                bt_strategy.execute_signal(signal, action)
            elif hasattr(bt_strategy, action):
                getattr(bt_strategy, action)()
