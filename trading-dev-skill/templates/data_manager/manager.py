#!/usr/bin/env python3
"""
Data Manager - 数据管理器核心实现

提供 5 个核心方法：
1. download_daily_data(symbol, day) — 下载单日数据并保存 CSV
2. batch_download_history(symbol, days=30) — 批量下载历史 N 天
3. init_today_realtime(symbol) — 下载今天数据 + 补齐 gap + 开启 WS
4. manage_memory_cache(symbol) — 内存管理：保留近 2 天数据
5. get_klines(symbol, timeframe, limit) — 统一对外接口（增量返回）
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
import aiohttp

from data_manager.kline_repository import KlineRepository
from data_manager.klines_data import Kline as KlineFull
from data_manager.klines_ws_client import KlinesWebSocketClient
from data_manager.indicators import compute_indicator, get_available_indicators

logger = logging.getLogger(__name__)

# Kline 别名，保持向后兼容
Kline = KlineFull


@dataclass
class DataManagerConfig:
    """数据管理器配置"""
    csv_dir: str = "./data/klines"
    csv_filename_pattern: str = "{symbol}_{timeframe}.csv"
    cache_max_size: int = 5000
    preload_1m_enabled: bool = True
    preload_days: int = 7
    cache_1m_max_rows: int = 500000
    cache_1m_max_age_days: int = 90

    # klines_service 集成配置
    klines_service_enabled: bool = True
    klines_service_ws_url: str = "ws://127.0.0.1:17081/ws/klines"
    klines_service_http_url: str = "http://127.0.0.1:17081"
    klines_service_history_days: int = 7

    # Kafka 集成配置 (新增)
    kafka_enabled: bool = False
    kafka_brokers: List[str] = None  # type: ignore
    kafka_topic: str = "biance_klines"
    kafka_group_id: Optional[str] = None  # None 时自动生成

    # 启动时自动同步配置
    sync_history_days: int = 30  # 启动时补齐历史天数
    auto_sync_on_connect: bool = True  # 是否启动时自动同步

    # 定时持久化配置
    persistence_interval_minutes: int = 5  # 缓存刷到 CSV 的间隔时间

    # 回测模式：禁用增量返回，每次调用返回完整数据
    backtest_mode: bool = False

    def __post_init__(self):
        """初始化后处理"""
        if self.kafka_brokers is None:
            object.__setattr__(self, 'kafka_brokers', [])

    @classmethod
    def from_env(cls, **kwargs) -> "DataManagerConfig":
        """
        从环境变量创建配置，支持覆盖

        环境变量:
        - KLINES_WS_URL: WebSocket URL
        - KLINES_HTTP_URL: HTTP URL

        Args:
            **kwargs: 直接传入的参数，优先级最高

        Returns:
            DataManagerConfig 实例
        """
        # 环境变量覆盖
        ws_url = os.environ.get("KLINES_WS_URL", cls.__dataclass_fields__["klines_service_ws_url"].default)
        http_url = os.environ.get("KLINES_HTTP_URL", cls.__dataclass_fields__["klines_service_http_url"].default)

        # 合并参数：kwargs > env > default
        config_kwargs = {
            "klines_service_ws_url": ws_url,
            "klines_service_http_url": http_url,
        }
        config_kwargs.update(kwargs)

        return cls(**config_kwargs)


class DataCache:
    """
    分层缓存设计:
    - 1m K 线：常驻内存（除非显式清除）
    - 大周期（15m/1h/4h）：LRU 淘汰
    """

    def __init__(self, max_size: int = 5000, preload_1m: bool = False,
                 config: Optional[DataManagerConfig] = None):
        self.max_size = max_size
        self.preload_1m = preload_1m
        self.config = config
        self._1m_cache: Dict[str, pd.DataFrame] = {}
        self._big_interval_cache: Dict[str, pd.DataFrame] = {}
        self._access_order: List[str] = []

    def _make_key(self, symbol: str, interval: str) -> str:
        return f"{symbol}_{interval}".upper()

    def _is_1m_interval(self, interval: str) -> bool:
        return interval.lower() == "1m"

    def get(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        """获取缓存数据"""
        symbol_upper = symbol.upper()
        if self._is_1m_interval(interval):
            return self._1m_cache.get(symbol_upper)

        key = self._make_key(symbol, interval)
        if key in self._big_interval_cache:
            if key in self._access_order:
                self._access_order.remove(key)
            self._access_order.append(key)
            return self._big_interval_cache[key]
        return None

    def put(self, symbol: str, interval: str, df: pd.DataFrame, force_1m: bool = False):
        """存入缓存"""
        symbol_upper = symbol.upper()
        if self._is_1m_interval(interval) or force_1m:
            self._1m_cache[symbol_upper] = df
            return

        key = self._make_key(symbol, interval)
        if key in self._big_interval_cache:
            self._access_order.remove(key)
        elif len(self._big_interval_cache) >= self.max_size:
            oldest = self._access_order.pop(0)
            del self._big_interval_cache[oldest]

        self._big_interval_cache[key] = df
        self._access_order.append(key)

    def get_1m_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """获取 1m 缓存数据"""
        return self._1m_cache.get(symbol.upper())

    def preload_1m_data(self, data_dict: Dict[str, pd.DataFrame]):
        """批量预加载 1m 数据"""
        for symbol, df in data_dict.items():
            self._1m_cache[symbol.upper()] = df

    def clear(self):
        """清空所有缓存"""
        self._1m_cache.clear()
        self._big_interval_cache.clear()
        self._access_order.clear()

    def remove(self, symbol: str, interval: str):
        """移除指定缓存"""
        symbol_upper = symbol.upper()
        if self._is_1m_interval(interval):
            self._1m_cache.pop(symbol_upper, None)
        else:
            key = self._make_key(symbol, interval)
            self._big_interval_cache.pop(key, None)
            if key in self._access_order:
                self._access_order.remove(key)

    def get_status(self) -> Dict[str, Any]:
        """获取缓存状态"""
        return {
            '1m_cache_symbols': list(self._1m_cache.keys()),
            '1m_cache_sizes': {s: len(df) for s, df in self._1m_cache.items()},
            'big_interval_cache_keys': list(self._big_interval_cache.keys()),
            'big_interval_cache_sizes': {
                k: len(df) for k, df in self._big_interval_cache.items()
            },
            'max_size': self.max_size,
        }


class DataManager:
    """
    数据管理器 — 5 个核心方法：
    1. download_daily_data — 下载单日数据
    2. batch_download_history — 批量下载历史
    3. init_today_realtime — 初始化今天实时数据
    4. manage_memory_cache — 管理内存缓存
    5. get_klines — 统一对外接口
    """

    # WebSocket 重连策略：每分钟重试，无限重连
    WS_RECONNECT_DELAY = 60.0
    WS_MAX_RECONNECT = 0  # 0 表示无限重试
    WS_MAX_BACKOFF = 60.0

    def __init__(self, config: Optional[DataManagerConfig] = None):
        self.config = config or DataManagerConfig()
        self.csv_dir = Path(self.config.csv_dir)
        self.cache = DataCache(
            max_size=self.config.cache_max_size,
            preload_1m=self.config.preload_1m_enabled,
            config=self.config,
        )
        self._connected = False
        self._last_kline_timestamp: Dict[str, datetime] = {}

        # 回测模式下跟踪当前 bar 时间戳
        self._current_backtest_timestamp: Optional[datetime] = None

        # K 线仓库
        self.kline_repo: Optional[KlineRepository] = None

        # asyncio 锁
        self._lock: Optional[asyncio.Lock] = None

        # WebSocket 客户端
        self._ws_client: Optional[KlinesWebSocketClient] = None
        self._ws_subscribed_symbols: set = set()
        self._ws_buffer: Dict[str, List[Dict[str, Any]]] = {}
        self._ws_buffer_size = 10
        self._last_api_fill_cache_ts: Dict[str, datetime] = {}

        # Kafka 消费者 (新增)
        self._kafka_consumer: Optional[Any] = None  # KlineKafkaConsumer
        self._kafka_enabled = False

        # Kline dispatch callback — 当 WS 收到新 K 线时通知策略引擎
        self._kline_dispatch_callback: Optional[Any] = None

        # 后台任务
        self._background_tasks: List[asyncio.Task] = []

        self.csv_dir.mkdir(parents=True, exist_ok=True)

    @property
    def lock(self) -> asyncio.Lock:
        if self._lock is None:
            self._lock = asyncio.Lock()
        return self._lock

    def enable_kline_repository(self):
        """启用 K 线仓库功能"""
        if self.kline_repo is None:
            self.kline_repo = KlineRepository(csv_dir=str(self.csv_dir))
            logger.info("KlineRepository 已启用")

    def _parse_interval_to_minutes(self, interval: str) -> int:
        """解析时间周期为分钟数"""
        interval = interval.lower()
        if interval.endswith("m"):
            try:
                return int(interval[:-1])
            except ValueError:
                return 1
        elif interval.endswith("h"):
            try:
                return int(interval[:-1]) * 60
            except ValueError:
                return 60
        elif interval.endswith("d"):
            try:
                return int(interval[:-1]) * 1440
            except ValueError:
                return 1440
        return 1

    def aggregate_1m_to_interval(
        self, df_1m: pd.DataFrame, target_interval: str
    ) -> pd.DataFrame:
        """从 1m 数据聚合生成目标周期"""
        if df_1m is None or df_1m.empty:
            return pd.DataFrame()

        from data_manager.klines_loader import resample_ohlcv
        return resample_ohlcv(df_1m, target_interval, datetime_column="timestamp")

    def register_timeframes_for_symbol(self, symbol: str, timeframes: List[str]):
        """注册策略需要的时间框架"""
        if self.kline_repo:
            self.kline_repo.register_symbol(symbol, timeframes)
            logger.info(f"{symbol} 注册时间框架到 KlineRepository: {timeframes}")
            # 注册后立即聚合到内存
            self._preload_big_intervals_to_cache(symbol.upper())

    def register_timeframes(self, symbol: str, timeframes: List[str]):
        """兼容别名，转发到 register_timeframes_for_symbol"""
        self.register_timeframes_for_symbol(symbol, timeframes)

    def _preload_all_big_intervals_from_csv(self, symbol: str):
        """
        从 CSV 加载指定 symbol 的所有大周期数据到缓存

        扫描 kline_repo 中注册的大周期时间框架，将已有 CSV 文件加载到缓存。
        用于 DataManager 初始化时恢复大周期数据，避免冷启动。

        Args:
            symbol: 交易对
        """
        if not self.kline_repo:
            return

        state = self.kline_repo._states.get(symbol.upper())
        if state is None:
            return

        big_intervals = [tf for tf in state.registered_timeframes if tf.lower() != "1m"]
        for interval in big_intervals:
            df = self._load_csv(symbol.upper(), interval)
            if df is not None and not df.empty:
                self.cache.put(symbol.upper(), interval, df)
                logger.info(
                    f"{symbol.upper()} {interval}: 从 CSV 加载 {len(df)} 条到缓存"
                )

    def _merge_kline_data(
        self, existing: pd.DataFrame, new_data: pd.DataFrame
    ) -> pd.DataFrame:
        """
        合并 K 线数据：去重并保持时间顺序

        Args:
            existing: 已有数据
            new_data: 新数据（可能包含更新）

        Returns:
            合并后的数据（已排序，无重复）
        """
        combined = pd.concat([existing, new_data], ignore_index=True)
        combined = combined.drop_duplicates(subset=['timestamp'], keep='last')
        return combined.sort_values('timestamp').reset_index(drop=True)

    def _preload_big_intervals_to_cache(self, symbol: str):
        """将指定 symbol 的大周期数据聚合到内存缓存"""
        if not self.kline_repo:
            return

        state = self.kline_repo._states.get(symbol)
        if state is None:
            return

        big_intervals = [tf for tf in state.registered_timeframes if tf.lower() != "1m"]
        if not big_intervals:
            return

        df_1m = self.cache.get_1m_data(symbol)
        if df_1m is None or df_1m.empty:
            return

        for interval in big_intervals:
            df = self.aggregate_1m_to_interval(df_1m, interval)
            if df is None or df.empty:
                continue

            existing = self.cache.get(symbol, interval)
            if existing is not None and not existing.empty:
                combined = self._merge_kline_data(existing, df)
                self.cache.put(symbol, interval, combined)
                logger.info(f"{symbol} {interval}: 合并聚合 {len(df)} 条 → 共 {len(combined)} 条")
            else:
                self.cache.put(symbol, interval, df)
                logger.info(f"{symbol} {interval}: 聚合 {len(df)} 条到内存")

        logger.info(f"{symbol}: 大周期已聚合到内存: {big_intervals}")

    def auto_load_missing_data(
        self, symbol: str, intervals: List[str],
        days: int = 7, exchange: str = "binance",
        instrument_type: str = "um"
    ) -> Dict[str, bool]:
        """
        兼容旧版同步方法：自动检测并加载缺失数据

        策略在 on_start() 中同步调用此方法。
        内部使用 asyncio.run() 调用异步下载流程。

        Args:
            symbol: 交易对名称
            intervals: 需要检查的 K 线周期列表
            days: 加载最近 N 天的数据
            exchange: 交易所（binance, okx）— 兼容参数，当前仅使用 klines_service API
            instrument_type: 交易类型（um=合约，spot=现货）— 兼容参数

        Returns:
            加载结果字典 {interval: 是否成功}
        """
        # 获取已有事件循环（避免 "no running event loop" 错误）
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        async def _do_load():
            return await self._auto_load_missing_data_async(
                symbol, intervals, days
            )

        if loop and loop.is_running():
            # 已有运行中的事件循环（策略在 async 上下文中调用）
            # 创建 task 但无法在此同步等待，返回占位结果
            logger.warning(
                f"{symbol}: auto_load_missing_data 在运行中的事件循环中被同步调用，"
                f"数据应由 connect_and_sync 提前补齐"
            )
            return {interval: True for interval in intervals}
        else:
            return asyncio.run(_do_load())

    async def _auto_load_missing_data_async(
        self, symbol: str, intervals: List[str], days: int
    ) -> Dict[str, bool]:
        """
        auto_load_missing_data 的异步实现

        流程：
        1. 检查 CSV 是否存在，存在则直接返回成功
        2. 调用 batch_download_history 补齐历史
        3. 调用 init_today_realtime 补齐今天
        4. 从 1m 缓存聚合大周期到 CSV
        """
        symbol_upper = symbol.upper()
        results: Dict[str, bool] = {}

        # 检查 1m CSV 是否存在
        csv_1m = self.csv_dir / "1m" / f"{symbol_upper}_1m.csv"
        if not csv_1m.exists():
            # 下载历史 + 今天
            batch_result = await self.batch_download_history(symbol_upper, days=days)
            success_count = sum(1 for v in batch_result.values() if v)
            if success_count == 0:
                logger.warning(f"{symbol_upper}: 1m 数据下载全部失败")
                return {interval: False for interval in intervals}
            await self.init_today_realtime(symbol_upper)

        # 确保 1m 数据加载到缓存
        if self.cache.get_1m_data(symbol_upper) is None:
            df = self._load_csv(symbol_upper, "1m")
            if df is not None:
                self.cache.put(symbol_upper, "1m", df, force_1m=True)

        # 对每个 interval 生成 CSV
        for interval in intervals:
            if interval == "1m":
                results[interval] = csv_1m.exists() or self.cache.get_1m_data(symbol_upper) is not None
                continue

            # 大周期：从 1m 聚合保存到 CSV
            csv_path = self.csv_dir / interval / f"{symbol_upper}_{interval}.csv"
            if csv_path.exists():
                results[interval] = True
                continue

            df_1m = self.cache.get_1m_data(symbol_upper)
            if df_1m is not None and not df_1m.empty:
                df_agg = self.aggregate_1m_to_interval(df_1m, interval)
                if df_agg is not None and not df_agg.empty:
                    if self.kline_repo:
                        kline_dicts = []
                        for _, row in df_agg.iterrows():
                            kline_dicts.append(row.to_dict())
                        self.kline_repo.save_klines_to_csv(
                            symbol_upper, interval, kline_dicts
                        )
                    results[interval] = True
                    logger.info(f"{symbol_upper} {interval}: 从 1m 聚合生成 {len(df_agg)} 条")
                else:
                    results[interval] = False
            else:
                results[interval] = False

        return results

    async def close(self):
        """关闭连接，清空缓存，断开 WS，停止后台任务"""
        # 停止定时持久化任务
        for task in self._background_tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._background_tasks.clear()

        for symbol in list(self._ws_buffer.keys()):
            buf = self._ws_buffer.pop(symbol, [])
            if buf and self.kline_repo and not self.config.backtest_mode:
                self.kline_repo.save_klines_to_csv(symbol, '1m', buf)

        if self._ws_client:
            try:
                await self._ws_client.disconnect()
            except Exception as e:
                logger.warning(f"断开 WS 连接异常：{e}")
            self._ws_client = None
            self._ws_subscribed_symbols.clear()

        self.cache.clear()
        self._connected = False
        logger.info("数据管理器已关闭")

    def connect(self) -> bool:
        """连接到数据源"""
        if self.csv_dir.exists():
            self._connected = True
            if self.kline_repo is None:
                self.kline_repo = KlineRepository(csv_dir=str(self.csv_dir))
            logger.info(f"数据管理器连接成功：{self.csv_dir}")
            return True
        else:
            logger.warning(f"数据目录不存在：{self.csv_dir}")
            self._connected = False
            return False

    def _get_last_csv_timestamp(self, symbol: str) -> Optional[datetime]:
        """
        获取 CSV 文件中最后一条数据的时间戳

        Args:
            symbol: 交易对

        Returns:
            最后一条数据的时间戳，无数据时返回 None
        """
        symbol_upper = symbol.upper()

        # 优先从缓存读取
        cached = self.cache.get_1m_data(symbol_upper)
        if cached is not None and not cached.empty and 'timestamp' in cached.columns:
            ts = cached['timestamp'].iloc[-1]
            if hasattr(ts, 'to_pydatetime'):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts

        # 缓存无数据，从 CSV 文件加载
        csv_path = self.csv_dir / "1m" / f"{symbol_upper}_1m.csv"
        if not csv_path.exists():
            return None

        try:
            # 只读最后一行，避免加载大文件
            df = pd.read_csv(csv_path, nrows=0)  # 只读列名
            if 'timestamp' not in df.columns:
                return None

            # 读取最后 5 行
            tail = pd.read_csv(csv_path, nrows=5)
            if tail.empty:
                return None

            ts = pd.to_datetime(tail['timestamp'].iloc[-1], utc=True)
            if hasattr(ts, 'to_pydatetime'):
                ts = ts.to_pydatetime()
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            return ts
        except Exception as e:
            logger.warning(f"读取 CSV 最后时间戳失败 {csv_path}: {e}")
            return None

    async def connect_and_sync(
        self,
        symbols: List[str],
        history_days: int = 30,
    ) -> Dict[str, bool]:
        """
        启动时数据同步流程：
        1. connect() — 连接数据源
        2. 从 CSV 加载已有数据到缓存
        3. 检测每个 symbol 最后一条数据的时间，计算缺失天数
        4. 调用 batch_download_history 补齐缺失的历史数据
        5. 调用 init_today_realtime 补齐今天数据 + 开启 WS

        Args:
            symbols: 需要同步的 symbol 列表
            history_days: 补齐历史天数上限（默认 30 天）

        Returns:
            {symbol: 是否成功}
        """
        # 1. 连接数据源
        if not self.connect():
            logger.error("数据源连接失败")
            return {s: False for s in symbols}

        results: Dict[str, bool] = {}
        now = datetime.now(timezone.utc)

        for symbol in symbols:
            symbol_upper = symbol.upper()
            logger.info(f"开始同步 {symbol_upper} 数据...")

            # 2. 从 CSV 加载到缓存
            df = self._load_csv(symbol_upper, "1m")
            if df is not None and not df.empty:
                self.cache.put(symbol_upper, "1m", df, force_1m=True)
                logger.info(f"{symbol_upper}: 从 CSV 加载 {len(df)} 条数据")

            # 3. 检测缺失天数
            last_ts = self._get_last_csv_timestamp(symbol_upper)
            if last_ts is None:
                # 无本地数据，需要下载完整历史
                missing_days = history_days
                logger.info(f"{symbol_upper}: 本地无数据，需要下载 {missing_days} 天历史")
            else:
                gap_seconds = (now - last_ts).total_seconds()
                missing_days = int(gap_seconds / 86400) + 1  # 向上取整
                if missing_days <= 0:
                    logger.info(f"{symbol_upper}: 数据完整，最后数据距今 {gap_seconds/60:.0f} 分钟")
                    results[symbol] = True
                    continue
                # 限制最大补齐天数
                if missing_days > history_days:
                    logger.warning(
                        f"{symbol_upper}: 缺失 {missing_days} 天数据，"
                        f"超过上限 {history_days} 天，只补齐最近 {history_days} 天"
                    )
                    missing_days = history_days
                else:
                    logger.info(f"{symbol_upper}: 检测到缺失 {missing_days} 天数据，开始补齐")

            # 4. 批量下载缺失历史（排除今天）
            if missing_days > 1:
                batch_result = await self.batch_download_history(
                    symbol_upper, days=missing_days - 1
                )
                success_count = sum(1 for v in batch_result.values() if v)
                logger.info(
                    f"{symbol_upper}: 批量下载 {success_count}/{missing_days - 1} 天成功"
                )
                # 部分成功也算成功
                if success_count == 0:
                    logger.warning(f"{symbol_upper}: 所有历史数据下载失败")

            # 5. 初始化今天实时数据（下载今天 + 补齐 gap + 开启 WS）
            today_ok = await self.init_today_realtime(symbol_upper)

            # 最终确认缓存中有数据
            has_data = self.cache.get_1m_data(symbol_upper) is not None
            results[symbol] = has_data or today_ok

            if results[symbol]:
                cached = self.cache.get_1m_data(symbol_upper)
                count = len(cached) if cached is not None else 0
                logger.info(f"✓ {symbol_upper}: 同步完成，缓存 {count} 条数据")
                # 聚合大周期数据到内存缓存
                self._preload_big_intervals_to_cache(symbol_upper)
            else:
                logger.error(f"✗ {symbol_upper}: 同步失败")

        success_count = sum(1 for v in results.values() if v)
        logger.info(
            f"✓ 数据同步完成：{success_count}/{len(symbols)} 个 symbol 成功"
        )
        return results

    # ==================== WebSocket 集成 ====================

    def set_kline_dispatch_callback(self, callback):
        """
        设置 K 线分发回调

        当 WS 收到新 K 线并完成缓存更新后，调用此回调通知策略引擎。

        Args:
            callback: 接收 Kline 对象的可调用对象
        """
        self._kline_dispatch_callback = callback

    async def start_klines_service_async(self) -> bool:
        """
        启动实时数据服务 (Kafka 或 WebSocket)

        优先级:
        1. 如果 Kafka 已启用且配置，使用 Kafka
        2. 否则使用 WebSocket

        Returns:
            是否启动成功
        """
        # 优先使用 Kafka
        if self.config.kafka_enabled and self.config.kafka_brokers:
            logger.info("使用 Kafka 作为实时数据源")
            return await self.init_kafka_consumer()

        # 回退到 WebSocket
        if not self.config.klines_service_enabled:
            logger.info("klines_service 已禁用，跳过启动")
            return False

        # 已连接则跳过，防止重复创建导致重复回调
        if self._ws_client is not None and self._ws_client._connected:
            logger.debug("WS 已连接，跳过重复启动")
            return True

        try:
            self._ws_client = KlinesWebSocketClient(
                ws_url=self.config.klines_service_ws_url,
                reconnect_delay=self.WS_RECONNECT_DELAY,
                max_reconnect=self.WS_MAX_RECONNECT,
                max_backoff=self.WS_MAX_BACKOFF,
            )
            self._ws_client.set_on_kline_callback(self._on_kline_received)

            connected = await self._ws_client.connect()
            if connected:
                self._connected = True
                logger.info(f"klines_service 连接成功：{self.config.klines_service_ws_url}")
                return True
            else:
                logger.warning("klines_service 连接失败")
                return False
        except Exception as e:
            logger.error(f"klines_service 连接异常：{e}")
            return False

    async def init_kafka_consumer(
        self,
        brokers: Optional[List[str]] = None,
        topic: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> bool:
        """
        初始化 Kafka 消费者 (替代 WebSocket)

        Args:
            brokers: Kafka broker 地址列表 (默认使用配置)
            topic: Kafka topic (默认使用配置)
            group_id: Consumer Group ID (默认使用配置或自动生成)

        Returns:
            是否初始化成功
        """
        brokers = brokers or self.config.kafka_brokers
        topic = topic or self.config.kafka_topic
        group_id = group_id or self.config.kafka_group_id

        if not brokers:
            logger.warning("Kafka brokers 未配置，跳过 Kafka 初始化")
            return False

        if self._kafka_consumer is not None and self._kafka_consumer.is_connected:
            logger.debug("Kafka Consumer 已连接，跳过重复初始化")
            return True

        try:
            from data_manager.kafka_consumer import KlineKafkaConsumer

            self._kafka_consumer = KlineKafkaConsumer(
                brokers=brokers,
                topic=topic,
                group_id=group_id,
            )
            self._kafka_consumer.set_on_kline_callback(self._on_kline_received)

            if self._kafka_consumer.connect():
                self._kafka_enabled = True
                await self._kafka_consumer.start_consume()
                self._connected = True
                logger.info(f"Kafka 消费者启动成功: brokers={brokers}, topic={topic}")
                return True
            else:
                self._kafka_consumer = None  # 清理失败的对象
                logger.error("Kafka 消费者连接失败")
                return False

        except Exception as e:
            self._kafka_consumer = None  # 清理异常时的对象
            logger.error(f"Kafka 初始化异常: {e}")
            return False

    async def subscribe_klines_async(self, symbols: List[str]) -> bool:
        """
        订阅 K 线数据

        支持 Kafka 和 WebSocket 两种模式。

        Args:
            symbols: 要订阅的 symbol 列表

        Returns:
            是否订阅成功
        """
        if self._kafka_enabled and self._kafka_consumer:
            self._kafka_consumer.add_symbols(symbols)
            logger.info(f"Kafka 订阅: {symbols}")
            return True

        if not self._ws_client:
            logger.warning("无可用的实时数据源 (Kafka 或 WebSocket)")
            return False

        if not self._ws_client._connected:
            logger.warning("WebSocket 未连接，无法订阅")
            return False

        try:
            await self._ws_client.subscribe(symbols)
            self._ws_subscribed_symbols.update(s.upper() for s in symbols)
            logger.info(f"WebSocket 订阅: {symbols}")
            return True
        except Exception as e:
            logger.error(f"WebSocket 订阅失败: {e}")
            return False

    async def stop_realtime(self):
        """停止实时数据服务"""
        # 停止 Kafka
        if self._kafka_consumer:
            self._kafka_consumer.disconnect()
            self._kafka_consumer = None
            self._kafka_enabled = False
            logger.info("Kafka 已停止")

        # 停止 WebSocket
        if self._ws_client:
            try:
                await self._ws_client.disconnect()
            except Exception:
                pass
            self._ws_client = None
            self._ws_subscribed_symbols.clear()
            logger.info("WebSocket 已停止")

        self._connected = False

    def get_realtime_status(self) -> Dict[str, Any]:
        """
        获取实时数据服务状态

        Returns:
            状态字典
        """
        if self._kafka_enabled and self._kafka_consumer:
            return {
                "mode": "kafka",
                "connected": self._kafka_consumer.is_connected,
                "running": self._kafka_consumer.is_running,
                "subscribed_symbols": list(self._kafka_consumer.subscribed_symbols),
                "brokers": self._kafka_consumer.brokers,
                "topic": self._kafka_consumer.topic,
                "group_id": self._kafka_consumer.group_id,
            }

        if self._ws_client:
            return {
                "mode": "websocket",
                "connected": self._ws_client._connected,
                "subscribed_symbols": list(self._ws_subscribed_symbols),
                "ws_url": self.config.klines_service_ws_url,
            }

        return {"mode": "none", "connected": False}

    def is_klines_service_available(self) -> bool:
        """检查实时数据服务是否可用"""
        return (self._ws_client is not None) or (self._kafka_consumer is not None)

    # ==================== API 调用 ====================

    async def _fetch_klines_from_api(
        self,
        symbol: str,
        interval: str,
        start_time_ms: Optional[int] = None,
        end_time_ms: Optional[int] = None,
        days: Optional[int] = None,
        limit: int = 1500,
    ) -> Optional[List]:
        """
        从 klines_service API 获取 K 线数据

        - 传入 startTime/endTime 时使用 GET /api/v1/klines（时间范围查询）
        - 传入 day 时使用 POST /api/v1/klines/daily（单日下载）
        """
        if start_time_ms is not None or end_time_ms is not None:
            # 时间范围查询：使用 GET /api/v1/klines
            url = f"{self.config.klines_service_http_url}/api/v1/klines"
            params: Dict[str, Any] = {
                "symbol": symbol.upper(),
                "interval": interval,
                "limit": limit,
            }
            if start_time_ms is not None:
                params["startTime"] = start_time_ms
            if end_time_ms is not None:
                params["endTime"] = end_time_ms

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            logger.error(f"API 请求失败 {symbol} {interval}: {resp.status} {text}")
                            return None
                        data = await resp.json()
                        if data and "data" in data:
                            return data["data"]
                        return data
            except Exception as e:
                logger.error(f"API 请求异常 {symbol} {interval}: {e}")
                return None
        else:
            # 单日下载：使用 POST /api/v1/klines/daily
            url = f"{self.config.klines_service_http_url}/api/v1/klines/daily"
            body: Dict[str, Any] = {
                "symbol": symbol.upper(),
                "interval": interval,
                "limit": limit,
            }
            if days is not None:
                body["day"] = days

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=body) as resp:
                        if resp.status != 200:
                            text = await resp.text()
                            logger.error(f"API 请求失败 {symbol} {interval}: {resp.status} {text}")
                            return None
                        data = await resp.json()
                        if data and "data" in data:
                            return data["data"]
                        return data
            except Exception as e:
                logger.error(f"API 请求异常 {symbol} {interval}: {e}")
                return None

    # ==================== Binance 公共 API 回退 ====================

    BINANCE_FAPI_BASE = "https://fapi.binance.com"

    async def _fetch_from_binance_public(
        self, symbol: str, day: str, limit: int = 1500,
    ) -> Optional[List]:
        """
        从 Binance 公共 API 下载 K 线数据（回退源）

        Args:
            symbol: 交易对
            day: 日期
            limit: 最大条数

        Returns:
            Binance 格式 K 线列表
        """
        symbol_upper = symbol.upper()
        day_start = datetime.strptime(day, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        start_ms = int(day_start.timestamp() * 1000)
        end_ms = start_ms + 86400000 - 1000  # 当天最后一毫秒

        url = f"{self.BINANCE_FAPI_BASE}/fapi/v1/klines"
        params = {
            "symbol": symbol_upper,
            "interval": "1m",
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": min(limit, 1500),
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.warning(
                            f"Binance 公共 API 请求失败 {symbol_upper} {day}: "
                            f"{resp.status} {text}"
                        )
                        return None
                    data = await resp.json()
                    if not data:
                        logger.debug(f"Binance 公共 API {symbol_upper} {day}: 返回空数据")
                        return None
                    return data
        except Exception as e:
            logger.warning(f"Binance 公共 API 请求异常 {symbol_upper} {day}: {e}")
            return None

    # ==================== 核心方法 1: download_daily_data ====================

    async def download_daily_data(self, symbol: str, day: str) -> bool:
        """
        下载指定日期的 K 线数据并保存到 CSV

        优先使用 klines_service API，失败或返回空时回退到 Binance 公共 API。

        Args:
            symbol: 交易对（如 "BTCUSDT"）
            day: 日期字符串（如 "2024-04-08"）

        Returns:
            是否下载成功
        """
        symbol_upper = symbol.upper()

        # 1. 优先使用 klines_service
        url = f"{self.config.klines_service_http_url}/api/v1/klines/daily"
        payload = {"symbol": symbol_upper, "day": day}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        klines = data.get("data") if isinstance(data, dict) else data
                        if klines:
                            return self._save_klines_and_cache(symbol_upper, klines, day)

            # 2. klines_service 返回空，回退到 Binance 公共 API
            logger.info(f"{symbol_upper} {day}: klines_service 无数据，回退到 Binance 公共 API")
            klines = await self._fetch_from_binance_public(symbol_upper, day)
            if not klines:
                logger.warning(f"{symbol_upper} {day}: 所有数据源均返回空")
                return False
            return self._save_klines_and_cache(symbol_upper, klines, day)

        except Exception as e:
            logger.error(f"下载 {symbol_upper} {day} 异常：{e}")
            return False

    def _save_klines_and_cache(
        self, symbol_upper: str, klines: List, day: str,
    ) -> bool:
        """解析 K 线数据、保存到 CSV 并更新缓存"""
        rows = []
        for kline in klines:
            rows.append({
                'timestamp': kline[0],
                'open': float(kline[1]),
                'high': float(kline[2]),
                'low': float(kline[3]),
                'close': float(kline[4]),
                'volume': float(kline[5]),
                'quote_volume': float(kline[7]),
                'trade_num': int(kline[8]),
                'active_buy_volume': float(kline[9]),
                'active_buy_quote_volume': float(kline[10]),
            })

        df = pd.DataFrame(rows)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
        df = df.sort_values('timestamp').reset_index(drop=True)

        if self.kline_repo:
            self.kline_repo.save_klines_to_csv(symbol_upper, "1m", rows)
            existing = self.cache.get_1m_data(symbol_upper)
            if existing is not None and not existing.empty:
                combined = pd.concat([existing, df], ignore_index=True)
                combined = combined.drop_duplicates(subset=['timestamp'], keep='last')
                combined = combined.sort_values('timestamp').reset_index(drop=True)
                self.cache.put(symbol_upper, '1m', combined, force_1m=True)
            else:
                self.cache.put(symbol_upper, '1m', df, force_1m=True)
        else:
            self.cache.put(symbol_upper, '1m', df, force_1m=True)

        logger.info(f"✓ {symbol_upper} {day}: 下载 {len(df)} 条 K 线")
        return True

    # ==================== 核心方法 2: batch_download_history ====================

    async def batch_download_history(self, symbol: str, days: int = 30) -> Dict[str, bool]:
        """
        批量下载最近 N 天历史数据（排除今天）

        Args:
            symbol: 交易对
            days: 下载天数（默认 30 天）

        Returns:
            {日期: 是否成功} 字典
        """
        today = datetime.now(timezone.utc).date()
        results: Dict[str, bool] = {}

        for d in range(days, 0, -1):
            day = (today - timedelta(days=d)).strftime("%Y-%m-%d")
            results[day] = await self.download_daily_data(symbol, day)

        success_count = sum(1 for v in results.values() if v)
        logger.info(
            f"✓ {symbol.upper()} 批量下载完成：{success_count}/{days} 天成功"
        )
        return results

    # ==================== 新方法: load_history / sync_to_latest 等 ====================

    def load_history(self, symbol: str) -> Optional[pd.DataFrame]:
        """
        从本地 CSV 读取 1m 历史数据

        Args:
            symbol: 交易对

        Returns:
            DataFrame 或 None
        """
        return self._load_csv(symbol, "1m")

    async def fetch_klines_range(
        self,
        symbol: str,
        interval: str,
        start_time_ms: int,
        end_time_ms: Optional[int] = None,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        通过 API 读取时间范围的 K 线数据

        Args:
            symbol: 交易对
            interval: 时间框架
            start_time_ms: 起始时间戳（毫秒）
            end_time_ms: 结束时间戳（毫秒，可选）

        Returns:
            API 原始返回数据（Binance 格式列表）或 None
        """
        return await self._fetch_klines_from_api(
            symbol, interval, start_time_ms=start_time_ms, end_time_ms=end_time_ms,
        )

    async def sync_to_latest(
        self, symbol: str, max_history_days: int = 7,
    ) -> bool:
        """
        将指定 symbol 的数据补充到最新

        逻辑：
        1. 检查缓存中是否有数据
        2. 若无，调用 batch_download_history + init_today_realtime
        3. 若有，计算距今时间差：
           - > 1 天：全量补齐（batch_download_history + init_today_realtime）
           - ≤ 1 天：只通过 API 补齐 gap

        Args:
            symbol: 交易对
            max_history_days: 补齐上限天数

        Returns:
            是否成功
        """
        symbol_upper = symbol.upper()

        # 检查缓存中已有数据
        cached = self.cache.get_1m_data(symbol_upper)
        if cached is None or cached.empty or 'timestamp' not in cached.columns:
            # 无本地数据，全量补齐
            logger.info(f"{symbol_upper}: 无本地数据，全量补齐 {max_history_days} 天")
            batch_result = await self.batch_download_history(
                symbol_upper, days=max_history_days - 1
            )
            success_count = sum(1 for v in batch_result.values() if v)
            if success_count == 0:
                logger.warning(f"{symbol_upper}: 历史数据下载全部失败")
            today_ok = await self.init_today_realtime(symbol_upper)
            return today_ok

        # 检查最新数据距今的差距
        latest_ts = cached['timestamp'].iloc[-1]
        if hasattr(latest_ts, 'to_pydatetime'):
            latest_ts = latest_ts.to_pydatetime()
        if latest_ts.tzinfo is None:
            latest_ts = latest_ts.replace(tzinfo=timezone.utc)

        gap_seconds = (datetime.now(timezone.utc) - latest_ts).total_seconds()
        gap_days = gap_seconds / 86400

        if gap_days > 1:
            # 差距 > 1 天，全量补齐
            logger.info(
                f"{symbol_upper}: 数据距今 {gap_days:.1f} 天，全量补齐"
            )
            capped_days = min(int(gap_days) + 1, max_history_days)
            if capped_days > 1:
                batch_result = await self.batch_download_history(
                    symbol_upper, days=capped_days - 1
                )
                success_count = sum(1 for v in batch_result.values() if v)
                if success_count == 0:
                    logger.warning(f"{symbol_upper}: 历史数据下载全部失败")
            today_ok = await self.init_today_realtime(symbol_upper)
            return today_ok
        else:
            # 差距 ≤ 1 天，只补齐 gap
            logger.info(
                f"{symbol_upper}: 数据距今 {gap_seconds/60:.0f} 分钟，补齐 gap"
            )
            gap_start_ms = int((latest_ts + timedelta(minutes=1)).timestamp() * 1000)
            api_data = await self._fetch_klines_from_api(
                symbol_upper, "1m", start_time_ms=gap_start_ms,
            )
            if api_data:
                return self._merge_api_data_to_cache(symbol_upper, api_data)
            logger.warning(f"{symbol_upper}: API 返回空数据，gap 未填充 (start_ms={gap_start_ms})")
            return False

    def cache_recent_data(
        self, symbols: List[str], days: int = 7,
    ) -> Dict[str, bool]:
        """
        将多个 symbols 的近 N 天 1m 数据加载到内存缓存

        Args:
            symbols: 交易对列表
            days: 加载天数

        Returns:
            {symbol: 是否成功}
        """
        results: Dict[str, bool] = {}
        for symbol in symbols:
            symbol_upper = symbol.upper()
            # 缓存已有则跳过
            if self.cache.get_1m_data(symbol_upper) is not None:
                results[symbol] = True
                continue

            df = self._load_csv(symbol_upper, "1m")
            if df is not None and not df.empty:
                self.cache.put(symbol_upper, "1m", df, force_1m=True)
                logger.info(f"{symbol_upper}: 加载 {len(df)} 条到缓存")
                results[symbol] = True
            else:
                logger.warning(f"{symbol_upper}: 无本地 CSV 数据")
                results[symbol] = False

        return results

    def _merge_api_data_to_cache(
        self, symbol: str, api_data: List,
    ) -> bool:
        """将 API 返回的数据合并到缓存"""
        rows = []
        for kline in api_data:
            rows.append({
                'timestamp': kline[0],
                'open': float(kline[1]),
                'high': float(kline[2]),
                'low': float(kline[3]),
                'close': float(kline[4]),
                'volume': float(kline[5]),
                'quote_volume': float(kline[7]),
                'trade_num': int(kline[8]),
                'active_buy_volume': float(kline[9]),
                'active_buy_quote_volume': float(kline[10]),
            })

        df_new = pd.DataFrame(rows)
        df_new['timestamp'] = pd.to_datetime(df_new['timestamp'], unit='ms', utc=True)
        df_new = df_new.sort_values('timestamp').reset_index(drop=True)

        existing = self.cache.get_1m_data(symbol)
        if existing is not None and not existing.empty:
            combined = pd.concat([existing, df_new], ignore_index=True)
            combined = combined.drop_duplicates(subset=['timestamp'], keep='last')
            combined = combined.sort_values('timestamp').reset_index(drop=True)
            self.cache.put(symbol, '1m', combined, force_1m=True)
        else:
            self.cache.put(symbol, '1m', df_new, force_1m=True)

        if self.kline_repo and rows:
            self.kline_repo.save_klines_to_csv(symbol, "1m", rows)

        logger.info(f"{symbol}: 补齐 {len(rows)} 条缺失数据到缓存")
        return True

    # ==================== 辅助方法: _load_csv ====================

    def _load_csv(self, symbol: str, timeframe: str = "1m") -> Optional[pd.DataFrame]:
        """
        从 CSV 加载 K 线数据（轻量加载器）

        Args:
            symbol: 交易对
            timeframe: 时间框架

        Returns:
            DataFrame 或 None
        """
        if not self.kline_repo:
            return None

        csv_path = self.csv_dir / timeframe / f"{symbol.upper()}_{timeframe}.csv"
        if not csv_path.exists():
            return None

        try:
            df = pd.read_csv(csv_path)
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
            df = df.sort_values('timestamp').reset_index(drop=True)
            logger.info(
                f"CSV 已加载: {csv_path} ({len(df)} 条), "
                f"最新: {df['timestamp'].iloc[-1]} | "
                f"O={df['open'].iloc[-1]} H={df['high'].iloc[-1]} "
                f"L={df['low'].iloc[-1]} C={df['close'].iloc[-1]}"
            )
            return df
        except Exception as e:
            logger.error(f"加载 CSV 失败 {csv_path}: {e}")
            return None

    # ==================== 核心方法 3: init_today_realtime ====================

    async def init_today_realtime(self, symbol: str) -> bool:
        """
        初始化今天的实时数据：
        1. 下载今天数据
        2. 从 CSV 加载到内存
        3. 通过 API 补齐缺失分钟
        4. 开启 WebSocket 连接
        5. 数据存入内存缓存

        Args:
            symbol: 交易对

        Returns:
            是否初始化成功
        """
        symbol_upper = symbol.upper()
        today = datetime.now(timezone.utc).date().strftime("%Y-%m-%d")

        # 1. 下载今天数据
        downloaded = await self.download_daily_data(symbol_upper, today)
        if not downloaded:
            logger.warning(f"{symbol_upper}: 今天数据下载失败，尝试从本地加载")

        # 2. 从 CSV 加载到缓存
        df = self._load_csv(symbol_upper, "1m")
        if df is not None and not df.empty:
            self.cache.put(symbol_upper, "1m", df, force_1m=True)
            logger.info(f"{symbol_upper}: 从 CSV 加载 {len(df)} 条数据")
        else:
            logger.warning(f"{symbol_upper}: 本地无今天数据")

        # 3. 检查并补齐 gap（从最后一条数据到现在）
        cached = self.cache.get_1m_data(symbol_upper)
        if cached is not None and not cached.empty and 'timestamp' in cached.columns:
            latest_ts = cached['timestamp'].iloc[-1]
            if hasattr(latest_ts, 'to_pydatetime'):
                latest_ts = latest_ts.to_pydatetime()
            if latest_ts.tzinfo is None:
                latest_ts = latest_ts.replace(tzinfo=timezone.utc)

            gap_seconds = (datetime.now(timezone.utc) - latest_ts).total_seconds()
            if gap_seconds > 120:
                gap_start = latest_ts + timedelta(minutes=1)
                start_ms = int(gap_start.timestamp() * 1000)
                api_data = await self._fetch_klines_from_api(
                    symbol_upper, "1m", start_time_ms=start_ms,
                )
                if api_data:
                    rows = []
                    for kline in api_data:
                        rows.append({
                            'timestamp': kline[0],
                            'open': float(kline[1]),
                            'high': float(kline[2]),
                            'low': float(kline[3]),
                            'close': float(kline[4]),
                            'volume': float(kline[5]),
                            'quote_volume': float(kline[7]),
                            'trade_num': int(kline[8]),
                            'active_buy_volume': float(kline[9]),
                            'active_buy_quote_volume': float(kline[10]),
                        })
                    df_new = pd.DataFrame(rows)
                    df_new['timestamp'] = pd.to_datetime(df_new['timestamp'], unit='ms', utc=True)
                    df_new = df_new.sort_values('timestamp').reset_index(drop=True)

                    combined = pd.concat([cached, df_new], ignore_index=True)
                    combined = combined.drop_duplicates(subset=['timestamp'], keep='last')
                    combined = combined.sort_values('timestamp').reset_index(drop=True)
                    self.cache.put(symbol_upper, '1m', combined, force_1m=True)

                    if self.kline_repo:
                        self.kline_repo.save_klines_to_csv(symbol_upper, "1m", rows)

                    logger.info(f"✓ {symbol_upper}: 补齐 {len(rows)} 条缺失数据")

        # 4. 开启 WebSocket
        ws_ok = False
        if self.cache.get_1m_data(symbol_upper) is not None:
            ws_ok = await self.start_klines_service_async()
            if ws_ok:
                await self.subscribe_klines_async([symbol_upper])
            else:
                logger.warning(f"{symbol_upper}: WS 启动失败，降级到 CSV 模式")

        # 5. 确认有数据
        return self.cache.get_1m_data(symbol_upper) is not None

    # ==================== 核心方法 4: manage_memory_cache ====================

    def manage_memory_cache(self, symbol: str) -> None:
        """
        管理内存缓存：保留近 2 天数据，淘汰更旧数据

        Args:
            symbol: 交易对
        """
        symbol_upper = symbol.upper()
        cached = self.cache.get_1m_data(symbol_upper)
        if cached is None or cached.empty:
            return

        # 1. 按时间裁剪：保留近 2 天
        cutoff = datetime.now(timezone.utc) - timedelta(days=2)
        if 'timestamp' in cached.columns:
            filtered = cached[cached['timestamp'] >= cutoff].copy()
            if len(filtered) < len(cached):
                removed = len(cached) - len(filtered)
                logger.info(f"{symbol_upper}: 淘汰 {removed} 条超过 2 天的旧数据")
        else:
            filtered = cached

        # 2. 行数限制
        max_rows = self.config.cache_1m_max_rows
        if len(filtered) > max_rows:
            filtered = filtered.tail(max_rows)
            logger.info(f"{symbol_upper}: 裁剪为最新 {max_rows} 行")

        # 3. 回写缓存
        self.cache.put(symbol_upper, "1m", filtered, force_1m=True)

        # 4. 持久化回 CSV（回测模式不写，避免多进程文件竞态）
        if self.kline_repo and not self.config.backtest_mode:
            self.kline_repo.save_dataframe_to_csv(symbol_upper, "1m", filtered)

    # ==================== WebSocket 回调 ====================

    def _backtest_update_cache(self, kline: Kline):
        """回测模式下的缓存更新：只写内存，不写 CSV、不检测 gap。"""
        symbol = kline.symbol.upper()

        kline_dict = {
            'timestamp': int(kline.timestamp.timestamp() * 1000),
            'open': kline.open,
            'high': kline.high,
            'low': kline.low,
            'close': kline.close,
            'volume': kline.volume,
            'quote_volume': kline.quote_volume,
            'trade_num': kline.trade_num,
            'active_buy_volume': kline.active_buy_volume,
            'active_buy_quote_volume': kline.active_buy_quote_volume,
        }

        df_new = pd.DataFrame([kline_dict])
        df_new['timestamp'] = pd.to_datetime(df_new['timestamp'], unit='ms', utc=True)

        existing = self.cache.get_1m_data(symbol)
        if existing is not None and not existing.empty:
            df_combined = pd.concat([existing, df_new], ignore_index=True)
            df_combined = df_combined.drop_duplicates(subset=['timestamp'], keep='last')
            df_combined = df_combined.sort_values('timestamp').reset_index(drop=True)
            self.cache.put(symbol, '1m', df_combined, force_1m=True)
        else:
            self.cache.put(symbol, '1m', df_new, force_1m=True)

    def _on_kline_received(self, kline: Kline):
        """K 线数据回调 — 验证时间戳、连续性，gap 补齐，写入缓存，更新大周期

        回测模式下跳过缓存更新和大周期聚合（数据已预加载，通过 backtest_timestamp 过滤）。
        时间戳验证仅对实时数据生效，回测数据本身是历史数据。
        """
        symbol = kline.symbol.upper()

        if self._ws_subscribed_symbols and symbol not in self._ws_subscribed_symbols:
            return

        if self.config.backtest_mode:
            # 回测优化：数据已预加载到缓存，通过 set_backtest_timestamp 过滤
            # 跳过冗余的缓存更新和大周期聚合，显著提升回测速度
            if self._kline_dispatch_callback:
                self._kline_dispatch_callback(kline)
            return

        # 时间戳验证（仅实时模式）：K 线时间滞后超过 5 分钟则跳过
        now = datetime.now(timezone.utc)
        kline_ts = kline.timestamp
        if kline_ts.tzinfo is None:
            kline_ts = kline_ts.replace(tzinfo=timezone.utc)

        diff_seconds = (now - kline_ts).total_seconds()
        if diff_seconds > 300:  # 5 分钟 = 300 秒
            logger.warning(
                f"{symbol}: K 线时间滞后 {diff_seconds:.0f} 秒，跳过处理 "
                f"(kline_ts={kline_ts.isoformat()})"
            )
            return

        kline_dict = {
            'timestamp': int(kline.timestamp.timestamp() * 1000),
            'open': kline.open,
            'high': kline.high,
            'low': kline.low,
            'close': kline.close,
            'volume': kline.volume,
            'quote_volume': kline.quote_volume,
            'trade_num': kline.trade_num,
            'active_buy_volume': kline.active_buy_volume,
            'active_buy_quote_volume': kline.active_buy_quote_volume,
        }

        existing = self.cache.get_1m_data(symbol)

        # 检查连续性，检测 gap 时触发 API 补齐
        if existing is not None and not existing.empty and 'timestamp' in existing.columns:
            latest_ts = existing['timestamp'].iloc[-1]
            new_ts = kline.timestamp
            if hasattr(latest_ts, 'to_pydatetime'):
                latest_ts = latest_ts.to_pydatetime()
            if latest_ts.tzinfo is None:
                latest_ts = latest_ts.replace(tzinfo=timezone.utc)
            if new_ts.tzinfo is None:
                new_ts = new_ts.replace(tzinfo=timezone.utc)

            diff_seconds = (new_ts - latest_ts).total_seconds()
            if diff_seconds > 90:
                logger.warning(
                    f"{symbol}: WS 推送检测到 gap（差 {diff_seconds:.0f} 秒），"
                    f"调用 API 补齐"
                )
                self._fill_ws_gap_async(symbol, latest_ts, new_ts)

        # 更新缓存
        df_new = pd.DataFrame([kline_dict])
        df_new['timestamp'] = pd.to_datetime(df_new['timestamp'], unit='ms', utc=True)

        existing = self.cache.get_1m_data(symbol)
        if existing is not None and not existing.empty:
            df_combined = pd.concat([existing, df_new], ignore_index=True)
            df_combined = df_combined.drop_duplicates(subset=['timestamp'], keep='last')
            df_combined = df_combined.sort_values('timestamp').reset_index(drop=True)
            self.cache.put(symbol, '1m', df_combined, force_1m=True)
        else:
            self.cache.put(symbol, '1m', df_new, force_1m=True)

        # 缓冲 + 批量持久化
        if self.kline_repo:
            buf = self._ws_buffer.setdefault(symbol, [])
            buf.append(kline_dict)
            if len(buf) >= self._ws_buffer_size:
                buf = self._ws_buffer.pop(symbol, [])
                self.kline_repo.save_klines_to_csv(symbol, '1m', buf)

            # 3.4 更新缓存的大周期 K 线数据
            self._update_big_intervals_from_cache(symbol)

        # 通知策略引擎分发 K 线到策略
        if self._kline_dispatch_callback:
            self._kline_dispatch_callback(kline)

        logger.info(
            f"[WS] {symbol} 1m @ {kline.timestamp} "
            f"open={kline.open} high={kline.high} low={kline.low} "
            f"close={kline.close} vol={kline.volume}"
        )

    def _fill_ws_gap_async(
        self, symbol: str, last_ts: datetime, new_ts: datetime,
    ):
        """
        WS 检测到 gap 时，通过 API 补齐缺失数据

        Args:
            symbol: 交易对
            last_ts: 缓存中最后一条时间
            new_ts: 新接收到的时间
        """
        start_ms = int((last_ts + timedelta(minutes=1)).timestamp() * 1000)
        end_ms = int(new_ts.timestamp() * 1000)

        async def _do_fill():
            try:
                api_data = await self._fetch_klines_from_api(
                    symbol, "1m", start_time_ms=start_ms, end_time_ms=end_ms,
                )
                if api_data:
                    self._merge_api_data_to_cache(symbol, api_data)
                    logger.info(f"{symbol}: WS gap 已补齐 {len(api_data)} 条")
            except Exception as e:
                logger.warning(f"{symbol}: WS gap 补齐失败: {e}")

        # 在已有事件循环中创建后台任务
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(_do_fill())
        else:
            asyncio.run(_do_fill())

    def _update_big_intervals_from_cache(self, symbol: str) -> Dict[str, bool]:
        """
        从 1m 缓存聚合大周期数据到缓存

        当 WS 或 polling 收到新 1m 数据时调用，实时更新大周期。

        Args:
            symbol: 交易对

        Returns:
            {timeframe: 是否成功}
        """
        results: Dict[str, bool] = {}

        # 检查 kline_repo 中注册的 symbol 时间框架
        if not self.kline_repo:
            return results

        state = self.kline_repo._states.get(symbol)
        if state is None:
            return results

        big_intervals = [tf for tf in state.registered_timeframes if tf.lower() != "1m"]
        if not big_intervals:
            return results

        df_1m = self.cache.get_1m_data(symbol)
        if df_1m is None or df_1m.empty:
            return results

        # 回测模式下只聚合到当前时间戳（不影响实盘）
        if self.config.backtest_mode and self._current_backtest_timestamp:
            if 'timestamp' in df_1m.columns:
                df_1m = df_1m[df_1m['timestamp'] <= self._current_backtest_timestamp]
                if df_1m.empty:
                    return results

        for interval in big_intervals:
            try:
                df_agg = self.aggregate_1m_to_interval(df_1m, interval)
                if df_agg is not None and not df_agg.empty:
                    self.cache.put(symbol, interval, df_agg)
                    # 回测模式不保存到 CSV
                    if self.kline_repo and not self.config.backtest_mode:
                        rows = df_agg.to_dict(orient="records")
                        self.kline_repo.save_klines_to_csv(symbol, interval, rows)
                    results[interval] = True
                    logger.debug(
                        f"{symbol} {interval}: 缓存聚合 {len(df_agg)} 条"
                    )
                else:
                    results[interval] = False
            except Exception as e:
                logger.warning(f"{symbol} {interval}: 缓存聚合失败: {e}")
                results[interval] = False

        return results

    # ==================== 辅助方法：CSV 路径 ====================

    def _get_file_path(self, symbol: str, interval: str) -> Path:
        """获取 CSV 文件路径"""
        interval = interval.lower()
        return self.csv_dir / interval / f"{symbol.upper()}_{interval}.csv"

    # ==================== 数据完整性检查（main.py 使用） ====================

    def is_data_complete(self, symbols: List[str]) -> Dict[str, bool]:
        """
        检查数据完整性

        标准：
        1. 缓存中有数据
        2. 最新数据距今 < 5 分钟

        Args:
            symbols: 需要检查的 symbol 列表

        Returns:
            {symbol: True/False}
        """
        results = {}
        for symbol in symbols:
            cached = self.cache.get_1m_data(symbol)
            if cached is None or cached.empty:
                results[symbol] = False
                continue

            if 'timestamp' in cached.columns:
                latest_ts = cached['timestamp'].iloc[-1]
                if hasattr(latest_ts, 'to_pydatetime'):
                    latest_ts = latest_ts.to_pydatetime()
                if latest_ts.tzinfo is None:
                    latest_ts = latest_ts.replace(tzinfo=timezone.utc)

                gap = (datetime.now(timezone.utc) - latest_ts).total_seconds()
                if gap > 300:
                    results[symbol] = False
                    continue
            else:
                results[symbol] = False
                continue

            results[symbol] = True
        return results

    # ==================== 缓存读取（get_klines 内部使用） ====================

    def get_dataframe_cached(self, symbol: str, interval: str,
                              limit: int = 5000) -> Optional[pd.DataFrame]:
        """
        获取 K 线 DataFrame（缓存优先）

        优先级:
        1. 1m → 1m 常驻缓存，未命中则 CSV 加载
        2. 大周期 → 从 1m 缓存实时聚合

        回测模式下自动按 backtest_timestamp 过滤数据。
        """
        bt_ts = self._current_backtest_timestamp if self.config.backtest_mode else None

        if interval == "1m":
            df = self.cache.get(symbol, interval)
            if df is None:
                df = self._load_csv(symbol, "1m")
                if df is not None:
                    self.cache.put(symbol, interval, df, force_1m=True)
            if df is not None:
                if bt_ts is not None and 'timestamp' in df.columns:
                    df = df[df['timestamp'] <= bt_ts]
                    if df.empty:
                        return None
                return df.tail(limit).copy() if len(df) > limit else df.copy()
        else:
            # 优先从缓存获取已加载的大周期数据
            df = self.cache.get(symbol, interval)
            if df is not None and not df.empty:
                if bt_ts is not None and 'timestamp' in df.columns:
                    df = df[df['timestamp'] <= bt_ts]
                    if df.empty:
                        return None
                return df.tail(limit).copy() if len(df) > limit else df.copy()

            # 回退: 从 1m 聚合
            df_1m = self.cache.get_1m_data(symbol)
            if df_1m is None or df_1m.empty:
                return None
            if bt_ts is not None and 'timestamp' in df_1m.columns:
                df_1m = df_1m[df_1m['timestamp'] <= bt_ts]
                if df_1m.empty:
                    return None
            df = self.aggregate_1m_to_interval(df_1m, interval)
            return df.tail(limit).copy() if df is not None and not df.empty else None

        return None

    # ==================== 核心方法 5: get_klines（同步对外接口） ====================

    def get_klines(self, symbol: str, interval: str,
                   limit: int = 10) -> List[Kline]:
        """
        同步对外接口：获取 K 线数据

        供策略在同步上下文中调用（on_start, on_kline 等）。

        内部处理:
        1. 1m 数据：缓存 → CSV 回退，增量返回
        2. 大周期：从 1m 缓存实时聚合，每次返回完整数据

        Args:
            symbol: 交易对
            interval: K 线周期
            limit: 返回数量

        Returns:
            Kline 对象列表
        """
        symbol_upper = symbol.upper()

        df = self.get_dataframe_cached(symbol_upper, interval, limit=limit)
        if df is None or df.empty:
            return []

        # 转换为 Kline 列表
        all_klines = []
        for _, row in df.iterrows():
            row_dict = row.to_dict()
            row_dict['symbol'] = symbol_upper
            row_dict['interval'] = interval
            all_klines.append(Kline.from_dict(row_dict))

        # 大周期：回测模式下按当前 bar 时间戳过滤后聚合
        if interval != "1m":
            if self.config.backtest_mode:
                bt_ts = self._current_backtest_timestamp
                if bt_ts is None:
                    return all_klines

                # 从 1m 数据重新聚合，只包含到当前 bar 时间戳
                df_1m = self.cache.get_1m_data(symbol_upper)
                if df_1m is None or df_1m.empty:
                    return all_klines

                # 确保有 timestamp 列
                if 'timestamp' not in df_1m.columns:
                    return all_klines

                # 过滤 1m 数据到当前回测时间
                df_1m_filtered = df_1m[df_1m['timestamp'] <= bt_ts]
                if df_1m_filtered.empty:
                    return []

                # 重新聚合
                df_agg = self.aggregate_1m_to_interval(df_1m_filtered, interval)
                if df_agg is None or df_agg.empty:
                    return []

                agg_klines = []
                for _, row in df_agg.iterrows():
                    row_dict = row.to_dict()
                    row_dict['symbol'] = symbol_upper
                    row_dict['interval'] = interval
                    agg_klines.append(Kline.from_dict(row_dict))

                return agg_klines

            # 正常模式：增量追踪 — 首次返回完整数据，后续只返回新增
            key = f"{symbol_upper}_{interval}"
            last_ts = self._last_kline_timestamp.get(key)

            if last_ts:
                # 非首次：只返回新增 K 线
                new_klines = [k for k in all_klines if k.timestamp > last_ts]
            else:
                # 首次：返回全部（策略需要足够历史计算指标）
                new_klines = all_klines

            # 更新追踪点
            if new_klines:
                self._last_kline_timestamp[key] = new_klines[-1].timestamp
            elif all_klines:
                self._last_kline_timestamp[key] = all_klines[-1].timestamp

            return new_klines

        # 1m 数据：增量返回
        key = f"{symbol_upper}_{interval}"
        last_ts = self._last_kline_timestamp.get(key)

        if last_ts:
            new_klines = [k for k in all_klines if k.timestamp > last_ts]
        else:
            # 首次调用：返回最后一条作为基准
            new_klines = all_klines[-1:] if all_klines else []

        # 更新追踪点
        if new_klines:
            self._last_kline_timestamp[key] = new_klines[-1].timestamp
        elif all_klines:
            self._last_kline_timestamp[key] = all_klines[-1].timestamp

        # 应用 limit
        if limit and len(new_klines) > limit:
            new_klines = new_klines[-limit:]

        return new_klines

    async def get_klines_async(self, symbol: str, interval: str,
                               limit: int = 10) -> List[Kline]:
        """
        异步版本：在增量返回基础上，1m 有新数据时自动持久化 + 聚合大周期

        供 main.py 轮询任务在异步上下文中调用。
        """
        symbol_upper = symbol.upper()
        result = self.get_klines(symbol_upper, interval, limit=limit)

        # 1m 有新数据 → 持久化 + 聚合
        if interval == '1m' and result and self.kline_repo:
            kline_dicts = [k.to_dict() for k in result]
            self.kline_repo.update_from_1m(symbol_upper, kline_dicts)

        return result

    def get_klines_sync(self, symbol: str, interval: str,
                        limit: int = 100) -> List[Kline]:
        """同步版本：获取全部 K 线数据（非增量）"""
        df = self.get_dataframe_cached(symbol, interval, limit=limit)
        if df is None or df.empty:
            return []

        klines = []
        for _, row in df.iterrows():
            row_dict = row.to_dict()
            row_dict['symbol'] = symbol
            row_dict['interval'] = interval
            klines.append(Kline.from_dict(row_dict))

        return klines

    def reset_kline_tracking(self, symbol: Optional[str] = None,
                             interval: Optional[str] = None):
        """重置 K 线时间戳追踪"""
        if symbol and interval:
            key = f"{symbol}_{interval}"
            self._last_kline_timestamp.pop(key, None)
        else:
            self._last_kline_timestamp.clear()

    def set_backtest_timestamp(self, timestamp: datetime):
        """回测模式下更新当前 bar 时间戳"""
        self._current_backtest_timestamp = timestamp

    # ==================== 技术指标接口 ====================

    def get_indicators(
        self,
        symbol: str,
        interval: str,
        indicator_name: str,
        params: Optional[Dict[str, Any]] = None,
        limit: int = 100,
    ) -> pd.DataFrame:
        """
        获取技术指标数据

        Args:
            symbol: 交易对
            interval: 时间框架 (1m, 5m, 15m, 1h 等)
            indicator_name: 指标名称 (adx, ema, sma, rsi, macd, boll, atr)
            params: 指标参数，覆盖默认值
            limit: 返回最近 N 条数据

        Returns:
            指标结果 DataFrame

        Raises:
            ValueError: 指标不存在或数据不足
        """
        df = self.get_dataframe_cached(symbol.upper(), interval, limit=limit)
        if df is None or df.empty:
            return pd.DataFrame()

        return compute_indicator(indicator_name, df, params)

    @staticmethod
    def get_available_indicators() -> List[str]:
        """获取所有可用技术指标名称"""
        return get_available_indicators()

    # ==================== 策略统一数据读取 ====================

    def get_line_data(
        self,
        symbol: str,
        interval: str,
        limit: int = 500,
        indicators: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        策略统一 K 线+指标读取方法

        所有策略通过此方法获取 K 线数据和任意技术指标，
        只需传入不同的参数即可，无需关心底层实现。

        Args:
            symbol: 交易对
            interval: 时间框架 (1m, 15m, 1h, 4h 等)
            limit: 返回最近 N 条 K 线
            indicators: 指标列表，每项包含:
                - name: 指标名称 (adx, rsi, macd 等)
                - params: 指标参数 (可选)

        Returns:
            {
                "symbol": str,
                "interval": str,
                "klines": List[Kline],
                "df": pd.DataFrame,  # 原始 DataFrame
                "indicators": {name: pd.DataFrame},  # 各指标结果
            }
        """
        symbol_upper = symbol.upper()
        klines = self.get_klines_sync(symbol_upper, interval, limit=limit)
        df = self.get_dataframe_cached(symbol_upper, interval, limit=limit)

        result: Dict[str, Any] = {
            "symbol": symbol_upper,
            "interval": interval,
            "klines": klines or [],
            "df": df if df is not None else pd.DataFrame(),
            "indicators": {},
        }

        if indicators and df is not None and not df.empty:
            for ind in indicators:
                name = ind["name"]
                params = ind.get("params")
                try:
                    ind_df = compute_indicator(name, df, params)
                    result["indicators"][name] = ind_df
                except Exception as e:
                    logger.warning(f"指标 {name} 计算失败: {e}")

        return result

    # ==================== 定时持久化 ====================

    def start_periodic_persistence(self) -> asyncio.Task:
        """
        启动定时持久化后台任务

        每 N 分钟将内存缓存中的 1m 数据刷新到 CSV 文件。

        Returns:
            创建的 asyncio.Task 对象
        """
        interval = self.config.persistence_interval_minutes

        async def _persistence_loop():
            logger.info(f"定时持久化已启动，每 {interval} 分钟执行一次")
            while True:
                await asyncio.sleep(interval * 60)
                try:
                    self._flush_all_cache_to_csv()
                except Exception as e:
                    logger.error(f"定时持久化失败: {e}")

        task = asyncio.create_task(_persistence_loop())
        self._background_tasks.append(task)
        return task

    def _flush_all_cache_to_csv(self) -> Dict[str, bool]:
        """
        将所有 1m 缓存数据持久化到 CSV 文件

        Returns:
            {symbol: 是否成功}
        """
        if not self.kline_repo:
            logger.warning("KlineRepository 未启用，无法持久化")
            return {}

        results: Dict[str, bool] = {}
        for symbol in list(self.cache._1m_cache.keys()):
            try:
                df = self.cache.get_1m_data(symbol)
                if df is None or df.empty:
                    continue
                # DataFrame → List[Dict] 以适配 save_klines_to_csv
                rows = df.to_dict(orient="records")
                self.kline_repo.save_klines_to_csv(symbol, "1m", rows)
                results[symbol] = True
                logger.debug(f"{symbol}: 定时持久化已保存 {len(df)} 条")
            except Exception as e:
                logger.error(f"{symbol}: 定时持久化失败: {e}")
                results[symbol] = False

        if results:
            logger.info(f"定时持久化完成: {len(results)} 个 symbol 已保存")
        return results
