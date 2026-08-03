#!/usr/bin/env python3
"""
Strategies Runtime — 策略运行时（由 cta_factory_service 管理）

职责：
- 发现 enabled 策略并注册到 factory
- 查询 factory 上次状态并恢复 running 的策略
- 接收 factory 回调（start/stop/pause/resume）
- 心跳上报策略状态
- 进程退出时通知 factory（不再自动重启）

不再负责：
- 自主启动策略（由 factory 控制）
- 进程崩溃自动重启（由 factory 控制）
- 策略内部逻辑（K 线分发、信号生成）

配置文件分离：
- config/settings.yaml - 系统配置（data_manager, signal_logging 等）
- config/strategies.yaml - 策略配置（策略列表、trading_mode）

使用方式:
    python run_strategies_manager.py
    python run_strategies_manager.py --config config/settings.yaml --strategies config/strategies.yaml
"""

import argparse
import asyncio
import logging
import os
import signal as signal_lib
import sys
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List

from strategy_core.factory_client import FactoryClient
from strategy_core.utils.strategy_naming import build_strategy_id, build_strategy_name
from strategy_core.utils.strategy_loader import get_strategy_name_params
from strategy_core.utils.log_handlers import DailyDirectoryFileHandler
from strategy_core.utils.strategies_loader import StrategiesLoader

logger = logging.getLogger(__name__)

# 策略进程启动命令
STRATEGY_PROCESS_CMD = [sys.executable, str(Path(__file__).parent / "run_strategy.py")]

def load_yaml_config(config_path: str) -> Dict[str, Any]:
    """加载 YAML 配置文件"""
    path = Path(config_path)
    if not path.exists():
        logging.warning(f"配置文件不存在：{config_path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def merge_configs(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """合并两个配置字典（override 覆盖 base）"""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # 递归合并字典
            result[key] = merge_configs(result[key], value)
        else:
            result[key] = value
    return result


def load_merged_config(
    system_config_path: str = "config/settings.yaml",
    strategies_config_path: str = "config/strategies.yaml",
) -> Dict[str, Any]:
    """加载并合并系统配置和策略配置

    Args:
        system_config_path: 系统配置文件路径
        strategies_config_path: 策略配置文件路径

    Returns:
        合并后的完整配置
    """
    system_config = load_yaml_config(system_config_path)
    strategies_config = load_yaml_config(strategies_config_path)

    # 合并：策略配置覆盖系统配置
    return merge_configs(system_config, strategies_config)


def parse_strategies_from_loader(loader: StrategiesLoader) -> List[Dict[str, Any]]:
    """
    从 StrategiesLoader 解析策略配置

    Args:
        loader: 已加载的 StrategiesLoader 实例

    Returns:
        策略配置列表，每个元素对应一个独立进程
    """
    instances = loader.filter(enabled_only=True)
    enabled = []

    for instance in instances:
        # 动态加载策略命名参数（用于构建 strategy_name）
        try:
            name_params = get_strategy_name_params(instance.name)
        except Exception as e:
            logger.warning(f"加载策略命名参数失败 {instance.name}: {e}")
            name_params = None

        # 从 config_path 读取 user_id
        user_id = ""
        try:
            config_path = Path(instance.config_path)
            if config_path.exists():
                full = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                user_id = str(full.get(instance.name, {}).get("user_id", ""))
        except Exception as e:
            logger.debug(f"从 config_path 读取 user_id 失败 {instance.config_path}: {e}")

        # 回退到共享配置
        if not user_id and name_params:
            user_id = name_params.get("user_id", "")

        strategy_id = build_strategy_id(
            instance.name, instance.interval, instance.version,
            instance.symbol, instance.trading_mode
        )

        if name_params:
            s_name = build_strategy_name(
                name_params["prefix"],
                name_params["version"],
                name_params["interval"],
                instance.symbol,
            )
        else:
            prefix = instance.name.upper().split("_")[0]
            s_name = build_strategy_name(prefix, instance.version, instance.interval, instance.symbol)

        enabled.append({
            "name": instance.name,
            "symbol": instance.symbol,
            "interval": instance.interval,
            "version": instance.version,
            "trading_mode": instance.trading_mode,
            "config": "config.yaml",
            "config_path": instance.config_path,
            "params": {},
            "strategy_id": strategy_id,
            "strategy_name": s_name,
            "user_id": user_id,
        })

    logger.info(f"解析策略配置完成，共 {len(enabled)} 个策略进程")
    return enabled


def parse_strategies_config(
    global_config_path: str = "config/settings.yaml",
    use_strategies_loader: bool = False,
) -> List[Dict[str, Any]]:
    """
    解析 strategies 配置，展开 symbols

    支持两种配置格式：
    1. 新格式（推荐）: 使用 StrategiesLoader 加载 config/strategies.yaml
    2. 旧格式（兼容）: 从 settings.yaml 或 zktrading.yaml 的 strategies 段解析

    旧配置格式（列表）：
    strategies:
      - name: cta_ict_v3
        symbol: BTCUSDT
        interval: 4h
        version: v2
        trading_mode: live
        config_path: config/strategies/cta_ict_v3/BTCUSDT.yaml

    Args:
        global_config_path: 配置文件路径
        use_strategies_loader: 是否使用新的 StrategiesLoader

    Returns:
        策略配置列表，每个元素对应一个独立进程
    """
    if use_strategies_loader:
        loader = StrategiesLoader(global_config_path).load()
        return parse_strategies_from_loader(loader)

    # 旧格式兼容
    global_config = load_yaml_config(global_config_path)
    strategies_section = global_config.get("strategies", [])

    enabled = []
    for item in strategies_section:
        if not isinstance(item, dict):
            continue
        if not item.get("enabled", False):
            continue

        name = item.get("name")
        if not name:
            logger.warning(f"策略配置缺少 name 字段，跳过: {item}")
            continue

        interval = item.get("interval", "4h")
        version = item.get("version", "v2")
        trading_mode = item.get("trading_mode", "live")
        config_file = item.get("config", "config.yaml")
        config_path = item.get("config_path")
        params = item.get("params", {})

        # 处理 symbol / symbols
        symbols = item.get("symbols", [item.get("symbol")])
        # 动态加载策略命名参数（用于构建 strategy_name）
        try:
            name_params = get_strategy_name_params(name)
        except Exception as e:
            logger.warning(f"加载策略命名参数失败 {name}: {e}")
            name_params = None

        # 优先从 config_path 读取 user_id（与子进程保持一致）
        config_user_id = ""
        if config_path:
            try:
                full = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
                config_user_id = str(full.get(name, {}).get("user_id", ""))
            except Exception as e:
                logger.debug(f"从 config_path 读取 user_id 失败 {config_path}: {e}")

        # 回退到共享配置
        fallback_user_id = name_params.get("user_id", "") if name_params else ""
        user_id = config_user_id or fallback_user_id

        for symbol in symbols:
            strategy_id = build_strategy_id(
                name, interval, version, symbol, trading_mode
            )

            if name_params:
                s_name = build_strategy_name(
                    name_params["prefix"],
                    name_params["version"],
                    name_params["interval"],
                    symbol,
                )
            else:
                prefix = name.upper().split("_")[0]
                s_name = build_strategy_name(prefix, version, interval, symbol)

            enabled.append({
                "name": name,
                "symbol": symbol,
                "interval": interval,
                "version": version,
                "trading_mode": trading_mode,
                "config": config_file,
                "config_path": config_path,
                "params": params,
                "strategy_id": strategy_id,
                "strategy_name": s_name,
                "user_id": user_id,
            })

    logger.info(f"解析策略配置完成，共 {len(enabled)} 个策略进程")
    return enabled


def build_strategy_command(
    strategy_config: Dict[str, Any],
    global_config_path: str,
) -> list:
    """
    构建策略进程启动命令

    Args:
        strategy_config: 策略配置（包含 name, symbol, interval, version, trading_mode, config_path）
        global_config_path: 全局配置路径

    Returns:
        命令参数列表
    """
    cmd = [
        *STRATEGY_PROCESS_CMD,
        "--name", strategy_config["name"],
        "--symbol", strategy_config["symbol"],
        "--interval", strategy_config["interval"],
        "--version", strategy_config["version"],
        "--trading-mode", strategy_config["trading_mode"],
        "--global-config", global_config_path,
    ]

    if strategy_config.get("config_path"):
        cmd.extend(["--config-path", strategy_config["config_path"]])
    elif strategy_config.get("config"):
        cmd.extend(["--config-file", strategy_config["config"]])

    return cmd


async def start_strategy_process(
    strategy_config: Dict[str, Any],
    global_config_path: str,
    log_level: str = "INFO",
) -> asyncio.subprocess.Process:
    """
    启动单个策略进程

    Args:
        strategy_config: 策略配置
        global_config_path: 全局配置路径
        log_level: 日志级别

    Returns:
        进程对象
    """
    cmd = build_strategy_command(strategy_config, global_config_path)
    strategy_id = strategy_config["strategy_id"]

    logger.info(f"启动策略进程: {' '.join(cmd)}")

    # 构建子进程环境，确保继承父进程环境
    env = os.environ.copy()
    env["LOG_LEVEL"] = log_level
    # 确保 PYTHONPATH 包含项目根目录
    project_root = str(Path(__file__).parent)
    if "PYTHONPATH" in env:
        if project_root not in env["PYTHONPATH"]:
            env["PYTHONPATH"] = f"{project_root}:{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = project_root

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    # 启动 stdout/stderr 转发
    asyncio.create_task(_forward_stream(proc.stdout, f"[{strategy_id}:out]"))
    asyncio.create_task(_forward_stream(proc.stderr, f"[{strategy_id}:err]"))

    logger.info(f"策略进程 {strategy_id} 已启动 (PID: {proc.pid})")
    return proc


async def _forward_stream(stream, prefix: str):
    """转发子进程输出到日志"""
    while True:
        line = await stream.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").rstrip()
        if text:
            logger.debug(f"{prefix} {text}")


class StrategyRuntime:
    """
    策略运行时（由 cta_factory_service 管理）

    流程：
    1. 发现 enabled 策略
    2. 注册到 factory
    3. 查询 factory 上次状态
    4. 恢复 running 的策略
    5. 启动回调 server
    6. 心跳上报
    7. 进程监控（退出时通知 factory，不自动重启）

    配置分离：
    - system_config_path: 系统配置（settings.yaml）
    - strategies_config_path: 策略配置（strategies.yaml）
    """

    def __init__(
        self,
        system_config_path: str = "config/settings.yaml",
        strategies_config_path: str = "config/strategies.yaml",
        strategies_dir: str = "./strategies",
        factory_endpoint: str = "http://127.0.0.1:8888",
        callback_port: int = 8892,
        callback_host: str = "0.0.0.0",
        log_level: str = "INFO",
        engine: Optional[Any] = None,
    ):
        self.system_config_path = system_config_path
        self.strategies_config_path = strategies_config_path
        self.strategies_dir = strategies_dir
        self.log_level = log_level
        self.callback_port = callback_port
        self.callback_host = callback_host

        # 加载并合并配置
        self.merged_config = load_merged_config(system_config_path, strategies_config_path)

        # 解析策略配置（使用 StrategiesLoader）
        loader = StrategiesLoader(strategies_config_path).load()
        self.strategy_configs: List[Dict[str, Any]] = parse_strategies_from_loader(loader)

        # 转换为 dict 格式
        self.enabled_strategies: Dict[str, Dict[str, Any]] = {}
        for cfg in self.strategy_configs:
            key = cfg["strategy_id"]
            self.enabled_strategies[key] = cfg

        # Factory client
        callback_url = f"http://{callback_host}:{callback_port}"

        # 从配置读取 position_proxy_url 和 position_api_path
        engine_config = self.merged_config.get("strategy_engine", {})
        position_proxy_url = engine_config.get("position_proxy_url", "http://127.0.0.1:8889")
        position_api_path = engine_config.get("position_api_path", "/api/position/user-order-positions")

        self.factory_client = FactoryClient(
            factory_endpoint=factory_endpoint,
            callback_url=callback_url,
            engine=engine,
            global_config_path=system_config_path,
            log_level=log_level,
            position_proxy_url=position_proxy_url,
            position_api_path=position_api_path,
        )

        # 进程管理
        self.processes: Dict[str, asyncio.subprocess.Process] = {}
        self._running = False
        self._shutdown_event = asyncio.Event()

        # 心跳间隔（秒）
        self.heartbeat_interval = 30

    def _register_all_to_factory(self) -> Dict[str, bool]:
        """注册所有 enabled 策略到 factory"""
        results = {}
        for cfg in self.strategy_configs:
            strategy_id = cfg["strategy_id"]

            result = self.factory_client.register({
                "strategy_id": strategy_id,
                "strategy_name": cfg["strategy_name"],
                "name": cfg["name"],
                "user_id": cfg.get("user_id", ""),
                "interval": cfg.get("interval", "4h"),
                "version": cfg.get("version", "v2"),
                "symbol": cfg["symbol"],
                "trading_mode": cfg.get("trading_mode", "live"),
                "script": str(Path(__file__).parent / "run_strategy.py"),
                "config_path": cfg.get("config_path"),
            })

            results[strategy_id] = result.get("status") == "success"
            if results[strategy_id]:
                logger.info(f"策略 {strategy_id} 注册成功")
            else:
                logger.warning(f"策略 {strategy_id} 注册失败: {result}")
        return results

    def _restore_running_strategies(self) -> Dict[str, bool]:
        """恢复 factory 中标记为 running 的策略，或首次启动"""
        results = {}
        for cfg in self.strategy_configs:
            strategy_id = cfg["strategy_id"]
            status = self.factory_client.query_status(strategy_id)
            logger.info(f"查询策略 {strategy_id} 状态: {status}")

            if status.get("running", False):
                # 恢复运行中的策略
                if self.factory_client.engine:
                    success = self.factory_client.engine.start_strategy(strategy_id)
                    results[strategy_id] = success
                    logger.info(f"恢复策略 {strategy_id}: {success}")
                else:
                    # 多进程模式：直接调用启动回调
                    result = self.factory_client._on_strategy_start(strategy_id)
                    results[strategy_id] = result.get("status") == "success"
                    logger.info(f"恢复策略 {strategy_id} (子进程): {result}")
            elif status.get("registered", False) and not status.get("running", False):
                # 已注册但未运行，请求启动
                logger.info(f"策略 {strategy_id} 已注册未运行，请求启动")
                start_result = self.factory_client.request_start(strategy_id)
                logger.info(f"策略 {strategy_id} 启动请求结果: {start_result}")

                # factory 返回 internal 模式时，需要本地启动子进程
                if start_result.get("status") == "success" and start_result.get("mode") == "internal":
                    logger.info(f"策略 {strategy_id} factory 使用 internal 模式，本地启动子进程")
                    if self.factory_client.engine:
                        success = self.factory_client.engine.start_strategy(strategy_id)
                        results[strategy_id] = success
                    else:
                        result = self.factory_client._on_strategy_start(strategy_id)
                        results[strategy_id] = result.get("status") == "success"
                        logger.info(f"策略 {strategy_id} 子进程启动: {result}")
                elif start_result.get("status") == "success":
                    # factory 会通过回调触发启动
                    results[strategy_id] = True
                else:
                    # factory 启动失败，本地启动
                    logger.warning(f"策略 {strategy_id} factory 启动失败，本地启动")
                    if self.factory_client.engine:
                        success = self.factory_client.engine.start_strategy(strategy_id)
                        results[strategy_id] = success
                    else:
                        result = self.factory_client._on_strategy_start(strategy_id)
                        results[strategy_id] = result.get("status") == "success"
        return results

    def _start_callback_server(self) -> None:
        """启动回调服务器（接收 factory 控制指令）"""
        self.factory_client.start_callback_server(host=self.callback_host, port=self.callback_port)
        logger.info(f"回调服务器已启动，监听 {self.callback_host}:{self.callback_port}")

    async def _heartbeat_loop(self) -> None:
        """心跳上报循环"""
        while self._running:
            try:
                running_strategies = self.factory_client.get_running_strategies()

                for cfg in self.strategy_configs:
                    strategy_id = cfg["strategy_id"]
                    status = "running" if strategy_id in running_strategies else "stopped"
                    self.factory_client.report_status(strategy_id, status)

                logger.debug(f"心跳上报完成，共 {len(self.strategy_configs)} 个策略，运行中: {len(running_strategies)}")
            except Exception as e:
                logger.warning(f"心跳上报失败: {e}")

            await asyncio.sleep(self.heartbeat_interval)

    def _handle_strategy_exit(self, strategy_id: str, exit_code: int) -> None:
        """处理策略进程退出（通知 factory，不自动重启）"""
        logger.warning(f"策略进程 {strategy_id} 退出 (code={exit_code})")
        self.factory_client.report_status(strategy_id, "stopped")

    async def start_all_processes(self) -> None:
        """启动所有策略进程（降级流程）"""
        self._running = True
        logger.info(f"策略运行时启动，共 {len(self.strategy_configs)} 个策略")

        for cfg in self.strategy_configs:
            strategy_id = cfg["strategy_id"]
            try:
                proc = await start_strategy_process(
                    cfg, self.system_config_path, self.log_level,
                )
                self.processes[strategy_id] = proc
            except Exception as e:
                logger.error(f"启动策略 {strategy_id} 失败: {e}")

    async def initialize_with_factory(self) -> bool:
        """
        新流程：初始化（注册 + 恢复状态 + 回调 server）

        Returns:
            是否成功初始化
        """
        self._running = True

        # 1. 注册所有策略到 factory
        reg_results = self._register_all_to_factory()
        if not any(reg_results.values()):
            logger.warning("所有策略注册失败，降级为本地自主管理")
            # 降级：启动所有策略进程
            await self.start_all_processes()
            return True

        # 2. 先启动回调 server（factory 需要能回调通知策略启动）
        self._start_callback_server()

        # 3. 再恢复/请求启动策略
        self._restore_running_strategies()

        logger.info("策略运行时初始化完成")
        return True

    async def monitor_loop(self) -> None:
        """
        监控循环（不再自动重启）

        检测进程退出，通知 factory。
        """
        logger.info("监控循环已启动")

        while self._running:
            for strategy_id, proc in list(self.processes.items()):
                if proc.returncode is not None or proc.poll() is not None:
                    try:
                        returncode = proc.returncode
                        if returncode is None:
                            returncode = await proc.wait()
                    except Exception:
                        returncode = -1

                    self._handle_strategy_exit(strategy_id, returncode)
                    del self.processes[strategy_id]

            await asyncio.sleep(2)

    async def stop_all(self) -> None:
        """优雅停止所有策略进程"""
        logger.info("策略运行时停止中...")
        self._running = False

        # 通知 factory 所有策略已停止
        for cfg in self.strategy_configs:
            strategy_id = cfg["strategy_id"]
            result = self.factory_client.request_stop(strategy_id)
            logger.info(f"通知 factory 策略 {strategy_id} 停止: {result}")

        # 停止回调 server
        self.factory_client.stop_callback_server()

        # 停止所有子进程（通过 FactoryClient）
        self.factory_client.stop_all_subprocesses()

        # 停止本地管理的子进程（如果有）
        for strategy_id, proc in self.processes.items():
            if proc.returncode is None:
                logger.info(f"向策略进程 {strategy_id} (PID={proc.pid}) 发送 SIGTERM")
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass

        if self.processes:
            done, pending = await asyncio.wait(
                [proc.wait() for proc in self.processes.values()],
                timeout=10.0,
            )

            for strategy_id, proc in self.processes.items():
                if proc.returncode is None:
                    logger.warning(f"策略进程 {strategy_id} 未响应 SIGTERM，发送 SIGKILL")
                    try:
                        proc.kill()
                    except ProcessLookupError:
                        pass

        self._shutdown_event.set()
        logger.info("策略运行时已停止")

    async def run_forever(self) -> None:
        """运行直到收到停止信号"""
        await asyncio.gather(
            self.monitor_loop(),
            self._heartbeat_loop(),
            self._shutdown_event.wait(),
        )


async def main():
    """CLI 入口点"""
    parser = argparse.ArgumentParser(description="Strategies Runtime")
    parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="系统配置文件路径（默认 config/settings.yaml）",
    )
    parser.add_argument(
        "--strategies",
        default="config/strategies.yaml",
        help="策略配置文件路径（默认 config/strategies.yaml）",
    )
    parser.add_argument(
        "--strategies-dir",
        default="./strategies",
        help="策略目录路径",
    )
    parser.add_argument(
        "--factory-endpoint",
        default="http://127.0.0.1:8888",
        help="factory-service RPC 端点",
    )
    parser.add_argument(
        "--callback-port",
        default=8892,
        type=int,
        help="回调服务器端口",
    )
    parser.add_argument(
        "--callback-host",
        default="0.0.0.0",
        help="回调服务器绑定地址",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    args = parser.parse_args()

    # 配置日志 - 按日目录存储（UTC 时间）
    file_handler = DailyDirectoryFileHandler(
        base_dir="logs",
        filename="strategies_runtime",
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - [Runtime] - %(name)s - %(levelname)s - %(message)s"
    ))

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        handlers=[
            file_handler,
            logging.StreamHandler(),
        ],
    )

    logger.info(f"系统配置: {args.config}")
    logger.info(f"策略配置: {args.strategies}")

    # 创建运行时（使用分离的配置）
    runtime = StrategyRuntime(
        system_config_path=args.config,
        strategies_config_path=args.strategies,
        strategies_dir=args.strategies_dir,
        factory_endpoint=args.factory_endpoint,
        callback_port=args.callback_port,
        callback_host=args.callback_host,
        log_level=args.log_level,
    )

    if not runtime.enabled_strategies:
        logger.error("没有已启用的策略，退出")
        sys.exit(1)

    # 注册信号处理
    loop = asyncio.get_event_loop()
    for sig in (signal_lib.SIGTERM, signal_lib.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(runtime.stop_all()),
        )

    ok = await runtime.initialize_with_factory()
    if ok:
        await runtime.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
