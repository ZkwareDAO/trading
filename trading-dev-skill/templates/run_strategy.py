#!/usr/bin/env python3
"""
Strategy Process Runner — 策略独立进程入口

每个策略运行在独立进程中，拥有：
- 独立的 DataManager（专属 CSV 路径，直连 Binance）
- 独立的 SignalLogger（存储信号 + 交易所直连下单）
- 独立的实时行情连接

单体模式：本进程直接加载 strategies/<name>/strategy.py 的 Strategy 类
（不经注册表/引擎），WS 收到 K 线 → on_kline → 信号统一写 CSV，
CSV 成功后由 SignalLogger 直连交易所下单。

使用方式:
    python run_strategy.py --name sar_snt3_v3 --symbol BTCUSDT --interval 4h --version v3 --trading-mode live

配置文件统一为 strategies/<name>/overrides/<symbol>.yaml（per-symbol），不再使用共享层 config.yaml。
"""

import argparse
import asyncio
import importlib
import logging
import os
import signal
import sys
import yaml
from pathlib import Path
from typing import Optional, Dict, Any

from data_manager import DataManager, DataManagerConfig
from strategy_core.constants import (
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TRAILING_PROFIT_ACTIVATION,
    DEFAULT_TRAILING_PROFIT_DRAWDOWN,
)
from strategy_core.signal_logging import (
    SignalLogger,
    SignalStorage,
    SignalCsvWriter,
    CtaSignalCSV,
    build_signal_params,
)
from strategy_core.utils.strategy_naming import build_strategy_id_from_overrides
from strategy_core.utils.log_handlers import DailyDirectoryFileHandler
from strategy_core.utils.env_placeholders import (
    resolve_env_placeholders as _resolve_env_placeholders,
)


def build_strategy_config(
    strategy_name: str,
    config_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """[已废弃] 配置统一走 per-symbol overrides，旧格式 --strategy 入口已移除。

    保留空壳仅为避免外部直接 import 报错，不再读 config.yaml。
    """
    return {}


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


def resolve_effective_log_level(
    cli_log_level: Optional[str],
    env_log_level: Optional[str],
) -> str:
    """
    解析策略配置之前的日志级别，优先级：CLI 参数 > LOG_LEVEL 环境变量 > 默认 INFO

    manager（run_strategies_manager.py）通过 LOG_LEVEL 环境变量而非命令行
    透传日志级别（build_strategy_command 拼出的命令不带 --log-level）：
    直接运行 run_strategy.py 时读 --log-level，由 manager 拉起时读环境变量。

    Args:
        cli_log_level: --log-level 传入的值（未指定为 None）
        env_log_level: LOG_LEVEL 环境变量值（未设置为 None）

    Returns:
        日志级别字符串（DEBUG/INFO/WARNING/ERROR），非法值回退 INFO
    """
    name = (cli_log_level or env_log_level or "INFO").upper()
    return name if hasattr(logging, name) else "INFO"


def _read_interval_from_overrides(overrides_section: Dict[str, Any]) -> Optional[str]:
    """从 overrides 段读取主周期（timeframes[0]）

    与 StrategiesLoader._load_overrides_fields 的读取逻辑保持一致。

    Args:
        overrides_section: overrides 配置中 <strategy_name> 段的内容

    Returns:
        主周期字符串（如 "4h"），未配置返回 None
    """
    timeframes = overrides_section.get("timeframes", [])
    if timeframes:
        return str(timeframes[0])
    return None


class StrategyProcessRunner:
    """
    策略进程运行器（单体模式）

    封装单个策略进程的全部生命周期：
    - DataManager（策略专属 CSV 路径）
    - 策略实例（直接加载 strategies/<dir>/strategy.py，不经注册表/引擎）
    - SignalLogger（信号存储 + 交易所直连下单）
    - CSV Writer（独立写入路径）
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
            strategy_name: 策略名称（标准化名称）
            strategy_config: 策略配置字典
            global_config_path: 全局配置路径
            trading_mode: 运行模式 (live / paper_trading / smoking)
            strategy_dir: 策略目录名
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
        # 单体模式：直连 Binance（公共 WS 实时 + fapi 历史），无需外部行情服务
        dm_global_config = self.global_config.get("data_manager", {})
        dm_config = DataManagerConfig(
            csv_dir=str(strategy_data_dir),
            cache_max_size=dm_global_config.get("cache_max_size", 10000),
            realtime_enabled=dm_global_config.get("realtime_enabled", True),
        )
        self.data_manager = DataManager(dm_config)

        # 初始化 SignalLogger（独立实例）
        signal_config = self.global_config.get("signal_logging", {})
        storage_path = signal_config.get("storage", {}).get("path", "data/signals")
        storage = SignalStorage(base_dir=storage_path)

        # 信号出口：存储（CSV）后由本进程直连交易所下单
        direct_trader = self._build_direct_trader()

        self.signal_logger = SignalLogger(
            storage,
            direct_trader=direct_trader,
        )
        self.csv_writer = SignalCsvWriter()

        # 策略实例（start() 时加载）
        self.strategy = None
        self._strategy_started = False

        # 仓位文件路径
        self._position_file_name = position_file_name or strategy_name

        # 运行状态
        self._running = False

    def _load_global_config(self, config_path: str) -> Dict[str, Any]:
        """加载全局 settings.yaml，并解析 ${VAR} 占位符为环境变量值"""
        path = Path(config_path)
        if not path.exists():
            logging.warning(f"全局配置文件不存在：{config_path}，使用空配置")
            return {}
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return _resolve_env_placeholders(raw)

    def _build_direct_trader(self):
        """按 direct_trading 配置构建直连下单执行器，未启用时返回 None

        凭证只从环境变量（.env）读，配置文件里不出现 key。
        缺凭证时 BinanceTrader 会抛 BinanceCredentialsError，此处不捕获——
        开着直连却下不了单必须让进程起不来，否则策略会在"以为已成交"的状态下继续跑。
        """
        direct_config = self.global_config.get("direct_trading", {}) or {}
        if not direct_config.get("enabled", False):
            return None

        # 只有 paper_trading 不下真单。live 与 smoking 都会真实成交 ——
        # smoking（冒烟）的设计意图就是用真单验证全链路，故不在此拦截。
        if self._paper_trading_mode:
            logging.warning(
                f"[{self.strategy_name}] direct_trading 已启用但当前为 paper_trading 模式，"
                f"不会向交易所下单"
            )
            return None

        exchange = str(direct_config.get("exchange", "binance")).lower()
        if exchange != "binance":
            raise ValueError(
                f"direct_trading.exchange 仅支持 binance，当前配置：{exchange}"
            )

        from strategy_core.signal_logging.binance_trader import (
            BinanceTrader,
            BinanceTraderConfig,
        )

        trader_config = BinanceTraderConfig(
            testnet=bool(direct_config.get("testnet", False)),
            recv_window=int(direct_config.get("recv_window", 5000)),
            timeout=float(direct_config.get("timeout", 10.0)),
            max_retries=int(direct_config.get("max_retries", 2)),
        )
        trader = BinanceTrader(trader_config)
        logging.info(
            f"[{self.strategy_name}] 直连下单已启用 (exchange=binance, "
            f"testnet={trader_config.testnet})，信号不再经 HTTP 推送"
        )
        return trader

    def load_strategy(self) -> bool:
        """
        加载指定策略（直接实例化，不扫描其他策略目录）

        Returns:
            是否加载成功
        """
        module_path = f"strategies.{self._strategy_dir}.strategy"
        try:
            module = importlib.import_module(module_path)
        except Exception as e:
            logging.error(f"[{self.strategy_name}] 导入策略模块失败 {module_path}: {e}")
            return False

        strategy_class = getattr(module, "Strategy", None)
        if strategy_class is None:
            logging.error(
                f"[{self.strategy_name}] 策略类 'Strategy' 未在模块 {module_path} 中找到"
            )
            return False

        try:
            self.strategy = strategy_class(
                data_manager=self.data_manager,
                config=self.strategy_config,
                strategy_name=self.strategy_name,
                trading_mode=self.trading_mode,
            )
        except Exception as e:
            logging.error(f"[{self.strategy_name}] 策略加载失败: {e}", exc_info=True)
            return False

        logging.info(
            f"[{self.strategy_name}] 策略 {self.strategy_name} 加载成功 (mode={self.trading_mode})"
        )
        return True

    async def connect_data_manager(self) -> bool:
        """连接 DataManager（加载 CSV 数据到缓存）"""
        return self.data_manager.connect()

    def _collect_subscribed_symbols(self) -> set:
        """收集当前策略订阅的所有 symbols"""
        inst = self.strategy
        if inst is None:
            return set()
        subs = getattr(inst, "subscribed_symbols", None)
        if subs:
            return set(subs)
        sym = getattr(inst, "symbol", None)
        if sym:
            return {sym}
        return set(getattr(inst, "symbols", []) or [])

    def _resolve_history_days(self, configured_days: int) -> int:
        """取 settings.yaml 配置值与策略自述所需天数的较大值。

        sync_history_days 是个与周期无关的固定值（默认 365），但所需天数
        随周期线性增长。实测：30 天对 8h 只有 90 根、对 1d 只有 30 根，
        均低于 ADX 的 100 根阈值。而指标层遇到数据不足只 `warnings.warn`
        不阻断，冷启动后策略会拿着不准确的 ADX 直接发信号 —— 无异常、
        无中断，只有一行 UserWarning，很难在实盘中被发现。

        取较大值而非直接覆盖：配置值仍可用于**上调**（例如策略只要 21 天
        但运维想多备一些），只是不再允许它把数据压到指标算不准的程度。
        """
        required = 0
        inst = self.strategy
        if inst is not None:
            calc = getattr(inst, "_calc_required_history_days", None)
            if callable(calc):
                try:
                    required = max(required, int(calc()))
                except Exception as e:
                    logging.warning(
                        f"[{self.strategy_name}] 计算所需历史天数失败，"
                        f"沿用配置值 {configured_days}: {e}"
                    )

        if required > configured_days:
            logging.info(
                f"[{self.strategy_name}] 历史数据天数 {configured_days} → "
                f"{required}（策略指标预热需要，避免 ADX 等指标算不准）"
            )
            return required
        return configured_days

    async def _load_historical_data(self, days: int) -> None:
        """
        加载历史数据 + 恢复大周期缓存

        Args:
            days: 补齐历史数据的天数上限（来自 settings.yaml data_manager.sync_history_days）

        复用已有方法:
        1. load_history — 加载 1m CSV 到缓存
        2. _preload_all_big_intervals_from_csv — 恢复已有大周期 CSV 到缓存
        3. sync_to_latest — 补齐缺失的历史数据
        4. _preload_big_intervals_to_cache — 聚合大周期到内存
        """
        symbols = self._collect_subscribed_symbols()
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

    def _handle_signal(self, signal: Any) -> None:
        """
        统一信号处理：写 CSV，再由 SignalLogger 直连下单

        策略只返回 Signal 对象，进程负责统一存储：
        1. 统一生成 CtaSignalCSV 对象（确保数据一致）
        2. SignalCsvWriter 写入 CSV
        3. CSV 成功后 SignalLogger 直连下单

        Args:
            signal: Signal 对象
        """
        cfg = self.strategy_config or {}
        params = build_signal_params(cfg)

        # 使用 signal.strategy_id 作为策略名称（完整策略实例名，如 ICT_1D_3_BNBUSDT_LIVE）
        # 用于 CSV 文件路径，与 history_positions 目录结构一致
        strategy_full_name = signal.strategy_id or ""

        # 从策略实例获取 trading_mode
        trading_mode = getattr(self.strategy, "_trading_mode", "live")

        # 获取调整后的资金（优先使用 metadata，否则使用配置）
        adjusted_cash = signal.metadata.get("adjusted_cash", params.get("strategy_cash", 100))

        cta_params = {
            "strategy_name": strategy_full_name,
            "strategy_version": params.get("strategy_version", cfg.get("version", "v1")),
            "interval": params.get("strategy_internal", ""),
            "strategy_params": dict(cfg.get("params", {}) or {}),
            "strategy_cash": adjusted_cash,
            "strategy_parts": params.get("strategy_parts", 1),
            "strategy_valid_before": params.get(
                "strategy_valid_before", cfg.get("valid_before", "2030-12-31 08:00:00")
            ),
            "strategy_type": params.get("strategy_type", "CTAFutureFactory"),
            "strategy_type_name": params.get("strategy_type_name", ""),
            "risk_strategy_type": params.get("risk_strategy_type", "cta_intraday"),
            "user_id": params.get("user_id", 1),
            "signal_exchange": params.get("signal_exchange", "binance"),
            "signal_order_type": params.get("signal_order_type", 1),
            "signal_slippage": params.get("signal_slippage", 0),
            "pos_type": params.get("pos_type", 2),
            "leverage": params.get("leverage", 5),
            "risk_stop_loss_pct": params.get("StopLossThreshold", DEFAULT_STOP_LOSS_PCT),
            "risk_trailing_profit_activation": params.get(
                "TakeProfitBackThreshold", DEFAULT_TRAILING_PROFIT_ACTIVATION
            ),
            "risk_trailing_profit_drawdown": params.get(
                "TakeProfitBackDynamicFallPercent", DEFAULT_TRAILING_PROFIT_DRAWDOWN
            ),
            "trading_mode": trading_mode,
        }

        # 1. 统一生成 CtaSignalCSV 对象
        try:
            cta_signal = CtaSignalCSV.from_signal(signal, **cta_params)
        except Exception as e:
            logging.error(f"[{self.strategy_name}] 信号数据生成失败: {e}")
            return

        # 2. 写入 CSV
        csv_ok = True
        if self.csv_writer:
            try:
                csv_ok = self.csv_writer.write_cta_signal(cta_signal)
            except Exception as e:
                logging.error(f"[{self.strategy_name}] CSV 写入失败: {e}")
                csv_ok = False

        # 3. 直连下单（CSV 失败时跳过，避免数据不一致）
        if csv_ok:
            try:
                self.signal_logger.log_cta_signal(cta_signal)
            except Exception as e:
                logging.error(f"[{self.strategy_name}] 直连下单失败: {e}")

    def _on_kline(self, kline: Any) -> None:
        """
        WS K 线回调：分发给策略实例，产生的信号统一落盘/下单

        Args:
            kline: Kline 对象
        """
        if not self._running or self.strategy is None or not self._strategy_started:
            return

        # 按 symbol 过滤：只处理本策略订阅的 symbol
        kline_symbol = kline.symbol.upper() if hasattr(kline, "symbol") else None
        subs = self._collect_subscribed_symbols()
        if kline_symbol and subs and kline_symbol not in subs:
            return

        try:
            signal = self.strategy.on_kline(kline)
            # 如果生成信号，统一存储 CSV + 下单
            if signal:
                self._handle_signal(signal)
        except Exception as e:
            logging.error(f"[{self.strategy_name}] 处理 K 线更新失败：{e}")

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

        # 加载历史数据 —— 必须在 on_start() 之前，
        # 因为策略 on_start() 需要从缓存中读取 K 线数据初始化
        # 天数取 settings.yaml 的 sync_history_days 与策略
        # _calc_required_history_days() 的较大值（见 _resolve_history_days）
        dm_global_config = self.global_config.get("data_manager", {})
        configured_days = dm_global_config.get("sync_history_days", 365)
        history_days = self._resolve_history_days(configured_days)
        await self._load_historical_data(days=history_days)

        # 启动策略（on_start 失败不中止进程：实例保留但不再分发 K 线，
        # 与原引擎的 ERROR 状态语义一致）
        try:
            self.strategy.on_start()
            self._strategy_started = True
            logging.info(f"[{self.strategy_name}] 策略已启动")
        except Exception as e:
            logging.error(f"[{self.strategy_name}] 策略启动失败: {e}", exc_info=True)

        # 注册 WS K 线分发回调
        self.data_manager.set_kline_dispatch_callback(self._on_kline)

        self._running = True
        return True

    async def stop(self) -> None:
        """停止策略进程"""
        logging.info(f"[{self.strategy_name}] 策略进程停止")
        self._running = False

        if self.strategy:
            try:
                self.strategy.on_stop()
            except Exception as e:
                logging.error(f"[{self.strategy_name}] 策略停止失败: {e}", exc_info=True)

        if self.data_manager:
            await self.data_manager.close()

    async def run_ws_driven(self) -> None:
        """
        运行 WS 驱动的策略进程

        WS 回调中直接调用 self._on_kline(kline)，
        替代 CSV 轮询机制。
        """
        if not self._running:
            await self.start()

        # 收集策略订阅的 symbols
        symbols = self._collect_subscribed_symbols()

        if symbols:
            logging.info(f"[{self.strategy_name}] 订阅实时行情 symbols: {symbols}")

        # 启动实时数据（Binance 公共 WS，REST 轮询回退）
        if symbols:
            ws_ok = await self.data_manager.start_realtime_async(list(symbols))
            if not ws_ok:
                logging.warning(f"[{self.strategy_name}] 实时行情不可用，降级到 CSV 模式")

        # 启动定时维护（1m 缓存落盘 + 按配置裁剪，防止内存无界增长）
        try:
            self.data_manager.start_periodic_persistence()
        except Exception as e:
            logging.warning(
                f"[{self.strategy_name}] 定时维护启动失败: {e}", exc_info=True,
            )

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

    # 新格式参数（--interval/--version/--trading-mode 可选，缺失时从 overrides 补全）
    parser.add_argument(
        "--name",
        default=None,
        help="策略目录名 (如 sar_snt3_v3)，必填（新格式）",
    )
    parser.add_argument(
        "--symbol",
        default=None,
        help="交易对 (如 BTCUSDT)，必填（新格式）",
    )
    parser.add_argument(
        "--interval",
        default=None,
        help="主周期 (如 4h)，可选；缺失时从 overrides 的 timeframes[0] 读取",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="版本号 (如 v2 / 3)，可选；缺失时从 overrides 的 version 读取",
    )
    parser.add_argument(
        "--trading-mode",
        choices=["live", "paper_trading", "smoking"],
        default=None,
        help="运行模式，可选；缺失时从 overrides 的 trading_mode 读取，默认 live",
    )
    parser.add_argument(
        "--config-path",
        default=None,
        help="策略配置文件完整路径 (优先级最高，覆盖默认 overrides 路径)",
    )

    # 通用参数
    parser.add_argument(
        "--global-config",
        default="config/settings.yaml",
        help="全局配置文件路径 (默认: config/settings.yaml)",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别（未指定时读 LOG_LEVEL 环境变量，再默认 INFO）",
    )

    args = parser.parse_args()

    # manager 用 LOG_LEVEL 环境变量透传 --log-level（run_strategies_manager.py 的
    # build_strategy_command 不在子进程命令行带 --log-level）；直接运行本脚本时走 CLI
    env_log_level = os.environ.get("LOG_LEVEL")
    early_log_level_name = resolve_effective_log_level(args.log_level, env_log_level)
    # 尽早配置日志，确保后续所有日志输出都能正确写入
    early_log_level = getattr(logging, early_log_level_name, logging.INFO)
    logging.basicConfig(
        level=early_log_level,
        format="%(asctime)s - [early] - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler()],
    )

    # 新格式：--name + --symbol 必填；--interval/--version/--trading-mode 缺失时从 overrides 补全
    if not (args.name and args.symbol):
        logging.error("必须指定 --name 和 --symbol")
        sys.exit(1)

    strategy_dir = args.name

    # 定位 overrides 配置文件路径（--config-path 优先，否则默认 strategies/<name>/overrides/<symbol>.yaml）
    if args.config_path:
        config_path = Path(args.config_path)
    else:
        config_path = Path("strategies") / args.name / "overrides" / f"{args.symbol}.yaml"

    # 读取 overrides 配置（用于补全 interval/version/trading_mode + 策略参数）
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            full_config = yaml.safe_load(f) or {}
        overrides_section = full_config.get(args.name, {})
        logging.info(f"加载配置文件: {config_path}")
    else:
        logging.warning(f"配置文件不存在: {config_path}，使用空配置")
        overrides_section = {}

    # 补全 interval/version/trading_mode：CLI > overrides > 默认值
    interval = args.interval or _read_interval_from_overrides(overrides_section) or "4h"
    version = args.version or str(overrides_section.get("version", "2"))
    trading_mode = args.trading_mode or overrides_section.get("trading_mode", "live")

    logging.info(
        f"参数来源: interval={interval}{'(CLI)' if args.interval else '(overrides)'}, "
        f"version={version}{'(CLI)' if args.version else '(overrides)'}, "
        f"trading_mode={trading_mode}{'(CLI)' if args.trading_mode else '(overrides)'}"
    )

    # 生成标准化 strategy_name（包含 trading_mode）
    strategy_name = build_strategy_id_from_overrides(
        args.name, args.symbol, trading_mode,
        interval=interval, version=version,
    )

    strategy_config = overrides_section
    # 覆盖 symbol
    strategy_config["symbols"] = [args.symbol]

    # 确定日志级别：策略配置优先，CLI/LOG_LEVEL 环境变量其次，默认 INFO
    log_level_str = resolve_log_level(args.log_level or env_log_level, strategy_config)
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
    elif env_log_level:
        logging.info(f"日志级别: {log_level_str}（来自环境变量 LOG_LEVEL）")
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

    # 注册 SIGTERM 信号处理器，确保停止时触发 on_stop()
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
