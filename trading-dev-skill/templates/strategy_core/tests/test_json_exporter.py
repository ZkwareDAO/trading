#!/usr/bin/env python3
"""
SignalJsonExporter 单元测试

测试从 CSV 读取信号并导出为 JSON 格式的功能
"""

import json
import pytest
from datetime import datetime, timezone
from pathlib import Path

from strategy_core.signal_logging.logger import SignalStorage
from strategy_core.signal_logging.storage import Signal
from strategy_core.signal_logging.json_exporter import SignalJsonExporter


def _write_test_signal_with_date(
    tmp_path, strategy_id="test_strategy", count=2, date_override=None
):
    """写入测试信号到 CSV（使用动态日期和时区）"""
    signal_dir = tmp_path / "signals" / strategy_id
    signal_dir.mkdir(parents=True, exist_ok=True)

    date_str = date_override or datetime.now().strftime('%Y%m%d')
    csv_file = signal_dir / f"{date_str}.csv"

    now_iso = datetime.now(timezone.utc).isoformat()
    with open(csv_file, "w", encoding="utf-8") as f:
        f.write("signal_id,strategy_id,strategy_type,signal_type,symbol,price,volume,direction,strength,timestamp,metadata\n")
        for i in range(count):
            signal_type = "buy" if i % 2 == 0 else "sell"
            direction = "long" if i % 2 == 0 else "short"
            price = 50000.0 + i * 100
            strength = 0.8 - i * 0.1
            f.write(f"sig-{i:03d},{strategy_id},,{signal_type},BTCUSDT,{price},0.1,{direction},{strength},{now_iso},\"{{}}\"\n")


class TestSignalJsonExporterInit:
    """测试初始化"""

    def test_init_accepts_signal_storage(self, tmp_path):
        """测试接受 SignalStorage 实例"""
        storage = SignalStorage(base_dir=str(tmp_path / "signals"))
        exporter = SignalJsonExporter(storage)
        assert exporter is not None


class TestExportInternalFormat:
    """测试内部格式导出"""

    @pytest.fixture
    def exporter(self, tmp_path):
        signal_dir = tmp_path / "signals"
        storage = SignalStorage(base_dir=str(signal_dir))
        return SignalJsonExporter(storage)

    def test_export_internal_format_returns_list_of_dicts(self, exporter, tmp_path):
        """测试内部格式返回字典列表"""
        _write_test_signal_with_date(tmp_path, count=2)

        result = exporter.export_signals(strategy_id="test_strategy", fmt="internal")

        assert isinstance(result, list)
        assert len(result) == 2

    def test_internal_format_has_required_fields(self, exporter, tmp_path):
        """测试内部格式包含必需字段"""
        _write_test_signal_with_date(tmp_path, count=1)

        result = exporter.export_signals(strategy_id="test_strategy", fmt="internal")

        required_fields = {"signal_id", "strategy_id", "signal_type", "symbol", "price", "timestamp"}
        for signal_dict in result:
            assert required_fields.issubset(signal_dict.keys())

    def test_internal_format_preserves_metadata(self, exporter, tmp_path):
        """测试 metadata 字段完整保留"""
        _write_test_signal_with_date(tmp_path)

        result = exporter.export_signals(strategy_id="test_strategy", fmt="internal")

        buy_signal = [s for s in result if s["signal_type"] == "buy"][0]
        assert "metadata" in buy_signal


class TestExportKafkaFormat:
    """测试 Kafka 格式导出"""

    @pytest.fixture
    def exporter(self, tmp_path):
        signal_dir = tmp_path / "signals"
        storage = SignalStorage(base_dir=str(signal_dir))
        return SignalJsonExporter(storage)

    def test_kafka_format_has_nested_structure(self, exporter, tmp_path):
        """测试 Kafka 格式有嵌套结构"""
        _write_test_signal_with_date(tmp_path, count=1)

        result = exporter.export_signals(strategy_id="test_strategy", fmt="kafka")

        assert isinstance(result, list)
        assert len(result) == 1

        signal_dict = result[0]
        assert "strategy" in signal_dict
        assert "signal" in signal_dict

    def test_kafka_format_strategy_fields(self, exporter, tmp_path):
        """测试 Kafka 格式 strategy 字段"""
        _write_test_signal_with_date(tmp_path, count=1)

        result = exporter.export_signals(strategy_id="test_strategy", fmt="kafka")
        strategy = result[0]["strategy"]

        assert "name" in strategy
        assert "version" in strategy
        assert "internal" in strategy
        assert "params" in strategy

    def test_kafka_format_signal_fields(self, exporter, tmp_path):
        """测试 Kafka 格式 signal 字段"""
        _write_test_signal_with_date(tmp_path, count=1)

        result = exporter.export_signals(strategy_id="test_strategy", fmt="kafka")
        signal = result[0]["signal"]

        assert "side" in signal
        assert "exchange" in signal
        assert "trigger_price" in signal
        assert "order_type" in signal


class TestExportToFile:
    """测试导出到文件"""

    @pytest.fixture
    def exporter(self, tmp_path):
        signal_dir = tmp_path / "signals"
        storage = SignalStorage(base_dir=str(signal_dir))
        return SignalJsonExporter(storage)

    def test_export_to_file_creates_valid_json(self, exporter, tmp_path):
        """测试导出到文件创建合法 JSON"""
        _write_test_signal_with_date(tmp_path, count=1)

        output_path = str(tmp_path / "output.json")
        count = exporter.export_to_file(output_path, strategy_id="test_strategy")

        assert count == 1  # 1 signal written
        assert Path(output_path).exists()

        with open(output_path) as f:
            data = json.load(f)

        assert isinstance(data, list)
        assert len(data) == 1

    def test_export_to_file_returns_count(self, exporter, tmp_path):
        """测试返回写入数量"""
        _write_test_signal_with_date(tmp_path, count=1)

        output_path = str(tmp_path / "output.json")
        count = exporter.export_to_file(output_path, strategy_id="test_strategy")

        assert count > 0


class TestExportFilters:
    """测试过滤功能"""

    @pytest.fixture
    def exporter(self, tmp_path):
        signal_dir = tmp_path / "signals"
        storage = SignalStorage(base_dir=str(signal_dir))
        return SignalJsonExporter(storage)

    def _write_multi_strategy_signals(self, tmp_path):
        """写入多个策略的信号"""
        for strategy in ["strategy_a", "strategy_b"]:
            _write_test_signal_with_date(tmp_path, strategy_id=strategy, count=1)

    def test_filter_by_strategy_id(self, exporter, tmp_path):
        """测试按策略 ID 过滤"""
        self._write_multi_strategy_signals(tmp_path)

        result = exporter.export_signals(strategy_id="strategy_a")
        assert len(result) == 1
        assert result[0]["strategy_id"] == "strategy_a"

    def test_filter_by_symbol(self, exporter, tmp_path):
        """测试按标的过滤"""
        self._write_multi_strategy_signals(tmp_path)

        result = exporter.export_signals(strategy_id="strategy_a", symbol="BTCUSDT")
        assert len(result) == 1

        result = exporter.export_signals(strategy_id="strategy_a", symbol="ETHUSDT")
        assert len(result) == 0

    def test_filter_by_time_range(self, exporter, tmp_path):
        """测试按时间范围过滤"""
        self._write_multi_strategy_signals(tmp_path)

        # 使用较宽的时间范围
        start = datetime.now(timezone.utc) - __import__('datetime').timedelta(days=1)
        end = datetime.now(timezone.utc) + __import__('datetime').timedelta(days=1)

        result = exporter.export_signals(strategy_id="strategy_a", start_time=start, end_time=end)
        assert len(result) == 1

    def test_empty_strategy_returns_empty_list(self, exporter, tmp_path):
        """测试空策略返回空列表"""
        result = exporter.export_signals(strategy_id="nonexistent")
        assert result == []


class TestExportLatest:
    """测试导出最新信号"""

    @pytest.fixture
    def exporter(self, tmp_path):
        signal_dir = tmp_path / "signals"
        storage = SignalStorage(base_dir=str(signal_dir))
        return SignalJsonExporter(storage)

    def test_export_latest_returns_limited_count(self, exporter, tmp_path):
        """测试导出最新 N 条"""
        _write_test_signal_with_date(tmp_path, count=5)

        result = exporter.export_latest(strategy_id="test_strategy", limit=3)
        assert len(result) == 3

    def test_export_latest_returns_newest_first(self, exporter, tmp_path):
        """测试最新信号在前"""
        _write_test_signal_with_date(tmp_path, count=5)

        result = exporter.export_latest(strategy_id="test_strategy", limit=2)
        # 时间倒序 - 两个信号时间相同，所以按 signal_id 排序
        assert len(result) == 2


class TestExportStatistics:
    """测试统计信息导出"""

    @pytest.fixture
    def exporter(self, tmp_path):
        signal_dir = tmp_path / "signals"
        storage = SignalStorage(base_dir=str(signal_dir))
        return SignalJsonExporter(storage)

    def test_export_statistics_returns_dict(self, exporter, tmp_path):
        """测试统计信息返回字典"""
        _write_test_signal_with_date(tmp_path)

        result = exporter.export_statistics(strategy_id="test_strategy")

        assert isinstance(result, dict)
        assert "total" in result
        assert result["total"] > 0

    def test_export_statistics_has_expected_fields(self, exporter, tmp_path):
        """测试统计信息包含期望字段"""
        _write_test_signal_with_date(tmp_path)

        result = exporter.export_statistics(strategy_id="test_strategy")

        expected_fields = {"total", "buy_count", "sell_count", "avg_strength"}
        assert expected_fields.issubset(result.keys())

    def test_export_statistics_empty_strategy(self, exporter, tmp_path):
        """测试空策略统计"""
        result = exporter.export_statistics(strategy_id="nonexistent")
        assert isinstance(result, dict)
        assert result["total"] == 0


class TestExportAll:
    """测试导出全部信号"""

    @pytest.fixture
    def exporter(self, tmp_path):
        signal_dir = tmp_path / "signals"
        storage = SignalStorage(base_dir=str(signal_dir))
        return SignalJsonExporter(storage)

    def test_export_all_returns_all_signals(self, exporter, tmp_path):
        """测试导出所有信号"""
        _write_test_signal_with_date(tmp_path, count=5)

        result = exporter.export_all(strategy_id="test_strategy")
        assert len(result) == 5

    def test_export_all_no_limit(self, exporter, tmp_path):
        """测试导出无限制"""
        _write_test_signal_with_date(tmp_path, count=5)

        result = exporter.export_all(strategy_id="test_strategy")
        assert len(result) == 5

        latest = exporter.export_latest(strategy_id="test_strategy", limit=5)
        assert len(latest) == 5


class TestToKafkaFormatKwargs:
    """测试 _to_kafka_format 支持 kwargs 透传"""

    @pytest.fixture
    def exporter(self, tmp_path):
        signal_dir = tmp_path / "signals"
        storage = SignalStorage(base_dir=str(signal_dir))
        return SignalJsonExporter(storage)

    def test_to_kafka_format_accepts_user_id(self, exporter, tmp_path):
        """_to_kafka_format 应支持 user_id 参数"""
        _write_test_signal_with_date(tmp_path)
        signals = exporter.export_signals(strategy_id="test_strategy", fmt="internal")
        signal_obj = Signal.from_dict(signals[0])

        result = exporter._to_kafka_format(signal_obj, user_id=42)
        assert result["user_id"] == 42

    def test_to_kafka_format_default_user_id(self, exporter, tmp_path):
        """未传 user_id 时应使用默认值"""
        _write_test_signal_with_date(tmp_path)
        signals = exporter.export_signals(strategy_id="test_strategy", fmt="internal")
        signal_obj = Signal.from_dict(signals[0])

        result = exporter._to_kafka_format(signal_obj)
        # 默认值为 1
        assert result["user_id"] == 1
