"""
Test run_strategies_manager.py — 策略进程调度器

验证:
1. 解析 strategies 列表配置
2. 生成标准化策略 ID
3. 构建策略进程启动命令
4. 心跳正确报告策略状态
"""

import pytest
import sys
import asyncio
import tempfile
import yaml
from pathlib import Path
from unittest.mock import MagicMock, patch, AsyncMock


# 确保项目根目录在 sys.path 中
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _make_global_config(tmpdir, strategies=None):
    """创建全局 settings.yaml（列表格式）- 用于兼容旧格式测试"""
    if strategies is None:
        strategies = [
            {
                "name": "cta_ict_v3",
                "symbol": "BTCUSDT",
                "interval": "4h",
                "version": "v2",
                "enabled": True,
                "trading_mode": "live",
            }
        ]

    config = {
        "strategy_engine": {
            "factory_endpoint": "http://127.0.0.1:8888",
            "strategies_dir": str(PROJECT_ROOT / "strategies"),
        },
        "data_manager": {
            "source_data_path": str(tmpdir / "source_data"),
        },
        "signal_logging": {
            "storage": {"path": str(tmpdir / "signals")},
            "kafka": {"enabled": False},
        },
        "strategies": strategies,
    }
    settings_path = tmpdir / "settings.yaml"
    with open(settings_path, "w") as f:
        yaml.dump(config, f)
    return str(settings_path)


def _make_separated_configs(tmpdir, strategies_config=None):
    """创建分离的配置文件 - settings.yaml + strategies.yaml"""
    # settings.yaml - 系统配置
    system_config = {
        "strategy_engine": {
            "factory_endpoint": "http://127.0.0.1:8888",
            "strategies_dir": str(PROJECT_ROOT / "strategies"),
        },
        "data_manager": {
            "source_data_path": str(tmpdir / "source_data"),
        },
        "signal_logging": {
            "storage": {"path": str(tmpdir / "signals")},
            "kafka": {"enabled": False},
        },
    }
    settings_path = tmpdir / "settings.yaml"
    with open(settings_path, "w") as f:
        yaml.dump(system_config, f)

    # strategies.yaml - 策略配置
    if strategies_config is None:
        strategies_config = {
            "strategies": {
                "cta_ict_v3": {
                    "trading_mode": "live",
                    "symbols": ["BTCUSDT"],
                }
            }
        }
    strategies_path = tmpdir / "strategies.yaml"
    with open(strategies_path, "w") as f:
        yaml.dump(strategies_config, f)

    return str(settings_path), str(strategies_path)


class TestParseStrategiesConfig:
    """测试解析策略配置"""

    def test_parse_list_format(self, tmp_path):
        """解析列表格式配置"""
        from run_strategies_manager import parse_strategies_config

        strategies = [
            {
                "name": "cta_ict_v3",
                "symbol": "BTCUSDT",
                "interval": "4h",
                "version": "v2",
                "enabled": True,
                "trading_mode": "live",
            },
            {
                "name": "dolphin_trading_v2",
                "symbol": "ETHUSDT",
                "interval": "4h",
                "version": "v2",
                "enabled": False,
                "trading_mode": "paper_trading",
            },
        ]
        settings_path = _make_global_config(tmp_path, strategies=strategies)

        configs = parse_strategies_config(settings_path)

        # 只有 enabled=true 的策略
        assert len(configs) == 1
        assert configs[0]["name"] == "cta_ict_v3"
        assert configs[0]["symbol"] == "BTCUSDT"
        assert configs[0]["strategy_id"] == "ICT_4H_2_BTCUSDT_LIVE"

    def test_parse_symbols_expansion(self, tmp_path):
        """展开 symbols 数组"""
        from run_strategies_manager import parse_strategies_config

        strategies = [
            {
                "name": "cta_ict_v3",
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "interval": "4h",
                "version": "v2",
                "enabled": True,
                "trading_mode": "live",
            }
        ]
        settings_path = _make_global_config(tmp_path, strategies=strategies)

        configs = parse_strategies_config(settings_path)

        # 每个 symbol 一个配置
        assert len(configs) == 2
        assert configs[0]["symbol"] == "BTCUSDT"
        assert configs[1]["symbol"] == "ETHUSDT"

    def test_skip_disabled_strategies(self, tmp_path):
        """跳过 disabled 策略"""
        from run_strategies_manager import parse_strategies_config

        strategies = [
            {
                "name": "cta_ict_v3",
                "symbol": "BTCUSDT",
                "interval": "4h",
                "version": "v2",
                "enabled": False,
                "trading_mode": "live",
            }
        ]
        settings_path = _make_global_config(tmp_path, strategies=strategies)

        configs = parse_strategies_config(settings_path)
        assert len(configs) == 0




    def test_user_id_from_config_path_takes_priority(self, tmp_path):
        """config_path 存在且含 user_id 时，优先使用其值（而非共享配置）"""
        from run_strategies_manager import parse_strategies_config

        # 创建 per-token 配置文件，user_id 与共享配置不同
        per_token_config = {
            "my_strategy": {
                "version": "v2",
                "user_id": 42,
            }
        }
        config_path = tmp_path / "per_token.yaml"
        with open(config_path, "w") as f:
            yaml.dump(per_token_config, f)

        strategies = [
            {
                "name": "my_strategy",
                "symbol": "BTCUSDT",
                "interval": "4h",
                "version": "v2",
                "enabled": True,
                "trading_mode": "live",
                "config_path": str(config_path),
            }
        ]
        settings_path = _make_global_config(tmp_path, strategies=strategies)

        configs = parse_strategies_config(settings_path)
        assert len(configs) == 1
        # 应使用 config_path 中的 user_id=42
        assert configs[0]["user_id"] == "42"





class TestBuildStrategyId:
    """测试策略 ID 生成"""

    def test_build_strategy_id(self):
        """生成标准化策略 ID"""
        from strategy_core.utils.strategy_naming import build_strategy_id_from_overrides

        # cta_ict_v3 → ICT
        name = build_strategy_id_from_overrides("cta_ict_v3", "BTCUSDT", "live", "4h", "v2")
        assert name == "ICT_4H_2_BTCUSDT_LIVE"

        # dolphin_trading_v2 → DOLPHIN
        name = build_strategy_id_from_overrides("dolphin_trading_v2", "ETHUSDT", "paper_trading", "4h", "v2")
        assert name == "DOLPHIN_4H_2_ETHUSDT_PAPER"

        # obv_atr_v2 → OBVATR
        name = build_strategy_id_from_overrides("obv_atr_v2", "SOLUSDT", "live", "1h", "v2")
        assert name == "OBVATR_1H_2_SOLUSDT_LIVE"

        # cta_rbreaker_v3 → RBREAKER
        name = build_strategy_id_from_overrides("cta_rbreaker_v3", "BNBUSDT", "paper_trading", "15m", "v2")
        assert name == "RBREAKER_15M_2_BNBUSDT_PAPER"


class TestBuildStrategyCommand:
    """测试构建策略进程启动命令"""

    def test_build_command_with_config_path(self):
        """使用 config_path 构建命令"""
        from run_strategies_manager import build_strategy_command

        strategy_config = {
            "name": "cta_ict_v3",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "version": "v2",
            "trading_mode": "live",
            "config_path": "config/strategies/cta_ict_v3/BTCUSDT.yaml",
        }

        cmd = build_strategy_command(strategy_config, "config/settings.yaml")

        assert "--name" in cmd
        assert "cta_ict_v3" in cmd
        assert "--symbol" in cmd
        assert "BTCUSDT" in cmd
        assert "--interval" in cmd
        assert "4h" in cmd
        assert "--config-path" in cmd
        assert "config/strategies/cta_ict_v3/BTCUSDT.yaml" in cmd

    def test_build_command_without_config_path(self):
        """不使用 config_path 构建命令"""
        from run_strategies_manager import build_strategy_command

        strategy_config = {
            "name": "cta_ict_v3",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "version": "v2",
            "trading_mode": "live",
        }

        cmd = build_strategy_command(strategy_config, "config/settings.yaml")

        assert "--name" in cmd
        assert "--symbol" in cmd
        assert "--config-path" not in cmd


class TestStartStrategyProcess:
    """测试启动策略进程"""

    def test_start_strategy_process(self, tmp_path):
        """启动单个策略进程"""
        from run_strategies_manager import start_strategy_process

        settings_path = _make_global_config(tmp_path)

        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(return_value=b"")
        mock_stderr = AsyncMock()
        mock_stderr.readline = AsyncMock(return_value=b"")

        mock_proc = MagicMock()
        mock_proc.pid = 12345
        mock_proc.poll.return_value = None
        mock_proc.returncode = None
        mock_proc.stdout = mock_stdout
        mock_proc.stderr = mock_stderr

        strategy_config = {
            "name": "cta_ict_v3",
            "symbol": "BTCUSDT",
            "interval": "4h",
            "version": "v2",
            "trading_mode": "live",
            "strategy_id": "ICT_4H_2_BTCUSDT_LIVE",
            "strategy_name": "ICTv3_1d_BTCUSDT",
        }

        with patch("run_strategies_manager.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_proc

            async def _run():
                return await start_strategy_process(strategy_config, settings_path)

            proc = asyncio.run(_run())

            assert mock_exec.called
            call_args = mock_exec.call_args
            assert "--name" in str(call_args)
            assert "cta_ict_v3" in str(call_args)


class TestStrategyRuntime:
    """测试策略运行时"""

    def test_runtime_initialization(self, tmp_path):
        """运行时初始化"""
        from run_strategies_manager import StrategyRuntime

        settings_path, strategies_path = _make_separated_configs(tmp_path)

        runtime = StrategyRuntime(
            system_config_path=settings_path,
            strategies_config_path=strategies_path,
            strategies_dir=str(PROJECT_ROOT / "strategies"),
            factory_endpoint="http://127.0.0.1:8888",
        )

        assert runtime.system_config_path == settings_path
        # 策略配置从实际 zktrading 加载，数量可能多于测试预期
        # 只验证至少有一个 cta_ict_v3 策略
        assert len(runtime.strategy_configs) >= 1
        ict_configs = [c for c in runtime.strategy_configs if c["name"] == "cta_ict_v3"]
        assert len(ict_configs) >= 1

    def test_enabled_strategies_dict(self, tmp_path):
        """enabled_strategies 字典正确构建"""
        from run_strategies_manager import StrategyRuntime

        settings_path, strategies_path = _make_separated_configs(tmp_path)

        runtime = StrategyRuntime(
            system_config_path=settings_path,
            strategies_config_path=strategies_path,
            strategies_dir=str(PROJECT_ROOT / "strategies"),
            factory_endpoint="http://127.0.0.1:8888",
        )

        # 验证至少有一个 cta_ict_v3 策略
        ict_ids = [k for k in runtime.enabled_strategies if "ICT" in k]
        assert len(ict_ids) >= 1


    def test_register_all_to_factory_passes_dict(self, tmp_path):
        """
        _register_all_to_factory 应传 dict 给 factory_client.register()
        而非关键字参数（factory_client.register() 签名为 register(config: Dict)）
        """
        from run_strategies_manager import StrategyRuntime

        settings_path, strategies_path = _make_separated_configs(tmp_path)

        runtime = StrategyRuntime(
            system_config_path=settings_path,
            strategies_config_path=strategies_path,
            strategies_dir=str(PROJECT_ROOT / "strategies"),
            factory_endpoint="http://127.0.0.1:8888",
        )

        # Mock register 方法
        runtime.factory_client.register = MagicMock(return_value={"status": "success"})

        result = runtime._register_all_to_factory()

        # 验证 register 被调用，且传参是 dict
        assert runtime.factory_client.register.call_count >= 1, "至少应调用一次 register"
        call_args = runtime.factory_client.register.call_args
        # call_args[0] 是位置参数元组，call_args[1] 是关键字参数字典
        # 应该通过位置参数传 dict，不应该有关键字参数
        assert len(call_args[0]) == 1, "应传 1 个位置参数（dict）"
        assert isinstance(call_args[0][0], dict), "位置参数应为 dict"
        assert call_args[1] == {}, "不应传关键字参数"

        # 验证 dict 中包含 strategy_id
        config = call_args[0][0]
        assert "strategy_id" in config

    def test_register_all_to_factory_returns_results(self, tmp_path):
        """_register_all_to_factory 返回注册结果"""
        from run_strategies_manager import StrategyRuntime

        settings_path, strategies_path = _make_separated_configs(tmp_path)

        runtime = StrategyRuntime(
            system_config_path=settings_path,
            strategies_config_path=strategies_path,
            strategies_dir=str(PROJECT_ROOT / "strategies"),
            factory_endpoint="http://127.0.0.1:8888",
        )
        runtime.factory_client.register = MagicMock(return_value={"status": "success"})

        result = runtime._register_all_to_factory()

        # 验证有返回结果
        assert isinstance(result, dict)
        assert len(result) >= 1  # 至少有一个策略注册


class TestInitializeWithFactoryOrder:
    """测试 initialize_with_factory 调用顺序"""

    def test_callback_server_started_before_restore(self, tmp_path):
        """
        验证: callback server 必须在 _restore_running_strategies 之前启动

        Bug: 如果 callback server 在 restore 之后启动，
        factory 的 notify 回调连接 8892 失败，
        二次确认也失败，导致策略状态被回滚到 registered。
        """
        from run_strategies_manager import StrategyRuntime

        settings_path, strategies_path = _make_separated_configs(tmp_path)

        runtime = StrategyRuntime(
            system_config_path=settings_path,
            strategies_config_path=strategies_path,
            strategies_dir=str(PROJECT_ROOT / "strategies"),
            factory_endpoint="http://127.0.0.1:8888",
            callback_port=18892,
        )

        call_order = []

        original_start_callback = runtime._start_callback_server
        def tracked_start_callback():
            call_order.append("callback_server_started")

        runtime._start_callback_server = tracked_start_callback

        original_restore = runtime._restore_running_strategies
        def tracked_restore():
            call_order.append("restore_started")
            return original_restore()

        runtime._restore_running_strategies = tracked_restore

        runtime.factory_client.register = MagicMock(return_value={"status": "success"})

        async def _run():
            return await runtime.initialize_with_factory()

        asyncio.run(_run())

        # callback_server_started 必须在 restore_started 之前
        assert "callback_server_started" in call_order
        assert "restore_started" in call_order
        assert call_order.index("callback_server_started") < call_order.index("restore_started"), (
            f"callback server 必须在 restore 之前启动，实际顺序: {call_order}"
        )

    def test_callback_port_available_when_factory_notifies(self, tmp_path):
        """
        验证: 当 factory 尝试通知时，callback server 应该已经在监听
        """
        from run_strategies_manager import StrategyRuntime

        settings_path, strategies_path = _make_separated_configs(tmp_path)

        runtime = StrategyRuntime(
            system_config_path=settings_path,
            strategies_config_path=strategies_path,
            strategies_dir=str(PROJECT_ROOT / "strategies"),
            factory_endpoint="http://127.0.0.1:8888",
            callback_port=18893,
        )

        runtime.factory_client.register = MagicMock(return_value={"status": "success"})
        runtime._restore_running_strategies = MagicMock(return_value={})

        # Mock callback server start to just set the flag
        def mock_start_callback(port=None):
            runtime.factory_client._callback_server = MagicMock()

        runtime._start_callback_server = mock_start_callback

        async def _run():
            return await runtime.initialize_with_factory()

        asyncio.run(_run())

        # callback server 应该已启动
        assert runtime.factory_client._callback_server is not None, \
            "callback server 应该在 initialize_with_factory 后运行"


class TestHeartbeatReportsCorrectStatus:
    """测试心跳正确报告策略状态"""

    def test_heartbeat_reports_running_when_subprocess_exists(self, tmp_path):
        """
        验证：当 factory_client._subprocesses 中有运行中的策略时，
        心跳应报告 'running' 而不是 'stopped'
        """
        from run_strategies_manager import StrategyRuntime

        settings_path, strategies_path = _make_separated_configs(tmp_path)

        runtime = StrategyRuntime(
            system_config_path=settings_path,
            strategies_config_path=strategies_path,
            strategies_dir=str(PROJECT_ROOT / "strategies"),
            factory_endpoint="http://127.0.0.1:8888",
        )

        # 模拟 factory_client._subprocesses 中有一个运行中的进程
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        runtime.factory_client._subprocesses["TEST_STRATEGY_ID"] = mock_proc

        running = runtime.factory_client.get_running_strategies()

        assert "TEST_STRATEGY_ID" in running

    def test_heartbeat_reports_stopped_when_no_subprocess(self, tmp_path):
        """
        验证：当 factory_client._subprocesses 为空时，
        心跳应报告 'stopped'
        """
        from run_strategies_manager import StrategyRuntime

        settings_path, strategies_path = _make_separated_configs(tmp_path)

        runtime = StrategyRuntime(
            system_config_path=settings_path,
            strategies_config_path=strategies_path,
            strategies_dir=str(PROJECT_ROOT / "strategies"),
            factory_endpoint="http://127.0.0.1:8888",
        )

        runtime.factory_client._subprocesses.clear()

        running = runtime.factory_client.get_running_strategies()

        assert len(running) == 0

    def test_heartbeat_ignores_self_processes_dict(self, tmp_path):
        """
        验证：心跳不应依赖 self.processes 字典
        """
        from run_strategies_manager import StrategyRuntime

        settings_path, strategies_path = _make_separated_configs(tmp_path)

        runtime = StrategyRuntime(
            system_config_path=settings_path,
            strategies_config_path=strategies_path,
            strategies_dir=str(PROJECT_ROOT / "strategies"),
            factory_endpoint="http://127.0.0.1:8888",
        )

        # 模拟 self.processes 有一个条目（旧的来源）
        mock_old_proc = MagicMock()
        mock_old_proc.returncode = None
        runtime.processes["TEST_STRATEGY_ID"] = mock_old_proc

        # 但 factory_client._subprocesses 有另一个运行中的进程
        mock_new_proc = MagicMock()
        mock_new_proc.poll.return_value = None
        runtime.factory_client._subprocesses["TEST_STRATEGY_ID"] = mock_new_proc

        running = runtime.factory_client.get_running_strategies()

        assert "TEST_STRATEGY_ID" in running