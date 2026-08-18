#!/usr/bin/env python3
"""
测试 BaseStrategy 远程仓位同步

验证：
1. 有本地持仓时查询远程仓位状态
2. 远程已平仓时清除本地状态
3. 远程仍在仓时继续检查出场
4. 缓存仓位状态避免频繁查询
5. 查询失败时继续使用本地状态
"""

import logging
from datetime import datetime, timezone, date
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from strategy_core.base.strategy import BaseStrategy
from strategy_core.base.core import BaseStrategyCore
from strategy_core.base.state import BaseState
from data_manager import DataManager


class MockStrategyCore(BaseStrategyCore):
    """模拟策略核心"""

    def _get_state(self, symbol):
        """获取状态"""
        if symbol not in self._state:
            from strategy_core.base.state import BaseState
            self._state[symbol] = BaseState()
        return self._state[symbol]

    def analyze(self, symbol, klines_data, current_time=None):
        return {"action": "hold", "price": 0, "strength": 0}

    def check_realtime_exit(self, symbol, current_price, current_time=None, bar_high=None, bar_low=None):
        return {"action": "hold", "price": current_price, "strength": 0}

    def get_status(self):
        return {"symbols": self.symbols}


class MockStrategy(BaseStrategy):
    """测试用模拟策略"""

    STRATEGY_TYPE = "mock_strategy"
    STRATEGY_PREFIX = "MOCK"
    DEFAULT_TIMEFRAME = "1h"

    def _create_core(self):
        return MockStrategyCore(
            symbols=self.symbols,
            timeframes=self.timeframes,
            params=self.params,
        )

    def _get_indicator_timeframes(self) -> set:
        return set(self.timeframes)


class TestBaseStrategyRemotePosition:
    """测试 BaseStrategy 远程仓位同步"""

    def _create_strategy(self, factory_client=None):
        """创建测试策略"""
        mock_data_manager = MagicMock(spec=DataManager)
        mock_data_manager.config = MagicMock()
        mock_data_manager.config.backtest_mode = False

        config = {
            "symbols": ["BTCUSDT"],
            "timeframes": ["1h"],
            "version": "v1",
            "signal": {"min_strength": 0.5},
            "capital": {"max_cash": 100},
        }

        strategy = MockStrategy(
            data_manager=mock_data_manager,
            config=config,
            trading_mode="live",
        )

        if factory_client:
            strategy._factory_client = factory_client

        return strategy


    def test_sync_remote_position_still_open(self, caplog):
        """远程仍在仓时保持本地状态"""
        mock_factory = MagicMock()
        mock_factory.is_position_open.return_value = (True, {"ID": 1})  # 远程仍在仓

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()

        # 设置本地持仓状态
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 70000.0

        with caplog.at_level(logging.DEBUG, logger="strategy_core.base.strategy"):
            strategy._sync_remote_position("BTCUSDT", "user_001")

        # 验证本地状态保持
        assert state.position == "long"

    def test_sync_remote_position_no_local_position(self):
        """无本地持仓时不查询远程"""
        mock_factory = MagicMock()

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()

        # 本地无持仓
        state = strategy._core._get_state("BTCUSDT")
        assert state.position is None

        strategy._sync_remote_position("BTCUSDT", "user_001")

        # 不应调用远程查询
        mock_factory.is_position_open.assert_not_called()

    def test_sync_remote_position_query_failure(self, caplog):
        """查询失败时保持本地状态"""
        mock_factory = MagicMock()
        mock_factory.is_position_open.return_value = (None, None)  # 查询失败

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()

        # 设置本地持仓状态
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 70000.0

        with caplog.at_level(logging.WARNING, logger="strategy_core.base.strategy"):
            strategy._sync_remote_position("BTCUSDT", "user_001")

        # 查询失败时保持本地状态（保守策略）
        assert state.position == "long"
        assert "查询失败" in caplog.text or "失败" in caplog.text

    def test_position_cache_ttl(self):
        """仓位状态缓存 30 秒"""
        mock_factory = MagicMock()
        mock_factory.is_position_open.return_value = (True, {"ID": 1})

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()

        # 设置本地持仓
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"

        # 第一次同步
        strategy._sync_remote_position("BTCUSDT", "user_001")
        assert mock_factory.is_position_open.call_count == 1

        # 30 秒内再次同步应使用缓存
        from datetime import timedelta
        strategy._position_cache_time["BTCUSDT"] = datetime.now(timezone.utc)

        strategy._sync_remote_position("BTCUSDT", "user_001")
        # 仍只调用一次（使用了缓存）
        assert mock_factory.is_position_open.call_count == 1


    def test_no_factory_client_graceful_skip(self):
        """无 factory_client 时跳过远程同步"""
        strategy = self._create_strategy(factory_client=None)
        strategy.on_start()

        # 设置本地持仓
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"

        # 应不抛异常
        strategy._sync_remote_position("BTCUSDT", "user_001")

        # 本地状态保持
        assert state.position == "long"

    def test_sync_logs_url_and_params(self, caplog):
        """验证日志输出请求 URL"""
        mock_factory = MagicMock()
        mock_factory.is_position_open.return_value = (True, {"ID": 1})
        mock_factory.position_proxy_url = "http://127.0.0.1:8889"
        mock_factory.position_api_path = "/api/cta/v1/user-order-positions"

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()

        # 设置本地持仓
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 70000.0

        with caplog.at_level(logging.INFO, logger="strategy_core.base.strategy"):
            strategy._sync_remote_position("BTCUSDT", "user_001")

        # 验证日志包含 URL 和 strategy_name
        assert "/api/cta/v1/user-order-positions" in caplog.text
        assert "strategy_name=" in caplog.text

    def test_sync_logs_local_state_on_close(self, caplog):
        """远程平仓时日志输出本地状态详情"""
        mock_factory = MagicMock()
        mock_factory.is_position_open.return_value = (False, {"ID": 1, "PnlValue": 0})  # 远程已平仓

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()

        # 设置本地持仓
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.position_id = "pos_123"
        state.entry_price = 75000.0

        with caplog.at_level(logging.INFO, logger="strategy_core.base.strategy"):
            strategy._sync_remote_position("BTCUSDT", "user_001")

        # 验证日志包含本地状态详情
        assert "position_id=pos_123" in caplog.text
        assert "entry_price=75000" in caplog.text or "entry_price=75000.00" in caplog.text
        assert "position=long" in caplog.text


    # ========== TDD: 远程止损判断测试 ==========



    def test_sync_remote_position_no_stop_loss_date_on_profit(self, caplog):
        """远程止盈平仓时不设置 stop_loss_date"""
        mock_factory = MagicMock()
        # 返回 (False, position_detail) - 远程已平仓且盈利
        mock_factory.is_position_open.return_value = (
            False,
            {
                "ID": 18226,
                "Side": 1,  # 空头
                "PnlValue": 230.496,  # 盈利（止盈）
                "PosPrice": 2.125,
                "CurrentPrice": 2.027,
                "CloseTime": "2026-06-05T15:12:29+08:00",
                "Deleted": 1,
            }
        )

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()

        # 设置本地持仓状态（空头）
        state = strategy._core._get_state("BTCUSDT")
        state.position = "short"
        state.entry_price = 2.125
        state.position_id = "test_pos_002"

        with caplog.at_level(logging.INFO, logger="strategy_core.base.strategy"):
            strategy._sync_remote_position("BTCUSDT", "user_001")

        # 验证 stop_loss_date 未设置
        assert state.stop_loss_date is None

    def test_sync_remote_position_handles_missing_pnl_value(self, caplog):
        """远程仓位数据缺失 PnlValue 时视为非止损"""
        mock_factory = MagicMock()
        # 返回 (False, position_detail) - 缺失 PnlValue
        mock_factory.is_position_open.return_value = (
            False,
            {
                "ID": 18217,
                "Side": 0,
                "PosPrice": 2.619,
                "CurrentPrice": 2.554,
                "CloseTime": "2026-06-02T23:10:30+08:00",
                "Deleted": 1,
            }
        )

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()

        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 2.619
        state.position_id = "test_pos_003"

        with caplog.at_level(logging.INFO, logger="strategy_core.base.strategy"):
            strategy._sync_remote_position("BTCUSDT", "user_001")

        # 缺失 PnlValue 时默认为 0，视为非止损
        assert state.stop_loss_date is None

    # ========== TDD: backtest/paper_trading 模式跳过远程同步 ==========

    def test_sync_remote_position_skips_in_backtest_mode(self, caplog):
        """回测模式下跳过远程仓位同步"""
        mock_factory = MagicMock()
        mock_factory.is_position_open.return_value = (True, {"ID": 1})

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()
        # 设置回测模式
        strategy._backtest_mode = True

        # 设置本地持仓
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 70000.0

        with caplog.at_level(logging.DEBUG, logger="strategy_core.base.strategy"):
            strategy._sync_remote_position("BTCUSDT", "user_001")

        # 验证：不应调用远程 API
        mock_factory.is_position_open.assert_not_called()
        # 验证：本地状态保持不变
        assert state.position == "long"
        # 验证：日志显示跳过原因
        assert "回测/paper模式" in caplog.text or "跳过远程仓位同步" in caplog.text

    def test_sync_remote_position_skips_in_paper_trading_mode(self, caplog):
        """paper_trading 模式下跳过远程仓位同步"""
        mock_factory = MagicMock()
        mock_factory.is_position_open.return_value = (True, {"ID": 1})

        # 创建 paper_trading 模式的策略
        mock_data_manager = MagicMock(spec=DataManager)
        mock_data_manager.config = MagicMock()
        mock_data_manager.config.backtest_mode = False

        config = {
            "symbols": ["BTCUSDT"],
            "timeframes": ["1h"],
            "version": "v1",
            "signal": {"min_strength": 0.5},
            "capital": {"max_cash": 100},
        }

        strategy = MockStrategy(
            data_manager=mock_data_manager,
            config=config,
            trading_mode="paper_trading",  # paper_trading 模式
        )
        strategy._factory_client = mock_factory
        strategy.on_start()

        # 设置本地持仓
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 70000.0

        with caplog.at_level(logging.DEBUG, logger="strategy_core.base.strategy"):
            strategy._sync_remote_position("BTCUSDT", "user_001")

        # 验证：不应调用远程 API
        mock_factory.is_position_open.assert_not_called()
        # 验证：本地状态保持不变
        assert state.position == "long"
        # 验证：_paper_trading_mode 标志正确
        assert strategy._paper_trading_mode is True
        # 验证：日志显示跳过原因
        assert "回测/paper模式" in caplog.text or "跳过远程仓位同步" in caplog.text

    def test_sync_remote_position_runs_in_live_mode(self, caplog):
        """live 模式下正常执行远程仓位同步"""
        mock_factory = MagicMock()
        mock_factory.is_position_open.return_value = (True, {"ID": 1})

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()
        # 确保是 live 模式
        assert strategy._trading_mode == "live"
        assert strategy._backtest_mode is False
        assert strategy._paper_trading_mode is False

        # 设置本地持仓
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 70000.0

        with caplog.at_level(logging.INFO, logger="strategy_core.base.strategy"):
            strategy._sync_remote_position("BTCUSDT", "user_001")

        # 验证：应调用远程 API
        mock_factory.is_position_open.assert_called_once()
        # 验证：本地状态保持（远程仍在仓）
        assert state.position == "long"


class TestPositionSnapshot:
    """测试 _snapshot_position 和 _log_position_diagnostic 快照机制"""

    def _create_strategy(self):
        """创建测试策略"""
        mock_data_manager = MagicMock(spec=DataManager)
        mock_data_manager.config = MagicMock()
        mock_data_manager.config.backtest_mode = False

        config = {
            "symbols": ["BTCUSDT"],
            "timeframes": ["1h"],
            "version": "v1",
            "signal": {"min_strength": 0.5},
            "capital": {"max_cash": 100},
        }

        strategy = MockStrategy(
            data_manager=mock_data_manager,
            config=config,
        )
        return strategy

    def test_snapshot_position_captures_all_fields(self):
        """_snapshot_position 应捕获 position/entry_price/stop_price/peak_price"""
        strategy = self._create_strategy()
        strategy.on_start()

        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 70000.0
        state.stop_price = 69000.0
        state.peak_price = 71000.0

        snapshot = strategy._snapshot_position(state)

        assert snapshot == {
            "position": "long",
            "entry_price": 70000.0,
            "stop_price": 69000.0,
            "peak_price": 71000.0,
        }

    def test_snapshot_position_preserves_values_after_clear(self):
        """_snapshot_position 捕获的值不受后续 clear_position 影响"""
        strategy = self._create_strategy()
        strategy.on_start()

        state = strategy._core._get_state("BTCUSDT")
        state.position = "short"
        state.entry_price = 50000.0
        state.stop_price = 51000.0
        state.peak_price = 49000.0

        snapshot = strategy._snapshot_position(state)
        state.clear_position()

        assert snapshot["position"] == "short"
        assert snapshot["entry_price"] == 50000.0
        assert snapshot["stop_price"] == 51000.0
        assert state.position is None
        assert state.entry_price == 0.0

    def test_log_position_diagnostic_uses_snapshot_not_cleared_state(self, caplog):
        """_log_position_diagnostic 在 state 清空后应使用快照值写日志"""
        from strategy_core.signal_logging import Signal, SignalType

        strategy = self._create_strategy()
        strategy.on_start()
        strategy._current_kline_timestamp = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)

        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 0.07
        state.stop_price = 0.07
        state.peak_price = 0.08

        snapshot = {"position": "long", "entry_price": 0.07, "stop_price": 0.07, "peak_price": 0.08}
        # 模拟 state 已被 check_realtime_exit 清空
        state.clear_position()

        signal = Signal(
            strategy_id="TEST",
            strategy_type="test",
            signal_type=SignalType.SELL_CLOSE,
            symbol="BTCUSDT",
            price=0.07,
            strength=0.8,
            direction="long",
            timestamp=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
            metadata={"reason": "测试止损"},
        )

        with caplog.at_level(logging.INFO, logger="strategy_core.base.strategy"):
            strategy._log_position_diagnostic("BTCUSDT", state, signal, 0.07,
                                              position_snapshot=snapshot)

        # 验证日志包含快照值（不是清零后的值）
        assert "position=long" in caplog.text
        assert "entry=0.07" in caplog.text
        assert "stop=0.07" in caplog.text
        assert "peak=0.08" in caplog.text
        # 验证日志不包含清零值
        assert "entry=0.00" not in caplog.text

    def test_log_position_diagnostic_falls_back_to_state_without_snapshot(self, caplog):
        """没有 snapshot 时 _log_position_diagnostic 应回退到 state 字段"""
        from strategy_core.signal_logging import Signal, SignalType

        strategy = self._create_strategy()
        strategy.on_start()
        strategy._current_kline_timestamp = datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc)

        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 0.07
        state.stop_price = 0.07
        state.peak_price = 0.08

        signal = Signal(
            strategy_id="TEST", strategy_type="test",
            signal_type=SignalType.BUY_CLOSE, symbol="BTCUSDT",
            price=0.07, strength=0, direction="long",
            timestamp=datetime(2026, 8, 10, 9, 0, tzinfo=timezone.utc),
            metadata={},
        )

        with caplog.at_level(logging.DEBUG, logger="strategy_core.base.strategy"):
            strategy._log_position_diagnostic("BTCUSDT", state, signal, 0.07)

        assert "entry=0.07" in caplog.text


class TestNotifyExitAndClear:
    """测试 _notify_exit_and_clear 无条件清理持久化"""

    def _create_strategy(self):
        """创建测试策略"""
        mock_data_manager = MagicMock(spec=DataManager)
        mock_data_manager.config = MagicMock()
        mock_data_manager.config.backtest_mode = False

        config = {
            "symbols": ["BTCUSDT"],
            "timeframes": ["1h"],
            "version": "v1",
            "signal": {"min_strength": 0.5},
            "capital": {"max_cash": 100},
        }

        strategy = MockStrategy(
            data_manager=mock_data_manager,
            config=config,
        )
        return strategy

    def test_notify_exit_and_clear_calls_exit_callback_without_position_id(self):
        """即使 position_id=None，_notify_exit_and_clear 也应调用 _notify_position_exit"""
        strategy = self._create_strategy()
        strategy.on_start()

        core = strategy._core
        core._notify_position_exit = MagicMock()

        state = core._get_state("BTCUSDT")
        state.position = "long"
        state.position_id = None
        state.entry_price = 70000.0

        core._notify_exit_and_clear(
            symbol="BTCUSDT",
            state=state,
            exit_price=69500.0,
            exit_reason="止损",
            is_stop_loss=True,
        )

        core._notify_position_exit.assert_called_once()
        assert state.position is None

    def test_notify_exit_and_clear_clears_persistence_with_null_position_id(self, tmp_path):
        """position_id=None 时 _on_position_exit 应能清理 position_id=null 的 JSON"""
        from strategy_core.position_persistence import PositionPersistence

        strategy_id = "TEST_NULL_POSITION_ID"

        persistence = PositionPersistence(base_path=tmp_path)
        json_path = tmp_path / f"{strategy_id}.json"
        json_path.write_text('{"position": "long", "position_id": null, "entry_price": 76.95}')

        assert json_path.exists()

        persistence.clear_on_exit(strategy_id, None)

        assert not json_path.exists()

    def test_notify_exit_and_clear_with_position_id_still_works(self):
        """有 position_id 时的正常流程不受影响"""
        strategy = self._create_strategy()
        strategy.on_start()

        core = strategy._core
        core._notify_position_exit = MagicMock()

        state = core._get_state("BTCUSDT")
        state.position = "long"
        state.position_id = "TEST_POS_123"
        state.entry_price = 70000.0

        core._notify_exit_and_clear(
            symbol="BTCUSDT",
            state=state,
            exit_price=69500.0,
            exit_reason="止损",
            is_stop_loss=True,
        )

        core._notify_position_exit.assert_called_once()
        assert state.position is None