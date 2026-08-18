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



    def test_returns_empty_when_no_test_yaml(self, temp_strategy_dir):
        """config.test.yaml 不存在时返回空字典."""
        result = load_strategy_config(str(temp_strategy_dir))
        assert result == {}
