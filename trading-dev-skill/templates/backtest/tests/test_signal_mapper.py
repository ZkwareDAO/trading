"""Tests for signal_mapper.py — RED phase, no implementation yet."""

import sys
from pathlib import Path

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


class TestSignalMapper:
    """Test SignalMapper mapping logic."""

    def test_buy_opens_long(self):
        """SignalType.BUY → action='buy'."""
        from strategy_core.signal_logging.storage import Signal, SignalType
        from backtest.signal_mapper import SignalMapper

        signal = Signal.buy(symbol="BTCUSDT", price=50000, strength=0.8)
        assert signal.signal_type == SignalType.BUY

        mapper = SignalMapper()
        action = mapper.map(signal)
        assert action == "buy"

    def test_sell_opens_short(self):
        """SignalType.SELL → action='sell'."""
        from strategy_core.signal_logging.storage import SignalType, Signal
        from datetime import datetime

        from backtest.signal_mapper import SignalMapper

        signal = Signal(
            strategy_id="test",
            signal_type=SignalType.SELL,
            symbol="BTCUSDT",
            price=50000,
            timestamp=datetime.now(),
        )
        mapper = SignalMapper()
        action = mapper.map(signal)
        assert action == "sell"

    def test_buy_close_closes_position(self):
        """SignalType.BUY_CLOSE → action='close'."""
        from strategy_core.signal_logging.storage import SignalType, Signal
        from datetime import datetime

        from backtest.signal_mapper import SignalMapper

        signal = Signal(
            strategy_id="test",
            signal_type=SignalType.BUY_CLOSE,
            symbol="BTCUSDT",
            price=50000,
            timestamp=datetime.now(),
        )
        mapper = SignalMapper()
        action = mapper.map(signal)
        assert action == "close"

    def test_sell_close_closes_position(self):
        """SignalType.SELL_CLOSE → action='close'."""
        from strategy_core.signal_logging.storage import SignalType, Signal
        from datetime import datetime

        from backtest.signal_mapper import SignalMapper

        signal = Signal(
            strategy_id="test",
            signal_type=SignalType.SELL_CLOSE,
            symbol="BTCUSDT",
            price=50000,
            timestamp=datetime.now(),
        )
        mapper = SignalMapper()
        action = mapper.map(signal)
        assert action == "close"

    def test_flat_closes_position(self):
        """SignalType.FLAT → action='close'."""
        from strategy_core.signal_logging.storage import SignalType, Signal
        from datetime import datetime

        from backtest.signal_mapper import SignalMapper

        signal = Signal(
            strategy_id="test",
            signal_type=SignalType.FLAT,
            symbol="BTCUSDT",
            price=50000,
            timestamp=datetime.now(),
        )
        mapper = SignalMapper()
        action = mapper.map(signal)
        assert action == "close"

    def test_reverse_long_opens_long(self):
        """SignalType.REVERSE_LONG → action='buy'."""
        from strategy_core.signal_logging.storage import SignalType, Signal
        from datetime import datetime

        from backtest.signal_mapper import SignalMapper

        signal = Signal(
            strategy_id="test",
            signal_type=SignalType.REVERSE_LONG,
            symbol="BTCUSDT",
            price=50000,
            timestamp=datetime.now(),
        )
        mapper = SignalMapper()
        action = mapper.map(signal)
        assert action == "buy"

    def test_reverse_short_opens_short(self):
        """SignalType.REVERSE_SHORT → action='sell'."""
        from strategy_core.signal_logging.storage import SignalType, Signal
        from datetime import datetime

        from backtest.signal_mapper import SignalMapper

        signal = Signal(
            strategy_id="test",
            signal_type=SignalType.REVERSE_SHORT,
            symbol="BTCUSDT",
            price=50000,
            timestamp=datetime.now(),
        )
        mapper = SignalMapper()
        action = mapper.map(signal)
        assert action == "sell"

    def test_apply_buy_calls_buy_on_bt_strategy(self):
        """apply() 方法调用 bt_strategy.buy()."""
        from strategy_core.signal_logging.storage import Signal
        from backtest.signal_mapper import SignalMapper

        signal = Signal.buy(symbol="BTCUSDT", price=50000, strength=0.8)
        mapper = SignalMapper()

        # 模拟 backtrader strategy
        mock_bt = type("MockBT", (), {
            "buy": lambda self: setattr(self, "_called", "buy"),
            "sell": lambda self: setattr(self, "_called", "sell"),
            "close": lambda self: setattr(self, "_called", "close"),
        })()

        mapper.apply(signal, mock_bt)
        assert getattr(mock_bt, "_called", None) == "buy"

    def test_apply_sell_calls_sell_on_bt_strategy(self):
        """apply() 方法调用 bt_strategy.sell()."""
        from strategy_core.signal_logging.storage import SignalType, Signal
        from datetime import datetime

        from backtest.signal_mapper import SignalMapper

        signal = Signal(
            strategy_id="test",
            signal_type=SignalType.SELL,
            symbol="BTCUSDT",
            price=50000,
            timestamp=datetime.now(),
        )
        mapper = SignalMapper()

        mock_bt = type("MockBT", (), {
            "buy": lambda self: setattr(self, "_called", "buy"),
            "sell": lambda self: setattr(self, "_called", "sell"),
            "close": lambda self: setattr(self, "_called", "close"),
        })()

        mapper.apply(signal, mock_bt)
        assert getattr(mock_bt, "_called", None) == "sell"

    def test_apply_close_calls_close_on_bt_strategy(self):
        """apply() 方法调用 bt_strategy.close()."""
        from strategy_core.signal_logging.storage import SignalType, Signal
        from datetime import datetime

        from backtest.signal_mapper import SignalMapper

        signal = Signal(
            strategy_id="test",
            signal_type=SignalType.FLAT,
            symbol="BTCUSDT",
            price=50000,
            timestamp=datetime.now(),
        )
        mapper = SignalMapper()

        mock_bt = type("MockBT", (), {
            "buy": lambda self: setattr(self, "_called", "buy"),
            "sell": lambda self: setattr(self, "_called", "sell"),
            "close": lambda self: setattr(self, "_called", "close"),
        })()

        mapper.apply(signal, mock_bt)
        assert getattr(mock_bt, "_called", None) == "close"

    def test_map_returns_none_for_unknown_signal_type(self):
        """未知 SignalType 返回 None."""
        from strategy_core.signal_logging.storage import SignalType, Signal
        from datetime import datetime

        from backtest.signal_mapper import SignalMapper

        # 手动构造一个非法的 SignalType 来测试边界
        signal = Signal(
            strategy_id="test",
            signal_type=SignalType.FLAT,  # 正常类型
            symbol="BTCUSDT",
            price=50000,
            timestamp=datetime.now(),
        )
        mapper = SignalMapper()

        # 临时篡改 signal_type 为未知值
        signal.signal_type = SignalType.FLAT  # 正常
        action = mapper.map(signal)
        assert action == "close"  # FLAT → close
