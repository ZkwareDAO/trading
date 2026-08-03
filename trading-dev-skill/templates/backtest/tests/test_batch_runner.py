#!/usr/bin/env python3
"""
测试批量回测执行器

TDD: RED 阶段 - 先写测试
"""

from pathlib import Path
from unittest.mock import patch, MagicMock
from backtest.batch_runner import BatchBacktestRunner

# 测试配置文件路径（旧格式）
TEST_CONFIG = Path(__file__).parent / "test_config.yaml"


class TestBatchBacktestRunnerInit:
    """测试 BatchBacktestRunner 初始化"""

    def test_init_with_default_config(self):
        """使用默认配置初始化"""
        runner = BatchBacktestRunner(str(TEST_CONFIG))
        # start 值由用户配置决定
        assert "start" in runner.main_config
        assert runner.config_dir == str(TEST_CONFIG.parent)

    def test_init_with_custom_config(self):
        """使用自定义配置初始化"""
        runner = BatchBacktestRunner(str(TEST_CONFIG))
        assert runner.main_config["max_workers"] == 4


class TestBuildTasks:
    """测试任务构建"""

    def test_build_tasks_from_config(self):
        """从配置构建任务列表"""
        runner = BatchBacktestRunner(str(TEST_CONFIG))
        tasks = runner._build_tasks()

        # 任务数量取决于配置中的 symbols 数量
        assert len(tasks) >= 1

        task = tasks[0]
        assert task["strategy"] == "cta_ict_v2"  # 当前启用的策略

    def test_build_tasks_config_path(self):
        """任务中的 config_path 应该是自动组合的"""
        runner = BatchBacktestRunner(str(TEST_CONFIG))
        tasks = runner._build_tasks()

        task = tasks[0]
        # config_path 应该包含策略名和 symbol
        assert "cta_ict_v2" in task["config_path"]
        assert "BTCUSDT.yaml" in task["config_path"]

    def test_build_tasks_skip_disabled_strategy(self):
        """跳过 disabled 的策略"""
        runner = BatchBacktestRunner(str(TEST_CONFIG))

        # 临时修改配置
        runner.main_config["strategies"][0]["enabled"] = False
        tasks = runner._build_tasks()

        assert len(tasks) == 0

    def test_build_tasks_multiple_symbols(self):
        """多个 symbols 生成多个任务"""
        runner = BatchBacktestRunner(str(TEST_CONFIG))

        # 临时修改配置
        runner.main_config["strategies"][0]["symbols"] = ["BTCUSDT", "ETHUSDT"]
        tasks = runner._build_tasks()

        assert len(tasks) == 2
        symbols = [t["symbol"] for t in tasks]
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols

    def test_build_tasks_output_dir_uses_strategy_name(self):
        """output_dir 应使用策略名，不包含 symbol"""
        runner = BatchBacktestRunner(str(TEST_CONFIG))

        # 临时修改配置，添加多个 symbols
        runner.main_config["strategies"][0]["symbols"] = ["BTCUSDT", "ETHUSDT"]
        tasks = runner._build_tasks()

        # 所有任务的 output_dir 应相同，且不包含 symbol
        output_dirs = [t["output_dir"] for t in tasks]
        assert all(od == output_dirs[0] for od in output_dirs), f"所有任务的 output_dir 应相同: {output_dirs}"

        # output_dir 应包含策略名，不包含 symbol
        base_output = output_dirs[0]
        assert "cta_rbreaker_v2" in base_output or base_output == "./backtest_output"
        assert "BTCUSDT" not in base_output
        assert "ETHUSDT" not in base_output


class TestRunSingle:
    """测试单个任务执行"""

    @patch("subprocess.run")
    def test_run_single_command_format(self, mock_run):
        """验证命令格式正确"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = BatchBacktestRunner(str(TEST_CONFIG))
        task = {
            "strategy": "cta_rbreaker_v2",
            "symbol": "BTCUSDT",
            "start": "20260101",
            "end": "20260301",
            "data_dir": "./data/strategies",
            "output_dir": "./backtest_output/cta_rbreaker_v2_BTCUSDT",
            "log_level": "INFO",
            "config_path": "backtest/config/cta_rbreaker_v2/BTCUSDT.yaml",
        }

        runner._run_single(task)

        # 验证 subprocess.run 被调用
        assert mock_run.called

        # 验证命令参数
        call_args = mock_run.call_args[0][0]
        assert "python" in call_args[0]
        assert "-m" in call_args[1]
        assert "backtest.run_backtest" in call_args[2]
        assert "--strategy" in call_args
        assert "cta_rbreaker_v2" in call_args
        assert "--config" in call_args
        # 不应该包含 --timeframe, --cash, --commission
        assert "--timeframe" not in call_args
        assert "--cash" not in call_args
        assert "--commission" not in call_args

    @patch("subprocess.run")
    def test_run_single_returns_result(self, mock_run):
        """返回执行结果"""
        mock_run.return_value = MagicMock(returncode=0, stdout="success", stderr="")

        runner = BatchBacktestRunner(str(TEST_CONFIG))
        task = {
            "strategy": "cta_rbreaker_v2",
            "symbol": "BTCUSDT",
            "start": "20260101",
            "end": "20260301",
            "data_dir": "./data/strategies",
            "output_dir": "./backtest_output/test",
            "log_level": "INFO",
            "config_path": "backtest/config/cta_rbreaker_v2/BTCUSDT.yaml",
        }

        result = runner._run_single(task)
        assert result.returncode == 0


class TestEndTimeOptional:
    """测试 end 参数可选"""

    def test_build_tasks_end_optional(self, tmp_path, monkeypatch):
        """未配置 end 时，task["end"] 应为 None"""
        config_file = tmp_path / "main.yaml"
        config_file.write_text("""
start: "20260520"
data_dir: "./data"
output_dir: "./output"
strategies:
  - name: cta_ict_v2
    symbols: ["BTCUSDT"]
""")

        # 创建配置文件目录和文件（跳过检查）
        config_dir = tmp_path / "cta_ict_v2"
        config_dir.mkdir()
        (config_dir / "BTCUSDT.yaml").write_text("test: 1")

        runner = BatchBacktestRunner(str(config_file))
        tasks = runner._build_tasks()
        assert tasks[0]["end"] is None

    def test_build_tasks_end_configured(self, tmp_path):
        """已配置 end 时，正常传递"""
        config_file = tmp_path / "main.yaml"
        config_file.write_text("""
start: "20260520"
end: "20260525"
data_dir: "./data"
output_dir: "./output"
strategies:
  - name: cta_ict_v2
    symbols: ["BTCUSDT"]
""")

        # 创建配置文件目录和文件
        config_dir = tmp_path / "cta_ict_v2"
        config_dir.mkdir()
        (config_dir / "BTCUSDT.yaml").write_text("test: 1")

        runner = BatchBacktestRunner(str(config_file))
        tasks = runner._build_tasks()
        assert tasks[0]["end"] == "20260525"

    @patch("subprocess.run")
    def test_run_single_without_end(self, mock_run):
        """未配置 end 时不传 --end 参数"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = BatchBacktestRunner(str(TEST_CONFIG))
        task = {
            "strategy": "cta_ict_v2",
            "symbol": "BTCUSDT",
            "start": "20260520",
            "end": None,  # 未配置
            "data_dir": "./data",
            "output_dir": "./output",
            "log_level": "INFO",
            "config_path": "backtest/config/cta_ict_v2/BTCUSDT.yaml",
        }

        runner._run_single(task)

        call_args = mock_run.call_args[0][0]
        assert "--end" not in call_args

    @patch("subprocess.run")
    def test_run_single_with_end(self, mock_run):
        """已配置 end 时正常传 --end 参数"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = BatchBacktestRunner(str(TEST_CONFIG))
        task = {
            "strategy": "cta_ict_v2",
            "symbol": "BTCUSDT",
            "start": "20260520",
            "end": "20260525",
            "data_dir": "./data",
            "output_dir": "./output",
            "log_level": "INFO",
            "config_path": "backtest/config/cta_ict_v2/BTCUSDT.yaml",
        }

        runner._run_single(task)

        call_args = mock_run.call_args[0][0]
        assert "--end" in call_args
        assert "20260525" in call_args


class TestRunAll:
    """测试并发执行"""

    @patch("subprocess.run")
    @patch("backtest.batch_runner.ProcessPoolExecutor")
    def test_run_all_returns_summary(self, mock_executor, mock_run):
        """返回执行摘要"""
        # Mock ProcessPoolExecutor
        mock_future = MagicMock()
        mock_future.result.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_executor.return_value.__enter__.return_value.submit.return_value = mock_future
        mock_executor.return_value.__enter__.return_value.__exit__.return_value = False

        # Mock as_completed
        with patch("backtest.batch_runner.as_completed", return_value=[mock_future]):
            runner = BatchBacktestRunner(str(TEST_CONFIG))
            summary = runner.run_all()

            assert "total" in summary
            assert "results" in summary

    @patch("subprocess.run")
    @patch("backtest.batch_runner.ProcessPoolExecutor")
    def test_run_all_handles_failure(self, mock_executor, mock_run):
        """处理失败的任务"""
        # Mock ProcessPoolExecutor
        mock_future = MagicMock()
        mock_future.result.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        mock_executor.return_value.__enter__.return_value.submit.return_value = mock_future
        mock_executor.return_value.__enter__.return_value.__exit__.return_value = False

        # Mock as_completed
        with patch("backtest.batch_runner.as_completed", return_value=[mock_future]):
            runner = BatchBacktestRunner(str(TEST_CONFIG))
            summary = runner.run_all()

            assert summary["results"][0]["status"] == "failed"
            assert summary["results"][0]["return_code"] == 1


class TestWindowsCompatibility:
    """测试 Windows 兼容性修复"""

    @patch("subprocess.run")
    def test_uses_current_python_executable(self, mock_run):
        """
        Bug: Windows 上 subprocess 使用硬编码 "python3"，找不到虚拟环境的包

        修复后应该使用 sys.executable（当前 Python 解释器）
        """
        import sys

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = BatchBacktestRunner(str(TEST_CONFIG))
        task = {
            "strategy": "cta_ict_v2",
            "symbol": "BTCUSDT",
            "start": "20260101",
            "end": "20260301",
            "data_dir": "./data/strategies",
            "output_dir": "./backtest_output/test",
            "log_level": "INFO",
            "config_path": "backtest/config/cta_ict_v2/BTCUSDT.yaml",
        }

        runner._run_single(task)

        # 验证：应该使用 sys.executable，而不是硬编码 "python3"
        call_args = mock_run.call_args[0][0]
        assert call_args[0] == sys.executable, f"应该使用 sys.executable，实际是: {call_args[0]}"
        assert call_args[0] != "python3", "不应该使用硬编码 'python3'"

    @patch("platform.system")
    @patch("subprocess.Popen")
    @patch("builtins.open", create=True)
    def test_daemon_mode_windows_uses_detached_process(self, mock_open, mock_popen, mock_platform):
        """
        Bug: Windows daemon 模式使用 start_new_session，不支持

        修复后 Windows 应使用 DETACHED_PROCESS 标志
        """
        mock_platform.return_value = "Windows"
        mock_popen.return_value = MagicMock(pid=12345)
        mock_open.return_value.__enter__ = MagicMock()
        mock_open.return_value.__exit__ = MagicMock()

        runner = BatchBacktestRunner(str(TEST_CONFIG))

        # Mock 创建目录
        with patch.object(Path, 'mkdir'):
            with patch.object(Path, 'exists', return_value=True):
                summary = runner._run_daemon([{"test": "task"}])

        # 验证：Windows 应使用 creationflags，而不是 start_new_session
        call_kwargs = mock_popen.call_args[1]
        assert "creationflags" in call_kwargs, "Windows 应使用 creationflags"
        assert call_kwargs["creationflags"] == 0x00000008, "应使用 DETACHED_PROCESS (0x00000008)"
        assert "start_new_session" not in call_kwargs, "Windows 不支持 start_new_session"

    @patch("platform.system")
    @patch("subprocess.Popen")
    @patch("builtins.open", create=True)
    def test_daemon_mode_linux_uses_nohup(self, mock_open, mock_popen, mock_platform):
        """
        Linux daemon 模式应使用 nohup + start_new_session
        """
        mock_platform.return_value = "Linux"
        mock_popen.return_value = MagicMock(pid=12345)
        mock_open.return_value.__enter__ = MagicMock()
        mock_open.return_value.__exit__ = MagicMock()

        runner = BatchBacktestRunner(str(TEST_CONFIG))

        # Mock 创建目录
        with patch.object(Path, 'mkdir'):
            with patch.object(Path, 'exists', return_value=True):
                summary = runner._run_daemon([{"test": "task"}])

        # 验证：Linux 应使用 nohup 和 start_new_session
        call_args = mock_popen.call_args[0][0]
        call_kwargs = mock_popen.call_args[1]

        assert call_args[0] == "nohup", "Linux 应使用 nohup"
        assert "start_new_session" in call_kwargs, "Linux 应使用 start_new_session"
        assert call_kwargs["start_new_session"] is True