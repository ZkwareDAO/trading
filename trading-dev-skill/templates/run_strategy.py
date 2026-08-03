#!/usr/bin/env python3
"""
Strategy Process Runner — 策略独立进程入口

每个策略运行在独立进程中，拥有：
- 独立的 DataManager（专属 CSV 路径）
- 独立的 SignalLogger + KafkaProducer
- 独立的 WS 连接
- 独立注册到 factory-service

使用方式:
    # 新格式（推荐）
    python run_strategy.py --name cta_ict_v2 --symbol BTCUSDT --interval 4h --version v2 --trading-mode live
    python run_strategy.py --name cta_ict_v2 --symbol BTCUSDT --interval 4h --version v2 --trading-mode paper_trading --config-file config.prod.yaml

    # 旧格式（兼容）
    python run_strategy.py --strategy cta_rbreaker
    python run_strategy.py --strategy cta_rbreaker --config /path/to/config.yaml
"""

import argparse
import asyncio
import logging
import os
import signal
import sys
import yaml
from pathlib import Path
from typing import Optional, Dict, Any

from data_manager import DataManager, DataManagerConfig
from strategy_core.strategy_engine.engine import StrategyEngine
from strategy_core.signal_logging import SignalLogger, SignalStorage, KafkaSignalProducer
from strategy_core.signal_logging.csv_adapter import SignalCsvWriter
from strategy_core.utils.config_loader import load_config_with_env
from strategy_core.utils.strategy_naming import build_strategy_id
from strategy_core.utils.log_handlers import DailyDirectoryFileHandler

def get_settings_path() -> str:
    """
    获取配置文件路径

    新模式：配置文件通过 --global-config 参数指定，或使用默认 config/settings.yaml
    不再依赖 CTA_ENV 环境变量

    Returns:
        配置文件路径
    """
    # 默认使用 settings.yaml
    settings_path = "config/settings.yaml"
    if not Path(settings_path).exists():
        logging.warning(f"默认配置文件不存在: {settings_path}")
    return settings_path


def build_strategy_config(
    strategy_name: str,
    config_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    加载策略配置文件

    支持多环境配置:
    - config.{env}.yaml (如 config.prod.yaml)
    - config.yaml (默认回退)

    Args:
        strategy_name: 策略目录名 (如 cta_rbreaker)
        config_dir: 策略目录路径，默认使用项目 strategies/{strategy_name}

    Returns:
        策略配置字典，失败返回空字典
    """
    # 转换为 Path 对象
    config_dir_path = Path(config_dir) if config_dir else None

    # 使用多环境配置加载器
    return load_config_with_env(strategy_name, config_dir=config_dir_path)


def resolve_log_level(
    cli_log_level: Optional[str],
    strategy_config: Dict[str, Any],
) -> str:
    """
    解析日志级别，优先级：策略配置 > CLI 参数 > 默认 INFO

    Args:
        cli_log_level: CLI 传入的日志级别（可能为 None）
        strategy_config: 策略配置字典

    Returns:
        日志级别字符串（DEBUG/INFO/WARNING/ERROR）
    """
    # 策略配置优先
    config_level = strategy_config.get("signal", {}).get("diagnostic_log_level")
    if config_level:
        return config_level.upper()

    # CLI 参数其次
    if cli_log_level:
        return cli_log_level.upper()

    # 默认 INFO
    return "INFO"


class StrategyProcessRunner:
    """
    策略进程运行器

    封装单个策略进程的全部生命周期：
    - DataManager（策略专属 CSV 路径）
    - StrategyEngine（只加载当前策略）
    - SignalLogger（独立 Kafka 连接）
    - CSV Writer（独立写入路径）

    支持两种初始化方式：
    1. 新格式：strategy_name（标准化名称）+ trading_mode
    2. 旧格式：strategy_name（目录名）+ strategy_config
    """

    def __init__(
        self,
        strategy_name: str,
        strategy_config: Dict[str, Any],
        global_config_path: str = "config/settings.yaml",
        trading_mode: str = "live",
        strategy_dir: Optional[str] = None,
        position_file_name: Optional[str] = None,
    ):
        """
        初始化策略进程

        Args:
            strategy_name: 策略名称（标准化名称或目录名）
            strategy_config: 策略配置字典
            global_config_path: 全局配置路径
            trading_mode: 运行模式 (live / paper_trading / smoking)
            strategy_dir: 策略目录名（新格式必须）
            position_file_name: 仓位文件名（不含扩展名）
        """
        self.strategy_name = strategy_name
        self.strategy_config = strategy_config
        self.trading_mode = trading_mode
        self._paper_trading_mode = (trading_mode == "paper_trading")
        self._strategy_dir = strategy_dir or strategy_name

        # 加载全局配置
        self.global_config = self._load_global_config(global_config_path)

        # 策略数据路径: data/strategies/{strategy_dir}/
        strategy_data_dir = Path("data") / "strategies" / self._strategy_dir
        strategy_data_dir.mkdir(parents=True, exist_ok=True)

        # 初始化 DataManager（独立实例）
        dm_global_config = self.global_config.get("data_manager", {})
        dm_config = DataManagerConfig(
            csv_dir=str(strategy_data_dir),
            cache_max_size=dm_global_config.get("cache_max_size", 10000),
            # Kafka 配置 (新增)
            kafka_enabled=dm_global_config.get("kafka_enabled", False),
            kafka_brokers=dm_global_config.get("kafka_brokers", []),
            kafka_topic=dm_global_config.get("kafka_topic", "biance_klines"),
            kafka_group_id=f"strategy-{self.strategy_name}",  # 使用策略名作为 group_id
            # WebSocket 配置 (回退)
            klines_service_enabled=dm_global_config.get("klines_service_enabled", True),
            klines_service_ws_url=dm_global_config.get("klines_service_ws_url", "ws://127.0.0.1:17081/ws/klines"),
            klines_service_http_url=dm_global_config.get("klines_service_http_url", "http://127.0.0.1:17081"),
        )
        self.data_manager = DataManager(dm_config)

        # 初始化 SignalLogger（独立实例）
        signal_config = self.global_config.get("signal_logging", {})
        storage_path = signal_config.get("storage", {}).get("path", "data/signals")
        storage = SignalStorage(base_dir=storage_path)

        kafka_config = signal_config.get("kafka", {})
        kafka_producer = None
        kafka_topic = kafka_config.get("topic", "strategy_signals")
        # 模拟盘不发送 Kafka
        if kafka_config.get("enabled", False) and not self._paper_trading_mode:
            kafka_producer = KafkaSignalProducer(kafka_config)

        # 读取 signal_hub 配置
        signal_hub_config = self.global_config.get("signal_hub", {})
        http_endpoint = None
        http_api_path = None
        # 模拟盘不发送 HTTP
        if signal_hub_config.get("enabled", False) and not self._paper_trading_mode:
            http_endpoint = signal_hub_config.get("endpoint")
            # 优先级：策略配置 > 全局配置 > 默认值
            strategy_api_path = self.strategy_config.get("signal", {}).get("api_path")
            global_api_path = signal_hub_config.get("api_path")
            http_api_path = strategy_api_path or global_api_path

        self.signal_logger = SignalLogger(
            storage,
            kafka_producer=kafka_producer,
            http_endpoint=http_endpoint,
            http_api_path=http_api_path,
            kafka_topic=kafka_topic,
        )
        self.csv_writer = SignalCsvWriter()

        # 初始化 StrategyEngine（只加载当前策略）
        engine_config = self.global_config.get("strategy_engine", {})
        factory_endpoint = engine_config.get("factory_endpoint", "http://127.0.0.1:8888")
        position_proxy_url = engine_config.get("position_proxy_url", "http://127.0.0.1:8889")
        strategies_dir = engine_config.get("strategies_dir", "./strategies")

        self.engine = StrategyEngine(
            factory_endpoint=factory_endpoint,
            position_proxy_url=position_proxy_url,
            strategies_dir=strategies_dir,
            data_manager=self.data_manager,
            signal_logger=self.signal_logger,
            csv_writer=self.csv_writer,
        )

        # 仓位文件路径
        self._position_file_name = position_file_name or strategy_name

        # 运行状态
        self._running = False

    def _load_global_config(self, config_path: str) -> Dict[str, Any]:
        """加载全局 settings.yaml"""
        path = Path(config_path)
        if not path.exists():
            logging.warning(f"全局配置文件不存在：{config_path}，使用空配置")
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def load_strategy(self) -> bool:
        """
        加载指定策略（不扫描其他策略目录）

        Returns:
            是否加载成功
        """
        # 使用标准化名称作为 strategy_id
        strategy_id = self.strategy_name
        module_path = f"strategies.{self._strategy_dir}.strategy"

        # 直接注册策略，不扫描其他策略
        self.engine.registry.register(
            strategy_id=strategy_id,
            strategy_name=self._strategy_dir,
            module_path=module_path,
            config=self.strategy_config,
        )

        # 实例化策略
        strategy_entry = self.engine.registry.get(strategy_id)
        if strategy_entry is None:
            logging.error(f"获取策略条目失败：{strategy_id}")
            return False

        success = self.engine.lifecycle.instantiate_strategy(
            strategy_entry,
            self.data_manager,
            strategy_name=self.strategy_name,
            trading_mode=self.trading_mode,
        )

        if success:
            logging.info(f"[{self.strategy_name}] 策略 {strategy_id} 加载成功 (mode={self.trading_mode})")
        else:
            entry = self.engine.registry.get(strategy_id)
            error_msg = entry.error_message if entry and entry.error_message else "未知错误"
            logging.error(f"[{self.strategy_name}] 策略加载失败: {error_msg}")

        return success

    async def connect_data_manager(self) -> bool:
        """连接 DataManager（加载 CSV 数据到缓存）"""
        return self.data_manager.connect()

    async def _collect_subscribed_symbols(self) -> set:
        """收集策略订阅的所有 symbols"""
        symbols = set()
        for entry in self.engine.registry.list_strategies().values():
            if entry.instance:
                if hasattr(entry.instance, "subscribed_symbols"):
                    symbols.update(entry.instance.subscribed_symbols)
                elif hasattr(entry.instance, "symbol"):
                    symbols.add(entry.instance.symbol)
        return symbols

    async def _load_historical_data(self, days: int = 7) -> None:
        """
        加载历史数据 + 恢复大周期缓存

        复用已有方法:
        1. load_history — 加载 1m CSV 到缓存
        2. _preload_all_big_intervals_from_csv — 恢复已有大周期 CSV 到缓存
        3. sync_to_latest — 补齐缺失的历史数据（默认 7 天）
        4. _preload_big_intervals_to_cache — 聚合大周期到内存
        """
        symbols = await self._collect_subscribed_symbols()
        for symbol in symbols:
            symbol_upper = symbol.upper()
            try:
                # 1. 加载 1m CSV 到缓存（避免 sync_to_latest 重复下载）
                df_1m = self.data_manager.load_history(symbol_upper)
                if df_1m is not None and not df_1m.empty:
                    self.data_manager.cache.put(symbol_upper, "1m", df_1m, force_1m=True)
                    logging.info(
                        f"[{self.strategy_name}] {symbol_upper}: 加载 1m CSV 到缓存 ({len(df_1m)} 行)"
                    )
                # 2. 恢复已有大周期 CSV 到缓存
                self.data_manager._preload_all_big_intervals_from_csv(symbol_upper)
                # 3. 复用 sync_to_latest 补齐历史数据
                await self.data_manager.sync_to_latest(
                    symbol_upper, max_history_days=days,
                )
                # 4. 聚合大周期到内存缓存
                self.data_manager._preload_big_intervals_to_cache(symbol_upper)
                logging.info(
                    f"[{self.strategy_name}] {symbol_upper}: 历史数据加载完成",
                )
            except Exception as e:
                logging.warning(
                    f"[{self.strategy_name}] {symbol_upper}: 历史数据加载失败: {e}",
                    exc_info=True,
                )

    async def start(self) -> bool:
        """
        启动策略进程

        Returns:
            是否启动成功
        """
        logging.info(f"[{self.strategy_name}] 策略进程启动")

        # 连接 DataManager
        dm_ok = await self.connect_data_manager()
        if not dm_ok:
            logging.warning(f"[{self.strategy_name}] DataManager 连接失败，但继续运行")

        # 加载策略
        loaded = self.load_strategy()
        if not loaded:
            logging.error(f"[{self.strategy_name}] 策略加载失败")
            return False

        # 加载历史数据（30 天默认）—— 必须在 engine.start_all() 之前，
        # 因为策略 on_start() 需要从缓存中读取 K 线数据初始化
        await self._load_historical_data(days=30)

        # 启动策略
        results = self.engine.start_all()
        for sid, success in results.items():
            if success:
                logging.info(f"[{self.strategy_name}] 策略 {sid} 已启动")
            else:
                logging.error(f"[{self.strategy_name}] 策略 {sid} 启动失败")

        # 注册 WS K 线分发回调
        self.data_manager.set_kline_dispatch_callback(
            lambda kline: self.engine.on_kline_update(kline)
        )

        self._running = True
        return True

    async def stop(self) -> None:
        """停止策略进程"""
        logging.info(f"[{self.strategy_name}] 策略进程停止")
        self._running = False

        if self.engine:
            self.engine.stop_all()

        if self.data_manager:
            await self.data_manager.close()

    async def run_ws_driven(self) -> None:
        """
        运行 WS 驱动的策略进程

        WS 回调中直接调用 strategy.on_kline(kline)，
        替代 CSV 轮询机制。
        """
        if not self._running:
            await self.start()

        # 收集策略订阅的 symbols
        symbols = set()
        for entry in self.engine.registry.list_strategies().values():
            if entry.instance:
                if hasattr(entry.instance, "subscribed_symbols"):
                    symbols.update(entry.instance.subscribed_symbols)
                elif hasattr(entry.instance, "symbol"):
                    symbols.add(entry.instance.symbol)

        if symbols:
            logging.info(f"[{self.strategy_name}] 订阅 WS symbols: {symbols}")

            # 启动实时数据服务（Kafka 或 WebSocket）
            ws_ok = await self.data_manager.start_klines_service_async()
            if ws_ok:
                # 订阅 symbols
                sub_ok = await self.data_manager.subscribe_klines_async(list(symbols))
                # 日志已由 DataManager 根据实际数据源打印
            else:
                logging.warning(f"[{self.strategy_name}] 实时数据服务不可用，降级到 CSV 模式")

        # 保持运行直到收到停止信号
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()


async def main():
    """CLI 入口点"""
    parser = argparse.ArgumentParser(description="Strategy Process Runner")

    # 新格式参数
    parser.add_argument(
        "--name",
        default=None,
        help="策略目录名 (如 cta_ict_v2)",
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="交易对 (如 BTCUSDT)",
    )
    parser.add_argument(
        "--interval",
        default=None,
        help="主周期 (如 4h)",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="版本号 (如 v2)",
    )
    parser.add_argument(
        "--trading-mode",
        choices=["live", "paper_trading", "smoking"],
        default="live",
        help="运行模式 (live 实盘 / paper_trading 模拟盘 / smoking 小金额实盘)",
    )
    parser.add_argument(
        "--config-file",
        default="config.yaml",
        help="策略配置文件名 (默认 config.yaml，在策略目录内查找)",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="策略配置文件完整路径 (优先级高于 --config-file)",
    )

    # 旧格式参数（兼容）
    parser.add_argument(
        "--strategy",
        default=None,
        help="策略名称（旧格式，如 cta_rbreaker）",
    )
    parser.add_argument(
        "--config",
        default=None,
        help="策略配置文件路径（旧格式）",
    )

    # 通用参数
    parser.add_argument(
        "--global-config",
        default="config/settings.yaml",
        help="全局配置文件路径 (默认: config/settings.yaml)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )

    args = parser.parse_args()

    # 尽早配置日志，确保后续所有日志输出都能正确写入
    # 使用环境变量或命令行参数确定日志级别
    early_log_level = getattr(logging, args.log_level, logging.INFO)
    logging.basicConfig(
        level=early_log_level,
        format="%(asctime)s - [early] - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )

    # 判断使用新格式还是旧格式
    use_new_format = args.name and args.symbol and args.interval and args.version

    if use_new_format:
        # 新格式：生成标准化 strategy_name（包含 trading_mode）
        strategy_name = build_strategy_id(
            args.name, args.interval, args.version, args.symbol, args.trading_mode
        )
        strategy_dir = args.name

        # 加载策略配置（优先使用 --config-path）
        if args.config_path:
            # 使用独立配置文件路径
            config_path = Path(args.config_path)
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    full_config = yaml.safe_load(f) or {}
                strategy_config = full_config.get(args.name, {})
                logging.info(f"加载配置文件: {config_path}")
            else:
                logging.error(f"配置文件不存在: {config_path}")
                sys.exit(1)
        else:
            # 使用策略目录内的配置文件
            config_path = Path("strategies") / args.name / args.config_file
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    full_config = yaml.safe_load(f) or {}
                strategy_config = full_config.get(args.name, {})
                logging.info(f"加载配置文件: {config_path}")
            else:
                logging.warning(f"配置文件不存在: {config_path}")
                strategy_config = {}

        # 覆盖 symbol
        strategy_config["symbols"] = [args.symbol]

        trading_mode = args.trading_mode

    elif args.strategy:
        # 旧格式兼容
        strategy_name = args.strategy
        strategy_dir = args.strategy

        strategy_config = build_strategy_config(
            args.strategy,
            config_dir=args.config,
        )
        if not strategy_config:
            logging.error(f"无法加载策略 {args.strategy} 的配置，退出")
            sys.exit(1)

        trading_mode = "live"

    else:
        logging.error("必须指定 --name/--symbol/--interval/--version 或 --strategy")
        sys.exit(1)

    # 确定日志级别：策略配置优先，命令行参数其次，默认 INFO
    log_level_str = resolve_log_level(args.log_level, strategy_config)
    log_level = getattr(logging, log_level_str, logging.INFO)

    # 更新日志级别（如果需要）
    if log_level != early_log_level:
        logging.getLogger().setLevel(log_level)

    # 添加按日目录存储的文件日志处理器
    file_handler = DailyDirectoryFileHandler(
        base_dir="logs/strategies",
        filename=strategy_name,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(
        f"%(asctime)s - [{strategy_name}] - %(name)s - %(levelname)s - %(message)s"
    ))
    logging.getLogger().addHandler(file_handler)

    # 更新 StreamHandler 格式，包含策略名称
    for handler in logging.getLogger().handlers:
        if isinstance(handler, logging.StreamHandler):
            handler.setFormatter(logging.Formatter(
                f"%(asctime)s - [{strategy_name}] - %(name)s - %(levelname)s - %(message)s"
            ))

    # 记录日志级别来源
    config_level = strategy_config.get("signal", {}).get("diagnostic_log_level")
    if config_level:
        logging.info(f"日志级别: {log_level_str}（来自策略配置）")
    elif args.log_level:
        logging.info(f"日志级别: {log_level_str}（来自命令行）")
    else:
        logging.info(f"日志级别: {log_level_str}（默认）")

    logging.info(f"trading_mode: {trading_mode}")

    # 获取全局配置路径
    global_config_path = args.global_config
    logging.info(f"全局配置: {global_config_path}")

    # 创建运行器
    runner = StrategyProcessRunner(
        strategy_name=strategy_name,
        strategy_config=strategy_config,
        global_config_path=global_config_path,
        trading_mode=trading_mode,
        strategy_dir=strategy_dir,
    )

    # 注册 SIGTERM 信号处理器，确保 factory stop 时触发 on_stop()
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def sigterm_handler():
        logging.info(f"[{strategy_name}] 收到 SIGTERM，触发仓位持久化...")
        stop_event.set()

    loop.add_signal_handler(signal.SIGTERM, sigterm_handler)

    # 启动并运行
    try:
        ok = await runner.start()
        if not ok:
            logging.error("策略启动失败，退出")
            sys.exit(1)

        # WS 驱动模式，等待 stop_event 或正常退出
        ws_task = asyncio.create_task(runner.run_ws_driven())
        stop_task = asyncio.create_task(stop_event.wait())

        # 任一完成则退出
        done, pending = await asyncio.wait(
            [ws_task, stop_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # 取消未完成的任务
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    except asyncio.CancelledError:
        # 正常停止时 asyncio.wait 可能被取消
        logging.info(f"[{strategy_name}] 任务已取消，正在停止...")
    except KeyboardInterrupt:
        logging.info("收到 Ctrl+C，正在停止...")
    finally:
        await runner.stop()


if __name__ == "__main__":
    asyncio.run(main())
