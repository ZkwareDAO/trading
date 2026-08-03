"""
CLI 测试

测试命令行入口功能
"""

from io import StringIO
from unittest.mock import patch, MagicMock

import pytest

from strategy_core.openviking_sync.__main__ import main, cmd_sync, cmd_health


class TestMain:
    """主入口测试"""

    def test_main_no_args(self):
        """无参数显示帮助"""
        with patch("sys.argv", ["openviking_sync"]):
            with patch("sys.stdout", new_callable=StringIO):
                result = main()
                assert result == 0

    def test_main_help(self):
        """帮助参数"""
        with patch("sys.argv", ["openviking_sync", "--help"]):
            with pytest.raises(SystemExit):
                main()


class TestCmdSync:
    """同步命令测试"""

    @patch("strategy_core.openviking_sync.__main__.TradingDataSyncService")
    def test_sync_today(self, mock_service_class):
        """同步今天"""
        mock_service = MagicMock()
        mock_service.sync_daily.return_value = MagicMock(
            total_success=1,
            total_failed=0,
            signals=[],
            backtests=[],
        )
        mock_service_class.from_settings.return_value = mock_service

        args = MagicMock(
            today=True,
            date=None,
            all=False,
            start=None,
            end=None,
            strategy=None,
            only_signals=False,
            only_backtest=False,
            config=None,
            verbose=False,
        )

        result = cmd_sync(args)

        assert result == 0
        mock_service.sync_daily.assert_called_once()

    @patch("strategy_core.openviking_sync.__main__.TradingDataSyncService")
    def test_sync_specific_date(self, mock_service_class):
        """同步指定日期"""
        mock_service = MagicMock()
        mock_service.sync_daily.return_value = MagicMock(
            total_success=1,
            total_failed=0,
            signals=[],
            backtests=[],
        )
        mock_service_class.from_settings.return_value = mock_service

        args = MagicMock(
            today=False,
            date="2026-05-29",
            all=False,
            start=None,
            end=None,
            strategy=None,
            only_signals=False,
            only_backtest=False,
            config=None,
            verbose=False,
        )

        result = cmd_sync(args)

        assert result == 0

    def test_sync_invalid_date(self):
        """无效日期格式"""
        args = MagicMock(
            today=False,
            date="invalid-date",
            all=False,
            start=None,
            end=None,
            strategy=None,
            only_signals=False,
            only_backtest=False,
            config=None,
            verbose=False,
        )

        result = cmd_sync(args)

        assert result == 1  # 返回错误码


class TestCmdHealth:
    """健康检查命令测试"""

    @patch("strategy_core.openviking_sync.__main__.OpenVikingClient")
    def test_health_check(self, mock_client_class):
        """健康检查"""
        mock_client = MagicMock()
        mock_client.check_health.return_value = True
        mock_client_class.return_value = mock_client

        args = MagicMock(config=None)

        result = cmd_health(args)

        assert result == 0


class TestCliIntegration:
    """CLI 集成测试"""

    def test_cli_import(self):
        """CLI 模块可导入"""
        from strategy_core.openviking_sync.__main__ import main
        assert callable(main)
