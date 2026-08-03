# NOTE: IP addresses in this test are mock values, not real endpoints
"""
OpenViking 客户端测试

测试 ov CLI 封装功能：
- check_health: 检查服务状态
- add_resource: 添加资源
- add_directory: 添加目录
- list_resources: 列出资源
- exists: 检查资源是否存在
- ensure_account: 确保账户存在
- _create_account: 创建账户
- _get_account_user_api_key: 获取账户 API Key
"""

import subprocess
import pytest
from unittest.mock import Mock, patch
from datetime import datetime

from strategy_core.openviking_sync.ov_client import (
    OpenVikingClient,
    OpenVikingConfig,
    OpenVikingError,
)


class TestOpenVikingConfig:
    """配置类测试"""

    def test_default_config(self):
        """默认配置值"""
        config = OpenVikingConfig()
        assert config.server_url == "http://localhost:1933"
        assert config.cli_path == "ov"
        assert config.timeout == 60.0
        assert config.enabled is True
        assert config.account == ""
        assert config.root_api_key == ""
        assert config.auto_create_account is True

    def test_custom_config(self):
        """自定义配置"""
        config = OpenVikingConfig(
            server_url="http://127.0.0.1:1933",
            cli_path="/usr/local/bin/ov",
            timeout=120.0,
            enabled=False,
            account="trading",
            root_api_key="test-root-key",
            auto_create_account=False,
        )
        assert config.server_url == "http://127.0.0.1:1933"
        assert config.cli_path == "/usr/local/bin/ov"
        assert config.timeout == 120.0
        assert config.enabled is False
        assert config.account == "trading"
        assert config.root_api_key == "test-root-key"
        assert config.auto_create_account is False

    def test_account_config(self):
        """账户配置"""
        config = OpenVikingConfig(
            account="trading",
            root_api_key="root-key-123",
        )
        assert config.account == "trading"
        assert config.root_api_key == "root-key-123"


class TestOpenVikingClientInit:
    """客户端初始化测试"""

    def test_init_with_config(self):
        """使用配置对象初始化"""
        config = OpenVikingConfig(server_url="http://test:1933")
        client = OpenVikingClient(config)
        assert client.config.server_url == "http://test:1933"
        assert client._account_ready is False
        assert client._account_api_key is None

    def test_init_disabled(self):
        """禁用状态初始化"""
        config = OpenVikingConfig(enabled=False)
        client = OpenVikingClient(config)
        assert not client.is_enabled()


class TestEnsureAccount:
    """账户确保测试"""

    def test_ensure_account_no_account_configured(self):
        """未配置账户时抛出异常"""
        config = OpenVikingConfig(account="")
        client = OpenVikingClient(config)
        with pytest.raises(OpenVikingError) as exc_info:
            client.ensure_account()
        assert "No account configuration found" in str(exc_info.value)

    def test_ensure_account_disabled(self):
        """禁用状态返回 False"""
        config = OpenVikingConfig(enabled=False, account="trading")
        client = OpenVikingClient(config)
        result = client.ensure_account()
        assert result is False

    @patch.object(OpenVikingClient, '_check_account_exists')
    @patch.object(OpenVikingClient, '_get_account_user_api_key')
    def test_ensure_account_exists(self, mock_get_key, mock_check):
        """账户已存在"""
        mock_check.return_value = True
        mock_get_key.return_value = "trading-api-key"

        config = OpenVikingConfig(account="trading", root_api_key="root-key")
        client = OpenVikingClient(config)
        result = client.ensure_account()

        assert result is True
        assert client._account_api_key == "trading-api-key"
        assert client._account_ready is True

    @patch.object(OpenVikingClient, '_check_account_exists')
    @patch.object(OpenVikingClient, '_get_account_user_api_key')
    def test_ensure_account_exists_but_no_key(self, mock_get_key, mock_check):
        """账户存在但获取 API Key 失败"""
        mock_check.return_value = True
        mock_get_key.return_value = None

        config = OpenVikingConfig(account="trading", root_api_key="root-key")
        client = OpenVikingClient(config)
        with pytest.raises(OpenVikingError) as exc_info:
            client.ensure_account()
        assert "Failed to get API key" in str(exc_info.value)

    @patch.object(OpenVikingClient, '_check_account_exists')
    @patch.object(OpenVikingClient, '_create_account')
    def test_ensure_account_create_success(self, mock_create, mock_check):
        """账户不存在但创建成功"""
        mock_check.return_value = False
        mock_create.return_value = "new-api-key"

        config = OpenVikingConfig(
            account="trading",
            root_api_key="root-key",
            auto_create_account=True,
        )
        client = OpenVikingClient(config)
        result = client.ensure_account()

        assert result is True
        assert client._account_api_key == "new-api-key"
        mock_create.assert_called_once()

    @patch.object(OpenVikingClient, '_check_account_exists')
    def test_ensure_account_no_root_key(self, mock_check):
        """没有 root_api_key 无法创建"""
        mock_check.return_value = False

        config = OpenVikingConfig(
            account="trading",
            root_api_key="",  # 没有 root key
            auto_create_account=True,
        )
        client = OpenVikingClient(config)
        with pytest.raises(OpenVikingError) as exc_info:
            client.ensure_account()
        assert "no root_api_key provided" in str(exc_info.value)

    @patch.object(OpenVikingClient, '_check_account_exists')
    @patch.object(OpenVikingClient, '_create_account')
    def test_ensure_account_create_failed(self, mock_create, mock_check):
        """账户创建失败"""
        mock_check.return_value = False
        mock_create.return_value = None

        config = OpenVikingConfig(
            account="trading",
            root_api_key="root-key",
            auto_create_account=True,
        )
        client = OpenVikingClient(config)
        with pytest.raises(OpenVikingError) as exc_info:
            client.ensure_account()
        assert "Failed to create account" in str(exc_info.value)

    @patch.object(OpenVikingClient, '_check_account_exists')
    def test_ensure_account_auto_create_disabled(self, mock_check):
        """禁用自动创建"""
        mock_check.return_value = False

        config = OpenVikingConfig(
            account="trading",
            root_api_key="root-key",
            auto_create_account=False,
        )
        client = OpenVikingClient(config)
        with pytest.raises(OpenVikingError) as exc_info:
            client.ensure_account()
        assert "auto_create is disabled" in str(exc_info.value)


class TestCheckAccountExists:
    """检查账户存在测试"""

    @patch.object(OpenVikingClient, '_run_admin_cmd')
    def test_account_exists_dict_format(self, mock_run):
        """账户存在（字典格式）"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"result": [{"account_id": "trading", "user_count": 1}]}',
        )

        config = OpenVikingConfig(account="trading", root_api_key="root-key")
        client = OpenVikingClient(config)
        result = client._check_account_exists()

        assert result is True

    @patch.object(OpenVikingClient, '_run_admin_cmd')
    def test_account_exists_string_format(self, mock_run):
        """账户存在（字符串格式）"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"result": ["default", "trading", "openclaw"]}',
        )

        config = OpenVikingConfig(account="trading", root_api_key="root-key")
        client = OpenVikingClient(config)
        result = client._check_account_exists()

        assert result is True

    @patch.object(OpenVikingClient, '_run_admin_cmd')
    def test_account_not_exists(self, mock_run):
        """账户不存在"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"result": [{"account_id": "default"}, {"account_id": "openclaw"}]}',
        )

        config = OpenVikingConfig(account="trading", root_api_key="root-key")
        client = OpenVikingClient(config)
        result = client._check_account_exists()

        assert result is False

    @patch.object(OpenVikingClient, '_run_admin_cmd')
    def test_check_account_error(self, mock_run):
        """检查失败"""
        mock_run.return_value = Mock(returncode=1, stderr="Error")

        config = OpenVikingConfig(account="trading", root_api_key="root-key")
        client = OpenVikingClient(config)
        result = client._check_account_exists()

        assert result is False

    def test_check_account_no_root_key(self):
        """没有 root_api_key"""
        config = OpenVikingConfig(account="trading", root_api_key="")
        client = OpenVikingClient(config)
        result = client._check_account_exists()

        assert result is False


class TestCreateAccount:
    """创建账户测试"""

    @patch.object(OpenVikingClient, '_run_admin_cmd')
    def test_create_account_success(self, mock_run):
        """创建成功，返回 API Key"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"account_id": "trading", "user_key": "dHJhZGluZw.dHJhZGluZ19hZG1pbg.xxx"}',
        )

        config = OpenVikingConfig(account="trading", root_api_key="root-key")
        client = OpenVikingClient(config)
        result = client._create_account()

        assert result == "dHJhZGluZw.dHJhZGluZ19hZG1pbg.xxx"
        mock_run.assert_called_once()

    @patch.object(OpenVikingClient, '_run_admin_cmd')
    @patch.object(OpenVikingClient, '_get_account_user_api_key')
    def test_create_account_no_key_in_response(self, mock_get_key, mock_run):
        """创建成功但响应中没有 key"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"account_id": "trading"}',
        )
        mock_get_key.return_value = "fallback-key"

        config = OpenVikingConfig(account="trading", root_api_key="root-key")
        client = OpenVikingClient(config)
        result = client._create_account()

        assert result == "fallback-key"
        mock_get_key.assert_called_once()

    @patch.object(OpenVikingClient, '_run_admin_cmd')
    @patch.object(OpenVikingClient, '_get_account_user_api_key')
    def test_create_account_already_exists(self, mock_get_key, mock_run):
        """账户已存在"""
        mock_run.return_value = Mock(
            returncode=1,
            stderr="Account already exists",
        )
        mock_get_key.return_value = "existing-key"

        config = OpenVikingConfig(account="trading", root_api_key="root-key")
        client = OpenVikingClient(config)
        result = client._create_account()

        assert result == "existing-key"
        mock_get_key.assert_called_once()

    @patch.object(OpenVikingClient, '_run_admin_cmd')
    def test_create_account_failed(self, mock_run):
        """创建失败"""
        mock_run.return_value = Mock(
            returncode=1,
            stderr="Permission denied",
        )

        config = OpenVikingConfig(account="trading", root_api_key="root-key")
        client = OpenVikingClient(config)
        result = client._create_account()

        assert result is None

    def test_create_account_no_root_key(self):
        """没有 root_api_key"""
        config = OpenVikingConfig(account="trading", root_api_key="")
        client = OpenVikingClient(config)
        result = client._create_account()

        assert result is None


class TestGetAccountUserApiKey:
    """获取账户用户 API Key 测试"""

    @patch.object(OpenVikingClient, '_run_admin_cmd')
    def test_get_key_success(self, mock_run):
        """成功获取 API Key"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"result": [{"user_id": "trading_admin", "api_key": "dHJhZGluZw.xxx"}]}',
        )

        config = OpenVikingConfig(account="trading", root_api_key="root-key")
        client = OpenVikingClient(config)
        result = client._get_account_user_api_key()

        assert result == "dHJhZGluZw.xxx"

    @patch.object(OpenVikingClient, '_run_admin_cmd')
    def test_get_key_no_users(self, mock_run):
        """没有用户"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"result": []}',
        )

        config = OpenVikingConfig(account="trading", root_api_key="root-key")
        client = OpenVikingClient(config)
        result = client._get_account_user_api_key()

        assert result is None

    @patch.object(OpenVikingClient, '_run_admin_cmd')
    def test_get_key_error(self, mock_run):
        """获取失败"""
        mock_run.return_value = Mock(returncode=1, stderr="Error")

        config = OpenVikingConfig(account="trading", root_api_key="root-key")
        client = OpenVikingClient(config)
        result = client._get_account_user_api_key()

        assert result is None

    def test_get_key_no_account(self):
        """没有配置账户"""
        config = OpenVikingConfig(account="", root_api_key="root-key")
        client = OpenVikingClient(config)
        result = client._get_account_user_api_key()

        assert result is None

    def test_get_key_no_root_key(self):
        """没有 root_api_key"""
        config = OpenVikingConfig(account="trading", root_api_key="")
        client = OpenVikingClient(config)
        result = client._get_account_user_api_key()

        assert result is None


class TestRunAdminCmd:
    """执行 admin 命令测试"""

    @patch("subprocess.run")
    @patch("tempfile.mkstemp")
    @patch("os.chmod")
    @patch("os.write")
    @patch("os.close")
    def test_run_admin_cmd_creates_temp_config(self, mock_close, mock_write, mock_chmod, mock_mkstemp, mock_run):
        """创建临时配置文件"""
        mock_mkstemp.return_value = (123, "/tmp/ov_admin_xxx.conf")
        mock_run.return_value = Mock(returncode=0, stdout='{"result": []}')

        config = OpenVikingConfig(
            server_url="http://127.0.0.1:1933",
            root_api_key="root-key",
        )
        client = OpenVikingClient(config)
        client._run_admin_cmd(["ov", "admin", "list-accounts", "-o", "json"])

        # 验证创建了临时配置文件
        mock_mkstemp.assert_called_once()
        mock_chmod.assert_called_once()
        mock_write.assert_called_once()
        mock_close.assert_called_once()

        # 验证命令包含 --sudo
        call_args = mock_run.call_args[0][0]
        assert "--sudo" in call_args


class TestCheckHealth:
    """健康检查测试"""

    @patch("subprocess.run")
    def test_check_health_success(self, mock_run):
        """服务正常"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"status": "healthy", "version": "0.3.20"}',
        )
        client = OpenVikingClient(OpenVikingConfig())
        assert client.check_health() is True
        mock_run.assert_called_once()

    @patch("subprocess.run")
    def test_check_health_failure(self, mock_run):
        """服务异常"""
        mock_run.return_value = Mock(returncode=1, stderr="Connection refused")
        client = OpenVikingClient(OpenVikingConfig())
        assert client.check_health() is False

    @patch("subprocess.run")
    def test_check_health_timeout(self, mock_run):
        """检查超时"""
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ov", timeout=5)
        client = OpenVikingClient(OpenVikingConfig())
        assert client.check_health() is False

    def test_check_health_disabled(self):
        """禁用状态直接返回 False"""
        client = OpenVikingClient(OpenVikingConfig(enabled=False))
        assert client.check_health() is False


class TestAddResource:
    """添加资源测试"""

    @patch("subprocess.run")
    def test_add_resource_success(self, mock_run):
        """成功添加文件"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"root_uri": "viking://resources/test.md", "status": "processing"}',
        )
        config = OpenVikingConfig(api_key="test-api-key")
        client = OpenVikingClient(config)

        result = client.add_resource(
            file_path="/tmp/test.md",
            target_uri="viking://resources/test.md",
            reason="Test upload",
            wait=True,
        )

        assert result["status"] == "processing"
        assert "root_uri" in result

    @patch("subprocess.run")
    def test_add_resource_with_wait(self, mock_run):
        """等待处理完成"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"root_uri": "viking://resources/test.md", "status": "completed"}',
        )
        config = OpenVikingConfig(api_key="test-api-key")
        client = OpenVikingClient(config)

        client.add_resource(
            file_path="/tmp/test.md",
            target_uri="viking://resources/test.md",
            wait=True,
            timeout=300,
        )

        # 验证调用参数包含 --wait
        call_args = mock_run.call_args[0][0]
        assert "--wait" in call_args
        assert "--timeout" in call_args or "300" in str(call_args)

    @patch("subprocess.run")
    def test_add_resource_failure(self, mock_run):
        """添加失败"""
        mock_run.return_value = Mock(
            returncode=1,
            stderr="Error: Resource already exists",
        )
        client = OpenVikingClient(OpenVikingConfig())

        with pytest.raises(OpenVikingError):
            client.add_resource(
                file_path="/tmp/test.md",
                target_uri="viking://resources/test.md",
            )

    @patch("subprocess.run")
    def test_add_resource_file_not_found(self, mock_run):
        """文件不存在"""
        mock_run.return_value = Mock(
            returncode=1,
            stderr="Error: File not found: /tmp/notexist.md",
        )
        client = OpenVikingClient(OpenVikingConfig())

        with pytest.raises(OpenVikingError):
            client.add_resource(
                file_path="/tmp/notexist.md",
                target_uri="viking://resources/test.md",
            )

    def test_add_resource_disabled(self):
        """禁用状态不执行"""
        client = OpenVikingClient(OpenVikingConfig(enabled=False))

        with pytest.raises(OpenVikingError, match="disabled"):
            client.add_resource(
                file_path="/tmp/test.md",
                target_uri="viking://resources/test.md",
            )


class TestAddDirectory:
    """添加目录测试"""

    @patch("subprocess.run")
    def test_add_directory_success(self, mock_run):
        """成功添加目录"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='{"root_uri": "viking://resources/test/", "status": "processing"}',
        )
        config = OpenVikingConfig(api_key="test-api-key")
        client = OpenVikingClient(config)

        result = client.add_directory(
            dir_path="/tmp/testdir",
            target_uri="viking://resources/test/",
            wait=True,
        )

        assert result["status"] == "processing"

    @patch("subprocess.run")
    def test_add_directory_with_filters(self, mock_run):
        """添加目录时过滤文件"""
        mock_run.return_value = Mock(returncode=0, stdout='{}')
        config = OpenVikingConfig(api_key="test-api-key")
        client = OpenVikingClient(config)

        client.add_directory(
            dir_path="/tmp/testdir",
            target_uri="viking://resources/test/",
            ignore_dirs=["node_modules", ".git"],
            exclude=["*.log", "*.tmp"],
        )

        call_args = mock_run.call_args[0][0]
        assert "--ignore-dirs" in call_args
        assert "--exclude" in call_args


class TestListResources:
    """列出资源测试"""

    @patch("subprocess.run")
    def test_list_resources_success(self, mock_run):
        """成功列出资源"""
        mock_run.return_value = Mock(
            returncode=0,
            stdout='["viking://resources/test1.md", "viking://resources/test2.md"]',
        )
        client = OpenVikingClient(OpenVikingConfig())

        result = client.list_resources("viking://resources/")

        assert len(result) == 2
        assert result[0] == "viking://resources/test1.md"

    @patch("subprocess.run")
    def test_list_resources_empty(self, mock_run):
        """空目录"""
        mock_run.return_value = Mock(returncode=0, stdout='[]')
        client = OpenVikingClient(OpenVikingConfig())

        result = client.list_resources("viking://resources/empty/")

        assert result == []


class TestExists:
    """检查资源存在测试"""

    @patch("subprocess.run")
    def test_exists_true(self, mock_run):
        """资源存在"""
        mock_run.return_value = Mock(returncode=0, stdout='{"exists": true}')
        client = OpenVikingClient(OpenVikingConfig())

        assert client.exists("viking://resources/test.md") is True

    @patch("subprocess.run")
    def test_exists_false(self, mock_run):
        """资源不存在"""
        mock_run.return_value = Mock(returncode=1, stderr="Not found")
        client = OpenVikingClient(OpenVikingConfig())

        assert client.exists("viking://resources/notexist.md") is False


class TestGenerateUri:
    """URI 生成测试（静态方法）"""

    def test_generate_signal_uri(self):
        """生成信号 URI"""
        date = datetime(2026, 5, 29)
        uri = OpenVikingClient.generate_signal_uri("RBREAKER", date)

        assert uri == "viking://resources/trading_data/2026/05/29/cta-signals/RBREAKER/20260529.md"

    def test_generate_backtest_uri(self):
        """生成回测 URI"""
        date = datetime(2026, 5, 29)
        uri = OpenVikingClient.generate_backtest_uri("RBREAKER", date)

        assert uri == "viking://resources/trading_data/2026/05/29/backtest/RBREAKER"

    def test_generate_daily_uri(self):
        """生成当日根 URI"""
        date = datetime(2026, 5, 29)
        uri = OpenVikingClient.generate_daily_uri(date)

        assert uri == "viking://resources/trading_data/2026/05/29/"

    def test_generate_uri_with_padding(self):
        """月份和日期补零"""
        date = datetime(2026, 1, 5)
        uri = OpenVikingClient.generate_signal_uri("ICT_4H", date)

        assert uri == "viking://resources/trading_data/2026/01/05/cta-signals/ICT_4H/20260105.md"

    def test_generate_signal_uri_with_account(self):
        """生成信号 URI（带账户）"""
        date = datetime(2026, 5, 29)
        uri = OpenVikingClient.generate_signal_uri("RBREAKER", date, account="trading")

        assert uri == "viking://resources/trading/trading_data/2026/05/29/cta-signals/RBREAKER/20260529.md"

    def test_generate_backtest_uri_with_account(self):
        """生成回测 URI（带账户）"""
        date = datetime(2026, 5, 29)
        uri = OpenVikingClient.generate_backtest_uri("RBREAKER", date, account="trading")

        assert uri == "viking://resources/trading/trading_data/2026/05/29/backtest/RBREAKER"

    def test_generate_daily_uri_with_account(self):
        """生成当日根 URI（带账户）"""
        date = datetime(2026, 5, 29)
        uri = OpenVikingClient.generate_daily_uri(date, account="trading")

        assert uri == "viking://resources/trading/trading_data/2026/05/29/"

    def test_generate_uri_empty_account(self):
        """空账户名不添加账户路径"""
        date = datetime(2026, 5, 29)
        uri = OpenVikingClient.generate_signal_uri("RBREAKER", date, account="")

        assert uri == "viking://resources/trading_data/2026/05/29/cta-signals/RBREAKER/20260529.md"
