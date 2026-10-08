"""Tests for run_strategies_manager.py log level handling."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


class TestStrategyProcessLogLevel:
    """Test log level configuration in strategy process."""

    def test_build_strategy_command_no_log_level_param(self):
        """build_strategy_command 不传递 --log-level 参数"""
        from run_strategies_manager import build_strategy_command

        strategy_config = {
            "name": "cta_ict_v3",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "version": "v2",
            "trading_mode": "live",
        }

        cmd = build_strategy_command(strategy_config, "config/settings.yaml")

        assert "--log-level" not in cmd, f"不应包含 --log-level: {cmd}"

    def test_run_strategy_prioritizes_config_over_cli(self):
        """run_strategy.py 策略配置优先级高于 CLI 参数"""
        from run_strategy import resolve_log_level

        # 策略配置 DEBUG，CLI INFO，应返回 DEBUG
        level = resolve_log_level(
            cli_log_level="INFO",
            strategy_config={"signal": {"diagnostic_log_level": "DEBUG"}},
        )
        assert level == "DEBUG", "策略配置应优先"

        # 策略配置无，CLI DEBUG，应返回 DEBUG
        level = resolve_log_level(
            cli_log_level="DEBUG",
            strategy_config={},
        )
        assert level == "DEBUG", "CLI 参数应生效"

        # 策略配置无，CLI None，应返回默认 INFO
        level = resolve_log_level(
            cli_log_level=None,
            strategy_config={},
        )
        assert level == "INFO", "默认应为 INFO"

    def test_env_log_level_used_when_no_cli(self):
        """无 --log-level 时读 LOG_LEVEL 环境变量（manager 透传路径）"""
        from run_strategy import resolve_effective_log_level

        assert resolve_effective_log_level(None, "DEBUG") == "DEBUG"
        # 环境变量小写也应归一化
        assert resolve_effective_log_level(None, "debug") == "DEBUG"

    def test_cli_log_level_overrides_env(self):
        """--log-level 优先于 LOG_LEVEL 环境变量"""
        from run_strategy import resolve_effective_log_level

        assert resolve_effective_log_level("INFO", "DEBUG") == "INFO"

    def test_default_log_level_info(self):
        """CLI 与环境变量都缺省时为 INFO"""
        from run_strategy import resolve_effective_log_level

        assert resolve_effective_log_level(None, None) == "INFO"

    def test_invalid_env_log_level_falls_back_to_info(self):
        """LOG_LEVEL 为非法值时回退 INFO"""
        from run_strategy import resolve_effective_log_level

        assert resolve_effective_log_level(None, "VERBOSE") == "INFO"

    def test_strategy_config_overrides_env_log_level(self):
        """manager 透传 DEBUG，但策略 overrides 配置的级别仍最高"""
        from run_strategy import resolve_log_level

        level = resolve_log_level(
            cli_log_level="DEBUG",
            strategy_config={"signal": {"diagnostic_log_level": "INFO"}},
        )
        assert level == "INFO", "策略配置应优先于环境变量透传值"