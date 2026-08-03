"""
测试 generate_signal_id 函数

TDD: 先写测试，再实现
"""

import pytest
from datetime import datetime, timezone

from strategy_core.signal_logging.storage import generate_signal_id, Signal, SignalType


class TestGenerateSignalId:
    """测试确定性 signal_id 生成"""

    def test_same_inputs_same_id(self):
        """相同输入应生成相同 ID"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        id1 = generate_signal_id("rbreaker", "BTCUSDT", ts, "buy")
        id2 = generate_signal_id("rbreaker", "BTCUSDT", ts, "buy")

        assert id1 == id2

    def test_different_strategy_different_id(self):
        """不同策略应生成不同 ID"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        id1 = generate_signal_id("rbreaker", "BTCUSDT", ts, "buy")
        id2 = generate_signal_id("dolphin", "BTCUSDT", ts, "buy")

        assert id1 != id2

    def test_different_symbol_different_id(self):
        """不同标的应生成不同 ID"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        id1 = generate_signal_id("rbreaker", "BTCUSDT", ts, "buy")
        id2 = generate_signal_id("rbreaker", "ETHUSDT", ts, "buy")

        assert id1 != id2

    def test_different_timestamp_different_id(self):
        """不同时间戳应生成不同 ID"""
        ts1 = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)
        ts2 = datetime(2026, 5, 18, 14, 31, 0, tzinfo=timezone.utc)

        id1 = generate_signal_id("rbreaker", "BTCUSDT", ts1, "buy")
        id2 = generate_signal_id("rbreaker", "BTCUSDT", ts2, "buy")

        assert id1 != id2

    def test_different_signal_type_different_id(self):
        """不同信号类型应生成不同 ID"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        id1 = generate_signal_id("rbreaker", "BTCUSDT", ts, "buy")
        id2 = generate_signal_id("rbreaker", "BTCUSDT", ts, "sell")

        assert id1 != id2

    def test_id_format(self):
        """ID 格式应为 sig_{16位hash}"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        signal_id = generate_signal_id("rbreaker", "BTCUSDT", ts, "buy")

        assert signal_id.startswith("sig_")
        assert len(signal_id) == 20  # "sig_" + 16 chars

    def test_case_insensitive_strategy(self):
        """策略名大小写不敏感"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        id1 = generate_signal_id("RBreaker", "BTCUSDT", ts, "buy")
        id2 = generate_signal_id("rbreaker", "BTCUSDT", ts, "buy")

        assert id1 == id2

    def test_case_insensitive_symbol(self):
        """标的大小写不敏感"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        id1 = generate_signal_id("rbreaker", "btcusdt", ts, "buy")
        id2 = generate_signal_id("rbreaker", "BTCUSDT", ts, "buy")

        assert id1 == id2

    def test_case_insensitive_signal_type(self):
        """信号类型大小写不敏感"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        id1 = generate_signal_id("rbreaker", "BTCUSDT", ts, "BUY")
        id2 = generate_signal_id("rbreaker", "BTCUSDT", ts, "buy")

        assert id1 == id2

    def test_timezone_aware_timestamp(self):
        """带时区的时间戳应正确处理"""
        ts_utc = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)
        # 相同时间，不同时区表示
        from datetime import timedelta
        ts_plus8 = datetime(2026, 5, 18, 22, 30, 0, tzinfo=timezone(timedelta(hours=8)))

        id1 = generate_signal_id("rbreaker", "BTCUSDT", ts_utc, "buy")
        id2 = generate_signal_id("rbreaker", "BTCUSDT", ts_plus8, "buy")

        # 相同时刻应生成相同 ID
        assert id1 == id2

    def test_backtest_live_consistency(self):
        """模拟实盘和回测生成相同 ID"""
        # 实盘场景：WS 推送的 K线时间
        live_kline_ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        # 回测场景：backtrader 遍历的相同 K线时间
        backtest_kline_ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        live_id = generate_signal_id("rbreaker", "BTCUSDT", live_kline_ts, "buy")
        backtest_id = generate_signal_id("rbreaker", "BTCUSDT", backtest_kline_ts, "buy")

        assert live_id == backtest_id


class TestSignalAutoGenerateId:
    """测试 Signal 自动生成确定性 ID"""

    def test_signal_auto_generates_id(self):
        """Signal 应自动生成确定性 ID"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        signal = Signal(
            strategy_id="RBreakerv2_1m_BTCUSDT",
            strategy_type="cta_rbreaker",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=50000.0,
            timestamp=ts,
        )

        # 验证 ID 格式
        assert signal.signal_id.startswith("sig_")
        assert len(signal.signal_id) == 20

    def test_same_signal_same_id(self):
        """相同参数的 Signal 应生成相同 ID"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        signal1 = Signal(
            strategy_id="RBreakerv2_1m_BTCUSDT",
            strategy_type="cta_rbreaker",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=50000.0,
            timestamp=ts,
        )

        signal2 = Signal(
            strategy_id="RBreakerv2_1m_BTCUSDT",
            strategy_type="cta_rbreaker",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=50000.0,
            timestamp=ts,
        )

        assert signal1.signal_id == signal2.signal_id

    def test_different_strategy_type_different_id(self):
        """不同 strategy_type 应生成不同 ID"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        signal1 = Signal(
            strategy_id="RBreakerv2_1m_BTCUSDT",
            strategy_type="cta_rbreaker",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=50000.0,
            timestamp=ts,
        )

        signal2 = Signal(
            strategy_id="Dolphinv1_1m_BTCUSDT",
            strategy_type="dolphin_trading",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=50000.0,
            timestamp=ts,
        )

        assert signal1.signal_id != signal2.signal_id

    def test_backward_compatible_without_strategy_type(self):
        """向后兼容：不传 strategy_type 时使用随机 UUID"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        signal = Signal(
            strategy_id="RBreakerv2_1m_BTCUSDT",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=50000.0,
            timestamp=ts,
        )

        # 没有 strategy_type 时，使用随机 UUID
        assert signal.signal_id  # 有 ID
        assert "-" in signal.signal_id  # UUID 格式包含连字符


class TestSignalFactoryMethodsWithStrategyType:
    """测试 Signal 工厂方法支持 strategy_type"""

    def test_buy_with_strategy_type_generates_deterministic_id(self):
        """Signal.buy() 传入 strategy_type 应生成确定性 ID"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        signal = Signal.buy(
            symbol="BTCUSDT",
            price=50000.0,
            strategy_id="RBreakerv2_1m_BTCUSDT",
            strategy_type="cta_rbreaker",
            timestamp=ts,
        )

        assert signal.signal_id.startswith("sig_")
        assert len(signal.signal_id) == 20
        assert signal.strategy_type == "cta_rbreaker"

    def test_sell_with_strategy_type_generates_deterministic_id(self):
        """Signal.sell() 传入 strategy_type 应生成确定性 ID"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        signal = Signal.sell(
            symbol="BTCUSDT",
            price=50000.0,
            strategy_id="RBreakerv2_1m_BTCUSDT",
            strategy_type="cta_rbreaker",
            timestamp=ts,
        )

        assert signal.signal_id.startswith("sig_")
        assert len(signal.signal_id) == 20

    def test_flat_with_strategy_type_generates_deterministic_id(self):
        """Signal.flat() 传入 strategy_type 应生成确定性 ID"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        signal = Signal.flat(
            symbol="BTCUSDT",
            price=50000.0,
            strategy_id="RBreakerv2_1m_BTCUSDT",
            strategy_type="cta_rbreaker",
            timestamp=ts,
        )

        assert signal.signal_id.startswith("sig_")
        assert len(signal.signal_id) == 20

    def test_buy_without_strategy_type_uses_uuid(self):
        """Signal.buy() 不传 strategy_type 应使用随机 UUID"""
        signal = Signal.buy(
            symbol="BTCUSDT",
            price=50000.0,
        )

        assert "-" in signal.signal_id  # UUID 格式

    def test_factory_methods_same_params_same_id(self):
        """工厂方法相同参数生成相同 ID"""
        ts = datetime(2026, 5, 18, 14, 30, 0, tzinfo=timezone.utc)

        signal1 = Signal.buy(
            symbol="BTCUSDT",
            price=50000.0,
            strategy_type="cta_rbreaker",
            timestamp=ts,
        )

        signal2 = Signal.buy(
            symbol="BTCUSDT",
            price=50000.0,
            strategy_type="cta_rbreaker",
            timestamp=ts,
        )

        assert signal1.signal_id == signal2.signal_id


class TestSignalFromDictWithStrategyType:
    """测试 Signal.from_dict() 和 from_row() 支持 strategy_type"""

    def test_from_dict_with_strategy_type(self):
        """from_dict 应正确解析 strategy_type"""
        data = {
            "signal_id": "",  # 空字符串触发自动生成
            "strategy_id": "RBreakerv2_1m_BTCUSDT",
            "strategy_type": "cta_rbreaker",
            "signal_type": "buy",
            "symbol": "BTCUSDT",
            "price": 50000.0,
            "timestamp": "2026-05-18T14:30:00+00:00",
        }

        signal = Signal.from_dict(data)

        assert signal.strategy_type == "cta_rbreaker"
        assert signal.signal_id.startswith("sig_")

    def test_from_dict_without_strategy_type_backward_compatible(self):
        """from_dict 无 strategy_type 时向后兼容"""
        data = {
            "signal_id": "existing-id-123",
            "strategy_id": "RBreakerv2_1m_BTCUSDT",
            "signal_type": "buy",
            "symbol": "BTCUSDT",
            "price": 50000.0,
            "timestamp": "2026-05-18T14:30:00+00:00",
        }

        signal = Signal.from_dict(data)

        assert signal.strategy_type is None
        assert signal.signal_id == "existing-id-123"

    def test_from_row_with_strategy_type(self):
        """from_row 应正确解析 strategy_type"""
        row = {
            "signal_id": "",
            "strategy_id": "RBreakerv2_1m_BTCUSDT",
            "strategy_type": "cta_rbreaker",
            "signal_type": "buy",
            "symbol": "BTCUSDT",
            "price": "50000.0",
            "timestamp": "2026-05-18T14:30:00+00:00",
            "volume": "0",
            "strength": "0.8",
            "direction": "long",
            "metadata": "{}",
        }

        signal = Signal.from_row(row)

        assert signal.strategy_type == "cta_rbreaker"
        assert signal.signal_id.startswith("sig_")
