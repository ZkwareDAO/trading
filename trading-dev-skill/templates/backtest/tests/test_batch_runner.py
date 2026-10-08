#!/usr/bin/env python3
"""
测试批量回测执行器

适配收敛后的接口：
- BatchBacktestRunner(strategies_config_path, profile, start_override, end_override)
- 策略登记表来自 config/strategies.yaml（与实盘共用）
- 回测参数来自 config/<profile>.yaml
- 旧的 main.yaml 双格式检测已删除，不再测试
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from backtest.batch_runner import BatchBacktestRunner

# 真实登记表与 profile（收敛后的单一事实来源）
STRATEGIES_CONFIG = "config/strategies.yaml"
PROFILE = "backtest"

# 注：run-profile 加载本身的测试在 test_config_loader.py::TestLoadProfile。
# batch_runner 与 run_backtest 共用 config_loader.load_profile，此处只测
# BatchBacktestRunner 如何使用它（构造期加载、缺失时报错）。


class TestBatchBacktestRunnerInit:
    """测试初始化"""

    def test_init_loads_profile_and_strategies(self):
        runner = BatchBacktestRunner(STRATEGIES_CONFIG, profile=PROFILE)
        assert runner.profile == PROFILE
        assert "max_workers" in runner.profile_cfg
        assert runner.profile_cfg["data_dir"] == "./data/klines"

    def test_init_missing_profile_raises(self):
        with pytest.raises(FileNotFoundError):
            BatchBacktestRunner(STRATEGIES_CONFIG, profile="not_exist_profile")


class TestBuildTasks:
    """测试任务构建"""

    def test_build_tasks_from_registry(self):
        """任务从 strategies.yaml 登记表展开，config_path 指向 overrides"""
        runner = BatchBacktestRunner(STRATEGIES_CONFIG, profile=PROFILE)
        tasks = runner._build_tasks()

        assert len(tasks) >= 1
        task = tasks[0]
        # 单一事实来源：per-symbol 参数一律从 strategies/<name>/overrides/ 读
        assert "overrides" in task["config_path"]
        assert task["config_path"].endswith(".yaml")
        assert task["profile"] == PROFILE

    def test_build_tasks_cli_start_override(self):
        """CLI --start 覆盖 profile.start"""
        runner = BatchBacktestRunner(
            STRATEGIES_CONFIG, profile=PROFILE, start_override="20260701"
        )
        tasks = runner._build_tasks()
        assert tasks[0]["start"] == "20260701"

    def test_build_tasks_cli_end_override(self):
        """CLI --end 覆盖 profile.end"""
        runner = BatchBacktestRunner(
            STRATEGIES_CONFIG, profile=PROFILE, end_override="20260801"
        )
        tasks = runner._build_tasks()
        assert tasks[0]["end"] == "20260801"


class TestRunSingle:
    """测试单任务命令构造"""

    def _make_task(self, end="20260708"):
        return {
            "strategy": "sar_snt3_v3",
            "symbol": "BTCUSDT",
            "start": "20260601",
            "end": end,
            "profile": PROFILE,
            "config_path": "strategies/sar_snt3_v3/overrides/BTCUSDT.yaml",
            "overrides": {},
        }

    @patch("subprocess.run")
    def test_run_single_command_format(self, mock_run):
        """命令只含收敛后的参数：--strategies/--start/--profile/--config-path"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = BatchBacktestRunner(STRATEGIES_CONFIG, profile=PROFILE)
        runner._run_single(self._make_task())

        assert mock_run.called
        call_args = mock_run.call_args[0][0]

        assert "-m" in call_args
        assert "backtest.run_backtest" in call_args
        assert "--strategies" in call_args
        assert "sar_snt3_v3:BTCUSDT" in call_args
        assert "--profile" in call_args
        assert "--config-path" in call_args

        # 已下放 profile 的参数不应出现在命令行
        for removed in ("--timeframe", "--cash", "--commission", "--data-dir", "--output-dir"):
            assert removed not in call_args, f"{removed} 应已下放到 profile"
        # 旧的 --strategy / --config 别名已删除
        assert "--strategy" not in call_args
        assert "--config" not in call_args

    @patch("subprocess.run")
    def test_run_single_returns_result(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="success", stderr="")

        runner = BatchBacktestRunner(STRATEGIES_CONFIG, profile=PROFILE)
        result = runner._run_single(self._make_task())
        assert result.returncode == 0

    @patch("subprocess.run")
    def test_run_single_without_end(self, mock_run):
        """end 为空时不传 --end"""
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = BatchBacktestRunner(STRATEGIES_CONFIG, profile=PROFILE)
        runner._run_single(self._make_task(end=""))

        call_args = mock_run.call_args[0][0]
        assert "--end" not in call_args

    @patch("subprocess.run")
    def test_run_single_with_end(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = BatchBacktestRunner(STRATEGIES_CONFIG, profile=PROFILE)
        runner._run_single(self._make_task(end="20260525"))

        call_args = mock_run.call_args[0][0]
        assert "--end" in call_args
        assert "20260525" in call_args

    @patch("subprocess.run")
    def test_uses_current_python_executable(self, mock_run):
        """必须用 sys.executable，不能硬编码 python3（Windows 虚拟环境兼容）"""
        import sys

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        runner = BatchBacktestRunner(STRATEGIES_CONFIG, profile=PROFILE)
        runner._run_single(self._make_task())

        call_args = mock_run.call_args[0][0]
        assert call_args[0] == sys.executable
        assert call_args[0] != "python3"


class TestRunAll:
    """测试并发执行"""

    @patch("subprocess.run")
    @patch("backtest.batch_runner.ProcessPoolExecutor")
    def test_run_all_returns_summary(self, mock_executor, mock_run):
        mock_future = MagicMock()
        mock_future.result.return_value = MagicMock(returncode=0, stdout="", stderr="")
        mock_executor.return_value.__enter__.return_value.submit.return_value = mock_future
        mock_executor.return_value.__enter__.return_value.__exit__.return_value = False

        with patch("backtest.batch_runner.as_completed", return_value=[mock_future]):
            runner = BatchBacktestRunner(STRATEGIES_CONFIG, profile=PROFILE)
            summary = runner.run_all()

            assert "total" in summary
            assert "results" in summary

    @patch("subprocess.run")
    @patch("backtest.batch_runner.ProcessPoolExecutor")
    def test_run_all_handles_failure(self, mock_executor, mock_run):
        mock_future = MagicMock()
        mock_future.result.return_value = MagicMock(returncode=1, stdout="", stderr="error")
        mock_executor.return_value.__enter__.return_value.submit.return_value = mock_future
        mock_executor.return_value.__enter__.return_value.__exit__.return_value = False

        with patch("backtest.batch_runner.as_completed", return_value=[mock_future]):
            runner = BatchBacktestRunner(STRATEGIES_CONFIG, profile=PROFILE)
            summary = runner.run_all()

            assert summary["results"][0]["status"] == "failed"
            assert summary["results"][0]["return_code"] == 1


class TestMainExitCode:
    """测试 main() 的退出码传播

    batch_runner 由 daily_backtest.py 在 crontab 中调用：若任务全崩仍返回 0，
    失败会被静默吞掉，定时任务看起来一切正常。退出码是唯一的对外故障信号。

    只 mock BatchBacktestRunner 与日志 handler，main() 的退出码逻辑本身真实执行。
    """

    def _run_main(self, summary, extra_argv=()):
        """以给定 summary 执行 main()，返回退出码（None 表示正常返回）"""
        import logging
        import backtest.batch_runner as br

        mock_runner = MagicMock()
        mock_runner.run_all.return_value = summary

        argv = ["batch_runner", "--config", STRATEGIES_CONFIG, "--profile", PROFILE]
        argv.extend(extra_argv)

        with patch.object(br, "BatchBacktestRunner", return_value=mock_runner), \
             patch.object(br, "DailyDirectoryFileHandler", return_value=logging.NullHandler()), \
             patch("sys.argv", argv):
            try:
                br.main()
            except SystemExit as e:
                return e.code
        return None

    def test_all_success_exits_zero(self):
        """全部成功不得退出非零"""
        summary = {
            "total": 2,
            "results": [
                {"status": "success", "return_code": 0, "task": {}},
                {"status": "success", "return_code": 0, "task": {}},
            ],
        }
        assert self._run_main(summary) in (None, 0)

    def test_any_failure_exits_one(self):
        """有任一任务失败必须以退出码 1 结束"""
        summary = {
            "total": 2,
            "results": [
                {"status": "success", "return_code": 0, "task": {}},
                {
                    "status": "failed",
                    "return_code": 1,
                    "stderr": "策略配置文件不存在: nope.yaml",
                    "task": {"strategy": "no_such", "symbol": "BTCUSDT"},
                },
            ],
        }
        assert self._run_main(summary) == 1

    def test_error_status_also_exits_one(self):
        """非 success 的其他状态（如异常 error）同样要传播失败"""
        summary = {
            "total": 1,
            "results": [
                {"status": "error", "error": "Timeout", "task": {"strategy": "x", "symbol": "y"}},
            ],
        }
        assert self._run_main(summary) == 1

    def test_daemon_mode_does_not_judge(self):
        """daemon 只负责拉起后台进程，没有最终结果，不参与退出码判定"""
        summary = {"total": 1, "results": [{"status": "started", "pid": 123, "task": {}}]}
        assert self._run_main(summary, extra_argv=["--daemon"]) in (None, 0)


class TestExplicitRunList:
    """测试 --run 显式运行清单（name:symbol,...）

    三个入口共用同一套清单协议：
      manager       --run        （不限数量）
      run_backtest  --strategies （强制单个）
      batch_runner  --run        （不限数量，本类测的就是它）

    与登记表路径的关键差异：登记表对缺失 overrides 是 warn+skip（长期清单，
    个别标的没配好不该阻断整批），显式清单直接报错（既然点名指定，静默跳过等于骗人）。
    """

    def test_run_list_overrides_registry(self):
        """--run 非空时，任务清单来自它而非 strategies.yaml"""
        runner = BatchBacktestRunner(
            STRATEGIES_CONFIG,
            profile=PROFILE,
            explicit_strategies="sar_snt3_v3:BTCUSDT,sar_snt3_v3:ETHUSDT",
        )
        tasks = runner._build_tasks()

        assert len(tasks) == 2
        assert [t["symbol"] for t in tasks] == ["BTCUSDT", "ETHUSDT"]
        assert all(t["strategy"] == "sar_snt3_v3" for t in tasks)

    def test_run_list_is_subset_of_registry(self, tmp_path):
        """--run 能跑登记表的真子集：登记表 2 个 symbol，指定 1 个就只跑 1 个。

        用临时登记表而非真实 config/strategies.yaml：模板仓库只登记 1 个策略
        ×1 个 symbol（历史上曾登记 13 个），`len(full) > len(one)` 在 1 任务
        登记表下恒假 —— 该断言依赖的是"登记表规模 > 清单规模"这一前提，
        与 --run 过滤逻辑本身无关，故由 fixture 保证前提成立。
        overrides 需真实存在（_build_tasks 对缺失文件 warning 跳过）。
        """
        registry = tmp_path / "strategies.yaml"
        registry.write_text(
            "strategies:\n"
            "  sar_snt3_v3:\n"
            "    trading_mode: \"paper_trading\"\n"
            "    symbols: [BTCUSDT, ETHUSDT]\n",
            encoding="utf-8",
        )

        full = BatchBacktestRunner(str(registry), profile=PROFILE)._build_tasks()
        one = BatchBacktestRunner(
            str(registry), profile=PROFILE,
            explicit_strategies="sar_snt3_v3:BTCUSDT",
        )._build_tasks()

        assert len(full) == 2
        assert len(one) == 1, "若相等则说明 --run 未生效，登记表仍被全量展开"
        assert one[0]["symbol"] == "BTCUSDT"

    def test_run_list_config_path_same_as_registry(self):
        """同一个 name:symbol，无论走清单还是登记表，都必须解析到同一份 overrides。

        这是"回测实盘共用同一份策略参数"的保证：--run 只改跑哪些，不改参数来源。
        """
        via_registry = {
            (t["strategy"], t["symbol"]): t["config_path"]
            for t in BatchBacktestRunner(STRATEGIES_CONFIG, profile=PROFILE)._build_tasks()
        }
        via_run = BatchBacktestRunner(
            STRATEGIES_CONFIG, profile=PROFILE,
            explicit_strategies="sar_snt3_v3:BTCUSDT",
        )._build_tasks()[0]

        key = (via_run["strategy"], via_run["symbol"])
        assert key in via_registry, "BTCUSDT 应同时存在于登记表，否则本测试失去对比意义"
        assert via_run["config_path"] == via_registry[key]

    def test_none_falls_back_to_registry(self):
        """不传 --run 时行为与改动前完全一致（登记表全量展开）"""
        without = BatchBacktestRunner(STRATEGIES_CONFIG, profile=PROFILE)._build_tasks()
        explicit_none = BatchBacktestRunner(
            STRATEGIES_CONFIG, profile=PROFILE, explicit_strategies=None
        )._build_tasks()
        empty_str = BatchBacktestRunner(
            STRATEGIES_CONFIG, profile=PROFILE, explicit_strategies=""
        )._build_tasks()

        assert len(without) == len(explicit_none) == len(empty_str)

    def test_missing_overrides_raises_at_construction(self):
        """显式指定但 overrides 不存在 → 构造期就报错，不是等到 run_all()

        set_explicit_pairs 只登记不校验，展开才检查文件。若留给 run_all() 惰性触发，
        异常会逃出 main() 的 try 变成裸 traceback，用户看到的是调用栈而非一行错误。
        """
        with pytest.raises(FileNotFoundError, match="NOSUCHCOIN"):
            BatchBacktestRunner(
                STRATEGIES_CONFIG, profile=PROFILE,
                explicit_strategies="sar_snt3_v3:NOSUCHCOIN",
            )

    @pytest.mark.parametrize("bad", ["garbage", "sar_snt3_v3:", ":BTCUSDT", "a:B,garbage"])
    def test_malformed_run_list_raises_value_error(self, bad):
        """格式非法 → ValueError（main() 的 except 会转成 exit 1）"""
        with pytest.raises(ValueError, match="运行清单格式错误"):
            BatchBacktestRunner(
                STRATEGIES_CONFIG, profile=PROFILE, explicit_strategies=bad,
            )

    def test_main_passes_run_argv_to_constructor(self):
        """main() 必须把 --run 透传给构造函数

        前面的测试都直接构造 Runner，绕过了 argparse。这条补上 CLI 接线：
        若 main() 漏传 explicit_strategies，--run 会被静默忽略、全量跑 13 个标的
        —— 用户以为只跑了 1 个，是最坏的失败方式（无报错、结果超集）。
        """
        import logging
        import backtest.batch_runner as br

        mock_runner = MagicMock()
        mock_runner.run_all.return_value = {"total": 0, "results": []}

        argv = [
            "batch_runner", "--config", STRATEGIES_CONFIG, "--profile", PROFILE,
            "--run", "sar_snt3_v3:BTCUSDT",
        ]
        with patch.object(br, "BatchBacktestRunner", return_value=mock_runner) as ctor, \
             patch.object(br, "DailyDirectoryFileHandler", return_value=logging.NullHandler()), \
             patch("sys.argv", argv):
            try:
                br.main()
            except SystemExit:
                pass

        assert ctor.call_args.kwargs["explicit_strategies"] == "sar_snt3_v3:BTCUSDT"

    def test_symbol_lowercase_normalized(self):
        """symbol 小写自动转大写，与实盘 --run 一致（overrides 文件名是大写）"""
        runner = BatchBacktestRunner(
            STRATEGIES_CONFIG, profile=PROFILE,
            explicit_strategies="sar_snt3_v3:btcusdt",
        )
        assert runner._build_tasks()[0]["symbol"] == "BTCUSDT"


class TestDaemonPlatformCompatibility:
    """测试 daemon 模式的跨平台处理

    用 tmp_path 真实写 batch 目录，只 mock Popen 与 platform.system。
    不 mock builtins.open —— 全局 mock open 会与 pytest/logging 自身的
    文件操作冲突导致死锁。
    """

    @patch("platform.system")
    @patch("subprocess.Popen")
    def test_daemon_mode_windows_uses_detached_process(
        self, mock_popen, mock_platform, tmp_path
    ):
        """Windows 必须用 DETACHED_PROCESS，不能用 start_new_session"""
        mock_platform.return_value = "Windows"
        mock_popen.return_value = MagicMock(pid=12345)

        runner = BatchBacktestRunner(STRATEGIES_CONFIG, profile=PROFILE)
        runner.profile_cfg["output_dir"] = str(tmp_path)

        runner._run_daemon([{"test": "task"}])

        call_kwargs = mock_popen.call_args[1]
        assert "creationflags" in call_kwargs
        assert call_kwargs["creationflags"] == 0x00000008
        assert "start_new_session" not in call_kwargs

    @patch("platform.system")
    @patch("subprocess.Popen")
    def test_daemon_mode_linux_uses_nohup(self, mock_popen, mock_platform, tmp_path):
        """Linux 使用 nohup + start_new_session"""
        mock_platform.return_value = "Linux"
        mock_popen.return_value = MagicMock(pid=12345)

        runner = BatchBacktestRunner(STRATEGIES_CONFIG, profile=PROFILE)
        runner.profile_cfg["output_dir"] = str(tmp_path)

        runner._run_daemon([{"test": "task"}])

        call_args = mock_popen.call_args[0][0]
        call_kwargs = mock_popen.call_args[1]

        assert call_args[0] == "nohup"
        assert call_kwargs["start_new_session"] is True
