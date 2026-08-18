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