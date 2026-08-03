#!/usr/bin/env python3
"""
测试 CSV strategy_params 包含风控字段，确保 CSV 和 Kafka 数据一致

验证：
1. CSV 存储的 strategy_params 包含风控字段
2. csv.to_json() 的 params 包含风控字段
3. CSV 和 Kafka 发送的数据一致
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml


class TestCsvParamsIncludesRiskFields:
    """测试 CSV strategy_params 包含风控字段"""

    def test_csv_strategy_params_includes_risk_fields(self, tmp_path):
        """CSV 存储的 strategy_params 应包含风控字段"""
        from strategy_core.signal_logging.csv_adapter import CtaSignalCSV, SignalCsvWriter
        from strategy_core.signal_logging.storage import Signal, SignalType

        # 创建信号
        signal = Signal(
            signal_id="test_001",
            strategy_id="test_strategy",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            strength=0.8,
            timestamp=datetime.now(timezone.utc),
        )

        # 策略参数（包含风控字段）
        strategy_params = {
            "threshold": 0.005,
            "StopLossThreshold": 0.02,
            "TakeProfitBackThreshold": 0.05,
            "TakeProfitBackDynamicFallPercent": 0.05,
        }

        # 写入 CSV
        # 注意：risk_stop_loss_pct 使用数值形式，如 2 表示 2%（见 constants.py）
        csv_writer = SignalCsvWriter(base_dir=str(tmp_path))
        csv_writer.write_signal(
            signal=signal,
            strategy_name="RBreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params=strategy_params,
            strategy_cash=1000,
            strategy_parts=2,
            risk_stop_loss_pct=2,  # 2 表示 2%
            risk_trailing_profit_activation=5,  # 5 表示 5%
            risk_trailing_profit_drawdown=5,  # 5 表示 5%
        )

        # 读取 CSV 文件
        csv_file = tmp_path / "RBreaker" / f"{datetime.now().strftime('%Y%m%d')}.csv"
        assert csv_file.exists()

        import csv
        with open(csv_file, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        # 验证 strategy_params 包含风控字段
        params = json.loads(row["strategy_params"])
        assert "StopLossThreshold" in params, "strategy_params 应包含 StopLossThreshold"
        assert params["StopLossThreshold"] == -0.02  # 止损阈值应为负数
        assert "TakeProfitBackThreshold" in params, "strategy_params 应包含 TakeProfitBackThreshold"
        assert params["TakeProfitBackThreshold"] == 0.05
        assert "TakeProfitBackDynamicFallPercent" in params, "strategy_params 应包含 TakeProfitBackDynamicFallPercent"
        assert params["TakeProfitBackDynamicFallPercent"] == 0.05

    def test_csv_to_json_includes_risk_fields_in_params(self, tmp_path):
        """CtaSignalCSV.to_json() 的 params 应包含风控字段"""
        from strategy_core.signal_logging.csv_adapter import CtaSignalCSV

        # 创建 CtaSignalCSV，strategy_params 包含风控字段
        # 注意：risk_stop_loss_pct 使用数值形式，如 2 表示 2%（见 constants.py）
        cta_signal = CtaSignalCSV(
            signal_id="test_001",
            signal_timestamp=int(datetime.now().timestamp() * 1000),
            symbol="BTCUSDT",
            pos_type=2,
            strategy_type="CTAFutureFactory",
            strategy_type_name="RBreaker",
            risk_strategy_type="cta_intraday",
            user_id=1,
            strategy_name="RBreaker_v2_1m_BTCUSDT",
            strategy_version="v2",
            strategy_internal="1m",
            strategy_params=json.dumps({
                "threshold": 0.005,
                "StopLossThreshold": 2,  # 2 表示 2%
                "TakeProfitBackThreshold": 5,  # 5 表示 5%
                "TakeProfitBackDynamicFallPercent": 5,  # 5 表示 5%
            }),
            strategy_valid_before="2030-12-31 08:00:00",
            strategy_cash=1000,
            strategy_parts=2,
            signal_side=1,
            signal_action="buy",
            signal_exchange="binance",
            signal_valid_before="2026-05-10 08:00:00",
            signal_trigger_price=70000.0,
            signal_slippage=0,
            signal_order_type=1,
            signal_quantity=0,
            signal_cash=500,
            strength=0.8,
            metadata="{}",
            risk_stop_loss_pct=2,  # 2 表示 2%
            risk_trailing_profit_activation=5,  # 5 表示 5%
            risk_trailing_profit_drawdown=5,  # 5 表示 5%
        )

        # 转换为 JSON
        json_data = cta_signal.to_json()

        # 验证 params 包含风控字段
        params = json_data["strategy"]["params"]
        assert params["StopLossThreshold"] == -0.02  # 止损阈值应为负数
        assert params["TakeProfitBackThreshold"] == 0.05
        assert params["TakeProfitBackDynamicFallPercent"] == 0.05

    def test_stop_loss_threshold_always_negative(self):
        """StopLossThreshold 无论输入正负，输出都应为负数"""
        from strategy_core.signal_logging.csv_adapter import CtaSignalCSV

        # 测试正数输入（数值形式：3 表示 3%）
        cta_positive = CtaSignalCSV(
            signal_id="test_001",
            signal_timestamp=1700000000000,
            symbol="BTCUSDT",
            risk_stop_loss_pct=3,  # 3 表示 3%
        )
        json_positive = cta_positive.to_json()
        assert json_positive["strategy"]["params"]["StopLossThreshold"] == -0.03

        # 测试负数输入
        cta_negative = CtaSignalCSV(
            signal_id="test_002",
            signal_timestamp=1700000000000,
            symbol="BTCUSDT",
            risk_stop_loss_pct=-3,  # -3 表示 -3%
        )
        json_negative = cta_negative.to_json()
        assert json_negative["strategy"]["params"]["StopLossThreshold"] == -0.03

        # 测试零值输入
        cta_zero = CtaSignalCSV(
            signal_id="test_003",
            signal_timestamp=1700000000000,
            symbol="BTCUSDT",
            risk_stop_loss_pct=0,  # 零
        )
        json_zero = cta_zero.to_json()
        assert json_zero["strategy"]["params"]["StopLossThreshold"] == 0

    def test_csv_row_stop_loss_threshold_negative(self):
        """CSV 行的 strategy_params 中 StopLossThreshold 也应为负数"""
        from strategy_core.signal_logging.csv_adapter import CtaSignalCSV
        import json

        cta_signal = CtaSignalCSV(
            signal_id="test_001",
            signal_timestamp=1700000000000,
            symbol="BTCUSDT",
            risk_stop_loss_pct=2,  # 2 表示 2%（数值形式）
        )

        csv_row = cta_signal.to_csv_row()
        params = json.loads(csv_row["strategy_params"])
        assert params["StopLossThreshold"] == -0.02  # 输出应为负数

    def test_engine_csv_and_kafka_use_same_params(self, tmp_path):
        """引擎写入 CSV 和发送 Kafka 应使用相同的数据（CtaSignalCSV 对象）"""
        from strategy_core.strategy_engine.engine import StrategyEngine
        from strategy_core.signal_logging.csv_adapter import SignalCsvWriter
        from strategy_core.signal_logging import SignalStorage, SignalLogger
        from strategy_core.signal_logging.storage import Signal, SignalType

        # 创建 mock
        mock_data_manager = MagicMock()
        mock_csv_writer = MagicMock(spec=SignalCsvWriter)
        mock_csv_writer.write_cta_signal.return_value = True
        mock_signal_logger = MagicMock()

        # 创建引擎
        engine = StrategyEngine(
            factory_endpoint="http://127.0.0.1:8888",
            strategies_dir=str(tmp_path / "strategies"),
            data_manager=mock_data_manager,
            signal_logger=mock_signal_logger,
            csv_writer=mock_csv_writer,
        )

        # 创建模拟的 StrategyEntry
        from strategy_core.strategy_engine.registry import StrategyEntry, StrategyStatus
        from strategy_core.signal_logging.storage import Signal

        entry = StrategyEntry(
            strategy_id="test_strategy_001",
            strategy_name="RBreaker_v2_1m_BTCUSDT",
            module_path="strategies.cta_rbreaker.strategy",
            config={
                "version": "v2",
                "params": {"threshold": 0.005},
                "risk": {
                    "stop_loss_pct": 2,  # 2 表示 2%（数值形式）
                    "trailing_profit_activation": 5,  # 5 表示 5%
                    "trailing_profit_drawdown": 5,  # 5 表示 5%
                },
            },
            status=StrategyStatus.RUNNING,
        )

        # 构建策略参数
        strategy_params = engine._build_strategy_params(entry)

        # 创建信号
        signal = Signal(
            signal_id="test_001",
            strategy_id="test_strategy_001",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            strength=0.8,
            timestamp=datetime.now(timezone.utc),
        )

        # 调用 _log_signal_unified
        engine._log_signal_unified(signal, strategy_params, entry)

        # 验证 CSV 和 Kafka 使用相同的 CtaSignalCSV 对象
        # CSV write_cta_signal 被调用
        mock_csv_writer.write_cta_signal.assert_called_once()
        csv_call = mock_csv_writer.write_cta_signal.call_args
        cta_signal_for_csv = csv_call.args[0]

        # Kafka log_cta_signal 被调用
        mock_signal_logger.log_cta_signal.assert_called_once()
        kafka_call = mock_signal_logger.log_cta_signal.call_args
        cta_signal_for_kafka = kafka_call.args[0]

        # 两者应该是同一个对象
        assert cta_signal_for_csv is cta_signal_for_kafka, "CSV 和 Kafka 应使用同一个 CtaSignalCSV 对象"

        # 验证风控字段
        json_data = cta_signal_for_csv.to_json()
        params = json_data["strategy"]["params"]
        assert params["StopLossThreshold"] == -0.02  # 止损阈值应为负数
        assert params["TakeProfitBackThreshold"] == 0.05
        assert params["TakeProfitBackDynamicFallPercent"] == 0.05

    def test_engine_leverage_from_config_to_json(self, tmp_path):
        """验证 capital.leverage 从配置文件正确传递到 JSON 输出"""
        from strategy_core.strategy_engine.engine import StrategyEngine
        from strategy_core.signal_logging.csv_adapter import SignalCsvWriter
        from strategy_core.signal_logging import SignalStorage, SignalLogger
        from strategy_core.signal_logging.storage import Signal, SignalType

        # 创建 mock
        mock_data_manager = MagicMock()
        mock_csv_writer = MagicMock(spec=SignalCsvWriter)
        mock_csv_writer.write_cta_signal.return_value = True
        mock_signal_logger = MagicMock()

        # 创建引擎
        engine = StrategyEngine(
            factory_endpoint="http://127.0.0.1:8888",
            strategies_dir=str(tmp_path / "strategies"),
            data_manager=mock_data_manager,
            signal_logger=mock_signal_logger,
            csv_writer=mock_csv_writer,
        )

        # 创建模拟的 StrategyEntry，包含 leverage 配置
        from strategy_core.strategy_engine.registry import StrategyEntry, StrategyStatus

        entry = StrategyEntry(
            strategy_id="test_strategy_leverage",
            strategy_name="RBreaker_v3_15m_SOLUSDT",
            module_path="strategies.cta_rbreaker.strategy",
            config={
                "version": "v3",
                "params": {"threshold": 0.005},
                "capital": {
                    "max_cash": 200,
                    "max_parts": 1,
                    "leverage": 10,  # 自定义杠杆倍数
                },
            },
            status=StrategyStatus.RUNNING,
        )

        # 构建策略参数
        strategy_params = engine._build_strategy_params(entry)

        # 创建信号
        signal = Signal(
            signal_id="test_leverage_001",
            strategy_id="test_strategy_leverage",
            signal_type=SignalType.BUY,
            symbol="SOLUSDT",
            price=150.0,
            strength=0.8,
            timestamp=datetime.now(timezone.utc),
        )

        # 调用 _log_signal_unified
        engine._log_signal_unified(signal, strategy_params, entry)

        # 获取 CtaSignalCSV 对象
        mock_csv_writer.write_cta_signal.assert_called_once()
        csv_call = mock_csv_writer.write_cta_signal.call_args
        cta_signal = csv_call.args[0]

        # 验证 leverage 正确传递到 JSON
        json_data = cta_signal.to_json()
        assert json_data["strategy"]["leverage"] == 10, "leverage 应从配置正确传递到 JSON"

    def test_csv_to_json_matches_kafka_format(self, tmp_path):
        """CSV 存储的数据 to_json() 后应与 Kafka 发送格式一致"""
        from strategy_core.signal_logging.csv_adapter import CtaSignalCSV
        from strategy_core.signal_logging.storage import Signal, SignalType

        # 创建信号
        signal = Signal(
            signal_id="test_001",
            strategy_id="RBreaker_v2_1m_BTCUSDT",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            strength=0.8,
            timestamp=datetime(2026, 5, 9, 10, 30, 0, tzinfo=timezone.utc),
        )

        # 策略参数（包含风控字段）
        # 注意：strategy_params 中的风控字段也使用数值形式
        strategy_params = {
            "threshold": 0.005,
            "StopLossThreshold": 2,  # 2 表示 2%（数值形式）
            "TakeProfitBackThreshold": 5,  # 5 表示 5%
            "TakeProfitBackDynamicFallPercent": 5,  # 5 表示 5%
        }

        # 从信号创建 CtaSignalCSV
        cta_signal = CtaSignalCSV.from_signal(
            signal=signal,
            strategy_name="RBreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params=strategy_params,
            strategy_cash=1000,
            strategy_parts=2,
            risk_stop_loss_pct=2,  # 2 表示 2%（数值形式）
            risk_trailing_profit_activation=5,  # 5 表示 5%
            risk_trailing_profit_drawdown=5,  # 5 表示 5%
        )

        # to_json() 应该可以直接发送到 Kafka
        json_data = cta_signal.to_json()

        # 验证 JSON 结构
        assert json_data["SignalID"] == "test_001"
        assert json_data["symbol"] == "BTCUSDT"
        assert json_data["strategy"]["version"] == "v2"
        assert json_data["strategy"]["internal"] == "1m"
        assert json_data["strategy"]["cash"] == 1000
        assert json_data["strategy"]["parts"] == 2

        # 验证 params 包含风控字段
        params = json_data["strategy"]["params"]
        assert params["StopLossThreshold"] == -0.02  # 止损阈值应为负数
        assert params["TakeProfitBackThreshold"] == 0.05
        assert params["TakeProfitBackDynamicFallPercent"] == 0.05

        # 验证 signal 部分
        assert json_data["signal"]["side"] == 1
        assert json_data["signal"]["action"] == "buy"
        assert json_data["signal"]["trigger_price"] == 70000.0
