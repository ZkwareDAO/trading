#!/usr/bin/env python3
"""
Backtest Data Loader - 回测数据智能加载器

功能:
1. 根据回测日期区间查找覆盖该区间的数据文件
2. 如果找到覆盖文件，加载并截取指定时间段数据
3. 如果没有覆盖文件，从更细粒度的源数据合成新文件
4. 支持多时间框架 (1m, 5m, 15m, 1h, 4h, 1d)
"""

import logging
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, List, Dict, Tuple, Any

import pandas as pd

from data_manager.klines_loader import resample_ohlcv, read_binance_klines_csv, transform_binance_klines

import pandas as pd

logger = logging.getLogger(__name__)


# 时间框架粒度顺序（从细到粗）
TIMEFRAME_GRANULARITY = {
    "1m": 1,
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "6h": 360,
    "12h": 720,
    "1d": 1440,
}


def parse_date_range_from_filename(filename: str) -> Optional[Tuple[datetime, datetime]]:
    """
    从文件名解析日期范围

    支持格式:
    - BTCUSDT-1m-20251201-20260407.csv
    - BTCUSDT_1m_20251201_20260407.csv

    Returns:
        (start_date, end_date) 元组，如果无法解析则返回 None
    """
    # 模式 1: BTCUSDT-1m-20251201-20260407.csv
    pattern1 = r"[\w\-]+-(\d{8})-(\d{8})\.csv$"
    # 模式 2: BTCUSDT_1m_20251201_20260407.csv
    pattern2 = r"[\w_]+_(\d{8})_(\d{8})\.csv$"

    for pattern in [pattern1, pattern2]:
        match = re.search(pattern, filename)
        if match:
            start_str = match.group(1)
            end_str = match.group(2)
            try:
                start_date = datetime.strptime(start_str, "%Y%m%d")
                end_date = datetime.strptime(end_str, "%Y%m%d").replace(hour=23, minute=59, second=59)
                return (start_date.replace(tzinfo=timezone.utc), end_date.replace(tzinfo=timezone.utc))
            except ValueError:
                continue

    return None


def is_file_covering_range(
    filepath: Path,
    start_date: datetime,
    end_date: datetime,
    timeframe: str
) -> Tuple[bool, Optional[Tuple[datetime, datetime]]]:
    """
    检查文件是否覆盖指定的日期范围

    Args:
        filepath: 文件路径
        start_date: 回测开始日期
        end_date: 回测结束日期
        timeframe: 时间框架

    Returns:
        (是否覆盖，文件日期范围)
    """
    # 尝试从文件名解析日期范围
    date_range = parse_date_range_from_filename(filepath.name)

    if date_range:
        file_start, file_end = date_range
        # 确保时区一致（都转换为 UTC）
        def ensure_utc(dt):
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        file_start_utc = ensure_utc(file_start)
        file_end_utc = ensure_utc(file_end)
        start_utc = ensure_utc(start_date)
        end_utc = ensure_utc(end_date)

        # 检查文件范围是否完全覆盖回测区间
        covers = file_start_utc <= start_utc and file_end_utc >= end_utc
        return (covers, (file_start_utc, file_end_utc))

    # 如果文件名没有日期范围，尝试从文件内容获取
    try:
        # 检查文件是否有表头
        with open(filepath, "r") as f:
            first_line = f.readline().strip().split(",")
        has_header = first_line[0].lower() == "timestamp" or first_line[0].lower() == "open_time"

        if has_header:
            # 标准格式 CSV（有表头）
            df = pd.read_csv(filepath, nrows=10)
            if 'timestamp' not in df.columns:
                return (False, None)

            first_ts = pd.to_datetime(df['timestamp'].iloc[0], utc=True)

            # 读取最后一行
            df_last = pd.read_csv(filepath, skiprows=lambda x: x == 0, nrows=1)
            last_ts = pd.to_datetime(df_last['timestamp'].iloc[0], utc=True)
        else:
            # Binance 格式 CSV（无表头）
            df = read_binance_klines_csv(filepath)
            df = transform_binance_klines(df, datetime_column="timestamp")

            first_ts = df['timestamp'].iloc[0]
            last_ts = df['timestamp'].iloc[-1]

        file_range = (first_ts, last_ts)

        # 确保时区一致
        def ensure_utc_dt(dt):
            if hasattr(dt, 'tzinfo') and dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt

        start_utc = ensure_utc_dt(start_date)
        end_utc = ensure_utc_dt(end_date)

        covers = first_ts <= start_utc and last_ts >= end_utc
        return (covers, file_range)

    except Exception as e:
        logger.debug(f"读取文件 {filepath} 失败：{e}")
        return (False, None)


def load_and_slice_data(
    filepath: Path,
    start_date: datetime,
    end_date: datetime,
    timeframe: str
) -> Optional[pd.DataFrame]:
    """
    加载 CSV 文件并截取指定日期范围的数据

    Args:
        filepath: 文件路径
        start_date: 开始日期
        end_date: 结束日期
        timeframe: 时间框架

    Returns:
        截取后的 DataFrame
    """
    try:
        # 检查文件是否有表头
        with open(filepath, "r") as f:
            first_line = f.readline().strip().split(",")
        has_header = first_line[0].lower() == "timestamp" or first_line[0].lower() == "open_time"

        if has_header:
            # 标准格式 CSV（有表头）
            df = pd.read_csv(filepath)
            df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
        else:
            # Binance 格式 CSV（无表头）
            df = read_binance_klines_csv(filepath)
            df = transform_binance_klines(df, datetime_column="timestamp")

        # 确保 start_date 和 end_date 有时区信息
        def ensure_utc(dt):
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)

        start_utc = ensure_utc(start_date)
        end_utc = ensure_utc(end_date)

        # 筛选日期范围
        mask = (df['timestamp'] >= start_utc) & (df['timestamp'] <= end_utc)
        df_filtered = df[mask].copy()

        if len(df_filtered) == 0:
            logger.warning(f"文件 {filepath} 中没有 {start_date} 到 {end_date} 的数据")
            return None

        logger.info(f"从 {filepath} 加载了 {len(df_filtered):,} 条数据 ({start_date} 到 {end_date})")
        return df_filtered

    except Exception as e:
        logger.error(f"加载文件 {filepath} 失败：{e}")
        return None


def find_source_timeframe(target_timeframe: str) -> Optional[str]:
    """
    查找用于合成目标时间框架的源时间框架

    Args:
        target_timeframe: 目标时间框架

    Returns:
        源时间框架，如果找不到则返回 None
    """
    target_minutes = TIMEFRAME_GRANULARITY.get(target_timeframe)
    if target_minutes is None:
        return None

    # 查找更细粒度的时间框架
    for tf, minutes in TIMEFRAME_GRANULARITY.items():
        if minutes < target_minutes and target_minutes % minutes == 0:
            return tf

    return None


class BacktestDataLoader:
    """
    回测数据智能加载器
    """

    def __init__(self, data_dir: str = "./data/klines"):
        """
        初始化加载器

        Args:
            data_dir: K 线数据目录
        """
        self.data_dir = Path(data_dir)
        self.symbol = "BTCUSDT"  # 默认交易对

    def load_data_for_backtest(
        self,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime,
        source_timeframe: str = "1m"
    ) -> Optional[pd.DataFrame]:
        """
        为回测加载数据

        Args:
            symbol: 交易对
            timeframe: 目标时间框架
            start_date: 回测开始日期
            end_date: 回测结束日期
            source_timeframe: 源数据时间框架（用于合成）

        Returns:
            DataFrame 对象
        """
        self.symbol = symbol
        timeframe = timeframe.lower()

        # 步骤 1: 查找是否有覆盖该区间的数据文件
        logger.info(f"步骤 1: 查找 {symbol} {timeframe} 数据文件...")
        existing_file = self.find_covering_file(timeframe, start_date, end_date)

        if existing_file:
            logger.info(f"找到覆盖文件：{existing_file}")
            df = load_and_slice_data(existing_file, start_date, end_date, timeframe)
            if df is not None:
                return df

        # 步骤 2: 从源数据合成
        logger.info(f"步骤 2: 未找到覆盖文件，尝试从 {source_timeframe} 合成...")
        df = self.synthesize_data(timeframe, start_date, end_date, source_timeframe)

        if df is not None:
            # 保存合成的数据
            saved_path = self.save_synthesized_data(df, symbol, timeframe, start_date, end_date)
            if saved_path:
                logger.info(f"合成数据已保存：{saved_path}")

        return df

    def find_covering_file(
        self,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[Path]:
        """
        查找覆盖指定日期范围的文件

        Args:
            timeframe: 时间框架
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            文件路径，如果找不到则返回 None
        """
        timeframe_dir = self.data_dir / self.symbol / timeframe

        if not timeframe_dir.exists():
            logger.debug(f"目录不存在：{timeframe_dir}")
            return None

        # 扫描所有 CSV 文件
        csv_files = list(timeframe_dir.glob("*.csv"))
        logger.debug(f"扫描到 {len(csv_files)} 个 CSV 文件")

        # 检查每个文件是否覆盖目标区间
        for filepath in csv_files:
            covers, date_range = is_file_covering_range(filepath, start_date, end_date, timeframe)
            if covers:
                logger.info(f"找到覆盖文件：{filepath.name} (范围：{date_range[0]} 到 {date_range[1]})")
                return filepath

        return None

    def synthesize_data(
        self,
        target_timeframe: str,
        start_date: datetime,
        end_date: datetime,
        source_timeframe: str = "1m"
    ) -> Optional[pd.DataFrame]:
        """
        从源数据合成目标时间框架的数据

        Args:
            target_timeframe: 目标时间框架
            start_date: 开始日期
            end_date: 结束日期
            source_timeframe: 源时间框架

        Returns:
            合成后的 DataFrame
        """
        # 步骤 1: 加载源数据
        logger.info(f"  加载 {source_timeframe} 源数据...")
        source_df = self.load_source_data(source_timeframe, start_date, end_date)

        if source_df is None or source_df.empty:
            logger.error(f"无法加载 {source_timeframe} 源数据")
            return None

        logger.info(f"  源数据量：{len(source_df):,} 条")

        # 步骤 2: 重采样到目标时间框架
        logger.info(f"  重采样 {source_timeframe} -> {target_timeframe}...")

        try:
            resampled_df = resample_ohlcv(source_df, target_timeframe, datetime_column="timestamp")
            logger.info(f"  重采样完成：{len(resampled_df):,} 条")

            # 步骤 3: 计算指标
            logger.info(f"  计算技术指标...")
            calculator = IndicatorCalculator()
            df_with_indicators = calculator.calculate(resampled_df)

            return df_with_indicators

        except Exception as e:
            logger.error(f"重采样失败：{e}")
            return None

    def load_source_data(
        self,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        加载源数据（支持多种文件格式）

        Args:
            timeframe: 时间框架
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            DataFrame 对象
        """
        timeframe_dir = self.data_dir / self.symbol / timeframe

        if not timeframe_dir.exists():
            logger.warning(f"目录不存在：{timeframe_dir}")
            return None

        # 查找覆盖文件
        covering_file = self.find_covering_file(timeframe, start_date, end_date)

        if covering_file:
            logger.info(f"  使用覆盖文件：{covering_file.name}")
            return load_and_slice_data(covering_file, start_date, end_date, timeframe)

        # 尝试加载每日文件
        logger.info(f"  尝试加载每日 CSV 文件...")
        all_dfs = []

        current = start_date
        while current <= end_date:
            date_str = current.strftime("%Y-%m-%d")
            daily_file = timeframe_dir / f"{self.symbol}-{timeframe}-{date_str}.csv"

            if daily_file.exists():
                try:
                    # 使用 Binance 格式读取器（处理无表头的 CSV）
                    df = read_binance_klines_csv(daily_file)
                    df = transform_binance_klines(df, datetime_column="timestamp")
                    all_dfs.append(df)
                except Exception as e:
                    logger.warning(f"加载每日文件失败 {daily_file}: {e}")

            current += pd.Timedelta(days=1)

        if all_dfs:
            combined = pd.concat(all_dfs, ignore_index=True)
            combined = combined.sort_values('timestamp').drop_duplicates(subset=['timestamp'], keep='last')
            mask = (combined['timestamp'] >= start_date) & (combined['timestamp'] <= end_date)
            return combined[mask].reset_index(drop=True)

        logger.warning(f"没有找到 {timeframe} 数据文件")
        return None

    def save_synthesized_data(
        self,
        df: pd.DataFrame,
        symbol: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[Path]:
        """
        保存合成的数据

        Args:
            df: DataFrame
            symbol: 交易对
            timeframe: 时间框架
            start_date: 开始日期
            end_date: 结束日期

        Returns:
            保存的文件路径
        """
        output_dir = self.data_dir / symbol / timeframe
        output_dir.mkdir(parents=True, exist_ok=True)

        # 生成文件名
        start_str = start_date.strftime("%Y%m%d")
        end_str = end_date.strftime("%Y%m%d")
        filename = f"{symbol}-{timeframe}-{start_str}-{end_str}.csv"
        filepath = output_dir / filename

        try:
            # 格式化时间戳
            df_copy = df.copy()
            if df_copy['timestamp'].dt.tz is None:
                df_copy['timestamp'] = df_copy['timestamp'].dt.tz_localize('UTC')
            df_copy['timestamp'] = df_copy['timestamp'].dt.strftime("%Y-%m-%d %H:%M:%S+00:00")

            # 保存 CSV
            df_copy.to_csv(filepath, index=False)
            logger.info(f"数据已保存到 {filepath}")
            return filepath

        except Exception as e:
            logger.error(f"保存数据失败：{e}")
            return None


def load_klines_for_backtest(
    data_dir: str,
    symbol: str,
    timeframe: str,
    start_date: datetime,
    end_date: datetime,
    source_timeframe: str = "1m"
) -> Optional[pd.DataFrame]:
    """
    便捷函数：为回测加载 K 线数据

    Args:
        data_dir: 数据目录
        symbol: 交易对
        timeframe: 目标时间框架
        start_date: 开始日期
        end_date: 结束日期
        source_timeframe: 源时间框架

    Returns:
        DataFrame 对象
    """
    loader = BacktestDataLoader(data_dir)
    return loader.load_data_for_backtest(symbol, timeframe, start_date, end_date, source_timeframe)
