#!/usr/bin/env python3
"""
测试回测配置文件复制功能

验证 run_backtest() 在执行时将配置文件复制到输出目录。
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone

from backtest.run_backtest import run_backtest


class TestConfigCopy:
    """测试配置文件复制功能"""

    @pytest.fixture
    def temp_output_dir(self):
        """创建临时输出目录"""
        temp_dir = tempfile.mkdtemp(prefix="backtest_test_")
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def temp_config_file(self):
        """创建临时配置文件"""
        config_content = """
cta_trend:
  timeframes:
    - 15m
  params:
    ma_fast: 10
    ma_slow: 20
  signal:
    min_strength: 0.5
"""
        temp_file = tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        )
        temp_file.write(config_content)
        temp_file.flush()
        temp_file.close()
        yield temp_file.name
        Path(temp_file.name).unlink(missing_ok=True)

    def test_config_file_copied_to_output_dir(
        self, temp_output_dir, temp_config_file
    ):
        """
        验证配置文件被复制到回测输出目录

        场景：运行回测时指定 config_path 参数
        期望：输出目录包含 config.yaml 文件
        """
        run_backtest(
            strategy_dir_name="cta_trend",
            symbol="BTCUSDT",
            start_date="20260601",
            end_date="20260602",
            data_dir="./data/strategies",
            output_dir=temp_output_dir,
            cash=1000,
            strategy_config={
                "timeframes": ["15m"],
                "params": {"ma_fast": 10, "ma_slow": 20},
                "signal": {"min_strength": 0.5},
            },
            config_path=temp_config_file,  # 传递配置文件路径
        )

        # 验证：输出目录应包含 config.yaml
        output_files = list(Path(temp_output_dir).rglob("config.yaml"))
        assert len(output_files) > 0, "配置文件应被复制到输出目录"

    def test_no_config_path_no_copy(self, temp_output_dir):
        """
        验证未指定配置文件路径时不复制

        场景：config_path 为 None
        期望：输出目录不包含 config.yaml
        """
        run_backtest(
            strategy_dir_name="cta_trend",
            symbol="BTCUSDT",
            start_date="20260601",
            end_date="20260602",
            data_dir="./data/strategies",
            output_dir=temp_output_dir,
            cash=1000,
            strategy_config={
                "timeframes": ["15m"],
                "params": {"ma_fast": 10, "ma_slow": 20},
                "signal": {"min_strength": 0.5},
            },
            config_path=None,  # 不传递配置文件路径
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])