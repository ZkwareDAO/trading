# NOTE: IP addresses in this test are mock values, not real endpoints
"""
K 线服务 URL 可配置化测试

测试:
- 默认 URL 值
- 自定义 URL 配置
- 环境变量覆盖
"""

import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from data_manager.manager import DataManager, DataManagerConfig


class TestKlinesServiceUrlConfig:
    """K 线服务 URL 配置测试"""

    def test_default_urls(self):
        """测试默认 URL 配置"""
        config = DataManagerConfig()

        assert config.klines_service_ws_url == "ws://127.0.0.1:17081/ws/klines"
        assert config.klines_service_http_url == "http://127.0.0.1:17081"

    def test_custom_urls(self):
        """测试自定义 URL 配置"""
        config = DataManagerConfig(
            klines_service_ws_url="ws://127.0.0.1:8080/ws/klines",
            klines_service_http_url="http://127.0.0.1:8080",
        )

        assert config.klines_service_ws_url == "ws://127.0.0.1:8080/ws/klines"
        assert config.klines_service_http_url == "http://127.0.0.1:8080"

    def test_manager_uses_config_urls(self):
        """测试 DataManager 使用配置中的 URL"""
        config = DataManagerConfig(
            klines_service_ws_url="ws://custom.host:9090/ws",
            klines_service_http_url="http://custom.host:9090",
        )
        dm = DataManager(config)

        assert dm.config.klines_service_ws_url == "ws://custom.host:9090/ws"
        assert dm.config.klines_service_http_url == "http://custom.host:9090"

    def test_env_var_override_ws_url(self):
        """测试环境变量覆盖 WS URL"""
        with patch.dict(os.environ, {
            "KLINES_WS_URL": "ws://env.override:17082/ws/klines"
        }):
            config = DataManagerConfig.from_env()
            assert config.klines_service_ws_url == "ws://env.override:17082/ws/klines"

    def test_env_var_override_http_url(self):
        """测试环境变量覆盖 HTTP URL"""
        with patch.dict(os.environ, {
            "KLINES_HTTP_URL": "http://env.override:17082"
        }):
            config = DataManagerConfig.from_env()
            assert config.klines_service_http_url == "http://env.override:17082"

    def test_env_var_override_both_urls(self):
        """测试环境变量覆盖两个 URL"""
        with patch.dict(os.environ, {
            "KLINES_WS_URL": "ws://prod.server:443/ws/klines",
            "KLINES_HTTP_URL": "http://prod.server:443"
        }):
            config = DataManagerConfig.from_env()
            assert config.klines_service_ws_url == "ws://prod.server:443/ws/klines"
            assert config.klines_service_http_url == "http://prod.server:443"

    def test_env_var_partial_override(self):
        """测试环境变量部分覆盖（只覆盖一个）"""
        with patch.dict(os.environ, {
            "KLINES_HTTP_URL": "http://new.server:17081"
        }, clear=False):
            # 清除可能存在的 KLINES_WS_URL
            os.environ.pop("KLINES_WS_URL", None)
            config = DataManagerConfig.from_env()
            assert config.klines_service_http_url == "http://new.server:17081"
            # WS URL 使用默认值
            assert config.klines_service_ws_url == "ws://127.0.0.1:17081/ws/klines"
