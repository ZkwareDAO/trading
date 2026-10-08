#!/usr/bin/env python3
"""
Strategies Runtime — 策略进程监督者

职责：
- 解析 enabled 策略清单（config/strategies.yaml 或 CLI --run）
- 拉起每个策略的独立子进程（run_strategy.py）
- 监控子进程退出（只告警，不自动重启）
- 收到 SIGTERM/SIGINT 时优雅停止所有子进程（SIGTERM→SIGKILL）

配置文件分离：
- config/settings.yaml - 系统配置（data_manager, signal_logging 等）
- config/strategies.yaml - 策略配置（策略列表、trading_mode）

使用方式:
    python run_strategies_manager.py
    python run_strategies_manager.py --run sar_snt3_v3:BTCUSDT,obv_atr_v2:ETHUSDT
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

from strategy_core.utils.strategy_naming import build_strategy_id_from_overrides
from strategy_core.utils.log_handlers import DailyDirectoryFileHandler
from strategy_core.utils.strategies_loader import StrategiesLoader
from strategy_core.utils.env_placeholders import (
    resolve_env_placeholders as _resolve_env_placeholders,
)

logger = logging.getLogger(__name__)

# 策略进程启动命令
STRATEGY_PROCESS_CMD = [sys.executable, str(Path(__file__).parent / "run_strategy.py")]


def load_yaml_config(config_path: str) -> Dict[str, Any]:
    """加载 YAML 配置文件，并解析 ${VAR} 占位符为环境变量值"""
    path = Path(config_path)
    if not path.exists():
        logging.warning(f"配置文件不存在：{config_path}")
        return {}
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    return _resolve_env_placeholders(raw)


def parse_explicit_strategies(raw: Optional[str]) -> List[tuple]:
    """解析运行清单字符串为 (name, symbol) 列表

    三个入口共用：manager --run / run_backtest --strategies / batch_runner --run。
    因调用方的 flag 名不同，报错信息不写具体 flag 名。

    格式: name:symbol,name:symbol
    示例: sar_snt3_v3:BTCUSDT,obv_atr_v2:ETHUSDT

    Args:
        raw: CLI 传入的原始字符串

    Returns:
        [(strategy_name, symbol), ...]，输入为空返回 []
    """
    if not raw or not raw.strip():
        return []

    pairs: List[tuple] = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(
                f"运行清单格式错误: '{item}'，应为 name:symbol（用逗号分隔多个）"
            )
        name, symbol = item.split(":", 1)
        name = name.strip()
        symbol = symbol.strip().upper()
        if not name or not symbol:
            raise ValueError(f"运行清单格式错误: '{item}'，name 和 symbol 不能为空")
        pairs.append((name, symbol))
    return pairs


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
        # user_id 仅从 per-symbol overrides 读取，缺失置 "0"
        user_id = "0"
        try:
            config_path = Path(instance.config_path)
            if config_path.exists():
                full = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                uid = full.get(instance.name, {}).get("user_id")
                user_id = str(uid) if uid not in (None, "") else "0"
        except Exception as e:
            logger.debug(f"从 overrides 读取 user_id 失败 {instance.config_path}: {e}")

        strategy_id = build_strategy_id_from_overrides(
            instance.name, instance.symbol, instance.trading_mode,
            interval=instance.interval, version=instance.version,
        )

        enabled.append({
            "name": instance.name,
            "symbol": instance.symbol,
            "interval": instance.interval,
            "version": instance.version,
            "trading_mode": instance.trading_mode,
            "config_path": instance.config_path,
            "params": {},
            "strategy_id": strategy_id,
            "strategy_name": strategy_id,
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
    2. 旧格式（兼容）: 从 settings.yaml 的 strategies 段解析

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

        # user_id 仅从 per-symbol overrides 读取，缺失置 "0"
        user_id = "0"
        if config_path:
            try:
                full = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
                uid = full.get(name, {}).get("user_id")
                user_id = str(uid) if uid not in (None, "") else "0"
            except Exception as e:
                logger.debug(f"从 overrides 读取 user_id 失败 {config_path}: {e}")

        for symbol in symbols:
            strategy_id = build_strategy_id_from_overrides(
                name, symbol, trading_mode,
                interval=interval, version=version,
            )

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
                "strategy_name": strategy_id,
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
    策略进程监督者

    流程：
    1. 解析 enabled 策略清单
    2. 拉起每个策略的独立子进程
    3. 监控子进程退出（只告警，不自动重启）
    4. 收到停止信号时优雅停止所有子进程
    """

    def __init__(
        self,
        system_config_path: str = "config/settings.yaml",
        strategies_config_path: str = "config/strategies.yaml",
        log_level: str = "INFO",
        explicit_strategies: Optional[str] = None,
    ):
        self.system_config_path = system_config_path
        self.strategies_config_path = strategies_config_path
        self.log_level = log_level

        # 解析策略配置（使用 StrategiesLoader）
        loader = StrategiesLoader(strategies_config_path).load()

        # CLI --strategies 优先于 config/strategies.yaml 登记表
        explicit_pairs = parse_explicit_strategies(explicit_strategies)
        if explicit_pairs:
            logger.info(f"使用 CLI --strategies 指定运行清单: {explicit_pairs}")
            loader.set_explicit_pairs(explicit_pairs)

        self.strategy_configs: List[Dict[str, Any]] = parse_strategies_from_loader(loader)

        # 转换为 dict 格式
        self.enabled_strategies: Dict[str, Dict[str, Any]] = {}
        for cfg in self.strategy_configs:
            key = cfg["strategy_id"]
            self.enabled_strategies[key] = cfg

        # 进程管理
        self.processes: Dict[str, asyncio.subprocess.Process] = {}
        self._running = False
        self._shutdown_event = asyncio.Event()

    async def start(self) -> None:
        """启动所有策略子进程"""
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

    async def monitor_loop(self) -> None:
        """
        监控循环（不自动重启）

        检测进程退出，记录告警日志。
        """
        logger.info("监控循环已启动")

        while self._running:
            for strategy_id, proc in list(self.processes.items()):
                # asyncio.subprocess.Process 无 poll()，直接检查 returncode
                if proc.returncode is not None:
                    returncode = proc.returncode
                    logger.warning(f"策略进程 {strategy_id} 退出 (code={returncode})")
                    del self.processes[strategy_id]

            await asyncio.sleep(2)

    async def _terminate_process(self, strategy_id: str, proc: asyncio.subprocess.Process) -> None:
        """SIGTERM 优雅停止，超时则 SIGKILL 并确认进程回收

        asyncio.subprocess.Process 无 poll()，用 returncode 判断存活。
        """
        if proc.returncode is not None:
            return

        logger.info(f"向策略进程 {strategy_id} (PID={proc.pid}) 发送 SIGTERM")
        try:
            proc.terminate()
        except ProcessLookupError:
            return

        try:
            await asyncio.wait_for(proc.wait(), timeout=10.0)
            return
        except asyncio.TimeoutError:
            pass
        except ProcessLookupError:
            return

        # SIGTERM 超时 → SIGKILL，并 await 确认进程真正回收
        logger.warning(f"策略进程 {strategy_id} 未响应 SIGTERM，发送 SIGKILL (PID={proc.pid})")
        try:
            proc.kill()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.error(f"策略进程 {strategy_id} SIGKILL 后仍超 5s 未退出 (PID={proc.pid})")
        except ProcessLookupError:
            pass

    async def stop_all(self) -> None:
        """优雅停止所有策略进程"""
        logger.info("策略运行时停止中...")
        self._running = False

        # 停止本地管理的子进程：每个进程独立 SIGTERM→SIGKILL，并发回收避免单个卡死阻塞全部
        if self.processes:
            await asyncio.gather(
                *(self._terminate_process(sid, proc) for sid, proc in self.processes.items()),
                return_exceptions=True,
            )

        self._shutdown_event.set()
        logger.info("策略运行时已停止")

    async def run_forever(self) -> None:
        """运行直到收到停止信号"""
        await asyncio.gather(self.monitor_loop(), self._shutdown_event.wait())


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
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    parser.add_argument(
        "--run",
        default=None,
        help=(
            "直接指定运行清单，格式 name:symbol,name:symbol。"
            "优先于 config/strategies.yaml 登记表；指定的 overrides 文件不存在则报错。"
            "示例: --run sar_snt3_v3:BTCUSDT,obv_atr_v2:ETHUSDT"
        ),
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
        log_level=args.log_level,
        explicit_strategies=args.run,
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

    await runtime.start()
    await runtime.run_forever()


if __name__ == "__main__":
    asyncio.run(main())
