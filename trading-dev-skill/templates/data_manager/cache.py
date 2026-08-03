#!/usr/bin/env python3
"""
并发安全缓存模块 — ShardCache

设计：
- 每个 symbol 独立的读写锁（分片锁），避免全局锁竞争
- 1m 数据常驻内存，不受 LRU 淘汰
- 大周期（15m/1h/4h）使用 LRU 淘汰策略
- 线程安全：多线程并发读写不同 symbol 互不阻塞
"""

import logging
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Any

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ShardCacheConfig:
    """分片缓存配置"""
    # 大周期 LRU 最大条目数
    max_big_interval_entries: int = 5000
    # 1m 数据最大行数（超过时裁剪）
    default_1m_rows_limit: int = 500000
    # 1m 数据最大保留天数
    default_1m_age_days: int = 90


class ShardCache:
    """
    分片并发安全缓存

    每个 symbol 拥有独立的锁，不同 symbol 的读写互不阻塞。
    1m 数据和大周期数据分开存储。
    """

    def __init__(self, config: Optional[ShardCacheConfig] = None):
        self.config = config or ShardCacheConfig()

        # 1m 缓存：{symbol_upper: DataFrame}
        self._1m_cache: Dict[str, pd.DataFrame] = {}
        # 每个 symbol 独立的锁
        self._1m_locks: Dict[str, threading.RLock] = {}
        # 全局锁保护 _1m_locks 字典本身
        self._lock_registry = threading.RLock()

        # 大周期缓存：{KEY: DataFrame}，KEY = "{SYMBOL}_{INTERVAL}" 大写
        self._big_interval_cache: Dict[str, pd.DataFrame] = {}
        self._big_interval_lock = threading.RLock()
        # LRU 访问顺序
        self._access_order: List[str] = []

    # ==================== 内部工具 ====================

    def _get_1m_lock(self, symbol: str) -> threading.RLock:
        """获取或创建指定 symbol 的 1m 锁"""
        sym = symbol.upper()
        # 快路径：锁已存在
        if sym in self._1m_locks:
            return self._1m_locks[sym]
        # 慢路径：创建新锁
        with self._lock_registry:
            if sym not in self._1m_locks:
                self._1m_locks[sym] = threading.RLock()
            return self._1m_locks[sym]

    @staticmethod
    def _make_big_key(symbol: str, interval: str) -> str:
        return f"{symbol.upper()}_{interval.upper()}"

    @staticmethod
    def _is_1m_interval(interval: str) -> bool:
        return interval.lower() == "1m"

    # ==================== 1m 缓存操作 ====================

    def get_1m_data(self, symbol: str) -> Optional[pd.DataFrame]:
        """获取 1m 缓存数据（线程安全）"""
        sym = symbol.upper()
        lock = self._get_1m_lock(sym)
        with lock:
            df = self._1m_cache.get(sym)
            if df is not None and not df.empty:
                return df.copy()
            return None

    def put_1m_data(self, symbol: str, df: pd.DataFrame) -> None:
        """
        存入 1m 数据（线程安全）

        如果行数超过配置限制，自动裁剪为最新 N 行。
        """
        if df is None or df.empty:
            return

        sym = symbol.upper()
        lock = self._get_1m_lock(sym)
        with lock:
            trimmed = df
            max_rows = self.config.default_1m_rows_limit
            if len(trimmed) > max_rows:
                trimmed = trimmed.tail(max_rows).copy()
                logger.debug(f"{sym}: 1m 数据裁剪为 {max_rows} 行")
            self._1m_cache[sym] = trimmed

    def put(self, symbol: str, interval: str, df: pd.DataFrame,
            force_1m: bool = False) -> None:
        """统一存入接口"""
        if self._is_1m_interval(interval) or force_1m:
            self.put_1m_data(symbol, df)
        else:
            self._put_big_interval(symbol, interval, df)

    def get(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        """统一获取接口"""
        if self._is_1m_interval(interval):
            return self.get_1m_data(symbol)
        return self._get_big_interval(symbol, interval)

    # ==================== 大周期缓存操作（LRU） ====================

    def _put_big_interval(self, symbol: str, interval: str,
                          df: pd.DataFrame) -> None:
        """存入大周期数据（LRU 淘汰，线程安全）"""
        if df is None or df.empty:
            return

        key = self._make_big_key(symbol, interval)
        with self._big_interval_lock:
            if key not in self._big_interval_cache:
                # 需要淘汰
                while len(self._big_interval_cache) >= self.config.max_big_interval_entries:
                    if self._access_order:
                        oldest = self._access_order.pop(0)
                        self._big_interval_cache.pop(oldest, None)
                        logger.debug(f"LRU 淘汰: {oldest}")
                    else:
                        break

            if key in self._access_order:
                self._access_order.remove(key)

            self._big_interval_cache[key] = df
            self._access_order.append(key)

    def _get_big_interval(self, symbol: str, interval: str) -> Optional[pd.DataFrame]:
        """获取大周期数据（刷新 LRU 顺序，线程安全）"""
        key = self._make_big_key(symbol, interval)
        with self._big_interval_lock:
            if key not in self._big_interval_cache:
                return None

            # 刷新访问顺序
            if key in self._access_order:
                self._access_order.remove(key)
            self._access_order.append(key)

            df = self._big_interval_cache[key]
            if df is not None and not df.empty:
                return df.copy()
            return None

    # ==================== 移除和清空 ====================

    def remove(self, symbol: str, interval: str) -> None:
        """移除指定缓存"""
        sym = symbol.upper()
        if self._is_1m_interval(interval):
            lock = self._get_1m_lock(sym)
            with lock:
                self._1m_cache.pop(sym, None)
        else:
            key = self._make_big_key(sym, interval)
            with self._big_interval_lock:
                self._big_interval_cache.pop(key, None)
                if key in self._access_order:
                    self._access_order.remove(key)

    def clear(self) -> None:
        """清空所有缓存"""
        with self._lock_registry:
            self._1m_cache.clear()
            self._1m_locks.clear()

        with self._big_interval_lock:
            self._big_interval_cache.clear()
            self._access_order.clear()

    def clear_symbol(self, symbol: str) -> None:
        """清空指定 symbol 的所有缓存（1m + 大周期）"""
        sym = symbol.upper()

        # 清空 1m
        lock = self._get_1m_lock(sym)
        with lock:
            self._1m_cache.pop(sym, None)

        # 清空大周期中该 symbol 的所有条目
        with self._big_interval_lock:
            keys_to_remove = [
                k for k in self._big_interval_cache
                if k.startswith(f"{sym}_")
            ]
            for key in keys_to_remove:
                self._big_interval_cache.pop(key, None)
                if key in self._access_order:
                    self._access_order.remove(key)

    # ==================== 状态查询 ====================

    def get_status(self) -> Dict[str, Any]:
        """获取缓存状态快照"""
        with self._lock_registry:
            symbols_1m = list(self._1m_cache.keys())
            row_counts = {
                s: len(df)
                for s, df in self._1m_cache.items()
            }

        with self._big_interval_lock:
            big_keys = list(self._big_interval_cache.keys())
            big_sizes = {
                k: len(df)
                for k, df in self._big_interval_cache.items()
            }

        return {
            '1m_symbols': set(symbols_1m),
            '1m_row_count': row_counts,
            'big_interval_entries': len(big_keys),
            'big_interval_keys': set(big_keys),
            'big_interval_sizes': big_sizes,
            'max_big_interval_entries': self.config.max_big_interval_entries,
        }
