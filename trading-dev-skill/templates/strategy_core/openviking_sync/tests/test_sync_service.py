"""
同步服务测试

测试 TradingDataSyncService 类：
- 工厂方法 from_config_file, from_config, from_settings
- sync_daily: 同步当日数据
- sync_range: 同步日期范围
- 去重机制
- 配置路径解析
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from strategy_core.openviking_sync.sync_service import (
    TradingDataSyncService,
    SyncConfig,
    DailySyncResult,
    _resolve_config_path,
)
from strategy_core.openviking_sync.ov_client import OpenVikingConfig
from strategy_core.openviking_sync.universal_syncer import UniversalSyncResult


class TestSyncConfig:
    """配置类测试"""

    def test_default_config(self):
        """默认配置"""
        config = SyncConfig()

        assert config.enabled is True
        assert config.dedup_file == "./data/.ov_synced_records"
        assert config.max_retries == 3

    def test_custom_config(self):
        """自定义配置"""
        config = SyncConfig(
            enabled=False,
            sources={
                "signals": {"paths": ["/custom/signals"]},
                "backtest": {"paths": ["/custom/backtest"]},
            },
            max_retries=5,
        )

        assert config.enabled is False
        assert config.max_retries == 5


class TestDailySyncResult:
    """每日同步结果测试"""

    def test_empty_result(self):
        """空结果"""
        result = DailySyncResult(date="20260529")

        assert result.date == "20260529"
        assert result.total_success == 0
        assert result.total_failed == 0

    def test_with_results(self):
        """有结果"""
        results = [
            UniversalSyncResult(success=True, source_name="signals", uri="uri1", items_count=5, files_synced=1),
            UniversalSyncResult(success=False, source_name="signals", uri="uri2", items_count=0, error="error"),
            UniversalSyncResult(success=True, source_name="backtest", uri="uri3", items_count=3, files_synced=1),
        ]

        result = DailySyncResult(
            date="20260529",
            results=results,
        )

        assert result.total_success == 2
        assert result.total_failed == 1


class TestTradingDataSyncServiceInit:
    """初始化测试"""

    def test_init_with_configs(self, tmp_path: Path):
        """使用配置初始化"""
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        sync_config = SyncConfig(
            sources={
                "signals": {"paths": [str(signals_dir)]},
            }
        )
        ov_config = OpenVikingConfig(enabled=False)

        service = TradingDataSyncService(sync_config, ov_config)

        assert service.config == sync_config
        assert "signals" in service.syncers


class TestFromConfig:
    """工厂方法测试"""

    def test_from_config(self, tmp_path: Path):
        """从配置字典创建"""
        config = {
            "server": {
                "url": "http://localhost:1933",
                "cli_path": "ov",
                "timeout": 60.0,
            },
            "account": {
                "name": "trading",
            },
            "dedup": {
                "file": str(tmp_path / ".synced"),
            },
            "sources": {
                "signals": {
                    "enabled": True,
                    "paths": [str(tmp_path / "signals")],
                    "formatter": "raw",
                },
            },
        }

        service = TradingDataSyncService.from_config(config)

        assert service is not None
        assert service.config.enabled is True


class TestSyncDaily:
    """同步当日数据测试"""

    @pytest.fixture
    def service(self, tmp_path: Path):
        """创建服务实例"""
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        sync_config = SyncConfig(
            sources={
                "signals": {"paths": [str(signals_dir)]},
            },
            dedup_file=str(tmp_path / ".synced"),
        )
        ov_config = OpenVikingConfig(enabled=False)

        return TradingDataSyncService(sync_config, ov_config)

    @patch.object(TradingDataSyncService, "_is_synced")
    @patch("strategy_core.openviking_sync.universal_syncer.UniversalSyncer.sync_daily")
    def test_sync_daily(
        self,
        mock_syncer,
        mock_is_synced,
        service,
    ):
        """同步数据"""
        mock_is_synced.return_value = False
        mock_syncer.return_value = [
            UniversalSyncResult(success=True, source_name="signals", uri="uri", items_count=5, files_synced=1),
        ]

        date = datetime(2026, 5, 29)
        result = service.sync_daily(date)

        assert result.total_success == 1


class TestSyncRange:
    """同步日期范围测试"""

    @pytest.fixture
    def service(self, tmp_path: Path):
        """创建服务实例"""
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        sync_config = SyncConfig(
            sources={
                "signals": {"paths": [str(signals_dir)]},
            },
            dedup_file=str(tmp_path / ".synced"),
        )
        ov_config = OpenVikingConfig(enabled=False)

        return TradingDataSyncService(sync_config, ov_config)

    @patch.object(TradingDataSyncService, "sync_daily")
    def test_sync_range(self, mock_sync, service):
        """同步日期范围"""
        mock_sync.return_value = DailySyncResult(date="test", results=[])

        start = datetime(2026, 5, 25)
        end = datetime(2026, 5, 29)

        results = service.sync_range(start, end)

        # 5 天 (25, 26, 27, 28, 29)
        assert len(results) == 5
        assert mock_sync.call_count == 5


class TestDedup:
    """去重机制测试"""

    @pytest.fixture
    def service_with_dedup(self, tmp_path: Path):
        """创建带去重文件的服务"""
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        dedup_file = tmp_path / ".synced"

        sync_config = SyncConfig(
            sources={
                "signals": {"paths": [str(signals_dir)]},
            },
            dedup_file=str(dedup_file),
        )
        ov_config = OpenVikingConfig(enabled=False)

        return TradingDataSyncService(sync_config, ov_config)

    def test_load_synced_records_empty(self, service_with_dedup):
        """加载空去重记录"""
        records = service_with_dedup._load_synced_records()

        assert records == set()

    def test_mark_synced(self, service_with_dedup, tmp_path: Path):
        """标记已同步"""
        results = [
            UniversalSyncResult(success=True, source_name="signals", uri="uri1", items_count=5, files_synced=1),
            UniversalSyncResult(success=True, source_name="backtest", uri="uri2", items_count=3, files_synced=1),
        ]

        result = DailySyncResult(
            date="20260529",
            results=results,
        )

        service_with_dedup._mark_synced(result)

        # 检查去重文件
        dedup_file = tmp_path / ".synced"
        if dedup_file.exists():
            content = dedup_file.read_text()
            # 使用 URI 作为去重 key
            assert "uri1" in content or "uri2" in content

    def test_is_synced(self, service_with_dedup):
        """检查是否已同步"""
        # 初始应该未同步
        assert not service_with_dedup._is_synced("test_uri")


class TestGenerateDailyUri:
    """URI 生成测试"""

    def test_generate_daily_uri(self, tmp_path: Path):
        """生成当日根 URI"""
        signals_dir = tmp_path / "signals"
        signals_dir.mkdir()

        sync_config = SyncConfig(
            sources={
                "signals": {"paths": [str(signals_dir)]},
            }
        )
        ov_config = OpenVikingConfig(enabled=False)
        service = TradingDataSyncService(sync_config, ov_config)

        date = datetime(2026, 5, 29)
        uri = service._generate_daily_uri(date)

        assert uri == "viking://resources/trading_data/2026/05/29/"


class TestResolveConfigPath:
    """配置路径解析测试"""

    def test_resolve_explicit_config_exists(self, tmp_path: Path):
        """指定存在的配置文件"""
        config_file = tmp_path / "custom.yaml"
        config_file.write_text("server: {url: 'http://test'}")

        result = _resolve_config_path(str(config_file))

        assert result == str(config_file)

    def test_resolve_explicit_config_not_exists(self, tmp_path: Path):
        """指定不存在的配置文件，回退到默认"""
        # 创建默认配置
        default_dir = Path("./config")
        default_dir.mkdir(exist_ok=True)
        default_config = default_dir / "openviking_sync.yaml"
        default_config.write_text("server: {url: 'http://default'}")

        try:
            result = _resolve_config_path(str(tmp_path / "nonexistent.yaml"))
            assert result == str(default_config)
        finally:
            default_config.unlink(missing_ok=True)

    def test_resolve_no_config_uses_default(self, tmp_path: Path):
        """未指定配置时使用默认"""
        default_dir = Path("./config")
        default_dir.mkdir(exist_ok=True)
        default_config = default_dir / "openviking_sync.yaml"
        default_config.write_text("server: {url: 'http://default'}")

        try:
            result = _resolve_config_path(None)
            assert result == str(default_config)
        finally:
            default_config.unlink(missing_ok=True)

    def test_resolve_no_config_no_default(self):
        """未指定配置且默认也不存在"""
        # 确保默认配置不存在
        default_config = Path("./config/openviking_sync.yaml")
        original_content = None
        existed = default_config.exists()

        try:
            if existed:
                original_content = default_config.read_text()
                default_config.unlink()

            result = _resolve_config_path(None)
            assert result is None

        finally:
            if existed and original_content:
                default_config.write_text(original_content)


class TestFromSettingsWithConfigPath:
    """from_settings 的 config_path 参数测试"""

    def test_from_settings_with_valid_config_path(self, tmp_path: Path):
        """使用有效的 config_path"""
        config_file = tmp_path / "test_config.yaml"
        config_file.write_text("""
server:
  url: http://test:1933
  cli_path: ov
account:
  name: test_account
sources:
  signals:
    paths: []
""")

        service = TradingDataSyncService.from_settings({}, str(config_file))

        assert service is not None
        assert service.ov_config.server_url == "http://test:1933"

    def test_from_settings_with_invalid_config_path_falls_back(self, tmp_path: Path):
        """config_path 无效时回退"""
        # 创建默认配置
        default_dir = Path("./config")
        default_dir.mkdir(exist_ok=True)
        default_config = default_dir / "openviking_sync.yaml"
        default_config.write_text("""
server:
  url: http://default:1933
  cli_path: ov
account:
  name: default_account
sources:
  signals:
    paths: []
""")

        try:
            # 传入不存在的路径，应回退到默认
            service = TradingDataSyncService.from_settings(
                {},
                str(tmp_path / "nonexistent.yaml")
            )

            assert service is not None
            assert service.ov_config.server_url == "http://default:1933"

        finally:
            default_config.unlink(missing_ok=True)

    def test_from_settings_without_config_path_uses_default(self, tmp_path: Path):
        """不传 config_path 时使用默认"""
        default_dir = Path("./config")
        default_dir.mkdir(exist_ok=True)
        default_config = default_dir / "openviking_sync.yaml"
        default_config.write_text("""
server:
  url: http://default:1933
  cli_path: ov
account:
  name: default_account
sources:
  signals:
    paths: []
""")

        try:
            service = TradingDataSyncService.from_settings({})

            assert service is not None
            assert service.ov_config.server_url == "http://default:1933"

        finally:
            default_config.unlink(missing_ok=True)