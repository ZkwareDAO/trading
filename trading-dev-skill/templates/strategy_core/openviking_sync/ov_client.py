"""
OpenViking 客户端

封装 ov CLI 命令，提供 Python API 与 OpenViking 服务交互。

核心功能：
- check_health: 检查服务状态 (ov status)
- add_resource: 添加文件资源 (ov add-resource)
- add_directory: 添加目录 (ov add-resource <dir>)
- list_resources: 列出资源 (ov ls)
- exists: 检查资源是否存在
"""

import json
import logging
import os
import subprocess
import shutil
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


class OpenVikingError(Exception):
    """OpenViking 操作错误"""
    pass


class ResourceExistsError(OpenVikingError):
    """资源已存在错误"""
    pass


@dataclass
class OpenVikingConfig:
    """OpenViking 配置"""
    server_url: str = "http://localhost:1933"
    cli_path: str = "ov"
    timeout: float = 60.0
    enabled: bool = True
    # 账户配置
    account: str = ""  # 目标账户名，如 "trading"
    api_key: str = ""  # 账户 API Key（直接使用，不依赖 CLI 配置）
    root_api_key: str = ""  # root API key，用于自动创建账户
    auto_create_account: bool = True  # 账户不存在时自动创建


class OpenVikingClient:
    """OpenViking CLI 客户端"""

    def __init__(self, config: OpenVikingConfig):
        self.config = config
        self._cli_available = self._check_cli_available()
        self._account_ready = False
        self._account_api_key: Optional[str] = None  # 账户的 API Key

    def _check_cli_available(self) -> bool:
        """检查 ov CLI 是否可用"""
        if not self.config.enabled:
            return False
        return shutil.which(self.config.cli_path) is not None

    def is_enabled(self) -> bool:
        """检查是否启用"""
        return self.config.enabled and self._cli_available

    def ensure_account(self) -> bool:
        """
        确保账户配置正确

        Returns:
            账户是否可用
        """
        if not self.is_enabled():
            return False

        # 如果直接配置了 api_key，直接使用
        if self.config.api_key:
            self._account_api_key = self.config.api_key
            self._account_ready = True
            logger.info("Using configured API key (masked)")
            return True

        # 如果配置了账户名，通过 root_api_key 获取账户的 API Key
        if self.config.account:
            if not self.config.root_api_key:
                raise OpenVikingError(
                    f"Account '{self.config.account}' configured but no root_api_key provided. "
                    f"Please configure root_api_key in settings.yaml to get account API key, "
                    f"or directly configure api_key."
                )

            # 检查账户是否存在
            if self._check_account_exists():
                self._account_api_key = self._get_account_user_api_key()
                if self._account_api_key:
                    self._account_ready = True
                    logger.info(f"Using account '{self.config.account}' (API key masked)")
                    return True
                else:
                    raise OpenVikingError(f"Failed to get API key for account '{self.config.account}'")

            # 尝试创建账户
            if self.config.auto_create_account:
                api_key = self._create_account()
                if api_key:
                    self._account_api_key = api_key
                    self._account_ready = True
                    return True
                raise OpenVikingError(f"Failed to create account '{self.config.account}'")

            raise OpenVikingError(
                f"Account '{self.config.account}' not found and auto_create is disabled. "
                f"Please enable auto_create or configure api_key directly."
            )

        # 没有配置账户也没有配置 api_key，报错
        raise OpenVikingError(
            "No account configuration found. Please configure either:\n"
            "  1. account.name + account.root_api_key (auto get/create account API key)\n"
            "  2. account.api_key (directly use the API key)\n"
            "in config/settings.yaml under openviking.account section."
        )

    def _create_temp_config_with_key(self, api_key: str) -> Tuple[Dict[str, str], Path]:
        """
        创建带有指定 API Key 的临时配置文件

        Args:
            api_key: API Key

        Returns:
            (环境变量字典, 临时配置路径)
        """
        temp_config = {
            "url": self.config.server_url,
            "api_key": api_key,
        }
        fd, temp_path = tempfile.mkstemp(suffix=".conf", prefix="ov_")
        try:
            os.chmod(temp_path, 0o600)
            os.write(fd, json.dumps(temp_config).encode('utf-8'))
        finally:
            os.close(fd)

        env = dict(os.environ)
        env["OPENVIKING_CONFIG"] = temp_path
        return env, Path(temp_path)

    def _run_admin_cmd(
        self,
        cmd: List[str],
        timeout: float = 30,
    ) -> subprocess.CompletedProcess:
        """
        执行 admin 命令（使用 root_api_key）

        Args:
            cmd: 命令列表（不含 --sudo）
            timeout: 超时时间

        Returns:
            命令执行结果
        """
        if not self.config.root_api_key:
            return subprocess.CompletedProcess(cmd, 1, "", "No root_api_key configured")

        env, temp_path = self._create_temp_config_with_key(self.config.root_api_key)
        full_cmd = cmd + ["--sudo"]

        try:
            return subprocess.run(
                full_cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        finally:
            temp_path.unlink(missing_ok=True)

    def _check_account_exists(self) -> bool:
        """检查账户是否存在"""
        if not self.config.root_api_key:
            logger.debug("No root_api_key configured, cannot check account")
            return False

        try:
            result = self._run_admin_cmd(
                [self.config.cli_path, "admin", "list-accounts", "-o", "json"],
                timeout=10,
            )
            if result.returncode != 0:
                return False

            data = json.loads(result.stdout)
            accounts = data.get("result", [])
            if isinstance(accounts, list):
                for acc in accounts:
                    if isinstance(acc, dict) and acc.get("account_id") == self.config.account:
                        return True
                    elif acc == self.config.account:
                        return True
            return False
        except Exception as e:
            logger.debug(f"Failed to check account: {e}")
            return False

    def _create_account(self) -> Optional[str]:
        """
        创建账户

        Returns:
            账户的 API Key 或 None
        """
        if not self.config.root_api_key:
            logger.warning("No root_api_key configured, cannot create account")
            return None

        try:
            # 管理员用户名：{account}_admin
            admin_user = f"{self.config.account}_admin"

            result = self._run_admin_cmd(
                [
                    self.config.cli_path, "admin", "create-account",
                    self.config.account,
                    "--admin", admin_user,
                    "-o", "json"
                ],
                timeout=30,
            )
            if result.returncode == 0:
                logger.info(f"Created account: {self.config.account}")
                # 解析返回的 API key
                try:
                    data = json.loads(result.stdout)
                    api_key = data.get("user_key", "")
                    if api_key:
                        logger.info(f"Account created: {self.config.account}")
                        return api_key
                except json.JSONDecodeError:
                    pass
                # 如果创建成功但没有返回 key，尝试获取
                return self._get_account_user_api_key()
            else:
                # 账户可能已存在
                error = result.stderr or result.stdout
                if "already exists" in error.lower() or "已存在" in error:
                    logger.info(f"Account already exists: {self.config.account}")
                    return self._get_account_user_api_key()
                logger.warning(f"Failed to create account: {error}")
                return None
        except Exception as e:
            logger.error(f"Failed to create account: {e}")
            return None

    def _get_account_user_api_key(self) -> Optional[str]:
        """
        获取账户用户的 API Key

        Returns:
            API Key 或 None
        """
        if not self.config.account:
            return None

        if not self.config.root_api_key:
            logger.debug("No root_api_key configured, cannot get account user API key")
            return None

        try:
            # 获取账户用户列表
            result = self._run_admin_cmd(
                [
                    self.config.cli_path, "admin", "list-users",
                    self.config.account,
                    "-o", "json"
                ],
                timeout=10,
            )
            if result.returncode != 0:
                return None

            data = json.loads(result.stdout)
            users = data.get("result", [])
            if not users:
                return None

            # 返回第一个用户的 API Key
            first_user = users[0] if isinstance(users[0], dict) else {"name": users[0]}
            return first_user.get("api_key")

        except Exception as e:
            logger.debug(f"Failed to get account user API key: {e}")
            return None

    def check_health(self) -> bool:
        """
        检查 OpenViking 服务状态

        执行: ov status

        Returns:
            服务是否健康
        """
        if not self.config.enabled:
            return False

        try:
            env, temp_path = self._create_temp_config()
            try:
                result = subprocess.run(
                    [self.config.cli_path, "status"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    env=env,
                )
                return result.returncode == 0
            finally:
                self._cleanup_temp_config(temp_path)
        except subprocess.TimeoutExpired:
            logger.warning("OpenViking health check timeout")
            return False
        except Exception as e:
            logger.warning(f"OpenViking health check failed: {e}")
            return False

    def _create_temp_config(self) -> Tuple[Dict[str, str], Optional[Path]]:
        """
        创建临时配置文件（如果需要）

        Returns:
            (环境变量字典, 临时配置路径或None)
        """
        if not self._account_api_key:
            return dict(os.environ), None

        return self._create_temp_config_with_key(self._account_api_key)

    def _cleanup_temp_config(self, temp_path: Optional[Path]):
        """清理临时配置文件"""
        if temp_path:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass

    def _run_cmd(
        self,
        cmd: List[str],
        timeout: float = None,
    ) -> subprocess.CompletedProcess:
        """
        执行命令

        Args:
            cmd: 命令列表
            timeout: 超时时间

        Returns:
            命令执行结果
        """
        timeout = timeout or self.config.timeout
        env, temp_path = self._create_temp_config()

        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        finally:
            self._cleanup_temp_config(temp_path)

    def _ensure_enabled(self):
        """确保客户端已启用"""
        if not self.config.enabled:
            raise OpenVikingError("OpenViking sync is disabled")
        if not self._account_ready:
            self.ensure_account()

    def _parse_result(self, result: subprocess.CompletedProcess, target_uri: str) -> Dict[str, Any]:
        """
        解析命令结果

        Args:
            result: 命令执行结果
            target_uri: 目标 URI

        Returns:
            解析后的结果字典
        """
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {
                "root_uri": target_uri,
                "status": "success",
                "raw_output": result.stdout,
            }

    def _execute_add(
        self,
        path: str,
        target_uri: str,
        reason: str = "",
        wait: bool = True,
        timeout: float = 300,
        extra_args: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        执行添加操作（文件或目录）

        Args:
            path: 文件或目录路径
            target_uri: 目标 URI
            reason: 添加原因
            wait: 是否等待处理
            timeout: 超时时间
            extra_args: 额外参数

        Returns:
            添加结果

        Raises:
            OpenVikingError: 添加失败
        """
        self._ensure_enabled()

        cmd = [
            self.config.cli_path,
            "add-resource",
            path,
            "--to", target_uri,
        ]

        # 添加账户参数，确保资源存储到正确的账户
        if self.config.account:
            cmd.extend(["--account", self.config.account])

        if reason:
            cmd.extend(["--reason", reason])

        if wait:
            cmd.extend(["--wait", "--timeout", str(timeout)])

        if extra_args:
            cmd.extend(extra_args)

        try:
            result = self._run_cmd(cmd, timeout=timeout)

            if result.returncode != 0:
                error_msg = result.stderr or result.stdout
                logger.error(f"add_resource failed: {error_msg}")
                raise OpenVikingError(f"Failed to add resource: {error_msg}")

            return self._parse_result(result, target_uri)

        except subprocess.TimeoutExpired:
            logger.error(f"add_resource timeout: {path}")
            raise OpenVikingError(f"Timeout adding resource: {path}")

    def add_resource(
        self,
        file_path: str,
        target_uri: str,
        reason: str = "",
        wait: bool = False,
        timeout: float = 300,
    ) -> Dict[str, Any]:
        """
        添加文件资源到 OpenViking

        执行: ov add-resource <file> --to <uri> --reason <reason> [--wait --timeout <seconds>]

        Args:
            file_path: 本地文件路径
            target_uri: 目标 Viking URI
            reason: 添加原因 (用于语义解析)
            wait: 是否等待处理完成
            timeout: 等待超时时间 (秒)

        Returns:
            添加结果，包含 root_uri 和 status

        Raises:
            OpenVikingError: 添加失败
        """
        return self._execute_add(
            path=file_path,
            target_uri=target_uri,
            reason=reason,
            wait=wait,
            timeout=timeout if wait else self.config.timeout,
        )

    def add_directory(
        self,
        dir_path: str,
        target_uri: str,
        reason: str = "",
        wait: bool = True,
        timeout: float = 600,
        ignore_dirs: Optional[List[str]] = None,
        exclude: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        添加目录到 OpenViking

        执行: ov add-resource <dir> --to <uri> [--wait] [--ignore-dirs ...] [--exclude ...]

        Args:
            dir_path: 本地目录路径
            target_uri: 目标 Viking URI
            reason: 添加原因
            wait: 是否等待处理
            timeout: 超时时间
            ignore_dirs: 忽略的目录名列表
            exclude: 排除的文件模式列表

        Returns:
            添加结果
        """
        extra_args = []
        if ignore_dirs:
            extra_args.extend(["--ignore-dirs", ",".join(ignore_dirs)])
        if exclude:
            extra_args.extend(["--exclude", ",".join(exclude)])

        return self._execute_add(
            path=dir_path,
            target_uri=target_uri,
            reason=reason,
            wait=wait,
            timeout=timeout,
            extra_args=extra_args if extra_args else None,
        )

    def list_resources(self, uri: str) -> List[Dict]:
        """
        列出资源

        执行: ov ls <uri>

        Args:
            uri: Viking URI

        Returns:
            资源列表
        """
        if not self.config.enabled:
            return []

        try:
            result = self._run_cmd([self.config.cli_path, "ls", uri])

            if result.returncode != 0:
                return []

            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                # 解析文本输出
                lines = result.stdout.strip().split("\n")
                return [{"uri": line.strip()} for line in lines if line.strip()]

        except Exception as e:
            logger.warning(f"list_resources failed: {e}")
            return []

    def exists(self, uri: str) -> bool:
        """
        检查资源是否存在

        Args:
            uri: Viking URI

        Returns:
            资源是否存在
        """
        if not self.config.enabled:
            return False

        try:
            result = self._run_cmd([self.config.cli_path, "ls", uri], timeout=10)
            return result.returncode == 0
        except Exception:
            return False

    # ========== 静态方法: URI 生成 ==========

    @staticmethod
    def _build_base_uri(account: str = "") -> str:
        """构建基础 URI 前缀"""
        base = "viking://resources/"
        if account:
            base += f"{account}/"
        return base

    @staticmethod
    def _build_date_path(date: datetime) -> str:
        """构建日期路径"""
        return f"{date.year}/{date.month:02d}/{date.day:02d}/"

    @staticmethod
    def generate_signal_uri(strategy: str, date: datetime, account: str = "") -> str:
        """
        生成信号目标 URI

        格式: viking://resources/{account}/trading_data/{year}/{month}/{day}/cta-signals/{strategy}/{date}.md

        Args:
            strategy: 策略名称
            date: 日期
            account: 账户名 (可选)

        Returns:
            目标 URI
        """
        base = OpenVikingClient._build_base_uri(account)
        date_path = OpenVikingClient._build_date_path(date)
        return f"{base}trading_data/{date_path}cta-signals/{strategy}/{date.strftime('%Y%m%d')}.md"

    @staticmethod
    def generate_backtest_uri(strategy: str, date: datetime, account: str = "") -> str:
        """
        生成回测目标 URI

        格式: viking://resources/{account}/trading_data/{year}/{month}/{day}/backtest/{strategy}

        Args:
            strategy: 策略名称
            date: 日期
            account: 账户名 (可选)

        Returns:
            目标 URI
        """
        base = OpenVikingClient._build_base_uri(account)
        date_path = OpenVikingClient._build_date_path(date)
        return f"{base}trading_data/{date_path}backtest/{strategy}"

    @staticmethod
    def generate_daily_uri(date: datetime, account: str = "") -> str:
        """
        生成当日根目录 URI

        格式: viking://resources/{account}/trading_data/{year}/{month}/{day}/

        Args:
            date: 日期
            account: 账户名 (可选)

        Returns:
            根 URI
        """
        base = OpenVikingClient._build_base_uri(account)
        date_path = OpenVikingClient._build_date_path(date)
        return f"{base}trading_data/{date_path}"
