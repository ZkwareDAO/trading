#!/usr/bin/env python3
"""
K 线数据加载器

功能:
1. 从本地 CSV 文件加载并合并 K 线数据
2. 支持 K 线周期转换（如 1m 聚合成 1h）
3. 保存数据到 CSV 文件
"""

import os
import concurrent.futures
import sys
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import List, Optional, Union

import pandas as pd
from dotenv import load_dotenv
from loguru import logger

# 加载 .env 文件
load_dotenv()

# Logger 配置
logger.remove()
logger.add(
    sink=sys.stderr,
    level="INFO",
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)


# ============================================================
# 数据读取函数
# ============================================================


def read_binance_klines_csv(file_path: Union[Path, str]) -> pd.DataFrame:
    """读取 Binance K 线 CSV 文件"""
    column_names = [
        "open_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "close_time",
        "quote_volume",
        "count",
        "taker_buy_volume",
        "taker_buy_quote_volume",
        "ignore",
    ]
    dtype_mapping = {
        "open_time": "int64",
        "open": "float64",
        "high": "float64",
        "low": "float64",
        "close": "float64",
        "volume": "float64",
        "close_time": "int64",
        "quote_volume": "float64",
        "count": "int64",
        "taker_buy_volume": "float64",
        "taker_buy_quote_volume": "float64",
        "ignore": "int64",
    }

    with open(file_path, "r") as f:
        first_line = f.readline().strip().split(",")
    has_header = first_line[0].lower() == "open_time"

    df = pd.read_csv(
        filepath_or_buffer=str(file_path),
        header=None,
        names=column_names,
        dtype=dtype_mapping,
        skiprows=(1 if has_header else 0),
        skipinitialspace=True,
    )
    return df


def transform_binance_klines(
    df: pd.DataFrame, datetime_column: str = "datetime"
) -> pd.DataFrame:
    """转换 Binance K 线数据格式"""
    df = df.copy()
    df.rename(columns={"open_time": datetime_column}, inplace=True)

    df = (
        df.sort_values(by=[datetime_column])
        .drop_duplicates(subset=[datetime_column])
        .reset_index(drop=True)
    )

    df[datetime_column] = pd.to_datetime(df[datetime_column], unit="ms", utc=True)

    columns_to_keep = [
        datetime_column,
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "count",
        "taker_buy_volume",
        "taker_buy_quote_volume",
    ]
    df = df[columns_to_keep]
    return df


# ============================================================
# 工具函数
# ============================================================


def convert_to_date(input_date: Union[str, pd.Timestamp, date, datetime]) -> date:
    """将各种日期格式转换为 datetime.date 对象"""
    if isinstance(input_date, pd.Timestamp):
        return input_date.date()
    elif isinstance(input_date, datetime):
        return input_date.date()
    elif isinstance(input_date, date):
        return input_date
    elif isinstance(input_date, str):
        for fmt in ("%Y-%m-%d", "%Y%m%d"):
            try:
                return datetime.strptime(input_date, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"不支持的日期格式：{input_date}")
    else:
        raise TypeError(f"无效的日期类型：{type(input_date)}")


def build_file_path(
    exchange: str,
    instrument_type: str,
    symbol: str,
    frequency: str,
    trade_date: date,
    data_path: str,
) -> Path:
    """构建数据文件路径（仅支持 Binance）"""
    symbol_fmt = symbol.upper()
    if instrument_type == "um":
        return Path(
            f"{data_path}/{exchange}/futures/{instrument_type}/daily/{symbol_fmt}/{frequency}/{symbol_fmt}-{frequency}-{trade_date.strftime('%Y-%m-%d')}.csv"
        )
    else:
        return Path(
            f"{data_path}/{exchange}/{instrument_type}/daily/{symbol_fmt}/{frequency}/{symbol_fmt}-{frequency}-{trade_date.strftime('%Y-%m-%d')}.csv"
        )


# ============================================================
# 核心数据加载函数
# ============================================================


def load_single_day(
    exchange: str,
    instrument_type: str,
    symbol: str,
    frequency: str,
    trade_date: date,
    data_path: str,
    datetime_column: str = "datetime",
) -> Optional[pd.DataFrame]:
    """处理单日 K 线数据"""
    file_path = build_file_path(
        exchange, instrument_type, symbol, frequency, trade_date, data_path
    )

    if not file_path.exists():
        logger.trace(f"文件不存在：{file_path}")
        return None

    try:
        df = read_binance_klines_csv(file_path)
        df = transform_binance_klines(df, datetime_column)
        return df
    except Exception as e:
        logger.error(f"处理 {trade_date} 数据失败：{e}")
        return None


def load_klines_data(
    symbol: str,
    start_date: Union[str, pd.Timestamp, date, datetime, None] = None,
    end_date: Union[str, pd.Timestamp, date, datetime, None] = None,
    exchange: str = "binance",
    instrument_type: str = "um",
    frequency: str = "1m",
    date_number: Optional[int] = None,
    max_workers: int = 4,
    datetime_column: str = "datetime",
) -> pd.DataFrame:
    """
    加载指定时间范围内的 K 线数据（仅支持 Binance）

    参数:
        symbol: 交易对名称（如 "btcusdt"）
        start_date: 开始日期
        end_date: 结束日期（可选，默认为今天）
        exchange: 交易所（固定为 "binance"）
        instrument_type: 交易类型（"um" 或 "spot"）
        frequency: K 线周期（"1m", "5m", "1h" 等）
        date_number: 指定加载最近 N 天数据（如指定，则忽略 start_date/end_date）
        max_workers: 最大并发进程数
        datetime_column: 时间列名

    返回:
        合并后的 DataFrame
    """
    data_path = os.getenv(
        "DATA_PATH", "./data"
    )

    # 确定日期范围
    if date_number is not None:
        end_dt = date.today()
        start_dt = end_dt - timedelta(days=date_number - 1)
    else:
        start_dt = convert_to_date(start_date) if start_date else date.today()
        end_dt = convert_to_date(end_date) if end_date else date.today()

    date_list = list(pd.date_range(start=start_dt, end=end_dt).date)
    logger.info(f"加载 {symbol} 数据：{start_dt} 至 {end_dt}，共 {len(date_list)} 天")

    # 并行加载数据
    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_date = {
            executor.submit(
                load_single_day,
                exchange,
                instrument_type,
                symbol,
                frequency,
                d,
                data_path,
                datetime_column,
            ): d
            for d in date_list
        }

        for future in concurrent.futures.as_completed(future_to_date):
            try:
                df = future.result()
                if df is not None and not df.empty:
                    results.append(df)
            except Exception as e:
                logger.error(f"加载数据失败：{e}")

    if not results:
        logger.warning("没有成功加载的数据")
        return pd.DataFrame()

    # 合并数据
    combined_df = pd.concat(results, ignore_index=True)
    combined_df = combined_df.sort_values(by=datetime_column).reset_index(drop=True)
    logger.info(f"成功加载 {len(combined_df)} 条 K 线记录")
    return combined_df


# ============================================================
# 重采样（K 线周期转换）
# ============================================================


def resample_ohlcv(
    df: pd.DataFrame, target_frequency: str, datetime_column: str = "datetime"
) -> pd.DataFrame:
    """
    将 K 线数据重采样到目标周期

    支持的目标周期：1m, 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1w

    参数:
        df: 输入 DataFrame，需包含 datetime 列和 OHLCV 列
        target_frequency: 目标周期（如 "1h", "4h", "1d"）
        datetime_column: 时间列名

    返回:
        重采样后的 DataFrame，timestamp 列带 UTC 时区
    """
    df = df.copy()

    # 确保时间戳是 UTC 带时区（与 1m 源数据保持一致）
    df[datetime_column] = pd.to_datetime(df[datetime_column], utc=True)

    # Binance 历史 CSV 使用 taker_buy_* 字段，实时 K 线则使用
    # active_buy_* 字段表示同一组数据。历史与实时数据拼接后，
    # 两列可能同时存在但在不同行上为 NaN。必须在重采样前逐行
    # 互补，否则聚合后的主动买入量只会覆盖其中一段数据。
    # 只填充缺失值，不覆盖任一已存在的非空值，也不为单一
    # schema 额外创建别名列。
    buy_volume_aliases = (
        ("taker_buy_volume", "active_buy_volume"),
        ("taker_buy_quote_volume", "active_buy_quote_volume"),
    )
    for historical_col, realtime_col in buy_volume_aliases:
        if historical_col in df.columns and realtime_col in df.columns:
            historical_values = df[historical_col].copy()
            realtime_values = df[realtime_col].copy()
            df[historical_col] = historical_values.combine_first(realtime_values)
            df[realtime_col] = realtime_values.combine_first(historical_values)

    df.set_index(datetime_column, inplace=True)

    # 重采样规则
    agg_dict = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
        "quote_volume": "sum",
        "count": "sum",
        "taker_buy_volume": "sum",
        "taker_buy_quote_volume": "sum",
        "active_buy_volume": "sum",
        "active_buy_quote_volume": "sum",
    }

    # 只保留输入 DataFrame 中存在的列
    existing_cols = {k: v for k, v in agg_dict.items() if k in df.columns}

    # pandas 频率格式处理
    freq = target_frequency
    if freq.endswith("m") and not freq.endswith("min"):
        freq = freq[:-1] + "min"
    elif freq.endswith("d"):
        freq = freq[:-1] + "D"

    # 对于 4h 周期，使用 origin='epoch' 确保时间戳对齐到 UTC 00:00/04:00/08:00/12:00/16:00/20:00
    if target_frequency in ("4h", "2h", "6h", "8h", "12h"):
        resampled = df.resample(freq, origin="epoch").agg(existing_cols)
    else:
        resampled = df.resample(freq).agg(existing_cols)

    resampled = resampled.dropna().reset_index()

    # 确保时间戳带 UTC 时区（与 1m 数据一致）
    if resampled[datetime_column].dt.tz is None:
        resampled[datetime_column] = resampled[datetime_column].dt.tz_localize("UTC")
    else:
        resampled[datetime_column] = resampled[datetime_column].dt.tz_convert("UTC")

    logger.debug(f"重采样到 {target_frequency}: {len(resampled)} 条记录")
    return resampled


# ============================================================
# 保存数据
# ============================================================


def save_to_csv(
    df: pd.DataFrame,
    symbol: str,
    exchange: str,
    instrument_type: str,
    frequency: str,
    output_dir: str = "./data/klines",
    filename_pattern: str = "{symbol}_{timeframe}.csv",
) -> str:
    """
    保存 DataFrame 到 CSV 文件

    参数:
        df: 要保存的 DataFrame
        symbol: 交易对名称
        exchange: 交易所
        instrument_type: 交易类型
        frequency: K 线周期
        output_dir: 输出目录
        filename_pattern: 文件名模式

    返回:
        保存的文件路径
    """
    df_out = df.copy()
    if "datetime" in df_out.columns:
        df_out = df_out.rename(columns={"datetime": "timestamp"})

    required_cols = ["timestamp", "open", "high", "low", "close", "volume"]
    available_cols = [c for c in required_cols if c in df_out.columns]
    df_out = df_out[available_cols]

    output_path = f"{output_dir}/{frequency}"
    os.makedirs(output_path, exist_ok=True)

    filename = filename_pattern.format(symbol=symbol.upper(), timeframe=frequency)
    full_path = os.path.join(output_path, filename)

    df_out.to_csv(full_path, index=False)
    logger.info(f"数据已保存到：{full_path} ({len(df_out)} 条记录)")
    return full_path


# ============================================================
# 重采样（K 线周期转换）
# ============================================================
