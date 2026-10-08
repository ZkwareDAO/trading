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
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import aiohttp

# 大缺口补齐复用运维脚本的下载链路（monthly/daily 归档 zip + fapi 分页）。
# scripts/download_data.py 只依赖 stdlib/pandas/requests/dotenv，无循环导入；
# backtest/run_backtest.py 已有同款 import 先例。
# 注意：_fetch_gap_range 不用 fetch_klines —— 测试统一 mock
# _fetch_from_binance_public，绕开它会打到真实网络。
from scripts.download_data import download_range, fetch_range_rows, _get_proxies

from data_manager.kline_repository import KlineRepository


def _get_proxy() -> Optional[str]:
    """读取代理环境变量（HTTPS_PROXY / https_proxy / HTTP_PROXY / http_proxy）"""
    return (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )
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

    # 实时行情：直连 Binance 公共 WS（wss://fstream.binance.com）+ REST 轮询回退
    realtime_enabled: bool = True

    # 启动时自动同步配置
    sync_history_days: int = 365  # 启动时补齐历史天数
    auto_sync_on_connect: bool = True  # 是否启动时自动同步

    # 定时持久化配置
    persistence_interval_minutes: int = 5  # 缓存刷到 CSV 的间隔时间

    # 回测模式：禁用增量返回，每次调用返回完整数据
    backtest_mode: bool = False


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

        # Kline dispatch callback — 当 WS 收到新 K 线时通知策略引擎
        self._kline_dispatch_callback: Optional[Any] = None

        # 后台任务
        self._background_tasks: List[asyncio.Task] = []
        # Binance REST 轮询任务（fstream 推送不可用时的回退实时源）
        self._binance_poll_task: Optional[asyncio.Task] = None
        # 每个已喂给策略的最新闭合 1m kline 时间戳，避免重复派发
        self._binance_poll_last_ts: Dict[str, int] = {}

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
        """解析时间周期为分钟数，无法解析时返回 0。

        与 KlineRepository._get_interval_minutes 保持一致（含 w 分支）。
        唯一调用方 _update_big_intervals_from_cache 用它算增量切片行数
        （tail_rows = period_minutes * 3），因此：
        - 漏掉 w 分支会让 1w 落到 fallback，tail_rows=3 → 增量桶只含 3 分钟
          数据，覆盖掉 CSV 里完整的同名周桶。
        - 无法解析时必须返回 0 而非 1：调用方按 `period_minutes > 0` 判断是否
          走增量，返回 0 才能安全退化到全量聚合路径。
        """
        tf = interval.lower().strip()
        try:
            if tf.endswith("m"):
                return int(tf[:-1])
            if tf.endswith("h"):
                return int(tf[:-1]) * 60
            if tf.endswith("d"):
                return int(tf[:-1]) * 1440
            if tf.endswith("w"):
                return int(tf[:-1]) * 1440 * 7
        except ValueError:
            return 0
        return 0

    def aggregate_1m_to_interval(
        self, df_1m: pd.DataFrame, target_interval: str,
        drop_partial_head: bool = False,
    ) -> pd.DataFrame:
        """从 1m 数据聚合生成目标周期

        Args:
            df_1m: 1m K 线数据
            target_interval: 目标周期
            drop_partial_head: 源数据起点未对齐到周期边界时丢弃残缺首桶。
                切片聚合（增量、被裁剪的缓存）必须开启，否则首桶的
                open/high/low/volume 会失真并覆盖已有正确值。
        """
        if df_1m is None or df_1m.empty:
            return pd.DataFrame()

        from data_manager.klines_loader import resample_ohlcv
        return resample_ohlcv(
            df_1m, target_interval, datetime_column="timestamp",
            drop_partial_head=drop_partial_head,
        )

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
            # 1m 缓存起点通常不落在大周期边界上（CSV 被裁剪、增量补齐等），
            # 首桶只含所属周期的后半段。_merge_kline_data 用 keep='last'
            # 让新值覆盖旧值，若不丢弃这个残缺桶，它会顶掉 CSV 里那根
            # 完整的同名桶，造成信息净损失。
            df = self.aggregate_1m_to_interval(
                df_1m, interval, drop_partial_head=True,
            )
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
            exchange: 交易所（binance, okx）— 兼容参数，数据直连 Binance 公共 API
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
                # 1m 缓存起点未必对齐大周期边界，残缺首桶不能落盘
                df_agg = self.aggregate_1m_to_interval(
                    df_1m, interval, drop_partial_head=True,
                )
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

        # Binance 回退模式的 REST 轮询任务是独立字段（不在 _background_tasks
        # 里），必须单独取消 —— 否则策略进程关停后该协程仍在后台轮询。
        # 之前唯一取消它的 stop_realtime() 未被关停路径调用。
        await self._cancel_binance_poll_task()

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

        必须读文件**尾部**：曾用 `pd.read_csv(csv_path, nrows=5)` 配
        `.iloc[-1]`，而 nrows 取的是**前** 5 行，于是拿到第 5 根 K 线
        （最早的数据）。connect_and_sync 据此算 missing_days，会把
        "数据只差 1 分钟"误判成缺失数天，触发无谓的历史重下。

        KlineRepository._get_last_kline_time 已踩过同一个坑并修好，
        这里复用它的 _read_last_line（按字节回扫，开销与文件大小无关），
        不再写第二份尾读实现。

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
            header = pd.read_csv(csv_path, nrows=0)
            if 'timestamp' not in header.columns:
                return None
            # timestamp 恒为首列（_save_dataframe / _append_to_csv 保证），
            # 故取末行第一个字段即可
            if list(header.columns).index('timestamp') != 0:
                logger.warning(
                    f"{csv_path}: timestamp 非首列，跳过尾读以免取错字段"
                )
                return None

            last_line = KlineRepository._read_last_line(csv_path)
            if not last_line:
                return None

            ts_field = last_line.split(",", 1)[0].strip()
            if not ts_field or ts_field.lower() == 'timestamp':
                return None

            ts = pd.to_datetime(ts_field, utc=True)
            if pd.isna(ts):
                return None
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

    async def start_realtime_async(self, symbols: Optional[List[str]] = None) -> bool:
        """
        启动实时数据服务（单体模式：直连 Binance 公共 WebSocket）

        combined-stream URL 由 _ws_subscribed_symbols 拼出，应先传 symbols 再启动。
        WS 推送不可用（风控限推等）时自动降级到 fapi REST 轮询。

        Args:
            symbols: 订阅的 symbol 列表

        Returns:
            是否启动成功
        """
        if not self.config.realtime_enabled:
            logger.info("realtime_enabled=False，跳过实时数据服务启动")
            return False

        # 已连接则跳过，防止重复创建导致重复回调
        if self._ws_client is not None and self._ws_client._connected:
            logger.debug("WS 已连接，跳过重复启动")
            return True

        # 登记 symbols（拼 combined-stream URL 需要）
        if symbols:
            self._ws_subscribed_symbols.update(s.upper() for s in symbols)

        return await self._start_binance_ws()

    async def subscribe_klines_async(self, symbols: List[str]) -> bool:
        """
        订阅 K 线数据（单体模式：streams 固定在连接 URL 里）

        登记 symbol；若实时通道已在运行且出现新 symbol，则重建通道 ——
        combined-stream 的 URL 在连接时固定，运行中追加的 symbol 不重连
        就收不到推送。单体模式下这是唯一实时数据源，不能静默丢订阅。

        Args:
            symbols: 要订阅的 symbol 列表

        Returns:
            是否订阅成功
        """
        added = {s.upper() for s in symbols} - self._ws_subscribed_symbols
        self._ws_subscribed_symbols.update(s.upper() for s in symbols)

        if not added:
            return True

        running = (
            (self._ws_client is not None and self._ws_client._connected)
            or (self._binance_poll_task is not None
                and not self._binance_poll_task.done())
        )
        if not running:
            logger.info(f"已登记待订阅 symbol: {sorted(added)}")
            return True

        logger.info(f"检测到新增订阅 {sorted(added)}，重建实时通道")
        all_symbols = list(self._ws_subscribed_symbols)
        await self.stop_realtime()
        # stop_realtime 会清空登记表，恢复后按全量 symbol 重启
        self._ws_subscribed_symbols.update(all_symbols)
        return await self.start_realtime_async(all_symbols)

    async def _cancel_binance_poll_task(self) -> bool:
        """取消 Binance REST 轮询任务并清空字段

        close() 与 stop_realtime() 两条清理路径共用。异常只记日志不外抛 ——
        关停流程不能因清理失败而中断。

        Returns:
            是否确实取消了一个在跑的任务（供调用方决定是否打日志）
        """
        task = self._binance_poll_task
        if not task or task.done():
            self._binance_poll_task = None
            return False

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass  # 预期路径：任务响应取消
        except Exception as e:
            logger.warning(f"取消 Binance 轮询任务时异常：{e}")
        self._binance_poll_task = None
        return True

    async def stop_realtime(self):
        """停止实时数据服务"""
        # 停止 Binance REST 轮询任务
        if await self._cancel_binance_poll_task():
            logger.info("Binance REST 轮询已停止")

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
            状态字典（mode: binance_ws / binance_rest / none）
        """
        if self._ws_client:
            return {
                "mode": "binance_ws",
                "connected": self._ws_client._connected,
                "subscribed_symbols": list(self._ws_subscribed_symbols),
                "ws_url": self._ws_client.ws_url,
            }

        if self._binance_poll_task is not None and not self._binance_poll_task.done():
            return {
                "mode": "binance_rest",
                "connected": True,
                "subscribed_symbols": list(self._ws_subscribed_symbols),
            }

        return {"mode": "none", "connected": False}

    def is_realtime_available(self) -> bool:
        """检查实时数据服务是否可用"""
        return self._ws_client is not None

    # ==================== Binance 公共数据源 ====================

    BINANCE_WS_BASE = "wss://fstream.binance.com"
    BINANCE_FAPI_BASE = "https://fapi.binance.com"
    # REST 轮询间隔（秒）。1m K 线每分钟闭合一次，15s 轮询可在闭合后 ~15s 内拾取。
    BINANCE_POLL_INTERVAL = 15.0

    async def _start_binance_ws(self) -> bool:
        """
        启动 Binance 实时数据源（单体模式唯一实时通道）。

        实现说明：
        - 优先尝试 fstream WebSocket 推送（部分出口 IP 可用）。
        - 若 WS 握手后 BINANCE_WS_PROBE_TIMEOUT 秒内收不到任何数据帧
          （典型表现：握手 101 通但被 Binance 风控限推），自动降级到 REST 轮询。
        - REST 轮询每 BINANCE_POLL_INTERVAL 秒拉一次 fapi/v1/klines，
          取最新闭合的 1m K 线喂给 _on_kline_received。

        Returns:
            是否启动成功（WS 或 REST 任一可用即 True）
        """
        if not self._ws_subscribed_symbols:
            logger.warning("Binance 回退：尚未订阅任何 symbol，无法启动")
            return False

        # 先尝试 WS 推送
        ws_ok = await self._start_binance_ws_push()
        if ws_ok:
            return True

        # WS 不可用，降级 REST 轮询
        logger.info("Binance WS 推送不可用，降级到 REST 轮询模式")
        return await self._start_binance_rest_poll()

    async def _start_binance_ws_push(self) -> bool:
        """尝试 fstream WS 推送，握手后在探测窗口内验证是否真有数据帧。"""
        streams = "/".join(
            f"{s.lower()}@kline_1m" for s in self._ws_subscribed_symbols
        )
        ws_url = f"{self.BINANCE_WS_BASE}/stream?streams={streams}"

        try:
            self._ws_client = KlinesWebSocketClient(
                ws_url=ws_url,
                reconnect_delay=self.WS_RECONNECT_DELAY,
                max_reconnect=0,
                max_backoff=self.WS_MAX_BACKOFF,
            )
            self._ws_client.set_on_kline_callback(self._on_kline_received)
            self._ws_client._subscribed_symbols_snapshot = list(self._ws_subscribed_symbols)

            connected = await self._ws_client.connect()
            if not connected:
                logger.warning("Binance 公共 WS 连接失败")
                return False

            # 探测：握手成功后短时间内验证是否有数据帧
            # 不直接 recv()（与 _receive_loop 的 recv 冲突），改为等首帧事件
            self._ws_client.reset_first_frame_event()
            probe_ok = await self._probe_binance_ws_data()
            if probe_ok:
                self._connected = True
                logger.info(f"Binance 公共 WS 连接成功并收到数据：{ws_url}")
                return True

            # 握手通但无数据帧 —— 风控限推，停掉 WS 转 REST
            logger.warning("Binance WS 握手成功但未收到数据帧（疑似风控限推），转 REST 轮询")
            try:
                await self._ws_client.disconnect()
            except Exception:
                pass
            self._ws_client = None
            return False
        except Exception as e:
            logger.error(f"Binance 公共 WS 连接异常：{e}")
            self._ws_client = None
            return False

    async def _probe_binance_ws_data(self, timeout: float = 12.0) -> bool:
        """握手后探测 timeout 秒内是否收到至少一条数据帧。

        通过 _ws_client.wait_first_frame 等首帧事件，
        不直接 recv() 以避免与 _receive_loop 的接收循环冲突。
        """
        if not self._ws_client:
            return False
        try:
            return await self._ws_client.wait_first_frame(timeout=timeout)
        except Exception:
            return False

    async def _start_binance_rest_poll(self) -> bool:
        """启动 Binance REST 轮询后台任务作为实时数据源。"""
        if self._binance_poll_task and not self._binance_poll_task.done():
            return True
        symbols = list(self._ws_subscribed_symbols)
        if not symbols:
            return False
        self._binance_poll_task = asyncio.create_task(self._binance_rest_poll_loop(symbols))
        self._connected = True
        logger.info(f"Binance REST 轮询已启动，symbols={symbols}，间隔 {self.BINANCE_POLL_INTERVAL}s")
        return True

    async def _binance_rest_poll_loop(self, symbols: List[str]):
        """REST 轮询主循环：定期拉取每个 symbol 最新闭合的 1m K 线。"""
        # 启动后立即拉一次，缩短首帧延迟
        await self._poll_once(symbols)
        while True:
            try:
                await asyncio.sleep(self.BINANCE_POLL_INTERVAL)
                await self._poll_once(symbols)
            except asyncio.CancelledError:
                logger.info("Binance REST 轮询任务被取消，退出")
                raise
            except Exception as e:
                logger.error(f"Binance REST 轮询异常：{e}")
                await asyncio.sleep(self.BINANCE_POLL_INTERVAL)

    async def _poll_once(self, symbols: List[str]):
        """拉取一次：每个 symbol 取最近 2 条 1m kline，喂入最新闭合的那条。"""
        for symbol in symbols:
            try:
                data = await self._fetch_from_binance_public(
                    symbol, start_time_ms=None, limit=2,
                )
            except Exception as e:
                logger.warning(f"REST 轮询 {symbol} 拉取异常：{e}")
                continue
            if not data or len(data) < 2:
                logger.debug(f"REST 轮询 {symbol}: 无数据")
                continue
            # data[-1] 是当前未闭合的 1m，data[-2] 是上一条已闭合的
            closed_raw = data[-2]
            kline = Kline.from_binance_format(closed_raw, symbol, "1m")
            kline.is_final = True
            ts_ms = int(kline.timestamp.timestamp() * 1000)
            last_ts = self._binance_poll_last_ts.get(symbol)
            if last_ts is not None and ts_ms <= last_ts:
                continue  # 已派发过，跳过
            self._binance_poll_last_ts[symbol] = ts_ms
            logger.debug(
                f"[REST-POLL] {symbol} closed kline ts={kline.timestamp.isoformat()} "
                f"O={kline.open} H={kline.high} L={kline.low} C={kline.close}"
            )
            self._on_kline_received(kline)


    # ==================== Binance 公共 API ====================

    async def _fetch_from_binance_public(
        self, symbol: str, day: Optional[str] = None, limit: int = 1500,
        start_time_ms: Optional[int] = None, end_time_ms: Optional[int] = None,
    ) -> Optional[List]:
        """
        从 Binance 公共 API 下载 1m K 线数据（回退源）

        两种调用方式：
        - 传 day：下载指定日期（00:00 ~ 23:59）的 1m 数据
        - 传 start_time_ms / end_time_ms：下载时间范围内的 1m 数据

        Args:
            symbol: 交易对
            day: 日期字符串（如 "2024-04-08"），与 start_time_ms 二选一
            limit: 最大条数
            start_time_ms: 起始时间戳（毫秒）
            end_time_ms: 结束时间戳（毫秒，可选）

        Returns:
            Binance 格式 K 线列表
        """
        symbol_upper = symbol.upper()
        # 实时轮询模式：不传 day 也不传 start_time_ms，只拉最近 limit 条
        if day is None and start_time_ms is None:
            url = f"{self.BINANCE_FAPI_BASE}/fapi/v1/klines"
            params = {
                "symbol": symbol_upper,
                "interval": "1m",
                "limit": min(limit, 1500),
            }
            return await self._binance_public_request(symbol_upper, url, params)
        if day is not None:
            day_start = datetime.strptime(day, "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            )
            start_ms = int(day_start.timestamp() * 1000)
            end_ms = start_ms + 86400000 - 1000  # 当天最后一毫秒
        else:
            start_ms = start_time_ms
            end_ms = end_time_ms if end_time_ms is not None else start_ms + 86400000 - 1000

        url = f"{self.BINANCE_FAPI_BASE}/fapi/v1/klines"
        params = {
            "symbol": symbol_upper,
            "interval": "1m",
            "startTime": start_ms,
            "endTime": end_ms,
            "limit": min(limit, 1500),
        }
        return await self._binance_public_request(symbol_upper, url, params)

    async def _binance_public_request(
        self, symbol_upper: str, url: str, params: Dict[str, Any]
    ) -> Optional[List]:
        """发起 Binance fapi 请求并返回 JSON（统一代理/超时/错误处理）。"""
        proxy = _get_proxy()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, proxy=proxy, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.warning(
                            f"Binance 公共 API 请求失败 {symbol_upper}: "
                            f"{resp.status} {text}"
                        )
                        return None
                    data = await resp.json()
                    if not data:
                        logger.debug(f"Binance 公共 API {symbol_upper}: 返回空数据")
                        return None
                    return data
        except Exception as e:
            logger.warning(f"Binance 公共 API 请求异常 {symbol_upper}: {e}")
            return None

    # ==================== 核心方法 1: download_daily_data ====================

    async def download_daily_data(self, symbol: str, day: str) -> bool:
        """
        下载指定日期的 K 线数据并保存到 CSV（Binance 公共 API）

        Args:
            symbol: 交易对（如 "BTCUSDT"）
            day: 日期字符串（如 "2024-04-08"）

        Returns:
            是否下载成功
        """
        symbol_upper = symbol.upper()

        klines = await self._fetch_from_binance_public(symbol_upper, day)
        if not klines:
            logger.warning(f"{symbol_upper} {day}: Binance 公共 API 返回空")
            return False
        return self._save_klines_and_cache(symbol_upper, klines, day)

    @staticmethod
    def _parse_binance_klines(klines: List) -> List[Dict]:
        """将 Binance 数组格式 K 线解析为 dict 列表

        Binance 数组下标：0=开盘时间 1=开 2=高 3=低 4=收 5=成交量
        7=成交额 8=成交笔数 9=主动买入量 10=主动买入成交额
        """
        return [
            {
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
            }
            for kline in klines
        ]

    def _save_klines_and_cache(
        self, symbol_upper: str, klines: List, day: str,
    ) -> bool:
        """解析 K 线数据、保存到 CSV 并更新缓存"""
        rows = self._parse_binance_klines(klines)

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
        通过 Binance 公共 API 读取时间范围的 K 线数据

        Args:
            symbol: 交易对
            interval: 时间框架
            start_time_ms: 起始时间戳（毫秒）
            end_time_ms: 结束时间戳（毫秒，可选）

        Returns:
            API 原始返回数据（Binance 格式列表）或 None
        """
        return await self._fetch_from_binance_public(
            symbol, start_time_ms=start_time_ms, end_time_ms=end_time_ms,
        )

    async def _fill_large_gap_via_download_range(
        self, symbol_upper: str, start_dt: datetime, end_dt: datetime,
    ) -> bool:
        """大缺口补齐：转调 scripts/download_data.py::download_range。

        download_range 走归档分块（monthly/daily zip）+ fapi 分页 + 自动重试，
        一年缺口约 12 次请求，替代按天循环的 batch_download_history（每天一次
        请求且单次 1500 条上限无分页）。

        **仅限 WS 未启动的启动期调用**（sync_to_latest 在 init_today_realtime
        之前）：download_range 合并后整文件重写 CSV，不经过 kline_repo 的
        threading.RLock，与 WS 追加写并发会竞态丢数据。运行期中部空洞
        （scan_and_fill_holes）走 fetch_range_rows 只取数不落盘，合并仍走
        加锁路径。

        Returns:
            是否补齐成功（download_range 返回 None 视为失败）
        """
        proxies = _get_proxies()
        try:
            path = await asyncio.to_thread(
                download_range, symbol_upper, "1m",
                start_dt, end_dt, str(self.csv_dir), proxies,
            )
        except RuntimeError as e:
            logger.warning(f"{symbol_upper}: 大缺口补齐失败 ({start_dt} ~ {end_dt}): {e}")
            return False
        if path is None:
            logger.warning(f"{symbol_upper}: 大缺口补齐无数据返回 ({start_dt} ~ {end_dt})")
            return False
        # download_range 已合并去重、ISO 规范化落盘，从 CSV 重载缓存
        df = self.load_history(symbol_upper)
        if df is not None and not df.empty:
            self.cache.put(symbol_upper, "1m", df, force_1m=True)
        return True

    async def sync_to_latest(
        self, symbol: str, max_history_days: int = 7,
    ) -> bool:
        """
        将指定 symbol 的数据补充到最新

        逻辑：
        1. 检查缓存中是否有数据
        2. 若无，走大缺口补齐（download_range 归档分块）+ init_today_realtime
        3. 若有，计算距今时间差：
           - > 1 天：走大缺口补齐 + init_today_realtime
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
            # 无本地数据，全量补齐（归档分块 + fapi 分页）
            logger.info(f"{symbol_upper}: 无本地数据，全量补齐 {max_history_days} 天")
            now = datetime.now(timezone.utc)
            ok = await self._fill_large_gap_via_download_range(
                symbol_upper, now - timedelta(days=max_history_days), now,
            )
            if not ok:
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
            # 差距 > 1 天，走大缺口补齐（归档分块 + fapi 分页）
            logger.info(
                f"{symbol_upper}: 数据距今 {gap_days:.1f} 天，全量补齐"
            )
            await self._fill_large_gap_via_download_range(
                symbol_upper, latest_ts, datetime.now(timezone.utc),
            )
            today_ok = await self.init_today_realtime(symbol_upper)
            return today_ok
        else:
            # 差距 ≤ 1 天，只补齐 gap
            logger.info(
                f"{symbol_upper}: 数据距今 {gap_seconds/60:.0f} 分钟，补齐 gap"
            )
            # 起点取 latest_ts 本身而非 +1min：进程被杀时最后一根 1m 往往是
            # 未闭合状态就落了盘（WS 缓冲区满 10 条即写 CSV），volume/high 残缺。
            # 跳过它则该根永不重取，聚合到大周期后永久失真。重复拉取安全 ——
            # save_klines_to_csv / _merge_api_data_to_cache 均按 timestamp
            # keep="last" 去重，API 的完整值会覆盖残缺值。
            gap_start_ms = int(latest_ts.timestamp() * 1000)
            api_data = await self._fetch_from_binance_public(
                symbol_upper, start_time_ms=gap_start_ms,
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
        rows = self._parse_binance_klines(api_data)

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
                # 含最后一根：崩溃时它可能是未闭合状态落盘的残缺根，
                # 见 sync_to_latest 中的同款注释
                gap_start = latest_ts
                start_ms = int(gap_start.timestamp() * 1000)
                api_data = await self._fetch_from_binance_public(
                    symbol_upper, start_time_ms=start_ms,
                )
                if api_data:
                    rows = self._parse_binance_klines(api_data)
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
            ws_ok = await self.start_realtime_async([symbol_upper])
            if not ws_ok:
                logger.warning(f"{symbol_upper}: 实时行情启动失败，降级到 CSV 模式")

        # 5. 确认有数据
        return self.cache.get_1m_data(symbol_upper) is not None

    # ==================== 核心方法 4: manage_memory_cache ====================

    def manage_memory_cache(self, symbol: str) -> None:
        """
        管理内存缓存：按 cache_1m_max_age_days / cache_1m_max_rows 裁剪 1m 数据

        注意：只裁剪 1m 缓存。大周期由 1m 聚合而来，裁剪后若某周期的
        大周期缓存尚未建立，可用桶数会随之减少 —— 已落盘的大周期 CSV
        由 _preload_all_big_intervals_from_csv 负责兜住历史。

        Args:
            symbol: 交易对
        """
        symbol_upper = symbol.upper()
        cached = self.cache.get_1m_data(symbol_upper)
        if cached is None or cached.empty:
            return

        # 1. 按时间裁剪：保留 cache_1m_max_age_days 天
        #    以前这里硬编码 2 天，与配置项不一致（配了也不生效）
        max_age_days = self.config.cache_1m_max_age_days
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        if 'timestamp' in cached.columns:
            filtered = cached[cached['timestamp'] >= cutoff].copy()
            if len(filtered) < len(cached):
                removed = len(cached) - len(filtered)
                logger.info(
                    f"{symbol_upper}: 淘汰 {removed} 条超过 {max_age_days} 天的旧数据"
                )
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

    def _utcnow(self) -> datetime:
        """当前 UTC 时间（可在测试中覆盖）

        `_on_kline_received` 的滞后校验依赖真实挂钟，这让「窗口相对 4h
        网格的位置」随运行时刻漂移，测试难以稳定构造场景。抽成方法供测试
        patch，生产行为不变。
        """
        return datetime.now(timezone.utc)

    def _on_kline_received(self, kline: Kline):
        """K 线数据回调 — 验证时间戳、连续性，gap 补齐，写入缓存，更新大周期

        回测模式下跳过缓存更新和大周期聚合（数据已预加载，通过 backtest_timestamp 过滤）。
        时间戳验证仅对实时数据生效，回测数据本身是历史数据。
        """
        symbol = kline.symbol.upper()

        # DEBUG: 打印每条收到的 K 线（实时订阅回执）
        _ts = kline.timestamp
        if _ts.tzinfo is None:
            _ts = _ts.replace(tzinfo=timezone.utc)
        logger.debug(
            f"[KLINE-RECV] {symbol} final={kline.is_final} "
            f"ts={_ts.isoformat()} O={kline.open} H={kline.high} "
            f"L={kline.low} C={kline.close} V={kline.volume}"
        )

        if self._ws_subscribed_symbols and symbol not in self._ws_subscribed_symbols:
            return

        if self.config.backtest_mode:
            # 回测优化：数据已预加载到缓存，通过 set_backtest_timestamp 过滤
            # 跳过冗余的缓存更新和大周期聚合，显著提升回测速度
            if self._kline_dispatch_callback:
                self._kline_dispatch_callback(kline)
            return

        # 时间戳验证（仅实时模式）：K 线时间滞后超过 5 分钟则跳过
        now = self._utcnow()
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
            if df_new['timestamp'].iloc[0] > existing['timestamp'].iloc[-1]:
                # 快速路径：新 K 线严格晚于缓存末尾，跳过 dedup + sort
                df_combined = pd.concat([existing, df_new], ignore_index=True)
            else:
                # 慢速路径：时间戳重叠或乱序（WS 重放、gap 补齐）
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

    async def _fetch_gap_range(
        self, symbol: str, last_ts: datetime, new_ts: datetime,
    ) -> List:
        """取回 [last_ts, new_ts) 区间的原始 API 数据，**不写缓存**。

        与 `_fill_gap_range` 的区别：这里只负责取，由调用方决定何时合并。
        `scan_and_fill_holes` 需要"全部取回后一次性合并"来避免策略读到
        部分补齐的中间态，故不能用会立即写缓存的 `_fill_gap_range`。

        分页说明：单次请求 1500 条上限，超过时分页翻页拉完整个区间
        （Binance fapi 协议）。曾用单次请求：20160 根的洞每轮 5 分钟维护
        只推进 1500 根，磨了 ~1 小时才补完。

        Returns:
            Binance 格式的原始 K 线列表；失败或无数据返回 []
        """
        # 起点含 last_ts 本身：WS 断连时缓存里那根往往停在未闭合状态，
        # volume 残缺。跳过它则该根永不重取，见 sync_to_latest 同款注释。
        start_ms = int(last_ts.timestamp() * 1000)
        end_ms = int(new_ts.timestamp() * 1000)

        # 单次请求 1500 条上限，按末根开盘时间 +1 分钟翻页直到覆盖整个区间。
        # 曾用单次请求：20160 根的洞每轮 5 分钟维护只推进 1500 根，磨了 ~1 小时。
        all_rows: List = []
        cursor = start_ms
        try:
            while cursor < end_ms:
                rows = await self._fetch_from_binance_public(
                    symbol, start_time_ms=cursor, end_time_ms=end_ms,
                )
                if not rows:
                    break
                all_rows.extend(rows)
                cursor = int(rows[-1][0]) + 60_000  # 1m
            return all_rows
        except Exception as e:
            logger.warning(f"{symbol}: gap 拉取失败 ({last_ts} ~ {new_ts}): {e}")
            return []

    async def _fetch_hole_rows_archive_first(
        self, symbol: str, last_ts: datetime, new_ts: datetime,
    ) -> List:
        """运行时补洞：归档优先，fapi 分页兜底，**不写缓存**。

        先走 scripts/download_data.py::fetch_range_rows（整月/整日一次
        归档 zip，几乎不占 fapi 限额）；归档链路整体失败或返回空时退回
        _fetch_gap_range（fapi 分页）。历史大洞（如 CSV 只从某日开始）
        单轮即可补完，不再每次维护只推进 1500 根。

        区间含 last_ts 本身（残缺根需被完整值覆盖），与 _fetch_gap_range
        的 [含, 不含) 语义一致。
        """
        try:
            rows = await asyncio.to_thread(
                fetch_range_rows, symbol, "1m", last_ts, new_ts, _get_proxies(),
            )
            if rows:
                return rows
            logger.debug(
                f"{symbol}: 归档链路未取到数据 ({last_ts} ~ {new_ts})，fapi 兜底"
            )
        except Exception as e:
            logger.warning(
                f"{symbol}: 归档补齐失败 ({last_ts} ~ {new_ts})，fapi 兜底: {e}"
            )
        return await self._fetch_gap_range(symbol, last_ts, new_ts)

    async def _fill_gap_range(
        self, symbol: str, last_ts: datetime, new_ts: datetime,
    ) -> int:
        """通过 API 补齐 [last_ts, new_ts) 区间并写入缓存，返回补齐条数。

        Args:
            symbol: 交易对
            last_ts: 区间起点（含）
            new_ts: 区间终点（不含）

        Returns:
            实际补齐的条数，失败或无数据返回 0
        """
        api_data = await self._fetch_gap_range(symbol, last_ts, new_ts)
        if api_data:
            self._merge_api_data_to_cache(symbol, api_data)
            return len(api_data)
        return 0

    def _fill_ws_gap_async(
        self, symbol: str, last_ts: datetime, new_ts: datetime,
    ):
        """
        WS 检测到 gap 时，通过 API 补齐缺失数据

        注意：只能发现"末尾断档"（缓存末根 vs 新推送）。序列**中部**的洞
        对这条路径不可见 —— 由 scan_and_fill_holes 在定时任务里兜住。

        Args:
            symbol: 交易对
            last_ts: 缓存中最后一条时间
            new_ts: 新接收到的时间
        """
        async def _do_fill():
            n = await self._fill_gap_range(symbol, last_ts, new_ts)
            if n:
                logger.info(f"{symbol}: WS gap 已补齐 {n} 条")

        # 在已有事件循环中创建后台任务
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            loop.create_task(_do_fill())
        else:
            asyncio.run(_do_fill())

    def find_holes(
        self, symbol: str, max_holes: int = 50,
    ) -> List[Tuple[datetime, datetime]]:
        """扫描 1m 缓存，返回中部空洞的 [起点, 终点) 区间列表。

        `_on_kline_received` 的连续性检查只比较缓存末根与新推送，
        发现不了序列中部的洞；而聚合遇到洞既不报错也不丢桶，只让
        volume 静默偏低（桶还在、时间戳连续，结构上看不出异常）。
        所以必须有一条独立的全序列扫描。

        Args:
            symbol: 交易对
            max_holes: 单次最多返回多少个洞。超出时截断并告警 ——
                洞太多说明数据源有系统性问题，逐个补齐意义不大，
                应走全量重下。

        Returns:
            [(起点, 终点), ...]，起点为洞前最后一根，终点为洞后第一根。
            与 _fill_gap_range 的 [含, 不含) 语义一致。
        """
        df = self.cache.get_1m_data(symbol.upper())
        if df is None or df.empty or "timestamp" not in df.columns:
            return []
        if len(df) < 2:
            return []

        ts = df["timestamp"]
        # 1m 数据相邻间隔应为 60 秒。用 90 秒阈值与 _on_kline_received 对齐，
        # 容忍交易所时间戳的秒级抖动。
        diffs = ts.diff().dt.total_seconds()
        breaks = diffs > 90

        holes: List[Tuple[datetime, datetime]] = []
        for pos in np.flatnonzero(breaks.to_numpy()):
            prev_ts = ts.iloc[pos - 1]
            curr_ts = ts.iloc[pos]
            if hasattr(prev_ts, "to_pydatetime"):
                prev_ts = prev_ts.to_pydatetime()
            if hasattr(curr_ts, "to_pydatetime"):
                curr_ts = curr_ts.to_pydatetime()
            holes.append((prev_ts, curr_ts))

        if len(holes) > max_holes:
            logger.warning(
                f"{symbol}: 检测到 {len(holes)} 个数据空洞，超出单次上限 "
                f"{max_holes}，本轮只补前 {max_holes} 个（数据源可能有"
                f"系统性问题，建议全量重下）"
            )
            holes = holes[:max_holes]

        return holes

    async def scan_and_fill_holes(self, symbol: str) -> int:
        """扫描并补齐 1m 缓存中部的空洞，返回补齐条数。

        由定时维护任务调用（方案 C）：不碰 `_on_kline_received` 热路径，
        代价是洞最多存在一个维护周期（默认 5 分钟）。对 1h/8h 策略无
        实质影响，且洞主要来自 WS 断连，断连后本就有重连流程。

        Returns:
            实际补齐的条数
        """
        symbol_upper = symbol.upper()
        holes = self.find_holes(symbol_upper)
        if not holes:
            return 0

        logger.warning(
            f"{symbol_upper}: 检测到 {len(holes)} 个 1m 数据空洞，开始补齐"
        )
        # 先把所有洞的数据【全部取回】，再一次性合并 —— 不要逐洞写缓存。
        #
        # 策略计算是纯同步的（strategy.py 里没有 async def），所以它一旦
        # 开始取数就不会被打断；但每次 API 调用之间有 await，事件循环会
        # 在此切到策略回调。若逐洞写缓存，策略就可能读到"洞1已补、洞2未补"
        # 的中间态 1m 序列（实测：180→200→220→240 四种行数）。
        # 全部取回后单次 cache.put 是原子的（per-symbol RLock + 整体替换
        # DataFrame 引用），策略只能看到补齐前或补齐后，不存在中间态。
        collected: List = []
        for last_ts, new_ts in holes:
            missing = int((new_ts - last_ts).total_seconds() // 60) - 1
            # 归档优先（月/日 zip 一次拉完），失败再走 fapi 分页
            api_data = await self._fetch_hole_rows_archive_first(
                symbol_upper, last_ts, new_ts,
            )
            collected.extend(api_data)
            logger.info(
                f"{symbol_upper}: 空洞 [{last_ts} ~ {new_ts}) "
                f"缺 {missing} 根，取回 {len(api_data)} 条"
            )

        if not collected:
            logger.warning(f"{symbol_upper}: 空洞补齐未取到任何数据")
            return 0

        # 单次原子合并 + 重算大周期，避免大周期桶残留偏低的 volume
        self._merge_api_data_to_cache(symbol_upper, collected)
        self._update_big_intervals_from_cache(symbol_upper)
        logger.info(f"{symbol_upper}: 空洞补齐完成，共合并 {len(collected)} 条")
        return len(collected)

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
                cached_agg = self.cache.get(symbol, interval)
                period_minutes = self._parse_interval_to_minutes(interval)
                df_agg = None
                new_rows = None

                if (cached_agg is not None and not cached_agg.empty
                        and not self.config.backtest_mode and period_minutes > 0):
                    # 增量路径：只 resample 尾部 3 个周期的 1m 数据。
                    # 切片起点按行数取，通常落在桶中间，故必须丢弃残缺首桶
                    # —— 否则它会覆盖缓存里那根完整的同名桶，且此后不再被
                    # 任何路径重算。
                    tail_rows = period_minutes * 3
                    df_tail = (df_1m.iloc[-tail_rows:]
                               if len(df_1m) > tail_rows else df_1m)
                    df_inc = self.aggregate_1m_to_interval(
                        df_tail, interval, drop_partial_head=True,
                    )

                    # 增量起点必须晚于缓存起点，否则 keep 为空 → 退化成截断
                    if (df_inc is not None and not df_inc.empty
                            and df_inc['timestamp'].iloc[0] > cached_agg['timestamp'].iloc[0]):
                        keep = cached_agg[
                            cached_agg['timestamp'] < df_inc['timestamp'].iloc[0]
                        ]
                        df_agg = pd.concat([keep, df_inc], ignore_index=True)
                        new_rows = df_inc  # 仅新增/更新的行需要落 CSV

                if df_agg is None:
                    # 全量路径：冷启动 / 回测模式 / 缓存为空 / 增量前置条件不满足。
                    # 与增量路径同样需要丢弃残缺首桶：1m 缓存起点由
                    # default_1m_rows_limit 裁剪决定，落在任意分钟而非周期边界，
                    # 首桶只含所属周期的后半段（实测 8h 仅 59%、1h 仅 72%）。
                    # 该残缺根会经下方 save_klines_to_csv 按时间戳覆盖写进 CSV，
                    # 顶掉原本完整的同名根，且窗口滑过后不再被任何路径重算。
                    df_agg = self.aggregate_1m_to_interval(
                        df_1m, interval, drop_partial_head=True,
                    )
                    new_rows = df_agg

                if df_agg is None or df_agg.empty:
                    results[interval] = False
                    continue

                self.cache.put(symbol, interval, df_agg)
                # 回测模式不保存到 CSV
                if self.kline_repo and not self.config.backtest_mode:
                    rows = new_rows.to_dict(orient="records")
                    self.kline_repo.save_klines_to_csv(symbol, interval, rows)
                results[interval] = True
                # 聚合诊断日志
                src_start = df_1m['timestamp'].iloc[0]
                src_end = df_1m['timestamp'].iloc[-1]
                agg_start = df_agg['timestamp'].iloc[0]
                agg_end = df_agg['timestamp'].iloc[-1]
                inc_info = ""
                if new_rows is not None and new_rows is not df_agg:
                    inc_info = (
                        f" 增量({len(new_rows)}根) "
                        f"[{new_rows['timestamp'].iloc[0]} ~ {new_rows['timestamp'].iloc[-1]}]"
                    )
                logger.info(
                    f"{symbol} {interval}: 聚合 {len(df_agg)} 根 "
                    f"[{agg_start} ~ {agg_end}] | "
                    f"1m源 {len(df_1m)}行 [{src_start} ~ {src_end}]"
                    f"{inc_info}"
                )
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
            # 回退: 从 1m 聚合。1m 缓存起点未必对齐大周期边界，残缺首桶
            # 会让策略在失真的 open/high/low 上算指标，必须丢弃。
            df = self.aggregate_1m_to_interval(
                df_1m, interval, drop_partial_head=True,
            )
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

                # 重新聚合。与实盘路径保持相同的首桶语义，避免回测失真。
                df_agg = self.aggregate_1m_to_interval(
                    df_1m_filtered, interval, drop_partial_head=True,
                )
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
        启动定时维护后台任务

        每 N 分钟：
        1. 扫描并补齐 1m 缓存中部的空洞（WS 路径发现不了，见 find_holes）
        2. 将内存缓存中的 1m 数据刷新到 CSV
        3. 按 cache_1m_max_age_days / cache_1m_max_rows 裁剪 1m 缓存

        补洞放在持久化**之前**，让补回的数据在同一轮落盘；
        裁剪放在持久化之后，确保被淘汰的数据已落盘。

        Returns:
            创建的 asyncio.Task 对象
        """
        interval = self.config.persistence_interval_minutes

        async def _persistence_loop():
            logger.info(f"定时维护已启动，每 {interval} 分钟执行一次")
            while True:
                await asyncio.sleep(interval * 60)
                # 先补洞：WS 的连续性检查只看末根，中部空洞只能在这里发现。
                # 回测模式跳过 —— 数据已预加载，且不应触发网络请求。
                if not self.config.backtest_mode:
                    for symbol in list(self.cache._1m_cache.keys()):
                        try:
                            await self.scan_and_fill_holes(symbol)
                        except Exception as e:
                            logger.error(f"{symbol}: 空洞补齐失败: {e}")
                try:
                    self._flush_all_cache_to_csv()
                except Exception as e:
                    logger.error(f"定时持久化失败: {e}")
                # 先落盘再裁剪，避免淘汰未持久化的数据
                for symbol in list(self.cache._1m_cache.keys()):
                    try:
                        self.manage_memory_cache(symbol)
                    except Exception as e:
                        logger.error(f"{symbol}: 内存缓存裁剪失败: {e}")

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
