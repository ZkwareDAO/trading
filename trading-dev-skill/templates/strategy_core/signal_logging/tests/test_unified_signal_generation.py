# NOTE: IP addresses in this test are mock values, not real endpoints
#!/usr/bin/env python3
"""
测试统一信号数据生成

验证：
1. CtaSignalCSV 对象生成一次，三种输出格式数据一致
2. CSV、HTTP、Kafka 使用相同的 JSON 数据
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch
from pathlib import Path

import pytest

from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV, SignalCsvWriter
from strategy_core.signal_logging.http_sender import HttpSignalSender


class TestUnifiedSignalGeneration:
    """测试统一信号数据生成"""

    def _make_signal(self) -> Signal:
        return Signal(
            signal_id="test_unified_001",
            strategy_id="RBreaker_v2_1m_BTCUSDT",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=70000.0,
            strength=0.85,
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        )

    def _make_strategy_params(self) -> dict:
        return {
            "strategy_name": "RBreaker_v2",
            "strategy_version": "v2",
            "interval": "1m",  # 注意：参数名是 interval，内部存储为 strategy_internal
            "strategy_params": {"threshold": 0.005},
            "strategy_cash": 1000,
            "strategy_parts": 2,
            "strategy_type": "CTAFutureFactory",
            "strategy_type_name": "RBreaker",
            "risk_strategy_type": "cta_intraday",
            "user_id": 1,
            "signal_exchange": "binance",
            "signal_order_type": 1,
            "signal_slippage": 0.001,
            "pos_type": 2,
            "risk_stop_loss_pct": 2.0,
            "risk_trailing_profit_activation": 5.0,
            "risk_trailing_profit_drawdown": 5.0,
        }

    def test_cta_signal_generated_once(self):
        """CtaSignalCSV 对象只生成一次"""
        signal = self._make_signal()
        params = self._make_strategy_params()

        # 生成一次
        cta = CtaSignalCSV.from_signal(signal, **params)

        # 验证基础字段
        assert cta.signal_id == "test_unified_001"
        assert cta.symbol == "BTCUSDT"
        assert cta.strategy_name == "RBreaker_v2"
        assert cta.strategy_version == "v2"
        assert cta.strategy_internal == "1m"

    def test_csv_and_json_data_consistent(self):
        """CSV 行数据和 JSON 数据一致"""
        signal = self._make_signal()
        params = self._make_strategy_params()

        cta = CtaSignalCSV.from_signal(signal, **params)

        # CSV 行数据
        csv_row = cta.to_csv_row()

        # JSON 数据
        json_data = cta.to_json()

        # 验证关键字段一致
        assert csv_row["signal_id"] == json_data["SignalID"]
        assert csv_row["symbol"] == json_data["symbol"]
        # strategy_name 在 CSV 中是完整名称，JSON 中 strategy.name 是基础名称
        assert csv_row["strategy_name"] == "RBreaker_v2"
        assert json_data["strategy"]["name"] == "RBreaker"

    def test_http_sender_accepts_cta_signal(self):
        """HTTP 发送器接受 CtaSignalCSV 对象"""
        signal = self._make_signal()
        params = self._make_strategy_params()

        cta = CtaSignalCSV.from_signal(signal, **params)

        sender = HttpSignalSender(base_url="http://127.0.0.1:18888")

        with patch("strategy_core.signal_logging.http_sender.requests.post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"status": "success"}'
            mock_post.return_value = mock_resp

            # 调用新方法 send_cta_signal
            result = sender.send_cta_signal(cta, topic="strategy_signals")

        assert result is True
        # 验证发送的数据
        call_args = mock_post.call_args
        sent_data = json.loads(call_args.kwargs["data"])
        assert sent_data["topic"] == "strategy_signals"
        message = json.loads(sent_data["message"])
        assert message["SignalID"] == "test_unified_001"

    def test_csv_writer_accepts_cta_signal(self, tmp_path):
        """CSV 写入器接受 CtaSignalCSV 对象"""
        signal = self._make_signal()
        params = self._make_strategy_params()

        cta = CtaSignalCSV.from_signal(signal, **params)

        writer = SignalCsvWriter(base_dir=str(tmp_path))

        # 调用新方法 write_cta_signal
        result = writer.write_cta_signal(cta)

        assert result is True

        # 验证文件存在
        csv_file = tmp_path / "RBreaker_v2" / "20240115.csv"
        assert csv_file.exists()

        # 验证内容
        import csv
        with open(csv_file, "r") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            assert len(rows) == 1
            assert rows[0]["signal_id"] == "test_unified_001"
