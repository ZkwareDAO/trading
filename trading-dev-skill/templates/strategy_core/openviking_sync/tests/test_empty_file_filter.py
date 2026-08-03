"""
空文件过滤测试

测试 UniversalSyncer 的空文件检测和跳过逻辑：
- CSV 只有表头时跳过
- JSON 无有效数据时跳过
- 有数据时正常上传
- 哨兵文件为空时跳过整个目录
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from strategy_core.openviking_sync.universal_syncer import UniversalSyncer
from strategy_core.openviking_sync.ov_client import OpenVikingClient, OpenVikingConfig


class TestSentinelFileFilter:
    """哨兵文件过滤测试"""

    @pytest.fixture
    def mock_ov_client(self):
        """创建模拟的 OpenViking 客户端"""
        config = OpenVikingConfig(
            server_url="http://localhost:1933",
            enabled=True,
            account="test",
        )
        client = OpenVikingClient(config)
        client.add_resource = Mock(return_value=None)
        return client

    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_skip_directory_when_sentinel_empty(self, mock_ov_client, temp_dir):
        """哨兵文件为空时跳过整个目录"""
        # 创建 symbol 目录结构
        symbol_dir = temp_dir / "cta_ict_v3" / "20260615" / "103839" / "ETHUSDT"
        symbol_dir.mkdir(parents=True)

        # 创建空的哨兵文件
        sentinel_file = symbol_dir / "backtest_signals.csv"
        sentinel_file.write_text("signal_id,signal_timestamp,symbol\n")

        # 创建其他文件
        trades_file = symbol_dir / "backtest_trades.csv"
        trades_file.write_text("trade_id,symbol\ntrade_001,ETHUSDT\n")

        config = {
            "paths": [str(temp_dir)],
            "pattern": "**/*",
            "formatter": "raw",
            "skip_empty": True,
            "sentinel_file": "backtest_signals.csv",
        }

        syncer = UniversalSyncer("test", config, mock_ov_client)
        files = syncer._scan_files(datetime.now(timezone.utc))
        filtered = syncer._filter_by_sentinel(files)

        # 所有文件都应该被过滤掉
        assert len(filtered) == 0

    def test_upload_directory_when_sentinel_has_data(self, mock_ov_client, temp_dir):
        """哨兵文件有数据时上传整个目录"""
        symbol_dir = temp_dir / "cta_ict_v3" / "20260615" / "103839" / "ETHUSDT"
        symbol_dir.mkdir(parents=True)

        # 创建有数据的哨兵文件
        sentinel_file = symbol_dir / "backtest_signals.csv"
        sentinel_file.write_text("signal_id,signal_timestamp,symbol\nsig_001,123,ETHUSDT\n")

        # 创建其他文件
        trades_file = symbol_dir / "backtest_trades.csv"
        trades_file.write_text("trade_id,symbol\ntrade_001,ETHUSDT\n")

        config = {
            "paths": [str(temp_dir)],
            "pattern": "**/*.csv",
            "formatter": "raw",
            "skip_empty": True,
            "sentinel_file": "backtest_signals.csv",
        }

        syncer = UniversalSyncer("test", config, mock_ov_client)
        files = syncer._scan_files(datetime.now(timezone.utc))
        filtered = syncer._filter_by_sentinel(files)

        # 两个文件都应该保留
        assert len(filtered) == 2
        file_names = [f.name for f in filtered]
        assert "backtest_signals.csv" in file_names
        assert "backtest_trades.csv" in file_names

    def test_keep_files_when_sentinel_not_exists(self, mock_ov_client, temp_dir):
        """哨兵文件不存在时保留所有文件"""
        symbol_dir = temp_dir / "cta_ict_v3" / "20260615" / "103839" / "ETHUSDT"
        symbol_dir.mkdir(parents=True)

        # 只创建非哨兵文件
        trades_file = symbol_dir / "backtest_trades.csv"
        trades_file.write_text("trade_id,symbol\ntrade_001,ETHUSDT\n")

        config = {
            "paths": [str(temp_dir)],
            "pattern": "**/*.csv",
            "formatter": "raw",
            "skip_empty": True,
            "sentinel_file": "backtest_signals.csv",
        }

        syncer = UniversalSyncer("test", config, mock_ov_client)
        files = syncer._scan_files(datetime.now(timezone.utc))
        filtered = syncer._filter_by_sentinel(files)

        # 文件应该保留（哨兵不存在）
        assert len(filtered) == 1
        assert filtered[0].name == "backtest_trades.csv"

    def test_multiple_symbol_directories(self, mock_ov_client, temp_dir):
        """多个 symbol 目录独立过滤"""
        # ETHUSDT - 空哨兵
        eth_dir = temp_dir / "cta_ict_v3" / "20260615" / "103839" / "ETHUSDT"
        eth_dir.mkdir(parents=True)
        (eth_dir / "backtest_signals.csv").write_text("signal_id\n")
        (eth_dir / "backtest_trades.csv").write_text("trade_id\ntrade_001\n")

        # BTCUSDT - 有数据哨兵
        btc_dir = temp_dir / "cta_ict_v3" / "20260615" / "103839" / "BTCUSDT"
        btc_dir.mkdir(parents=True)
        (btc_dir / "backtest_signals.csv").write_text("signal_id\nsig_001\n")
        (btc_dir / "backtest_trades.csv").write_text("trade_id\ntrade_002\n")

        config = {
            "paths": [str(temp_dir)],
            "pattern": "**/*.csv",
            "formatter": "raw",
            "skip_empty": True,
            "sentinel_file": "backtest_signals.csv",
        }

        syncer = UniversalSyncer("test", config, mock_ov_client)
        files = syncer._scan_files(datetime.now(timezone.utc))
        filtered = syncer._filter_by_sentinel(files)

        # 只有 BTCUSDT 目录的文件保留
        assert len(filtered) == 2
        for f in filtered:
            assert "BTCUSDT" in str(f)


class TestEmptyFileDetection:
    """空文件检测测试"""

    @pytest.fixture
    def mock_ov_client(self):
        """创建模拟的 OpenViking 客户端"""
        config = OpenVikingConfig(
            server_url="http://localhost:1933",
            enabled=True,
            account="test",
        )
        client = OpenVikingClient(config)
        client.add_resource = Mock(return_value=None)
        return client

    @pytest.fixture
    def temp_dir(self):
        """创建临时目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_skip_empty_csv_only_header(self, mock_ov_client, temp_dir):
        """CSV 只有表头时跳过上传"""
        # 创建只有表头的 CSV
        csv_file = temp_dir / "empty_signals.csv"
        csv_file.write_text("signal_id,signal_timestamp,symbol\n")

        # 配置启用空文件跳过
        config = {
            "paths": [str(temp_dir)],
            "pattern": "*.csv",
            "formatter": "raw",
            "skip_empty": True,
        }

        syncer = UniversalSyncer("test", config, mock_ov_client)
        result = syncer._sync_file(csv_file, datetime.now(timezone.utc), "test")

        # 应该跳过，返回 None
        assert result is None
        # 不应该调用上传
        mock_ov_client.add_resource.assert_not_called()

    def test_upload_csv_with_data(self, mock_ov_client, temp_dir):
        """CSV 有数据行时正常上传"""
        # 创建有数据的 CSV
        csv_file = temp_dir / "signals.csv"
        csv_file.write_text(
            "signal_id,signal_timestamp,symbol\n"
            "sig_001,1234567890000,BTCUSDT\n"
        )

        config = {
            "paths": [str(temp_dir)],
            "pattern": "*.csv",
            "formatter": "raw",
            "skip_empty": True,
        }

        syncer = UniversalSyncer("test", config, mock_ov_client)
        result = syncer._sync_file(csv_file, datetime.now(timezone.utc), "test")

        # 应该正常上传
        assert result is not None
        assert result.success is True
        mock_ov_client.add_resource.assert_called_once()

    def test_skip_empty_json(self, mock_ov_client, temp_dir):
        """JSON 无有效数据时跳过上传"""
        # 创建空持仓 JSON
        json_file = temp_dir / "empty_position.json"
        json_file.write_text(json.dumps({"position": None, "position_id": None}))

        config = {
            "paths": [str(temp_dir)],
            "pattern": "*.json",
            "formatter": "raw",
            "skip_empty": True,
        }

        syncer = UniversalSyncer("test", config, mock_ov_client)
        result = syncer._sync_file(json_file, datetime.now(timezone.utc), "test")

        # 应该跳过
        assert result is None
        mock_ov_client.add_resource.assert_not_called()

    def test_upload_json_with_data(self, mock_ov_client, temp_dir):
        """JSON 有有效数据时正常上传"""
        # 创建有持仓的 JSON
        json_file = temp_dir / "position.json"
        json_file.write_text(json.dumps({
            "position": "long",
            "position_id": "test_123",
            "symbol": "BTCUSDT",
        }))

        config = {
            "paths": [str(temp_dir)],
            "pattern": "*.json",
            "formatter": "raw",
            "skip_empty": True,
        }

        syncer = UniversalSyncer("test", config, mock_ov_client)
        result = syncer._sync_file(json_file, datetime.now(timezone.utc), "test")

        # 应该正常上传
        assert result is not None
        assert result.success is True
        mock_ov_client.add_resource.assert_called_once()

    def test_no_skip_when_disabled(self, mock_ov_client, temp_dir):
        """禁用 skip_empty 时，空文件也上传"""
        # 创建只有表头的 CSV
        csv_file = temp_dir / "empty.csv"
        csv_file.write_text("header\n")

        config = {
            "paths": [str(temp_dir)],
            "pattern": "*.csv",
            "formatter": "raw",
            "skip_empty": False,  # 禁用
        }

        syncer = UniversalSyncer("test", config, mock_ov_client)
        result = syncer._sync_file(csv_file, datetime.now(timezone.utc), "test")

        # 应该上传（即使为空）
        assert result is not None
        mock_ov_client.add_resource.assert_called_once()


class TestCsvDataRows:
    """CSV 数据行计数测试"""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_count_empty_csv(self, temp_dir):
        """空 CSV（只有表头）返回 0 行数据"""
        csv_file = temp_dir / "empty.csv"
        csv_file.write_text("col1,col2,col3\n")

        from strategy_core.openviking_sync.universal_syncer import UniversalSyncer
        rows = UniversalSyncer._count_csv_data_rows(csv_file)
        assert rows == 0

    def test_count_csv_with_one_row(self, temp_dir):
        """有 1 行数据的 CSV 返回 1"""
        csv_file = temp_dir / "one_row.csv"
        csv_file.write_text("col1,col2\nval1,val2\n")

        from strategy_core.openviking_sync.universal_syncer import UniversalSyncer
        rows = UniversalSyncer._count_csv_data_rows(csv_file)
        assert rows == 1

    def test_count_csv_with_multiple_rows(self, temp_dir):
        """有多行数据的 CSV 返回正确行数"""
        csv_file = temp_dir / "multi.csv"
        csv_file.write_text("col1,col2\nval1,val2\nval3,val4\nval5,val6\n")

        from strategy_core.openviking_sync.universal_syncer import UniversalSyncer
        rows = UniversalSyncer._count_csv_data_rows(csv_file)
        assert rows == 3


class TestJsonValidity:
    """JSON 数据有效性测试"""

    @pytest.fixture
    def temp_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_empty_json_object(self, temp_dir):
        """空 JSON 对象无效"""
        json_file = temp_dir / "empty.json"
        json_file.write_text("{}")

        from strategy_core.openviking_sync.universal_syncer import UniversalSyncer
        assert UniversalSyncer._is_valid_json_data(json_file) is False

    def test_null_position(self, temp_dir):
        """position 为 null 时无效"""
        json_file = temp_dir / "null.json"
        json_file.write_text(json.dumps({"position": None}))

        from strategy_core.openviking_sync.universal_syncer import UniversalSyncer
        assert UniversalSyncer._is_valid_json_data(json_file) is False

    def test_valid_position(self, temp_dir):
        """有 position 值时有效"""
        json_file = temp_dir / "valid.json"
        json_file.write_text(json.dumps({"position": "long", "position_id": "123"}))

        from strategy_core.openviking_sync.universal_syncer import UniversalSyncer
        assert UniversalSyncer._is_valid_json_data(json_file) is True

    def test_valid_array(self, temp_dir):
        """非空数组有效"""
        json_file = temp_dir / "array.json"
        json_file.write_text(json.dumps([{"id": 1}]))

        from strategy_core.openviking_sync.universal_syncer import UniversalSyncer
        assert UniversalSyncer._is_valid_json_data(json_file) is True

    def test_empty_array(self, temp_dir):
        """空数组无效"""
        json_file = temp_dir / "empty_array.json"
        json_file.write_text("[]")

        from strategy_core.openviking_sync.universal_syncer import UniversalSyncer
        assert UniversalSyncer._is_valid_json_data(json_file) is False
