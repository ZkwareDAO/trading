#!/usr/bin/env python3
"""
测试 run_strategy.py 中的数据加载流程

TDD RED phase: 测试先写
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class TestLoadHistoricalData:
    """测试 _load_historical_data 方法"""

    @pytest.mark.asyncio
    async def test_loads_history_for_each_symbol(self):
        """为每个订阅的 symbol 调用 sync_to_latest"""
        from run_strategy import StrategyProcessRunner

        runner = StrategyProcessRunner.__new__(StrategyProcessRunner)
        runner.strategy_name = "cta_rbreaker"
        runner.data_manager = MagicMock()

        # 模拟策略实例
        mock_instance = MagicMock()
        mock_instance.subscribed_symbols = {"BTCUSDT", "ETHUSDT"}
        runner.strategy = mock_instance

        # Mock 已有方法
        runner.data_manager._preload_all_big_intervals_from_csv = MagicMock()
        runner.data_manager.sync_to_latest = AsyncMock(return_value=True)
        runner.data_manager._preload_big_intervals_to_cache = MagicMock()

        await runner._load_historical_data(days=30)

        # 验证每个 symbol 都调用了 sync_to_latest
        assert runner.data_manager.sync_to_latest.await_count == 2
        runner.data_manager.sync_to_latest.assert_any_await("BTCUSDT", max_history_days=30)
        runner.data_manager.sync_to_latest.assert_any_await("ETHUSDT", max_history_days=30)

    @pytest.mark.asyncio
    async def test_handles_empty_symbols(self):
        """无订阅 symbol 时安全返回"""
        from run_strategy import StrategyProcessRunner

        runner = StrategyProcessRunner.__new__(StrategyProcessRunner)
        runner.strategy_name = "cta_rbreaker"
        runner.data_manager = MagicMock()
        runner.strategy = None

        runner.data_manager._preload_all_big_intervals_from_csv = MagicMock()
        runner.data_manager.sync_to_latest = AsyncMock(return_value=True)
        runner.data_manager._preload_big_intervals_to_cache = MagicMock()

        # 不应抛出异常
        await runner._load_historical_data(days=30)
        runner.data_manager.sync_to_latest.assert_not_called()

    @pytest.mark.asyncio
    async def test_continues_on_individual_failure(self):
        """某个 symbol 加载失败不阻断其他"""
        from run_strategy import StrategyProcessRunner

        runner = StrategyProcessRunner.__new__(StrategyProcessRunner)
        runner.strategy_name = "cta_rbreaker"
        runner.data_manager = MagicMock()

        mock_instance = MagicMock()
        mock_instance.subscribed_symbols = {"BTCUSDT", "ETHUSDT"}
        runner.strategy = mock_instance

        runner.data_manager._preload_all_big_intervals_from_csv = MagicMock()
        runner.data_manager.sync_to_latest = AsyncMock(side_effect=RuntimeError("API down"))
        runner.data_manager._preload_big_intervals_to_cache = MagicMock()

        # 不应抛出异常
        await runner._load_historical_data(days=30)

    @pytest.mark.asyncio
    async def test_start_calls_load_historical_data(self):
        """start() 中应调用 _load_historical_data"""
        from run_strategy import StrategyProcessRunner

        runner = StrategyProcessRunner.__new__(StrategyProcessRunner)
        runner.strategy_name = "cta_rbreaker"
        runner.strategy_config = {"symbols": ["BTCUSDT"]}
        runner.global_config = {"signal_logging": {}, "data_manager": {}}
        runner.data_manager = MagicMock()
        runner.data_manager.connect = MagicMock(return_value=True)
        runner.data_manager.set_kline_dispatch_callback = MagicMock()
        runner.strategy = None
        runner.load_strategy = MagicMock(return_value=True)
        runner._load_historical_data = AsyncMock()

        # _resolve_history_days 需要访问 strategy 实例（None 时沿用配置值 30）
        result = await runner.start()

        assert result is True
        runner._load_historical_data.assert_awaited_once_with(days=30)
