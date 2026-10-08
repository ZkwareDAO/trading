#!/usr/bin/env python3
"""
K 线仓库模块 - 轻量级多时间框架更新管理

功能:
- 维护 symbol 和时间框架的注册关系
- 记录每个 symbol 最后更新的时间框架
- 1m K 线更新时触发大周期聚合（直接保存到 CSV）
- 不存储 K 线数据在内存中，读取时从 CSV 加载

设计原则:
- 轻量级：只维护元数据和更新标识
- 懒加载：需要时从 CSV 读取数据
- 实时聚合：1m 更新时立即聚合并保存到大周期 CSV
"""

import io
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass, field
import threading

import pandas as pd

from data_manager.klines_loader import resample_ohlcv

logger = logging.getLogger(__name__)


@dataclass
class SymbolState:
    """Symbol 状态信息"""

    symbol: str
    registered_timeframes: Set[str] = field(default_factory=set)  # 注册的时间框架
    last_updated_timeframe: Optional[str] = None  # 最后更新的时间框架
    last_update_time: Optional[datetime] = None  # 最后更新时间
    last_1m_kline_time: Optional[datetime] = None  # 最后一条 1m K 线时间


class KlineRepository:
    """
    K 线仓库类 - 轻量级设计

    仅维护：
    - symbol 与时间框架的注册关系
    - 最后更新的时间框架标识
    - 触发聚合时直接写入 CSV 文件

    不存储：
    - K 线数据本身（读取时从 CSV 加载）
    """

    # 尾部重写时向文件末尾回扫的最大字节数。
    # 增量聚合只重写最后 1-2 根 K 线，1MB 足够覆盖上万行的重叠窗口；
    # 超出则判定重叠过深，回退全量合并。
    _TAIL_SCAN_BYTES = 1024 * 1024

    # 聚合时源数据读取行数的下界与"窗口天数"上界。
    # 下界保证即使目标 CSV 刚更新过也读到足够上下文。
    # 上界防止目标 CSV 长期未更新（策略停跑多日）时把读取退化成全量扫描，
    # 同时必须足够大以补齐停跑期间缺失的大周期 K 线——夹太小会在 CSV 中
    # 留下永久空洞（末根写上了，中间补不回）。14 天覆盖绝大多数停机场景，
    # 1m 源下约 2 万行，实测聚合 ~30ms，可接受。
    MIN_SOURCE_LIMIT = 1000
    MAX_SOURCE_WINDOW_DAYS = 14
    # 目标 CSV 为空（冷启动）时的读取行数：一次性多读些把近期历史建起来，
    # 该分支只在首次聚合走到，不影响稳态开销。
    COLD_START_SOURCE_LIMIT = 20000

    def __init__(self, csv_dir: str = "./data/klines"):
        """
        初始化 K 线仓库

        Args:
            csv_dir: CSV 文件存储目录
        """
        self.csv_dir = Path(csv_dir)
        self.csv_dir.mkdir(parents=True, exist_ok=True)

        # Symbol 状态：{symbol: SymbolState}
        self._states: Dict[str, SymbolState] = {}

        # 线程锁
        self._lock = threading.RLock()

    def register_symbol(self, symbol: str, timeframes: List[str]):
        """
        注册 symbol 及其需要的时间框架

        Args:
            symbol: 交易对
            timeframes: 时间框架列表
        """
        with self._lock:
            if symbol not in self._states:
                self._states[symbol] = SymbolState(symbol=symbol)

            state = self._states[symbol]
            old_count = len(state.registered_timeframes)
            state.registered_timeframes.update(timeframes)
            new_count = len(state.registered_timeframes)

            if new_count > old_count:
                logger.info(
                    f"{symbol} 注册时间框架：{timeframes}, 当前已注册：{state.registered_timeframes}"
                )

    def _get_file_path(self, symbol: str, timeframe: str) -> Path:
        """获取 CSV 文件路径

        固定格式: {csv_dir}/{timeframe}/{SYMBOL}_{timeframe}.csv
        """
        timeframe = timeframe.lower()
        symbol_upper = symbol.upper()
        filename = f"{symbol_upper}_{timeframe}.csv"
        return self.csv_dir / timeframe / filename

    def save_klines_to_csv(
        self, symbol: str, interval: str, klines: List[Dict[str, Any]]
    ) -> bool:
        """统一 CSV 持久化入口 — 时间戳 = 唯一主键。

        所有 K 线数据持久化（WS 推送、gap 补齐、API 回退、缓存保存）
        都调用此方法，确保：
        1. 读现有 CSV
        2. 合并新旧数据
        3. 按时间戳去重（新覆盖旧）
        4. 按时间戳排序
        5. 写回 CSV

        Args:
            symbol: 交易对（大小写不敏感）
            interval: K 线周期（大小写不敏感）
            klines: K 线字典列表，须包含 timestamp/open/high/low/close/volume

        Returns:
            是否保存成功
        """
        if not klines:
            return False

        filepath = self._get_file_path(symbol, interval)

        df_new = pd.DataFrame(klines)

        # 验证必要列
        required_cols = ["timestamp", "open", "high", "low", "close", "volume"]
        for col in required_cols:
            if col not in df_new.columns:
                logger.error(f"save_klines_to_csv: 缺少必要列 {col}")
                return False

        # 解析/规范化时间戳（支持毫秒数字和已解析的 datetime）
        if "timestamp" in df_new.columns:
            if pd.api.types.is_numeric_dtype(df_new["timestamp"]):
                df_new["timestamp"] = pd.to_datetime(df_new["timestamp"], unit="ms", utc=True)
            else:
                df_new["timestamp"] = pd.to_datetime(df_new["timestamp"], utc=True)
            # 截断到秒级，与 CSV 存储格式对齐（strftime 不带毫秒），确保去重匹配
            df_new["timestamp"] = df_new["timestamp"].dt.floor("s")

        # 智能合并保存：快速路径直接追加，仅重叠时全量合并
        if self._smart_merge_save(df_new, filepath, f"{symbol.upper()} {interval}"):
            return True

        if filepath.exists():
            # 慢速路径：全量合并去重
            try:
                df_existing = pd.read_csv(filepath)
                if not df_existing.empty:
                    df_existing["timestamp"] = pd.to_datetime(
                        df_existing["timestamp"], utc=True
                    )
                    df_combined = pd.concat([df_existing, df_new], ignore_index=True)
                    df_combined["timestamp"] = pd.to_datetime(
                        df_combined["timestamp"], utc=True
                    )
                    df_combined = df_combined.drop_duplicates(
                        subset=["timestamp"], keep="last"
                    )
                    df_combined = df_combined.sort_values("timestamp").reset_index(
                        drop=True
                    )
                    df_to_save = df_combined
                else:
                    df_to_save = df_new
            except Exception as e:
                logger.error(f"读取已有 CSV 失败，使用新数据保存：{e}")
                df_to_save = df_new
        else:
            df_to_save = df_new

        try:
            self._save_dataframe(df_to_save, filepath)
            logger.info(
                f"{symbol.upper()} {interval}: 保存了 {len(df_to_save)} 条 → {filepath}"
            )
            return True
        except Exception as e:
            logger.error(f"保存 CSV 失败 {symbol.upper()} {interval}: {e}")
            return False

    def save_dataframe_to_csv(
        self, symbol: str, interval: str, df: pd.DataFrame,
    ) -> bool:
        """保存 DataFrame 到 CSV — 时间戳 = 唯一主键。

        与 save_klines_to_csv 行为一致：
        1. 读现有 CSV
        2. 合并
        3. 按时间戳去重（新覆盖旧）
        4. 排序
        5. 写入

        Args:
            symbol: 交易对
            interval: K 线周期
            df: K 线数据 DataFrame

        Returns:
            是否保存成功
        """
        if df is None or df.empty:
            return False

        filepath = self._get_file_path(symbol, interval)
        df_to_save = df.copy()

        # 验证必要列
        required_cols = ["timestamp", "open", "high", "low", "close", "volume"]
        for col in required_cols:
            if col not in df_to_save.columns:
                logger.error(f"save_dataframe_to_csv: 缺少必要列 {col}")
                return False

        # 智能合并保存：快速路径直接追加，仅重叠时全量合并
        # 规范化时间戳（与 CSV 存储格式对齐）
        if pd.api.types.is_numeric_dtype(df_to_save["timestamp"]):
            df_to_save["timestamp"] = pd.to_datetime(
                df_to_save["timestamp"], unit="ms", utc=True
            )
        else:
            df_to_save["timestamp"] = pd.to_datetime(
                df_to_save["timestamp"], utc=True
            )
        df_to_save["timestamp"] = df_to_save["timestamp"].dt.floor("s")

        if self._smart_merge_save(df_to_save, filepath, f"{symbol.upper()} {interval}"):
            return True

        if filepath.exists():
            # 慢速路径：全量合并
            try:
                df_existing = pd.read_csv(filepath)
                if not df_existing.empty:
                    df_existing["timestamp"] = pd.to_datetime(
                        df_existing["timestamp"], utc=True
                    )
                    df_merged = pd.concat(
                        [df_existing, df_to_save], ignore_index=True
                    )
                    df_merged["timestamp"] = pd.to_datetime(
                        df_merged["timestamp"], utc=True
                    )
                    df_to_save = df_merged.sort_values("timestamp").reset_index(
                        drop=True
                    )
            except Exception as e:
                logger.warning(f"读取现有 CSV 失败，直接覆盖：{e}")

        # 确保必要列 + 排序
        available_cols = [c for c in required_cols if c in df_to_save.columns]
        extra_cols = [c for c in df_to_save.columns if c not in required_cols]
        df_to_save = df_to_save[available_cols + extra_cols]
        df_to_save = df_to_save.drop_duplicates(subset=["timestamp"], keep="last")
        df_to_save = df_to_save.sort_values("timestamp").reset_index(drop=True)

        try:
            self._save_dataframe(df_to_save, filepath)
            logger.info(
                f"{symbol.upper()} {interval}: 缓存持久化 {len(df_to_save)} 条 → {filepath}"
            )
            return True
        except Exception as e:
            logger.error(f"缓存持久化失败 {symbol.upper()} {interval}: {e}")
            return False


    def _get_dataframe(
        self, symbol: str, timeframe: str, limit: int = 5000
    ) -> Optional[pd.DataFrame]:
        """
        从 CSV 文件加载数据

        Args:
            symbol: 交易对
            timeframe: 时间框架
            limit: 最大加载条数（有值时只读尾部，避免加载全量）

        Returns:
            DataFrame 对象
        """
        filepath = self._get_file_path(symbol, timeframe)

        if not filepath.exists():
            logger.debug(f"CSV 文件不存在：{filepath}")
            return None

        try:
            if limit:
                # 有 limit 时只读尾部，避免加载全量 CSV（1m 可达 190 万行）
                df = self._read_csv_tail(filepath, nrows=limit)
                if df is None:
                    # tail 读失败，回退全量读
                    df = pd.read_csv(filepath)
                    if "timestamp" in df.columns:
                        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            else:
                df = pd.read_csv(filepath)
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)

            if df is None or df.empty:
                return df

            # 按时间排序
            df = df.sort_values("timestamp").reset_index(drop=True)

            # 限制条数
            if limit and len(df) > limit:
                df = df.tail(limit)

            return df

        except Exception as e:
            logger.error(f"加载 CSV 失败 {filepath}: {e}")
            return None

    def _get_last_kline_time(self, symbol: str, timeframe: str) -> Optional[datetime]:
        """获取 CSV 文件中最后一条 K 线的时间

        必须读文件尾部：曾用 pd.read_csv(nrows=1) 读到的是**首行**
        （最早的 K 线），使 _get_aggregation_start_time 算出的 start_ts
        早于全部源数据，增量聚合的时间过滤退化为空操作。

        本方法每分钟每周期各调用一次，不能复用 _read_csv_tail —— 它对
        < 10MB 的文件走全量读。这里只需最后一行的第一个字段，
        直接按字节回扫即可，开销与文件大小无关。
        """
        filepath = self._get_file_path(symbol, timeframe)

        if not filepath.exists():
            return None

        try:
            last_line = self._read_last_line(filepath)
            if not last_line:
                return None

            ts_field = last_line.split(",", 1)[0].strip()
            if not ts_field or ts_field.lower() == "timestamp":
                return None

            last_ts = pd.to_datetime(ts_field, utc=True)
            if pd.isna(last_ts):
                return None
            return last_ts

        except Exception as e:
            logger.debug(f"获取 {symbol} {timeframe} 最后时间失败：{e}")
            return None

    @staticmethod
    def _read_last_line(filepath: Path, probe_bytes: int = 4096) -> Optional[str]:
        """读取文件最后一行非空文本，开销与文件大小无关。

        从尾部回扫 probe_bytes，逐步加倍直到确认拿到的是完整的一行：
        seek 可能落在行中间，只有读到 >= 2 行（或已覆盖整个文件）才能保证
        最后一行未被截断。返回 None 表示文件为空或读取失败。
        """
        try:
            size = filepath.stat().st_size
            if size == 0:
                return None

            span = min(probe_bytes, size)
            while True:
                with open(filepath, "rb") as f:
                    f.seek(size - span)
                    lines = [ln for ln in f.read(span).split(b"\n") if ln.strip()]
                if len(lines) >= 2 or span >= size:
                    break
                span = min(span * 2, size)

            if not lines:
                return None
            return lines[-1].decode("utf-8", errors="replace")
        except Exception:
            return None

    def _get_interval_minutes(self, timeframe: str) -> int:
        """时间框架换算为分钟数，无法解析时返回 0。"""
        tf = timeframe.lower().strip()
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

    def _resolve_source_limit(
        self,
        source_tf: str,
        start_ts: Optional[datetime],
        period_minutes: int,
    ) -> int:
        """计算源数据读取行数：覆盖 start_ts，且不超出有界窗口。

        _get_dataframe 按"尾部 N 行"截断，而 start_ts 是周期边界对齐的
        时间点。两者不协商时，尾部窗口的起点会落在目标周期桶中间，
        且策略停跑多日后重启时读不到停跑区间，
        大周期 CSV 会留下永久空洞（末根写上了，中间补不回）。
        这里按 start_ts 到当前时间的跨度反推行数。

        上界按 MAX_SOURCE_WINDOW_DAYS 天与 3 个目标周期取大：前者把稳态开销
        钉在毫秒级，后者保证 1d 这类大周期仍能覆盖到 start_ts。

        Args:
            source_tf: 源时间框架（决定每行代表多少分钟）
            start_ts: 聚合起始时间，None 表示目标 CSV 为空（冷启动）
            period_minutes: 目标周期的分钟数，用作冗余余量

        Returns:
            读取行数，落在 [MIN_SOURCE_LIMIT, 有界上限] 内
        """
        if start_ts is None:
            # 冷启动：目标 CSV 为空，一次性多读些把近期历史建起来
            return self.COLD_START_SOURCE_LIMIT

        source_minutes = self._get_interval_minutes(source_tf) or 1

        # 有界窗口上限：max(N 天, 3 个目标周期)，换算成源数据行数
        window_minutes = max(
            self.MAX_SOURCE_WINDOW_DAYS * 24 * 60, period_minutes * 3
        )
        max_limit = int(window_minutes / source_minutes) + 1

        start = pd.Timestamp(start_ts)
        if start.tzinfo is None:
            start = start.tz_localize("UTC")
        # 时钟漂移可能让 start_ts 落在未来，钳到 0 避免负数行数
        span_minutes = max(
            0.0, (pd.Timestamp.now(tz="UTC") - start).total_seconds() / 60
        )

        # 跨度换算成源数据行数，再加一个目标周期的冗余，
        # 抵消源数据缺口与尾部读取的行对齐误差。
        limit = int((span_minutes + period_minutes) / source_minutes) + 1

        return max(self.MIN_SOURCE_LIMIT, min(limit, max_limit))

    def _get_interval_hours(self, timeframe: str) -> Optional[int]:
        """获取时间周期对应的小时数，分钟级返回 0，无法解析返回 None。

        d/w 必须带上倍数：曾经无条件返回 24 / 168，于是 "3d" 被当成 "1d"，
        _get_aggregation_start_time 只往回退 1 天而非 3 天，源数据窗口不足
        一个完整周期，首桶残缺（靠 drop_partial_head 兜掉，表现为少一根）。
        """
        tf = timeframe.lower().strip()
        try:
            if tf.endswith("h"):
                return int(tf[:-1])
            if tf.endswith("m"):
                return 0
            if tf.endswith("d"):
                return int(tf[:-1]) * 24
            if tf.endswith("w"):
                return int(tf[:-1]) * 24 * 7
        except ValueError:
            return None
        return None

    def update_from_1m(
        self, symbol: str, new_1m_klines: List[Dict[str, Any]]
    ) -> Dict[str, bool]:
        """
        从新的 1m K 线更新所有已注册的时间框架

        核心逻辑：
        1. 更新 1m CSV 文件
        2. 对于每个已注册的大周期，从 1m CSV 读取数据并聚合
        3. 直接写入大周期 CSV 文件
        4. 不存储数据在内存中

        Args:
            symbol: 交易对
            new_1m_klines: 新的 1m K 线列表（字典格式）

        Returns:
            更新时间框架结果 {timeframe: 是否成功}
        """
        if not new_1m_klines:
            return {}

        with self._lock:
            results = {}

            # 更新 1m CSV 文件
            success_1m = self._update_1m_csv(symbol, new_1m_klines)
            results["1m"] = success_1m

            if not success_1m:
                logger.warning(f"{symbol} 1m 数据更新失败")
                return results

            # 更新状态
            if symbol not in self._states:
                self._states[symbol] = SymbolState(symbol=symbol)

            state = self._states[symbol]
            state.last_updated_timeframe = "1m"
            state.last_update_time = datetime.now(timezone.utc)

            # 获取最后一条 1m K 线时间
            if new_1m_klines:
                last_kline = new_1m_klines[-1]
                state.last_1m_kline_time = last_kline.get("timestamp")

            # 获取需要聚合的大周期
            target_timeframes = state.registered_timeframes - {"1m"}

            for target_tf in target_timeframes:
                try:
                    result = self._aggregate_and_save(symbol, "1m", target_tf)
                    results[target_tf] = result

                    if result:
                        logger.debug(f"{symbol} {target_tf}: 聚合成功")
                    else:
                        logger.debug(f"{symbol} {target_tf}: 聚合无新数据")

                except Exception as e:
                    logger.error(f"{symbol} {target_tf}: 聚合失败：{e}")
                    results[target_tf] = False

            # 更新最后更新时间框架（如果所有大周期都成功）
            if all(results.values()):
                state.last_updated_timeframe = "all"

            return results

    def _update_1m_csv(self, symbol: str, new_klines: List[Dict[str, Any]]) -> bool:
        """更新 1m CSV 文件（委托给 save_klines_to_csv）"""
        return self.save_klines_to_csv(symbol, "1m", new_klines)

    def _aggregate_and_save(self, symbol: str, source_tf: str, target_tf: str) -> bool:
        """
        从源时间框架聚合并保存到目标时间框架 CSV

        Args:
            symbol: 交易对
            source_tf: 源时间框架
            target_tf: 目标时间框架

        Returns:
            是否成功
        """
        # 先确定聚合起始时间，再据此决定要读多少源数据。
        # 顺序不能反：start_ts 决定"该从哪聚合"，limit 决定"实际读到哪"，
        # 若 limit 用写死的公式，其起点可能晚于 start_ts，落在目标周期桶
        # 中间；且策略停跑多日后重启时读不到停跑区间，
        # 大周期 CSV 会留下永久空洞。
        start_ts = self._get_aggregation_start_time(symbol, target_tf)

        period_minutes = self._get_interval_minutes(target_tf) or 24 * 60
        limit = self._resolve_source_limit(source_tf, start_ts, period_minutes)

        df_source = self._get_dataframe(symbol, source_tf, limit=limit)

        if df_source is None or df_source.empty:
            logger.debug(f"{symbol}: 没有 {source_tf} 数据，无法聚合 {target_tf}")
            return False

        # 过滤需要聚合的数据（start_ts 已在读取前算出）
        if start_ts:
            df_to_aggregate = df_source[df_source["timestamp"] >= start_ts]
        else:
            df_to_aggregate = df_source

        if df_to_aggregate.empty:
            logger.debug(f"{symbol} {target_tf}: 没有需要聚合的数据")
            return True  # 没有新数据也算成功

        # 聚合
        logger.debug(
            f"{symbol}: 从 {len(df_to_aggregate)} 条 {source_tf} K 线聚合 {target_tf}..."
        )
        # start_ts 已 floor 到周期边界，但 df_source 是 limit 尾部切片：
        # start_ts 为 None 或早于切片起点时，首桶仍会残缺。下游按时间戳
        # 覆盖写 CSV，残缺桶会顶掉已有的完整桶，故统一丢弃。
        df_aggregated = resample_ohlcv(
            df_to_aggregate, target_tf, datetime_column="timestamp",
            drop_partial_head=True,
        )

        if df_aggregated.empty:
            logger.debug(f"{symbol} {target_tf}: 聚合结果为空")
            return True

        # 智能合并保存
        filepath = self._get_file_path(symbol, target_tf)

        if self._smart_merge_save(df_aggregated, filepath, f"{symbol} {target_tf}"):
            return True

        if filepath.exists():
            # 慢速路径：全量合并
            try:
                df_existing = pd.read_csv(filepath)
                if not df_existing.empty:
                    df_existing["timestamp"] = pd.to_datetime(
                        df_existing["timestamp"], utc=True
                    )

                    existing_timestamps = set(df_existing["timestamp"].tolist())

                    to_update = []
                    to_append = []

                    for _, row in df_aggregated.iterrows():
                        if row["timestamp"] in existing_timestamps:
                            to_update.append(row)
                        else:
                            to_append.append(row)

                    # 更新已存在的行
                    if to_update:
                        update_df = pd.DataFrame(to_update)
                        for ts in update_df["timestamp"].unique():
                            mask = df_existing["timestamp"] == ts
                            df_existing.loc[mask] = update_df[
                                update_df["timestamp"] == ts
                            ].values[0]
                        logger.debug(
                            f"{symbol} {target_tf}: 更新了 {len(to_update)} 条 K 线"
                        )

                    # 追加新行
                    if to_append:
                        append_df = pd.DataFrame(to_append)
                        df_existing = pd.concat(
                            [df_existing, append_df], ignore_index=True
                        )
                        logger.debug(
                            f"{symbol} {target_tf}: 追加了 {len(to_append)} 条 K 线"
                        )

                    df_to_save = df_existing
                else:
                    df_to_save = df_aggregated

            except Exception as e:
                logger.error(f"读取现有 {target_tf} CSV 失败：{e}")
                df_to_save = df_aggregated
        else:
            df_to_save = df_aggregated

        # 排序并保存
        df_to_save = df_to_save.sort_values("timestamp").reset_index(drop=True)

        try:
            self._save_dataframe(df_to_save, filepath)
            logger.info(f"{symbol} {target_tf}: 保存了 {len(df_to_save)} 条记录")
            return True
        except Exception as e:
            logger.error(f"保存 {target_tf} CSV 失败：{e}")
            return False

    def _get_aggregation_start_time(
        self, symbol: str, target_tf: str
    ) -> Optional[datetime]:
        """
        获取聚合的起始时间

        从目标 CSV 读取最后一条 K 线时间，向下对齐到周期边界，
        并往回多取一个周期以确保包含未关闭的 K 线

        Args:
            symbol: 交易对
            target_tf: 目标时间框架

        Returns:
            起始时间
        """
        last_ts = self._get_last_kline_time(symbol, target_tf)

        if last_ts is None:
            return None

        interval_hours = self._get_interval_hours(target_tf)

        if interval_hours and interval_hours >= 24:
            # 日线及以上：对齐到当日午夜，再往回退一个完整周期。
            # 不能走下面的 `hour // interval_hours` 分支 —— 那个式子对
            # interval_hours >= 24 恒等于 0，只是碰巧等价于"取午夜"，
            # 语义上是巧合而非意图。
            start_ts = pd.Timestamp(last_ts).normalize() - pd.Timedelta(
                hours=interval_hours
            )
            return start_ts.to_pydatetime()
        elif interval_hours and interval_hours > 0:
            # 向下对齐到周期边界
            # 将 datetime 转换为 pandas Timestamp 以使用 floor 方法
            last_ts_pd = pd.Timestamp(last_ts)
            start_ts = last_ts_pd.floor("h").replace(
                hour=(last_ts.hour // interval_hours) * interval_hours,
                minute=0,
                second=0,
                microsecond=0,
            )
            # 往回多取一个周期
            start_ts = start_ts - pd.Timedelta(hours=interval_hours)
            return start_ts.to_pydatetime()
        elif interval_hours == 0:
            # 分钟级别周期
            return last_ts - pd.Timedelta(minutes=15)
        else:
            return last_ts - pd.Timedelta(days=1)

    @staticmethod
    def _format_timestamp_for_csv(df: pd.DataFrame) -> pd.DataFrame:
        """格式化时间戳列为 UTC 字符串，返回新 DataFrame。

        格式 "%Y-%m-%d %H:%M:%S+00:00" 与 _try_tail_rewrite 的字节级
        查找硬编码一致，修改此处必须同步更新 _try_tail_rewrite。
        """
        result = df.copy()
        if result["timestamp"].dt.tz is None:
            result["timestamp"] = result["timestamp"].dt.tz_localize("UTC")
        else:
            result["timestamp"] = result["timestamp"].dt.tz_convert("UTC")
        result["timestamp"] = result["timestamp"].dt.strftime(
            "%Y-%m-%d %H:%M:%S+00:00"
        )
        return result

    def _save_dataframe(self, df: pd.DataFrame, filepath: Path):
        """保存 DataFrame 到 CSV"""
        save_df = self._format_timestamp_for_csv(df)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        save_df.to_csv(filepath, index=False)

    def _read_csv_tail(
        self, filepath: Path, nrows: int = 500
    ) -> Optional[pd.DataFrame]:
        """高效读取 CSV 尾部 N 行，用于时间戳重叠检测。

        小文件 (< 10MB) 直接全量读取；大文件用 seek 只读尾部。
        返回 None 表示读取失败。
        """
        if not filepath.exists():
            return None
        try:
            file_size = filepath.stat().st_size
            if file_size < 10 * 1024 * 1024:  # < 10MB: 全量读
                df = pd.read_csv(filepath)
                if "timestamp" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
                return df.tail(nrows)

            # 大文件：seek 到尾部读取，避免读全量
            # bytes_per_line=80 覆盖 taker_buy_* 等额外列，5x 乘数覆盖估算误差
            bytes_per_line = 80
            read_bytes = min(nrows * bytes_per_line * 5, file_size)
            with open(filepath, "rb") as f:
                f.seek(max(0, file_size - read_bytes))
                raw_lines = f.readlines()
            if len(raw_lines) <= 1:
                return pd.DataFrame()
            # 读取 header 拼接到尾部数据前面
            with open(filepath, "r") as f:
                header = f.readline()

            csv_text = header + b"".join(raw_lines[1:]).decode("utf-8")
            df = pd.read_csv(io.StringIO(csv_text))
            if "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
            return df.tail(nrows)
        except Exception as e:
            logger.debug(f"读取 CSV 尾部失败 {filepath}: {e}")
            return None

    def _append_to_csv(self, df: pd.DataFrame, filepath: Path):
        """追加 DataFrame 到已有 CSV 文件（不读全量，极快）。

        列顺序与已有 CSV header 对齐，时间戳格式与 _save_dataframe 一致。

        Raises:
            ValueError: 待写入列集与 CSV header 不一致（缺列或多列）。
                两个方向都必须拒绝，否则各有一种静默损坏：

                - 缺列：写出短行。header 仍是 N 列而数据行只有 N-1 个值，
                  pandas 按位置解析导致后续列整体左移（quote_volume 被
                  相邻列的值顶掉）。已落盘即不可逆。
                - 多列：多余列被静默丢弃，文件永远停在旧 schema。这是
                  data/klines 全部停留在 6 列的原因——实盘 API 明明写
                  10 列也扩不回去。

                抛错后 _smart_merge_save 回退到全量合并路径，那里用
                pd.concat 取列的并集（缺失处补 NaN），既不错位也能让
                header 自然升级到更宽的 schema。
        """
        existing_cols = pd.read_csv(filepath, nrows=0).columns.tolist()
        missing = [c for c in existing_cols if c not in df.columns]
        extra = [c for c in df.columns if c not in existing_cols]
        if missing or extra:
            raise ValueError(
                f"追加数据列集与 CSV header 不一致 (缺少={missing}, 多余={extra})，"
                f"拒绝追加以免列错位/丢列，回退全量合并"
            )
        # 对齐列顺序，再格式化时间戳
        save_df = df[existing_cols]
        save_df = self._format_timestamp_for_csv(save_df)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        save_df.to_csv(filepath, mode="a", header=False, index=False)

    def _smart_merge_save(
        self, df_new: pd.DataFrame, filepath: Path, log_label: str
    ) -> bool:
        """智能合并保存：依次尝试快速追加和尾部重写，任一成功即返回 True。
        均不满足时返回 False，调用方应回退到全量合并。
        """
        return (
            self._try_fast_append(df_new, filepath, log_label)
            or self._try_tail_rewrite(df_new, filepath, log_label)
        )

    def _try_fast_append(
        self, df_new: pd.DataFrame, filepath: Path, log_label: str
    ) -> bool:
        """尝试快速追加：读尾部检测重叠，无重叠则追加并返回 True。

        有重叠或任何异常返回 False，调用方应回退到全量合并。
        """
        if not filepath.exists():
            return False
        df_tail = self._read_csv_tail(filepath)
        if df_tail is None or df_tail.empty:
            return False
        latest_existing = df_tail["timestamp"].max()
        earliest_new = df_new["timestamp"].min()
        if earliest_new <= latest_existing:
            return False
        try:
            df_to_append = df_new.drop_duplicates(
                subset=["timestamp"], keep="last"
            )
            self._append_to_csv(df_to_append, filepath)
            logger.info(f"{log_label}: 追加了 {len(df_to_append)} 条 → {filepath}")
            return True
        except Exception as e:
            logger.debug(f"追加 CSV 失败，回退到全量保存：{e}")
            return False

    def _try_tail_rewrite(
        self, df_new: pd.DataFrame, filepath: Path, log_label: str
    ) -> bool:
        """尝试尾部重写：重叠仅限文件尾部时，truncate 掉重叠行再 append。

        增量聚合每次都会重写未闭合的最后几根 K 线，时间戳必然与 CSV 尾部重叠。
        全量合并的成本由文件总行数决定；尾部重写只与重叠行数相关。

        用 _read_csv_tail 获取尾部 DataFrame 做内存比对，找到截断点后
        seek+truncate+append。不逐行解析文件。

        成功返回 True；重叠深入文件中部、或任何异常时返回 False，
        调用方应回退到全量合并。
        """
        if not filepath.exists():
            return False
        try:
            # 1000 行足够覆盖所有周期的尾部重叠窗口。
            # 增量聚合最多重写 3 个周期的 K 线；1d = 1440 分钟也只需 ~1500 行，
            # 但 _read_csv_tail 已在内存中完成比对，1000 行足够检测尾部重叠深度。
            df_tail = self._read_csv_tail(filepath, nrows=1000)
            if df_tail is None or df_tail.empty:
                return False

            earliest_new = df_new["timestamp"].min()
            new_ts = set(df_new["timestamp"].dropna())

            # 在内存中找第一条 >= earliest_new 的行，其字节偏移即截断点
            tail_ts = df_tail["timestamp"]
            overlap_mask = tail_ts >= earliest_new
            if not overlap_mask.any():
                # 没有重叠 → 纯新增，交给 append 路径
                return False

            overlap_in_tail = tail_ts[overlap_mask]
            # 如果重叠行中任何一条不在新数据里，则不是纯尾部覆盖
            for ts in overlap_in_tail:
                if ts not in new_ts:
                    return False
            # 如果 tail 的第一条就已经重叠，说明重叠可能更深入文件主体
            if overlap_mask.iloc[0]:
                return False

            # 找出截断点：最后一条 < earliest_new 的行的位置
            before_idx = (~overlap_mask).sum() - 1
            if before_idx < 0:
                return False
            truncate_ref_ts = tail_ts.iloc[before_idx]

            # 用字节偏移定位截断点：从尾扫描找到 truncate_ref_ts 所在行
            file_size = filepath.stat().st_size
            scan_bytes = min(self._TAIL_SCAN_BYTES, file_size)
            if scan_bytes <= 0:
                return False
            with open(filepath, "rb") as f:
                f.seek(max(0, file_size - scan_bytes))
                chunk = f.read(scan_bytes)
                chunk_start = max(0, file_size - scan_bytes)

            # 丢弃首个不完整行
            first_nl = chunk.find(b"\n")
            if first_nl == -1:
                return False
            cursor = chunk_start + first_nl + 1

            # 找到 truncate_ref_ts 所在行的末尾偏移 = 截断点
            ref_bytes = truncate_ref_ts.strftime("%Y-%m-%d %H:%M:%S+00:00").encode()
            ref_pos = chunk.find(ref_bytes)
            if ref_pos == -1:
                return False
            nl_after = chunk.find(b"\n", ref_pos)
            if nl_after == -1:
                return False
            truncate_at = chunk_start + nl_after + 1

            if truncate_at <= 0:
                return False

            df_to_write = df_new.drop_duplicates(
                subset=["timestamp"], keep="last"
            ).sort_values("timestamp")

            with open(filepath, "r+b") as f:
                f.truncate(truncate_at)
            self._append_to_csv(df_to_write, filepath)
            logger.info(
                f"{log_label}: 尾部重写 {len(df_to_write)} 条 → {filepath}"
            )
            return True
        except Exception as e:
            logger.debug(f"尾部重写失败，回退到全量保存：{e}")
            return False

    def get_status(self) -> Dict[str, Any]:
        """获取仓库状态"""
        with self._lock:
            status: Dict[str, Any] = {
                "symbols": list(self._states.keys()),
                "registered_timeframes": {},
                "last_update": {},
            }

            for symbol, state in self._states.items():
                status["registered_timeframes"][symbol] = list(
                    state.registered_timeframes
                )
                status["last_update"][symbol] = {
                    "timeframe": state.last_updated_timeframe,
                    "time": str(state.last_update_time),
                    "last_1m_kline_time": str(state.last_1m_kline_time),
                }

            return status

    def save_all(self) -> Dict[str, int]:
        """
        保存所有已注册 symbol 的数据到 CSV

        注意：KlineRepository 使用即时保存策略，在 update_from_1m 时
        已经自动保存数据。此方法主要用于确保所有数据已持久化。

        Returns:
            {symbol: 保存的文件数量}
        """
        with self._lock:
            result = {}

            for symbol, state in self._states.items():
                files_saved = 0

                # 遍历已注册的时间框架，检查文件是否存在
                for timeframe in state.registered_timeframes:
                    filepath = self._get_file_path(symbol, timeframe)
                    if filepath.exists():
                        files_saved += 1

                result[symbol] = files_saved

            return result

    def clear(self, symbol: Optional[str] = None):
        """
        清除状态（不清除 CSV 文件）

        Args:
            symbol: 交易对（可选）
        """
        with self._lock:
            if symbol:
                if symbol in self._states:
                    del self._states[symbol]
                    logger.debug(f"已清除 {symbol} 的状态")
            else:
                self._states.clear()
                logger.debug("已清除所有状态")
