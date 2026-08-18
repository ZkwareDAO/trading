#!/usr/bin/env python3
"""
回测框架入口 — 对标 run_strategy.py

配置加载与实盘对齐：统一走 strategies/<name>/overrides/<symbol>.yaml（per-symbol）。
回测专有参数（timeframe/data_dir/cash/commission/输出目录）下放到 config/backtest.yaml。

使用方式:
    # 标准用法：name:symbol 自动加载 overrides，回测参数从 profile 读
    python -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260601 --end 20260811

    # 自定义配置文件路径（覆盖默认 overrides 路径）
    python -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --config-path /path/to/custom.yaml --start 20260601

    # 批量回测请用 backtest.batch_runner
"""

import argparse
import importlib
import json
import logging
import sys
import yaml
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Any, List

from dotenv import load_dotenv

# 加载 .env 文件（必须在其他 imports 之前）
load_dotenv()

from strategy_core.constants import TF_MINUTES
from strategy_core.utils.log_handlers import DailyDirectoryFileHandler
from strategy_core.utils.strategy_naming import build_strategy_id_from_overrides

# 复用实盘 run_strategies_manager 的 name:symbol 解析逻辑，保证回测/实盘 CLI 风格一致
from run_strategies_manager import parse_explicit_strategies

import backtrader as bt
import pandas as pd

from data_manager import DataManager, DataManagerConfig
from data_manager.klines_loader import load_klines_data, save_to_csv
from backtest.bt_strategy import BacktestBTStrategy
from backtest.signal_mapper import SignalMapper
from backtest.backtest_reporter import BacktestReporter
from backtest.config_loader import (
    load_profile,
    merge_config_with_overrides,
    verify_data_dir_consistency,
)

logger = logging.getLogger(__name__)


def _parse_kline_timestamps(values: pd.Series) -> pd.Series:
    """解析字符串或秒/毫秒/微秒/纳秒数值时间戳为 UTC。

    Binance 原始 CSV 使用 13 位毫秒时间戳。直接调用
    ``pd.to_datetime(values, utc=True)`` 会把它当成纳秒，从而错误地
    解析到 1970 年。
    """
    if pd.api.types.is_datetime64_any_dtype(values.dtype):
        return pd.to_datetime(values, utc=True, errors="coerce")

    parsed = pd.Series(pd.NaT, index=values.index, dtype="datetime64[ns, UTC]")
    numeric = pd.to_numeric(values, errors="coerce")
    numeric_mask = numeric.notna()

    absolute = numeric.abs()
    unit_masks = {
        "s": numeric_mask & (absolute < 1e11),
        "ms": numeric_mask & (absolute >= 1e11) & (absolute < 1e14),
        "us": numeric_mask & (absolute >= 1e14) & (absolute < 1e17),
        "ns": numeric_mask & (absolute >= 1e17),
    }
    for unit, mask in unit_masks.items():
        if mask.any():
            parsed.loc[mask] = pd.to_datetime(
                numeric.loc[mask], unit=unit, utc=True, errors="coerce"
            )

    text_mask = ~numeric_mask
    if text_mask.any():
        parsed.loc[text_mask] = pd.to_datetime(
            values.loc[text_mask], utc=True, errors="coerce"
        )
    return parsed

# 策略简称 → 目录名映射
STRATEGY_MAP = {
    "rbreaker": "cta_rbreaker_v3",
    "rbreaker_v3": "cta_rbreaker_v3",
    "rbreaker_v2": "cta_rbreaker_v2",
    "trend": "cta_trend",
    "ict": "cta_ict",
    "ict_v2": "cta_ict_v2",
    "trend_strength": "cta_trend_strength",
    "dolphin": "dolphin_trading",
    "bollinger": "cta_bollinger_oscillator",
    "bollinger_daily": "bollinger_daily",
    "delphi": "delphi_aggressive",
    "obv": "obv_atr",
    "obv_v2": "obv_atr_v2",
}


def resolve_strategy_name(short_name: str) -> str:
    """将简称解析为策略目录名."""
    if short_name in STRATEGY_MAP:
        return STRATEGY_MAP[short_name]
    # 直接使用作为目录名
    return short_name


def parse_date_input(value: str) -> tuple[str, datetime]:
    """解析日期输入，返回 (YYYYMMDD, datetime对象).

    支持: YYYYMMDD、秒时间戳(10位)、毫秒时间戳(13位)
    """
    if value.isdigit() and len(value) in (10, 13):
        ts = int(value)
        if len(value) == 13:
            dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
        else:  # len == 10
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    else:
        dt = datetime.strptime(value, "%Y%m%d").replace(tzinfo=timezone.utc)
    return dt.strftime("%Y%m%d"), dt


_SYNC_BUFFER_DAYS = 5
_SYNC_MIN_DAYS = 30

_WARMUP_MARGIN = 1.2


def calc_warmup_1m_bars(strategy_config: Dict[str, Any]) -> int:
    """根据策略配置计算 warm-up 所需 1m K 线根数。

    遍历 params 中 *_timeframes + *_period 组合，
    取 max(period × tf_minutes) 作为 warm-up 需求。
    无指标周期参数时默认 1 个 4h 周期 (240 根 1m)。
    加 20% 安全余量。
    """
    params = strategy_config.get("params", {})
    timeframes_list = strategy_config.get("timeframes", [])

    max_bars = 0

    # 从 *_timeframes 字段收集指标周期
    for key, value in params.items():
        if key.endswith("_timeframes") and isinstance(value, str):
            tf = value.lower()
            tf_minutes = TF_MINUTES.get(tf, 0)
            if tf_minutes == 0:
                continue
            # 找对应的 period: obv_timeframes → obv_ma_period / obv_breakout_period 等
            prefix = key[: -len("_timeframes")]
            period = 1
            for pkey, pval in params.items():
                if pkey.startswith(prefix) and pkey.endswith("_period") and isinstance(pval, (int, float)):
                    period = max(period, int(pval))
            max_bars = max(max_bars, period * tf_minutes)

    # 从顶层 timeframes 列表补充（如 ["4h"]），结合 params 中的 *_period
    if isinstance(timeframes_list, list):
        for tf in timeframes_list:
            tf_minutes = TF_MINUTES.get(tf.lower(), 0)
            if tf_minutes == 0:
                continue
            max_period = 1
            for pkey, pval in params.items():
                if pkey.endswith("_period") and isinstance(pval, (int, float)):
                    max_period = max(max_period, int(pval))
            max_bars = max(max_bars, max_period * tf_minutes)

    # 默认 1 个 4h 周期
    if max_bars == 0:
        max_bars = TF_MINUTES["4h"]

    return int(max_bars * _WARMUP_MARGIN)


def _calc_sync_days(start_date: str) -> int:
    """根据 start_date (YYYYMMDD) 到今天的天数 + buffer 计算需要同步的历史天数."""
    start = datetime.strptime(start_date, "%Y%m%d")
    now = datetime.now()
    delta_days = (now - start).days + _SYNC_BUFFER_DAYS
    return max(delta_days, _SYNC_MIN_DAYS)


def load_strategy_config(strategy_dir: str, symbol: str | None = None) -> Dict[str, Any]:
    """从策略目录加载 per-symbol overrides 配置。

    优先 strategies/<name>/overrides/<SYMBOL>.yaml；未指定 symbol 或文件
    不存在时回退到目录下任意一个 overrides/*.yaml（取第一个），再不行返回空。
    """
    overrides_dir = Path(strategy_dir) / "overrides"
    strategy_name = Path(strategy_dir).name

    candidates = []
    if symbol:
        candidates.append(overrides_dir / f"{symbol.upper()}.yaml")
    if overrides_dir.is_dir():
        # 回退：取 overrides 下第一个 yaml
        candidates.extend(sorted(overrides_dir.glob("*.yaml")))

    for config_path in candidates:
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                full_config = yaml.safe_load(f)
            cfg = full_config.get(strategy_name, {}) if full_config else {}
            logger.info(f"加载 overrides 配置: {config_path}")
            return cfg

    logger.warning(f"未找到 overrides 配置: {overrides_dir} (symbol={symbol})")
    return {}


def load_strategy_config_from_path(config_path: str, strategy_name: str) -> Dict[str, Any]:
    """从指定路径加载策略配置文件."""
    config_path = Path(config_path)
    if not config_path.exists():
        logger.warning(f"策略配置文件不存在: {config_path}")
        return {}
    with open(config_path, "r", encoding="utf-8") as f:
        full_config = yaml.safe_load(f)
    return full_config.get(strategy_name, {})


def resolve_log_level(cli_log_level: str | None, strategy_config: Dict[str, Any]) -> str:
    """解析日志级别，优先级：命令行 > 配置文件 > 默认 INFO."""
    if cli_log_level:
        return cli_log_level.upper()

    config_level = strategy_config.get("signal", {}).get("diagnostic_log_level")
    if config_level:
        return config_level.upper()

    return "INFO"


def load_strategy_module(strategy_dir_name: str):
    """动态加载策略模块."""
    module_path = f"strategies.{strategy_dir_name}.strategy"
    module = importlib.import_module(module_path)
    return module.Strategy


def _parse_symbols(symbol_arg: str) -> List[str]:
    """解析 symbol 参数，支持逗号分隔."""
    return [s.strip().upper() for s in symbol_arg.split(",") if s.strip()]


def _save_big_interval_csvs(data_manager, symbol: str, data_dir: str) -> None:
    """保存大周期数据到 CSV（仅回测使用）.

    从缓存中获取已聚合的大周期数据（15m/4h/1d 等），合并到现有 CSV 文件。

    Args:
        data_manager: DataManager 实例
        symbol: 标的代码（如 BTCUSDT）
        data_dir: 数据目录路径
    """
    state = data_manager.kline_repo._states.get(symbol)
    if not state:
        return

    # 获取所有注册的大周期（排除 1m）
    big_intervals = [tf for tf in state.registered_timeframes if tf.lower() != '1m']
    if not big_intervals:
        return

    for interval in big_intervals:
        df = data_manager.cache.get(symbol, interval)
        if df is None or df.empty:
            continue

        csv_path = Path(data_dir) / interval / f'{symbol}_{interval}.csv'
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        # 合并现有数据
        if csv_path.exists():
            df_old = pd.read_csv(csv_path)
            if 'timestamp' in df_old.columns:
                df_old['timestamp'] = _parse_kline_timestamps(df_old['timestamp'])
            df = pd.concat([df_old, df], ignore_index=True)
            df = df.drop_duplicates(subset=['timestamp'], keep='last')

        df = df.sort_values('timestamp').reset_index(drop=True)
        df.to_csv(csv_path, index=False)
        logger.info(f'{symbol} {interval} CSV 已更新: {len(df)} 行')


def _read_klines_csv(csv_path: Path) -> pd.DataFrame:
    """读取 1m K 线 CSV，兼容两种格式：
    - 已规范化：timestamp 列为 ISO 字符串（`%Y-%m-%d %H:%M:%S+00:00`）
    - 原始 Binance 格式：timestamp 为毫秒整数，额外带 close_time/ignore 等列

    统一返回带 UTC tz 的 datetime timestamp。
    """
    df = pd.read_csv(csv_path)
    if 'timestamp' not in df.columns:
        return df
    if pd.api.types.is_numeric_dtype(df['timestamp']):
        # 原始毫秒时间戳（Binance 下载格式），需指定 unit='ms'
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', utc=True)
    else:
        df['timestamp'] = pd.to_datetime(df['timestamp'], utc=True)
    return df


def _ensure_normalized_csv(csv_path: Path, df: pd.DataFrame) -> None:
    """若磁盘上的 CSV 仍是原始格式（毫秒时间戳/带 close_time 等列），
    则写回规范化格式（backtrader GenericCSVData 需要 `%Y-%m-%d %H:%M:%S+00:00`）。
    """
    try:
        with open(csv_path, 'r') as f:
            header = f.readline().strip().split(',')
            first_data = f.readline().strip().split(',')
    except OSError:
        return

    needs_rewrite = False
    # 额外的 Binance 原始列 → 需重写
    extra_cols = {'close_time', 'ignore'}
    if any(c in header for c in extra_cols):
        needs_rewrite = True
    # timestamp 是纯数字 → 需重写
    elif first_data and first_data[0].isdigit():
        needs_rewrite = True

    if not needs_rewrite:
        return

    out = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']].copy()
    # timestamp 已在 _read_klines_csv 中转为 tz-aware datetime
    out['timestamp'] = out['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S+00:00')
    out.to_csv(csv_path, index=False)
    logger.info(f"{csv_path.name} 已规范化为 ISO 时间戳格式")


def preload_klines_to_cache(
    data_manager,
    symbols: List[str],
    timeframe: str,
    data_dir: str,
    strategy_dir_name: str,
    start_date: str,
    strategy_config: Dict[str, Any] | None = None,
    end_date: str | None = None,
) -> None:
    """预加载 K 线数据到 DataManager 缓存。

    数据源：{data_dir}/{timeframe}/{SYMBOL}_{timeframe}.csv
    若 CSV 不存在，自动调用 load_klines_data 下载数据。
    若 CSV 存在但起点不满足 warm-up 需求，自动补齐缺失区间。
    若 CSV 最新时间早于当前时间，自动补齐到最新。
    """
    warmup_bars = calc_warmup_1m_bars(strategy_config or {})
    bt_start = datetime.strptime(start_date, "%Y%m%d").replace(tzinfo=timezone.utc)
    warmup_start = bt_start - timedelta(minutes=warmup_bars)
    warmup_start_str = warmup_start.strftime("%Y-%m-%d")

    # 指定回测结束时间时只补齐到该日期，避免历史回测无意义地同步到今天。
    if end_date:
        _, sync_end = parse_date_input(end_date)
        sync_end = sync_end.replace(hour=23, minute=59, second=59)
    else:
        sync_end = datetime.now(timezone.utc)
    sync_end_str = sync_end.strftime("%Y-%m-%d")

    for sym in symbols:
        csv_path = Path(data_dir) / timeframe / f"{sym}_{timeframe}.csv"

        df_1m = None
        if csv_path.exists():
            df_1m = _read_klines_csv(csv_path)
            logger.info(f"{sym} 1m CSV 已加载: {len(df_1m)} 行")
            _ensure_normalized_csv(csv_path, df_1m)

        if df_1m is None or df_1m.empty:
            logger.info(f"{sym} CSV 不存在，自动下载历史数据 (warm-up: {warmup_start_str})...")
            df_1m = load_klines_data(
                symbol=sym.lower(),
                start_date=warmup_start_str,
                end_date=sync_end_str,
                frequency="1m",
                instrument_type="um",
            )
            if df_1m is not None and not df_1m.empty:
                save_to_csv(
                    df_1m, symbol=sym, exchange="binance",
                    instrument_type="um", frequency="1m",
                    output_dir=data_dir,
                )
                if csv_path.exists():
                    df_1m = _read_klines_csv(csv_path)
            else:
                logger.warning(f"{sym} 下载数据失败，跳过")

        elif df_1m is not None and not df_1m.empty:
            csv_earliest = df_1m['timestamp'].min()
            csv_latest = df_1m['timestamp'].max()

            # 检查 warm-up 起始时间
            if csv_earliest > warmup_start:
                logger.info(
                    f"{sym} CSV 起始 {csv_earliest} 晚于 warm-up 需求 {warmup_start}，"
                    f"自动补齐 {warmup_start_str} ~ {csv_earliest.strftime('%Y-%m-%d')}"
                )
                df_gap = load_klines_data(
                    symbol=sym.lower(),
                    start_date=warmup_start_str,
                    end_date=csv_earliest.strftime("%Y-%m-%d"),
                    frequency="1m",
                    instrument_type="um",
                )
                if df_gap is not None and not df_gap.empty:
                    if 'timestamp' in df_gap.columns:
                        df_gap['timestamp'] = _parse_kline_timestamps(df_gap['timestamp'])
                    elif 'datetime' in df_gap.columns:
                        df_gap = df_gap.rename(columns={'datetime': 'timestamp'})
                        df_gap['timestamp'] = _parse_kline_timestamps(df_gap['timestamp'])
                    df_1m = pd.concat([df_gap, df_1m], ignore_index=True)
                    df_1m = df_1m.drop_duplicates(subset=['timestamp'], keep='last')
                    df_1m = df_1m.sort_values('timestamp').reset_index(drop=True)
                    save_to_csv(
                        df_1m, symbol=sym, exchange="binance",
                        instrument_type="um", frequency="1m",
                        output_dir=data_dir,
                    )
                    if csv_path.exists():
                        df_1m = _read_klines_csv(csv_path)
                    csv_latest = df_1m['timestamp'].max()
                else:
                    logger.warning(f"{sym} warm-up 区间数据下载失败，使用现有数据")

            # 检查回测结束时间（补齐 CSV 最新时间到当前最新时间）
            if csv_latest < sync_end - timedelta(minutes=5):
                logger.info(
                    f"{sym} CSV 最新 {csv_latest} 早于目标时间 {sync_end}，"
                    f"自动补齐 {csv_latest.strftime('%Y-%m-%d')} ~ {sync_end_str}"
                )
                df_gap_end = load_klines_data(
                    symbol=sym.lower(),
                    start_date=csv_latest.strftime("%Y-%m-%d"),
                    end_date=sync_end_str,
                    frequency="1m",
                    instrument_type="um",
                )
                if df_gap_end is not None and not df_gap_end.empty:
                    if 'timestamp' in df_gap_end.columns:
                        df_gap_end['timestamp'] = _parse_kline_timestamps(df_gap_end['timestamp'])
                    elif 'datetime' in df_gap_end.columns:
                        df_gap_end = df_gap_end.rename(columns={'datetime': 'timestamp'})
                        df_gap_end['timestamp'] = _parse_kline_timestamps(df_gap_end['timestamp'])
                    df_1m = pd.concat([df_1m, df_gap_end], ignore_index=True)
                    df_1m = df_1m.drop_duplicates(subset=['timestamp'], keep='last')
                    df_1m = df_1m.sort_values('timestamp').reset_index(drop=True)
                    save_to_csv(
                        df_1m, symbol=sym, exchange="binance",
                        instrument_type="um", frequency="1m",
                        output_dir=data_dir,
                    )
                    if csv_path.exists():
                        df_1m = _read_klines_csv(csv_path)
                else:
                    logger.warning(f"{sym} 回测结束区间数据下载失败，使用现有数据")

        if df_1m is not None and not df_1m.empty:
            data_manager.cache.put(sym, "1m", df_1m, force_1m=True)
            logger.info(f"{sym} 1m 数据已加载到缓存: {len(df_1m)} 行")

        # 从 1m 聚合大周期
        data_manager._preload_big_intervals_to_cache(sym)

        # 保存大周期 CSV（仅回测）
        _save_big_interval_csvs(data_manager, sym, data_dir)


def run_backtest(
    strategy_dir_name: str,
    symbol: str,
    start_date: str,
    end_date: str,
    start_dt: datetime | None = None,
    end_dt: datetime | None = None,
    timeframe: str = "1m",
    data_dir: str = "./data/klines",
    output_dir: str = "./backtest_output",
    cash: float | None = None,
    commission: float = 0.0004,  # 币安合约 taker 手续费 0.04%
    strategy_config: Dict[str, Any] | None = None,
    config_path: str | None = None,  # 配置文件路径，用于复制到输出目录
    use_today_as_output_date: bool = True,  # 输出目录日期模式
) -> None:
    """执行回测.

    Args:
        start_date: YYYYMMDD 格式日期字符串
        end_date: YYYYMMDD 格式日期字符串
        start_dt: 精确的开始时间（用于 fromdate），若为 None 则从 start_date 解析
        end_dt: 精确的结束时间（用于 todate），若为 None 则从 end_date 解析
        strategy_config: 策略配置（若为 None 则从默认路径加载）
    """
    symbols = _parse_symbols(symbol)
    timeframe = "1m"  # 强制使用 1m 周期，与实盘 WS 推送一致
    strategy_dir = str(Path("strategies") / strategy_dir_name)

    # 解析精确时间（若未提供）
    if start_dt is None:
        start_dt = datetime.strptime(start_date, "%Y%m%d").replace(tzinfo=timezone.utc)
    if end_dt is None:
        end_dt = datetime.strptime(end_date, "%Y%m%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )

    # 1. 加载策略配置（若未提供则从 overrides 加载）
    if strategy_config is None:
        strategy_config = load_strategy_config(strategy_dir, symbol=symbols[0] if symbols else None)
    if not strategy_config:
        logger.error(f"无法加载策略 {strategy_dir_name} 的配置")
        sys.exit(1)
    logger.info(f"策略配置已加载: {strategy_dir_name}")

    # 从配置文件读取 max_cash（若未显式指定 cash）
    if cash is None:
        max_cash = strategy_config.get("capital", {}).get("max_cash", 5000)
        cash = max_cash
        logger.info(f"从配置文件读取初始资金: max_cash={cash}")

    # 计算预热时间
    warmup_bars = calc_warmup_1m_bars(strategy_config)
    warmup_start_dt = start_dt - timedelta(minutes=warmup_bars)

    logger.info(
        f"回测时间范围: start={start_dt.isoformat()}, end={end_dt.isoformat()}, "
        f"warmup={warmup_start_dt.isoformat()} ({warmup_bars} bars)"
    )

    # 2. 创建 DataManager（真实实例，禁用 WS，回测模式返回完整数据）
    dm_config = DataManagerConfig(
        csv_dir=data_dir,
        klines_service_enabled=False,
        auto_sync_on_connect=False,
        preload_1m_enabled=False,
        backtest_mode=True,
    )
    data_manager = DataManager(dm_config)
    data_manager.connect()
    logger.info(f"DataManager 已连接: {data_dir}")

    # 3. 注册时间框架（每个 symbol）
    timeframes = strategy_config.get("timeframes", strategy_config.get("timeframe", [timeframe]))
    if isinstance(timeframes, str):
        timeframes = [timeframes]

    for sym in symbols:
        data_manager.register_timeframes(sym, timeframes)
        data_manager.reset_kline_tracking(sym, timeframe)
    logger.info(f"已注册时间框架: {timeframes}，symbols: {symbols}")

    # 4. 预加载历史数据到缓存（每个 symbol）
    preload_klines_to_cache(
        data_manager,
        symbols,
        timeframe,
        data_dir,
        strategy_dir_name,
        start_date,
        strategy_config,
        end_date=end_date,
    )


    # 5. 加载策略实例
    StrategyClass = load_strategy_module(strategy_dir_name)

    strategy_config["symbols"] = symbols
    if "symbol" in strategy_config:
        del strategy_config["symbol"]

    strategy = StrategyClass(
        data_manager=data_manager,
        config=strategy_config,
        trading_mode="backtest",  # 回测模式，确保数据隔离
    )

    # 对于 R-Breaker 等需要 1d 价格线的策略：用回测起始日的 K 线数据初始化价格线
    _bt_first_day_kline = None
    if hasattr(strategy, '_prev_daily_kline'):
        first_sym_csv = _find_csv_files(data_dir, symbols[0], timeframe, strategy_dir_name)
        if first_sym_csv:
            try:
                first_day_df = pd.read_csv(first_sym_csv[0])
                first_row = first_day_df.iloc[0]
                _bt_first_day_kline = type('FakeKline', (), {
                    'symbol': symbols[0],
                    'interval': strategy_config.get('price_line', {}).get('timeframe', '1d'),
                    'timestamp': pd.Timestamp(str(first_row['timestamp'])).to_pydatetime(),
                    'open': float(first_row['open']),
                    'high': float(first_row['high']),
                    'low': float(first_row['low']),
                    'close': float(first_row['close']),
                    'volume': float(first_row['volume']),
                })()
            except Exception as e:
                logger.warning(f"[Backtest] 价格线数据构造失败: {e}")

    # 6. 创建 backtrader Cerebro 引擎
    cerebro = bt.Cerebro()
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)
    logger.info(f"初始资金: {cash:.2f}, 手续费: {commission:.4f}")

    _tf_map = {
        "1m": (bt.TimeFrame.Minutes, 1),
        "4h": (bt.TimeFrame.Minutes, 240),
        "1h": (bt.TimeFrame.Minutes, 60),
        "30m": (bt.TimeFrame.Minutes, 30),
        "15m": (bt.TimeFrame.Minutes, 15),
        "8h": (bt.TimeFrame.Minutes, 480),
        "6h": (bt.TimeFrame.Minutes, 360),
        "1d": (bt.TimeFrame.Days, 1),
    }
    bt_timeframe, bt_compression = _tf_map.get(timeframe, (bt.TimeFrame.Minutes, 1))

    # 为每个 symbol 加载 CSV feed
    feeds_loaded = 0
    for sym in symbols:
        csv_files = _find_csv_files(data_dir, sym, timeframe, strategy_dir_name)
        if not csv_files:
            logger.error(f"未找到 {sym} 的 CSV 数据文件（全局/策略目录均无）")
            logger.info("请先下载历史数据: python data_manager/klines_loader.py ...")
            sys.exit(1)

        for csv_file in csv_files:
            # CSV 首列 `timestamp` 为毫秒时间戳（binance 原始格式），
            # backtrader GenericCSVData 只能解析字符串日期，因此改走 PandasData：
            # 先用 pandas 把 ms 时间戳转成 tz-naive UTC datetime 作为索引。
            df = pd.read_csv(csv_file)
            if "timestamp" not in df.columns:
                logger.error(f"CSV 缺少 timestamp 列: {csv_file}")
                sys.exit(1)
            # Historical files may contain Binance millisecond epochs or
            # normalized ISO-8601 timestamps.  Use the same mixed-format
            # parser as the preload path instead of assuming milliseconds.
            df["datetime"] = _parse_kline_timestamps(df["timestamp"]).dt.tz_convert(None)
            if df["datetime"].isna().any():
                invalid_count = int(df["datetime"].isna().sum())
                logger.error(
                    f"CSV 包含 {invalid_count} 个无法解析的 timestamp: {csv_file}"
                )
                sys.exit(1)
            df = df.set_index("datetime")[["open", "high", "low", "close", "volume"]]

            # backtrader 的 fromdate/todate 需要 tz-naive datetime
            fromdate_naive = warmup_start_dt.replace(tzinfo=None)
            todate_dt = end_dt.replace(hour=23, minute=59, second=59) if end_dt.hour == 0 else end_dt
            todate_naive = todate_dt.replace(tzinfo=None)

            data = bt.feeds.PandasData(
                dataname=df,
                name=sym,
                timeframe=bt_timeframe,
                compression=bt_compression,
                sessionend=None,
                fromdate=fromdate_naive,
                todate=todate_naive,
            )
            cerebro.adddata(data)
            logger.info(f"数据已加载: {csv_file} ({sym}, {len(df)} 根 K 线)")
            feeds_loaded += 1


    logger.info(f"共加载 {feeds_loaded} 个数据 feed，{len(symbols)} 个 symbol")

    # 8. 添加分析器
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe")

    # 8.5 提前创建回测输出目录（用于 signals.csv）
    symbol_label = "_".join(symbols)
    reporter = BacktestReporter(output_dir=output_dir)
    # 根据配置决定输出目录日期：True 使用当天，False 使用回测结束日期
    output_date = None if use_today_as_output_date else end_date
    run_dir = reporter.create_run_dir(strategy_dir_name, symbol=symbol_label, backtest_date=output_date)

    # 8.6 复制配置文件到回测输出目录
    if config_path and Path(config_path).exists():
        import shutil
        config_dest = run_dir / "config.yaml"
        shutil.copy2(config_path, config_dest)
        logger.info(f"配置文件已复制: {config_dest}")

    # 9. 添加策略（含价格线注入）
    cerebro.addstrategy(
        BacktestBTStrategy,
        cta_strategy=strategy,
        signal_mapper=SignalMapper(),
        data_manager=data_manager,
        bt_first_day_kline=_bt_first_day_kline,
        signal_csv_dir=str(run_dir),  # 信号 CSV 输出目录（回测结果目录）
        strategy_type=strategy_dir_name,  # 策略类型，用于输出子目录
        strategy_config=strategy_config,  # 策略配置，用于 CtaSignalCSV
        signal_start_dt=start_dt,  # 只有超过此时间才生成信号
    )

    # 10. 运行回测
    logger.info("开始回测...")
    _bt_start_time = datetime.now()
    results = cerebro.run()
    strat = results[0]
    _bt_end_time = datetime.now()

    end_value = strat._sim_cash
    # 加上未平仓的浮动盈亏
    for data in strat.datas:
        sym = getattr(data, "_name", "UNKNOWN")
        pos = strat._sim_positions.get(sym)
        if pos and pos.size > 0:
            price = float(data.close[0])
            if pos.side == "long":
                end_value += (price - pos.price) * pos.size
            else:
                end_value += (pos.price - price) * pos.size

    logger.info(f"回测完成: 初始 {cash:.2f} → 最终 {end_value:.2f}")

    # 11. 构建 reporter 输入数据
    # strategy_name 属性可能存在但为 None，故用 or 兜底到目录名，避免报告出现 "None 回测"
    strategy_id = getattr(strategy, "strategy_name", None) or strategy_dir_name
    daily_equity = strat.get_daily_equity()

    bt_config = {
        "name": f"{strategy_id} 回测",
        "start_date": start_date[:4] + "-" + start_date[4:6] + "-" + start_date[6:8],
        "end_date": end_date[:4] + "-" + end_date[4:6] + "-" + end_date[6:8],
        "initial_cash": cash,
        "symbols": symbols,
        "data_dir": data_dir,
    }

    peak_equity = max((r["equity"] for r in daily_equity), default=cash)
    max_dd = 0.0
    peak = cash
    for r in daily_equity:
        eq = r["equity"]
        if eq > peak:
            peak = eq
        dd = (peak - eq) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd

    accounts = [{
        "strategy_id": strategy_id,
        "cash": end_value,
        "frozen_cash": 0.0,
        "total_equity": end_value,
        "peak_equity": peak_equity,
        "max_drawdown": max_dd,
        "position_count": len(strat._sim_positions),
        "trade_count": len(strat.trades_completed),
    }]

    # 12. 生成报告（复用已创建的 run_dir）
    tf_equity = strat.get_tf_equity()
    tf_key = strat.get_tf_key()

    paths = reporter.generate(
        strategy_name=strategy_dir_name,
        symbol=symbol_label,
        config=bt_config,
        accounts=accounts,
        daily_equity=daily_equity,
        trades=strat.trades_completed,
        klines_processed=strat.klines_processed,
        signals_processed=len(strat.signals_generated),
        start_time=_bt_start_time,
        end_time=_bt_end_time,
        tf_equity=tf_equity if tf_equity else None,
        tf_key=tf_key,
    )

    logger.info("回测输出文件:")
    for name, path in paths.items():
        logger.info(f"  {name}: {path}")


def _find_csv_file(data_dir: str, symbol: str, timeframe: str,
                    strategy_dir_name: str = "") -> Path:
    """查找 CSV 文件: {data_dir}/{timeframe}/{SYMBOL}_{timeframe}.csv"""
    return Path(data_dir) / timeframe / f"{symbol}_{timeframe}.csv"


def _find_csv_files(data_dir: str, symbol: str, timeframe: str,
                    strategy_dir_name: str = "") -> list:
    """查找匹配的 CSV 文件: {data_dir}/{timeframe}/{SYMBOL}_{timeframe}.csv"""
    tf_dir = Path(data_dir) / timeframe
    pattern = f"{symbol}_{timeframe}.csv"
    return sorted(tf_dir.glob(pattern)) if tf_dir.exists() else []


def main():
    """CLI 入口点.

    CLI 参数收敛为 7 个（原 16 个）。回测专有参数（timeframe/data_dir/output_dir/
    cash/commission/输出日期模式）下放到 config/backtest.yaml，由 --profile 选取。
    symbol 唯一来源是 --strategies 的 name:symbol，与实盘 --run 格式一致。
    """
    parser = argparse.ArgumentParser(description="CTA 策略回测框架")
    parser.add_argument(
        "--strategies",
        required=True,
        help=(
            "运行清单，格式 name:symbol（与实盘 run_strategies_manager.py 的 --run 一致）。"
            "自动加载 strategies/<name>/overrides/<symbol>.yaml；文件不存在则报错。"
            "示例: --strategies sar_snt3_v3:BTCUSDT"
        ),
    )
    parser.add_argument(
        "--start",
        required=True,
        help="开始日期 (YYYYMMDD 或时间戳)，覆盖 profile.start",
    )
    parser.add_argument(
        "--end",
        default=None,
        help="结束日期 (YYYYMMDD 或时间戳，默认当前时间)，覆盖 profile.end",
    )
    parser.add_argument(
        "--profile",
        default="backtest",
        help="run-profile（默认 backtest），从 config/<name>.yaml 读取回测专有参数",
    )
    parser.add_argument(
        "--config-path",
        dest="config_path",
        default=None,
        help="策略配置文件完整路径（覆盖默认 overrides 路径，与实盘 --config-path 一致）",
    )
    parser.add_argument(
        "--overrides",
        default=None,
        help="配置覆盖字段（JSON 字符串），用于覆盖配置文件中的特定字段",
    )
    parser.add_argument(
        "--log-level",
        default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别（优先级高于 profile 与配置文件）",
    )

    args = parser.parse_args()

    # 加载 run-profile（回测专有参数：cash/commission/data_dir/output_dir/...）
    try:
        profile_cfg = load_profile(args.profile)
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"加载 profile 失败: {e}")
        sys.exit(1)

    # 回测专有参数全部来自 profile，CLI 不得覆盖（避免回测与实盘读两份策略参数）
    timeframe = profile_cfg.get("timeframe", "1m")
    data_dir = profile_cfg.get("data_dir", "./data/klines")
    output_dir = profile_cfg.get("output_dir", "./backtest_output")
    cash = profile_cfg.get("cash", 5000)
    commission = profile_cfg.get("commission", 0.0004)
    use_today_as_output_date = profile_cfg.get("use_today_as_output_date", True)

    # data_dir 是 profile 与 settings.yaml 间唯一的语义重复（回测不读 settings.yaml）。
    # 只改一处会导致实盘往 A 目录写、回测从 B 目录读，回测基于过时数据却无提示 ——
    # 属于回测失真，故启动即校验。settings.yaml 缺失时跳过（纯回测使用者不该被实盘配置阻断）。
    try:
        settings_csv_dir = None
        settings_path = Path("config/settings.yaml")
        if settings_path.exists():
            with open(settings_path, "r", encoding="utf-8") as f:
                settings_csv_dir = (
                    (yaml.safe_load(f) or {}).get("data_manager", {}).get("csv_dir")
                )
        verify_data_dir_consistency(data_dir, settings_csv_dir)
    except ValueError as e:
        logger.error(str(e))
        sys.exit(1)

    # 运行清单：单次回测只跑一个 name:symbol，symbol 唯一来源就是这里
    pairs = parse_explicit_strategies(args.strategies)
    if len(pairs) != 1:
        logger.error(
            f"--strategies 仅支持单个 name:symbol，收到 {len(pairs)} 个: {pairs}。"
            f"批量回测请用 backtest.batch_runner。"
        )
        sys.exit(1)
    strategy_dir_name, symbol_cli = pairs[0]

    # --config-path 优先；否则按 overrides 约定推导
    config_path_resolved = args.config_path or str(
        Path("strategies") / strategy_dir_name / "overrides" / f"{symbol_cli}.yaml"
    )
    if not Path(config_path_resolved).exists():
        logger.error(f"策略配置文件不存在: {config_path_resolved}")
        sys.exit(1)
    strategy_config = load_strategy_config_from_path(config_path_resolved, strategy_dir_name)
    logger.info(f"配置来源(--strategies): {config_path_resolved}")
    logger.info(f"profile: {args.profile} | data_dir={data_dir} cash={cash} commission={commission}")

    if not strategy_config:
        logger.error(f"无法加载策略 {strategy_dir_name} 的配置")
        sys.exit(1)

    # 合并 overrides（如果提供）
    if args.overrides:
        try:
            overrides = json.loads(args.overrides)
            strategy_config = merge_config_with_overrides(strategy_config, overrides)
            logger.info(f"已应用配置覆盖: {list(overrides.keys())}")
        except json.JSONDecodeError as e:
            logger.error(f"overrides JSON 解析失败: {e}")
            sys.exit(1)

    # 日志级别优先级：CLI > 策略配置 diagnostic_log_level > profile > 默认 INFO
    # 这里就地展开而不调 resolve_log_level：后者不认识 profile 这一级
    if args.log_level:
        log_level_str = args.log_level.upper()
    elif strategy_config.get("signal", {}).get("diagnostic_log_level"):
        log_level_str = strategy_config["signal"]["diagnostic_log_level"].upper()
    else:
        log_level_str = profile_cfg.get("log_level", "INFO").upper()
    log_level = getattr(logging, log_level_str, logging.INFO)

    # 解析日期参数（支持时间戳）- 必须在日志初始化之前
    start_date, start_dt = parse_date_input(args.start)
    if args.end:
        end_date, end_dt = parse_date_input(args.end)
    else:
        end_dt = datetime.now(timezone.utc)
        end_date = end_dt.strftime("%Y%m%d")

    # 生成标准化日志文件名（与实盘一致）
    timeframes = strategy_config.get("timeframes")
    interval = timeframes[0] if timeframes else "4h"
    version = strategy_config.get("version", "v2")
    log_filename = build_strategy_id_from_overrides(
        strategy_dir=strategy_dir_name,
        symbol=symbol_cli,
        trading_mode="backtest",  # 回测模式
        interval=interval,
        version=version,
    )

    # 添加按日目录存储的文件日志处理器
    # 回测模式：使用 --end 参数作为日志目录日期，与输出目录一致
    file_handler = DailyDirectoryFileHandler(
        base_dir="logs/backtest",
        filename=log_filename,
        encoding="utf-8",
        date_override=end_date,
    )
    file_handler.setFormatter(logging.Formatter(
        f"%(asctime)s - [{log_filename}] - %(name)s - %(levelname)s - %(message)s"
    ))

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            file_handler,
            logging.StreamHandler(),
        ],
    )

    # 回测模式下，针对高频模块降低日志级别，减少 IO 开销
    if log_level <= logging.INFO:
        logging.getLogger("data_manager.manager").setLevel(logging.WARNING)
        logging.getLogger("backtest.bt_strategy").setLevel(logging.WARNING)

    logger.info(f"日志级别: {log_level_str}")

    run_backtest(
        strategy_dir_name=strategy_dir_name,
        symbol=symbol_cli,
        start_date=start_date,
        end_date=end_date,
        start_dt=start_dt,
        end_dt=end_dt,
        timeframe=timeframe,
        data_dir=data_dir,
        output_dir=output_dir,
        cash=cash,
        commission=commission,
        strategy_config=strategy_config,
        config_path=config_path_resolved,  # 实际生效的配置路径，复制到输出目录供复现
        use_today_as_output_date=use_today_as_output_date,
    )


if __name__ == "__main__":
    main()
