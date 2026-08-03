#!/usr/bin/env python3
"""Tests for load_strategy_config — 验证始终加载 config.test.yaml."""

import tempfile
from pathlib import Path

import pytest
import yaml

from backtest.run_backtest import load_strategy_config


class TestLoadStrategyConfig:
    """load_strategy_config 应始终加载 config.test.yaml."""

    @pytest.fixture
    def temp_strategy_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            strategy_dir = Path(tmpdir) / "test_strategy"
            strategy_dir.mkdir()
            yield strategy_dir

    def test_loads_config_test_yaml(self, temp_strategy_dir):
        """应加载 config.test.yaml 中的内容."""
        config = {
            "test_strategy": {
                "version": "1",
                "symbols": ["ETHUSDT"],
                "timeframes": ["4h"],
                "params": {
                    "obv_timeframes": "4h",
                    "atr_timeframes": "1h",
                },
            }
        }
        config_path = temp_strategy_dir / "config.test.yaml"
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config, f)

        result = load_strategy_config(str(temp_strategy_dir))
        assert result["timeframes"] == ["4h"]
        assert result["params"]["obv_timeframes"] == "4h"
        assert result["params"]["atr_timeframes"] == "1h"

    def test_ignores_config_yaml(self, temp_strategy_dir):
        """即使存在 config.yaml，也应忽略并只加载 config.test.yaml."""
        # 创建 config.yaml
        old_config = {
            "test_strategy": {
                "symbols": ["BTCUSDT"],
                "timeframes": ["1h"],
            }
        }
        old_path = temp_strategy_dir / "config.yaml"
        with open(old_path, "w", encoding="utf-8") as f:
            yaml.dump(old_config, f)

        # 创建 config.test.yaml
        new_config = {
            "test_strategy": {
                "symbols": ["ETHUSDT"],
                "timeframes": ["4h"],
            }
        }
        new_path = temp_strategy_dir / "config.test.yaml"
        with open(new_path, "w", encoding="utf-8") as f:
            yaml.dump(new_config, f)

        result = load_strategy_config(str(temp_strategy_dir))
        assert result["symbols"] == ["ETHUSDT"]
        assert result["timeframes"] == ["4h"]

    def test_returns_empty_when_no_test_yaml(self, temp_strategy_dir):
        """config.test.yaml 不存在时返回空字典."""
        result = load_strategy_config(str(temp_strategy_dir))
        assert result == {}
