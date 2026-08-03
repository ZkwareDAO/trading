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

    def test_sync_remote_position_closed(self, caplog):
        """远程已平仓时清除本地状态"""
        # Mock factory client
        mock_factory = MagicMock()
        mock_factory.is_position_open.return_value = (False, {"ID": 1, "PnlValue": 0})  # 远程已平仓

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()

        # 设置本地持仓状态
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 70000.0
        state.position_id = "test_pos_001"

        with caplog.at_level(logging.INFO, logger="strategy_core.base.strategy"):
            strategy._sync_remote_position("BTCUSDT", "user_001")

        # 验证本地状态已清除
        assert state.position is None
        assert "远程仓位已平仓" in caplog.text or "已清除" in caplog.text

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

    def test_on_kline_with_remote_sync(self, caplog):
        """on_kline 集成远程仓位同步"""
        mock_factory = MagicMock()
        mock_factory.is_position_open.return_value = (False, {"ID": 1, "PnlValue": 0})  # 远程已平仓

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()

        # 设置本地持仓
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 70000.0

        # 模拟 K 线
        mock_kline = MagicMock()
        mock_kline.symbol = "BTCUSDT"
        mock_kline.close = 71000.0
        mock_kline.high = 71500.0
        mock_kline.low = 70500.0
        mock_kline.timestamp = datetime.now(timezone.utc)

        with caplog.at_level(logging.INFO, logger="strategy_core.base.strategy"):
            signal = strategy.on_kline(mock_kline)

        # 远程已平仓，本地状态清除，不应返回信号
        assert state.position is None

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

    def test_sync_remote_position_closed_persists_history(self, tmp_path, caplog):
        """远程已平仓时应记录历史仓位并清理持久化文件"""
        from strategy_core.position_persistence import PositionPersistence
        from strategy_core.history_position_logger import HistoryPositionLogger
        import csv
        import shutil

        # Mock factory client
        mock_factory = MagicMock()
        mock_factory.is_position_open.return_value = (False, {"ID": 18282, "PnlValue": -203.424})  # 远程已平仓

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()

        # 设置完整的本地持仓状态
        state = strategy._core._get_state("BTCUSDT")
        state.position = "short"
        state.position_id = "OBVATR_1H_V2_BTCUSDT_LIVE_BTCUSDT_1782232320"
        state.entry_price = 62593.80
        state.entry_time = datetime(2026, 6, 23, 10, 0, tzinfo=timezone.utc)
        state.entry_timestamp = 1782232320
        state.peak_price = 63000.0
        state.stop_price = 63500.0
        state.max_pnl_pct = 2.5
        state.min_pnl_pct = -1.2

        # 使用真实的 data 目录（会被清理）
        strategy_id = strategy.strategy_id_for("BTCUSDT")
        persist_dir = Path("data/positions")
        history_dir = Path("data/history_positions")

        # 确保目录存在
        persist_dir.mkdir(parents=True, exist_ok=True)
        history_dir.mkdir(parents=True, exist_ok=True)

        # 预清理历史文件，避免残留数据干扰
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        history_file = history_dir / strategy_id / f"{date_str}.csv"
        if history_file.exists():
            history_file.unlink()

        # 创建持久化文件
        persist = PositionPersistence()
        persist.save_on_entry(
            strategy_name=strategy_id,
            position_id=state.position_id,
            state=state.to_persist_dict(),
            trading_mode="live",
        )

        # 验证持久化文件存在
        persist_file = persist_dir / f"{strategy_id}.json"
        assert persist_file.exists(), "持久化文件应在同步前存在"

        # 设置当前价格（远程平仓时需要出场价格）
        strategy._current_price = 62000.0

        try:
            with caplog.at_level(logging.INFO, logger="strategy_core.base.strategy"):
                # 执行远程同步，应该触发持久化清理和历史记录
                strategy._sync_remote_position("BTCUSDT", "user_001")

            # 验证1: 本地状态已清除
            assert state.position is None
            assert state.position_id is None

            # 验证2: 持久化文件已清理
            assert not persist_file.exists(), "持久化文件应该在远程平仓后删除"

            # 验证3: 历史记录文件已生成
            assert history_file.exists(), "历史记录文件应该在远程平仓后生成"

            # 验证4: 历史记录内容正确
            with open(history_file, "r") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
                assert len(rows) == 1, f"应有一条历史记录，实际有 {len(rows)} 条"
                row = rows[0]
                assert row["position_id"] == "OBVATR_1H_V2_BTCUSDT_LIVE_BTCUSDT_1782232320"
                assert row["position_type"] == "short"
                assert float(row["entry_price"]) == 62593.8
                assert float(row["exit_price"]) == 62000.0  # 使用当前价格
                assert row["exit_reason"] == "remote_closed"  # 标记远程平仓
        finally:
            # 清理测试生成的文件
            if persist_file.exists():
                persist_file.unlink()
            if history_file.exists():
                history_file.unlink()
                # 删除空目录
                strategy_history_dir = history_dir / strategy_id
                if strategy_history_dir.exists() and not any(strategy_history_dir.iterdir()):
                    strategy_history_dir.rmdir()

    # ========== TDD: 远程止损判断测试 ==========

    def test_sync_remote_position_sets_stop_loss_date_on_loss(self, caplog):
        """远程止损平仓时设置 stop_loss_date（必须是今天的止损）"""
        from datetime import date
        from pathlib import Path
        today = date.today()
        today_str = today.isoformat()

        mock_factory = MagicMock()
        # 返回 (False, position_detail) - 远程已平仓且亏损（今天的止损）
        mock_factory.is_position_open.return_value = (
            False,
            {
                "ID": 18217,
                "Side": 0,  # 多头
                "PnlValue": -24.765,  # 亏损（止损）
                "PosPrice": 2.619,
                "CurrentPrice": 2.554,
                "CloseTime": f"{today_str}T23:10:30+08:00",
                "Deleted": 1,
            }
        )

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()

        # 设置本地持仓状态（多头）
        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 2.619
        state.position_id = "test_pos_001"

        try:
            with caplog.at_level(logging.INFO, logger="strategy_core.base.strategy"):
                strategy._sync_remote_position("BTCUSDT", "user_001")

            # 验证 stop_loss_date 已设置（今天的日期）
            assert state.stop_loss_date == today
        finally:
            # 清理测试生成的持久化文件
            cooldown_file = Path("data/stop_loss_cool_down") / f"{strategy.strategy_id_for('BTCUSDT')}.json"
            if cooldown_file.exists():
                cooldown_file.unlink()

    def test_sync_remote_position_skips_historical_stop_loss(self, caplog):
        """历史止损不设置冷却（判断 is_stop_loss 时已排除历史日期）"""
        from pathlib import Path
        mock_factory = MagicMock()
        # 返回 (False, position_detail) - 远程已平仓且亏损（3天前的止损）
        mock_factory.is_position_open.return_value = (
            False,
            {
                "ID": 18217,
                "Side": 0,
                "PnlValue": -24.765,
                "PosPrice": 2.619,
                "CurrentPrice": 2.554,
                "CloseTime": "2026-06-23T23:10:30+08:00",  # 历史日期
                "Deleted": 1,
            }
        )

        strategy = self._create_strategy(factory_client=mock_factory)
        strategy.on_start()

        state = strategy._core._get_state("BTCUSDT")
        state.position = "long"
        state.entry_price = 2.619
        state.position_id = "test_pos_003"

        try:
            with caplog.at_level(logging.INFO, logger="strategy_core.base.strategy"):
                strategy._sync_remote_position("BTCUSDT", "user_001")

            # 历史止损不应设置冷却（is_stop_loss=False）
            assert state.stop_loss_date is None
            # 日志应显示 is_stop_loss=False
            assert "is_stop_loss=False" in caplog.text
        finally:
            # 清理
            cooldown_file = Path("data/stop_loss_cool_down") / f"{strategy.strategy_id_for('BTCUSDT')}.json"
            if cooldown_file.exists():
                cooldown_file.unlink()

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