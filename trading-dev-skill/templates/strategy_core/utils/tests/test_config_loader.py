#!/usr/bin/env python3
"""
测试多环境配置加载器

验证:
1. 指定 env 参数时加载对应配置
2. 环境配置不存在时回退到默认配置
3. 未设置 CTA_ENV 且无 env 参数时使用默认 config.yaml
"""

import os
import tempfile
import yaml
from pathlib import Path
from unittest.mock import patch

import pytest


class TestConfigLoaderWithEnv:
    """测试 load_config_with_env 函数"""

    def test_load_dev_config_when_env_is_dev(self, tmp_path):
        """CTA_ENV=dev 时加载 config.dev.yaml"""
        # 创建测试配置文件
        strategy_dir = tmp_path / "test_strategy"
        strategy_dir.mkdir()

        dev_config = {"test_strategy": {"enabled": True, "symbols": ["BTCUSDT"]}}
        with open(strategy_dir / "config.dev.yaml", "w") as f:
            yaml.dump(dev_config, f)

        # 设置环境变量
        with patch.dict(os.environ, {"CTA_ENV": "dev"}):
            from strategy_core.utils.config_loader import load_config_with_env
            config = load_config_with_env("test_strategy", config_dir=strategy_dir)

        assert config["enabled"] == True
        assert config["symbols"] == ["BTCUSDT"]

    def test_load_prod_config_when_env_is_prod(self, tmp_path):
        """CTA_ENV=prod 时加载 config.prod.yaml"""
        strategy_dir = tmp_path / "test_strategy"
        strategy_dir.mkdir()

        prod_config = {"test_strategy": {"enabled": True, "symbols": ["ETHUSDT"], "user_id": 999}}
        with open(strategy_dir / "config.prod.yaml", "w") as f:
            yaml.dump(prod_config, f)

        with patch.dict(os.environ, {"CTA_ENV": "prod"}):
            from strategy_core.utils.config_loader import load_config_with_env
            config = load_config_with_env("test_strategy", config_dir=strategy_dir)

        assert config["symbols"] == ["ETHUSDT"]
        assert config["user_id"] == 999

    def test_fallback_to_default_config_when_env_config_missing(self, tmp_path):
        """环境配置不存在时回退到 config.yaml"""
        strategy_dir = tmp_path / "test_strategy"
        strategy_dir.mkdir()

        # 只创建默认配置
        default_config = {"test_strategy": {"enabled": False, "symbols": ["SOLUSDT"]}}
        with open(strategy_dir / "config.yaml", "w") as f:
            yaml.dump(default_config, f)

        with patch.dict(os.environ, {"CTA_ENV": "prod"}):
            from strategy_core.utils.config_loader import load_config_with_env
            config = load_config_with_env("test_strategy", config_dir=strategy_dir)

        # 应该加载默认配置
        assert config["enabled"] == False
        assert config["symbols"] == ["SOLUSDT"]

    def test_return_empty_dict_when_no_config_exists(self, tmp_path):
        """没有任何配置文件时返回空字典"""
        strategy_dir = tmp_path / "test_strategy"
        strategy_dir.mkdir()

        with patch.dict(os.environ, {"CTA_ENV": "dev"}):
            from strategy_core.utils.config_loader import load_config_with_env
            config = load_config_with_env("test_strategy", config_dir=strategy_dir)

        assert config == {}

    def test_default_env_uses_config_yaml(self, tmp_path):
        """未设置 CTA_ENV 时默认使用 config.yaml"""
        strategy_dir = tmp_path / "test_strategy"
        strategy_dir.mkdir()

        # 只创建默认配置
        default_config = {"test_strategy": {"default_config": True}}
        with open(strategy_dir / "config.yaml", "w") as f:
            yaml.dump(default_config, f)

        # 清除 CTA_ENV
        env_copy = os.environ.copy()
        if "CTA_ENV" in env_copy:
            del env_copy["CTA_ENV"]

        with patch.dict(os.environ, env_copy, clear=True):
            from strategy_core.utils.config_loader import load_config_with_env
            config = load_config_with_env("test_strategy", config_dir=strategy_dir)

        assert config["default_config"] == True

    def test_load_from_explicit_path(self, tmp_path):
        """指定路径时直接加载该文件（策略层逻辑）"""
        strategy_dir = tmp_path / "test_strategy"
        strategy_dir.mkdir()

        custom_config = {"test_strategy": {"custom": True}}
        custom_path = strategy_dir / "custom.yaml"
        with open(custom_path, "w") as f:
            yaml.dump(custom_config, f)

        # 直接测试配置加载器不处理指定路径
        # 指定路径是策略层 load_strategy_config 的职责
        # 这里验证 load_config_with_env 的行为
        with patch.dict(os.environ, {"CTA_ENV": "dev"}):
            from strategy_core.utils.config_loader import load_config_with_env
            config = load_config_with_env("test_strategy", config_dir=strategy_dir)

        # config_dir 下没有 config.dev.yaml 或 config.yaml，应返回空
        assert config == {}