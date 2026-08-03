#!/usr/bin/env python3
"""
测试配置加载器

TDD: RED 阶段 - 先写测试
"""

import pytest
from backtest.config_loader import (
    load_main_config,
    load_batch_config,
    build_config_path,
    resolve_config_path,
    parse_date,
)


class TestLoadMainConfig:
    """测试全局配置加载"""

    def test_load_main_config_success(self):
        """成功加载 main.yaml"""
        config = load_main_config("backtest/config/main.yaml")

        # start 值由用户配置决定
        assert "start" in config
        # end 已改为可选，不在此断言
        assert config["data_dir"] == "./data/strategies"
        # output_dir 由用户配置决定，只验证存在
        assert "output_dir" in config
        # max_workers 由用户配置决定
        assert "max_workers" in config
        assert config["log_level"] == "INFO"

    def test_load_main_config_strategies(self):
        """加载策略列表 - 新格式不再包含 strategies 字段"""
        config = load_main_config("backtest/config/main.yaml")

        # 新格式：策略列表在 strategies.yaml，main.yaml 只包含回测参数
        assert "start" in config
        assert "data_dir" in config
        assert "output_dir" in config

    def test_load_main_config_file_not_found(self):
        """配置文件不存在时抛出异常"""
        with pytest.raises(FileNotFoundError):
            load_main_config("backtest/config/not_exist.yaml")


class TestLoadBatchConfig:
    """测试批量配置加载"""

    def test_load_batch_config_success(self):
        """成功加载批量配置"""
        config = load_batch_config("backtest/config/cta_rbreaker_v3/BTCUSDT.yaml")

        # load_batch_config 返回策略配置内容（去除顶层策略名）
        assert "enabled" in config
        assert config["enabled"] is True

    def test_load_batch_config_file_not_found(self):
        """配置文件不存在时抛出异常"""
        with pytest.raises(FileNotFoundError):
            load_batch_config("backtest/config/cta_rbreaker_v3/NOTEXIST.yaml")


class TestBuildConfigPath:
    """测试配置路径组合"""

    def test_build_config_path_basic(self):
        """基本路径组合"""
        path = build_config_path("backtest/config", "cta_rbreaker_v3", "BTCUSDT")
        assert path == "backtest/config/cta_rbreaker_v3/BTCUSDT.yaml"

    def test_build_config_path_with_dot_slash(self):
        """带 ./ 前缀的路径"""
        path = build_config_path("./backtest/config", "cta_ict_v3", "ETHUSDT")
        assert path == "./backtest/config/cta_ict_v3/ETHUSDT.yaml"

    def test_build_config_path_absolute(self):
        """绝对路径"""
        path = build_config_path("/tmp/test_config", "cta_rbreaker_v3", "BTCUSDT")
        assert path == "/tmp/test_config/cta_rbreaker_v3/BTCUSDT.yaml"


class TestResolveConfigPath:
    """测试路径解析"""

    def test_resolve_existing_path(self):
        """解析已存在的路径"""
        path = resolve_config_path("backtest/config/cta_rbreaker_v3/BTCUSDT.yaml")
        # 应该返回绝对路径或原始路径
        assert "cta_rbreaker_v3/BTCUSDT.yaml" in path

    def test_resolve_non_existing_path(self):
        """解析不存在的路径，返回原始路径"""
        path = resolve_config_path("backtest/config/not_exist.yaml")
        assert path == "backtest/config/not_exist.yaml"


class TestParseDate:
    """测试日期解析"""

    def test_parse_date_yyyymmdd(self):
        """YYYYMMDD 格式"""
        date_str, dt = parse_date("20250101")
        assert date_str == "20250101"
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 1

    def test_parse_date_yyyy_mm_dd(self):
        """YYYY-MM-DD 格式"""
        date_str, dt = parse_date("2025-01-01")
        assert date_str == "20250101"
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 1

    def test_parse_date_timestamp_seconds(self):
        """秒时间戳格式"""
        date_str, dt = parse_date("1735689600")  # 2025-01-01 00:00:00 UTC
        assert dt.year == 2025
        assert dt.month == 1

    def test_parse_date_timestamp_milliseconds(self):
        """毫秒时间戳格式"""
        date_str, dt = parse_date("1735689600000")  # 2025-01-01 00:00:00 UTC
        assert dt.year == 2025
        assert dt.month == 1
