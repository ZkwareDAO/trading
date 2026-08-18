#!/usr/bin/env python3
"""
测试策略子进程启动时环境变量传递

验证:
1. 子进程继承父进程的环境变量
2. PYTHONPATH 正确设置
3. LOG_LEVEL 正确传递
"""

import asyncio
import os
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


def _make_strategy_config():
    """创建测试用的策略配置"""
    return {
        "strategy_id": "ICT_4H_2_BTCUSDT_LIVE",
        "name": "cta_ict_v3",
        "symbol": "BTCUSDT",
        "interval": "4h",
        "version": "2",
        "trading_mode": "live",
        "strategy_name": "ICT_4H_2_BTCUSDT_LIVE",
    }


class TestSubprocessEnvironment:
    """测试子进程环境变量传递"""

    def test_subprocess_inherits_parent_env(self):
        """子进程应继承父进程的环境变量"""
        from run_strategies_manager import start_strategy_process

        strategy_config = _make_strategy_config()
        test_env = {
            "PYTHONPATH": "/test/path",
            "VIRTUAL_ENV": "/test/.venv",
            "PATH": "/test/bin:/usr/bin",
        }

        with patch.dict(os.environ, test_env, clear=True):
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                async def mock_readline():
                    return b""

                mock_stdout = MagicMock()
                mock_stdout.readline = mock_readline
                mock_stderr = MagicMock()
                mock_stderr.readline = mock_readline

                mock_exec.return_value = MagicMock(
                    pid=12345,
                    stdout=mock_stdout,
                    stderr=mock_stderr,
                )

                async def run_test():
                    proc = await start_strategy_process(strategy_config, "config/settings.yaml", log_level="DEBUG")
                    return proc

                proc = asyncio.run(run_test())

                call_args = mock_exec.call_args
                assert "env" in call_args.kwargs, "应传递 env 参数"

                passed_env = call_args.kwargs["env"]
                assert passed_env.get("LOG_LEVEL") == "DEBUG"
                assert passed_env.get("VIRTUAL_ENV") == "/test/.venv"

    def test_subprocess_pythonpath_includes_project_root(self):
        """子进程 PYTHONPATH 应包含项目根目录"""
        from run_strategies_manager import start_strategy_process

        strategy_config = _make_strategy_config()
        project_root = str(Path(__file__).parent.parent)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            async def mock_readline():
                return b""

            mock_stdout = MagicMock()
            mock_stdout.readline = mock_readline
            mock_stderr = MagicMock()
            mock_stderr.readline = mock_readline

            mock_exec.return_value = MagicMock(
                pid=12345,
                stdout=mock_stdout,
                stderr=mock_stderr,
            )

            async def run_test():
                proc = await start_strategy_process(strategy_config, "config/settings.yaml")
                return proc

            proc = asyncio.run(run_test())

            call_args = mock_exec.call_args
            passed_env = call_args.kwargs.get("env", {})

            pythonpath = passed_env.get("PYTHONPATH", "")
            assert project_root in pythonpath or pythonpath == project_root

    def test_subprocess_inherits_virtual_env(self):
        """子进程应继承 VIRTUAL_ENV 环境变量"""
        from run_strategies_manager import start_strategy_process

        strategy_config = _make_strategy_config()

        with patch.dict(os.environ, {"VIRTUAL_ENV": "/home/test/.venv"}):
            with patch("asyncio.create_subprocess_exec") as mock_exec:
                async def mock_readline():
                    return b""

                mock_stdout = MagicMock()
                mock_stdout.readline = mock_readline
                mock_stderr = MagicMock()
                mock_stderr.readline = mock_readline

                mock_exec.return_value = MagicMock(
                    pid=12345,
                    stdout=mock_stdout,
                    stderr=mock_stderr,
                )

                async def run_test():
                    proc = await start_strategy_process(strategy_config, "config/settings.yaml")
                    return proc

                proc = asyncio.run(run_test())

                call_args = mock_exec.call_args
                passed_env = call_args.kwargs.get("env", {})

                assert passed_env.get("VIRTUAL_ENV") == "/home/test/.venv"

    def test_strategy_process_cmd_uses_sys_executable(self):
        """策略进程命令应使用 sys.executable"""
        from run_strategies_manager import STRATEGY_PROCESS_CMD

        import sys
        assert sys.executable in STRATEGY_PROCESS_CMD[0] or STRATEGY_PROCESS_CMD[0] == sys.executable