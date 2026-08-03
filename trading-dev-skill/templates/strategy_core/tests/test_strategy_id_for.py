#!/usr/bin/env python3
"""测试 strategy_id_for() 方法实现数据隔离

验证：
1. strategy_id_for() 返回含 trading_mode 的完整 ID
2. 数据存储路径使用 strategy_id_for() 实现 LIVE/PAPER 隔离
3. 远程仓位查询仍使用 strategy_name_for()（不含 MODE）
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from strategy_core.position_persistence import PositionPersistence
from strategy_core.history_position_logger import HistoryPositionLogger
from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.csv_adapter import SignalCsvWriter


class TestStrategyIdFor:
    """测试 BaseStrategy.strategy_id_for() 方法"""

    def test_strategy_id_for_live_mode(self):
        """实盘模式应返回 _LIVE 后缀"""
        # 使用模拟策略实例
        from strategy_core.base.strategy import BaseStrategy
        from data_manager import DataManager

        # 创建模拟策略
        mock_dm = MagicMock(spec=DataManager)

        # 模拟策略类
        class MockStrategy(BaseStrategy):
            STRATEGY_TYPE = "cta_rbreaker"
            STRATEGY_PREFIX = "RBREAKER"
            DEFAULT_TIMEFRAME = "15m"

            def _create_core(self):
                pass

            def _get_indicator_timeframes(self):
                return ["15m"]

        strategy = MockStrategy(
            data_manager=mock_dm,
            strategy_name="RBREAKER_15M_V3_BTCUSDT_LIVE",
            trading_mode="live",
        )
        strategy.symbols = ["BTCUSDT"]
        strategy.version = "v3"
        strategy.main_timeframe = "15m"

        result = strategy.strategy_id_for("BTCUSDT")
        assert result == "RBREAKER_15M_V3_BTCUSDT_LIVE"

    def test_strategy_id_for_paper_trading_mode(self):
        """模拟盘模式应返回 _PAPER 后缀"""
        from strategy_core.base.strategy import BaseStrategy
        from data_manager import DataManager

        mock_dm = MagicMock(spec=DataManager)

        class MockStrategy(BaseStrategy):
            STRATEGY_TYPE = "cta_rbreaker"
            STRATEGY_PREFIX = "RBREAKER"
            DEFAULT_TIMEFRAME = "15m"

            def _create_core(self):
                pass

            def _get_indicator_timeframes(self):
                return ["15m"]

        strategy = MockStrategy(
            data_manager=mock_dm,
            strategy_name="RBREAKER_15M_V3_BTCUSDT_PAPER",
            trading_mode="paper_trading",
        )
        strategy.symbols = ["BTCUSDT"]
        strategy.version = "v3"
        strategy.main_timeframe = "15m"

        result = strategy.strategy_id_for("BTCUSDT")
        assert result == "RBREAKER_15M_V3_BTCUSDT_PAPER"

    def test_strategy_id_for_backtest_mode(self):
        """回测模式应返回 _BACKTEST 后缀"""
        from strategy_core.base.strategy import BaseStrategy
        from data_manager import DataManager

        mock_dm = MagicMock(spec=DataManager)

        class MockStrategy(BaseStrategy):
            STRATEGY_TYPE = "cta_rbreaker"
            STRATEGY_PREFIX = "RBREAKER"
            DEFAULT_TIMEFRAME = "15m"

            def _create_core(self):
                pass

            def _get_indicator_timeframes(self):
                return ["15m"]

        strategy = MockStrategy(
            data_manager=mock_dm,
            strategy_name="RBREAKER_15M_V3_BTCUSDT_BACKTEST",
            trading_mode="backtest",
        )
        strategy.symbols = ["BTCUSDT"]
        strategy.version = "v3"
        strategy.main_timeframe = "15m"

        result = strategy.strategy_id_for("BTCUSDT")
        assert result == "RBREAKER_15M_V3_BTCUSDT_BACKTEST"

    def test_strategy_id_for_smoking_mode(self):
        """小金额实盘模式应返回 _SMOKING 后缀"""
        from strategy_core.base.strategy import BaseStrategy
        from data_manager import DataManager

        mock_dm = MagicMock(spec=DataManager)

        class MockStrategy(BaseStrategy):
            STRATEGY_TYPE = "dolphin_trading"
            STRATEGY_PREFIX = "DOLPHIN"
            DEFAULT_TIMEFRAME = "4h"

            def _create_core(self):
                pass

            def _get_indicator_timeframes(self):
                return ["4h"]

        strategy = MockStrategy(
            data_manager=mock_dm,
            strategy_name="DOLPHIN_4H_V2_BTCUSDT_SMOKING",
            trading_mode="smoking",
        )
        strategy.symbols = ["BTCUSDT"]
        strategy.version = "v2"
        strategy.main_timeframe = "4h"

        result = strategy.strategy_id_for("BTCUSDT")
        assert result == "DOLPHIN_4H_V2_BTCUSDT_SMOKING"

    def test_strategy_name_for_unchanged(self):
        """strategy_name_for() 应保持不含 MODE（Factory 依赖）"""
        from strategy_core.base.strategy import BaseStrategy
        from data_manager import DataManager

        mock_dm = MagicMock(spec=DataManager)

        class MockStrategy(BaseStrategy):
            STRATEGY_TYPE = "cta_rbreaker"
            STRATEGY_PREFIX = "RBREAKER"
            DEFAULT_TIMEFRAME = "15m"

            def _create_core(self):
                pass

            def _get_indicator_timeframes(self):
                return ["15m"]

        strategy = MockStrategy(
            data_manager=mock_dm,
            trading_mode="live",
        )
        strategy.symbols = ["BTCUSDT"]
        strategy.version = "v3"
        strategy.main_timeframe = "15m"

        result = strategy.strategy_name_for("BTCUSDT")
        assert result == "RBREAKER_15M_V3_BTCUSDT"
        assert "_LIVE" not in result


class TestPositionStorageIsolation:
    """测试仓位存储路径隔离"""

    def test_live_position_path_contains_live(self, tmp_path: Path):
        """实盘仓位应存储在 _LIVE 目录"""
        persistence = PositionPersistence(base_path=tmp_path)

        # 存储 live 模式仓位
        persistence.save_on_entry(
            strategy_name="RBREAKER_15M_V3_BTCUSDT_LIVE",
            position_id="test_123",
            state={"position": "long", "entry_price": 100.0},
            trading_mode="live",
        )

        # 验证文件路径
        filepath = tmp_path / "RBREAKER_15M_V3_BTCUSDT_LIVE.json"
        assert filepath.exists()

        # 验证内容
        data = json.load(filepath.open())
        assert data["trading_mode"] == "live"

    def test_paper_position_path_contains_paper(self, tmp_path: Path):
        """模拟盘仓位应存储在 _PAPER 目录"""
        persistence = PositionPersistence(base_path=tmp_path)

        persistence.save_on_entry(
            strategy_name="RBREAKER_15M_V3_BTCUSDT_PAPER",
            position_id="test_456",
            state={"position": "short", "entry_price": 200.0},
            trading_mode="paper_trading",
        )

        filepath = tmp_path / "RBREAKER_15M_V3_BTCUSDT_PAPER.json"
        assert filepath.exists()

        data = json.load(filepath.open())
        assert data["trading_mode"] == "paper_trading"

    def test_live_and_paper_positions_isolated(self, tmp_path: Path):
        """同一策略的实盘和模拟盘仓位应隔离"""
        persistence = PositionPersistence(base_path=tmp_path)

        # 存储两个仓位
        persistence.save_on_entry(
            strategy_name="RBREAKER_15M_V3_BTCUSDT_LIVE",
            position_id="live_123",
            state={"position": "long", "entry_price": 100.0},
            trading_mode="live",
        )
        persistence.save_on_entry(
            strategy_name="RBREAKER_15M_V3_BTCUSDT_PAPER",
            position_id="paper_456",
            state={"position": "short", "entry_price": 200.0},
            trading_mode="paper_trading",
        )

        # 验证隔离
        live_file = tmp_path / "RBREAKER_15M_V3_BTCUSDT_LIVE.json"
        paper_file = tmp_path / "RBREAKER_15M_V3_BTCUSDT_PAPER.json"

        assert live_file.exists()
        assert paper_file.exists()

        live_data = json.load(live_file.open())
        paper_data = json.load(paper_file.open())

        assert live_data["position"] == "long"
        assert paper_data["position"] == "short"


class TestHistoryPositionIsolation:
    """测试历史仓位存储路径隔离"""

    def test_live_history_path_contains_live(self, tmp_path: Path):
        """实盘历史仓位应存储在 _LIVE 目录"""
        logger = HistoryPositionLogger(base_path=tmp_path)

        logger.log_position_exit(
            strategy_name="RBREAKER_15M_V3_BTCUSDT_LIVE",
            symbol="BTCUSDT",
            position_id="live_123",
            position_type="long",
            entry_price=100.0,
            exit_price=110.0,
            entry_time=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            exit_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            entry_timestamp=1735725600,
            exit_timestamp=1735732800,
            peak_price=115.0,
            stop_price=95.0,
            trading_mode="live",
        )

        # 验证目录路径
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        csv_path = tmp_path / "RBREAKER_15M_V3_BTCUSDT_LIVE" / f"{date_str}.csv"
        assert csv_path.exists()

    def test_paper_history_path_contains_paper(self, tmp_path: Path):
        """模拟盘历史仓位应存储在 _PAPER 目录"""
        logger = HistoryPositionLogger(base_path=tmp_path)

        logger.log_position_exit(
            strategy_name="RBREAKER_15M_V3_BTCUSDT_PAPER",
            symbol="BTCUSDT",
            position_id="paper_456",
            position_type="short",
            entry_price=200.0,
            exit_price=190.0,
            entry_time=datetime(2026, 1, 1, 10, 0, tzinfo=timezone.utc),
            exit_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
            entry_timestamp=1735725600,
            exit_timestamp=1735732800,
            peak_price=185.0,
            stop_price=210.0,
            trading_mode="paper_trading",
        )

        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        csv_path = tmp_path / "RBREAKER_15M_V3_BTCUSDT_PAPER" / f"{date_str}.csv"
        assert csv_path.exists()


class TestSignalStorageIsolation:
    """测试信号存储路径隔离"""

    def test_live_signal_path_contains_live(self, tmp_path: Path):
        """实盘信号应存储在 _LIVE 目录"""
        writer = SignalCsvWriter(base_dir=str(tmp_path))

        signal = Signal(
            signal_id="live_001",
            strategy_id="RBREAKER_15M_V3_BTCUSDT_LIVE",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=100.0,
            strength=0.8,
            direction="long",
            timestamp=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
        )

        writer.write_signal(
            signal=signal,
            strategy_name="RBREAKER_15M_V3_BTCUSDT_LIVE",
            strategy_version="v3",
            interval="15m",
            trading_mode="live",
        )

        csv_path = tmp_path / "RBREAKER_15M_V3_BTCUSDT_LIVE" / "20260612.csv"
        assert csv_path.exists()

    def test_paper_signal_path_contains_paper(self, tmp_path: Path):
        """模拟盘信号应存储在 _PAPER 目录"""
        writer = SignalCsvWriter(base_dir=str(tmp_path))

        signal = Signal(
            signal_id="paper_001",
            strategy_id="RBREAKER_15M_V3_BTCUSDT_PAPER",
            signal_type=SignalType.SELL,
            symbol="BTCUSDT",
            price=200.0,
            strength=0.7,
            direction="short",
            timestamp=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
        )

        writer.write_signal(
            signal=signal,
            strategy_name="RBREAKER_15M_V3_BTCUSDT_PAPER",
            strategy_version="v3",
            interval="15m",
            trading_mode="paper_trading",
        )

        csv_path = tmp_path / "RBREAKER_15M_V3_BTCUSDT_PAPER" / "20260612.csv"
        assert csv_path.exists()