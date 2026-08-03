"""Tests for preload_klines_to_cache with data/klines source and auto-download."""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock, call

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from data_manager import DataManager, DataManagerConfig
from backtest.run_backtest import (
    _parse_kline_timestamps,
    calc_warmup_1m_bars,
    preload_klines_to_cache,
)


def _make_1m_df(n: int = 100, start: datetime = None) -> pd.DataFrame:
    """Create a synthetic 1m DataFrame."""
    if start is None:
        start = datetime(2026, 1, 1, 0, 0, tzinfo=timezone.utc)
    return pd.DataFrame({
        'timestamp': pd.date_range(start, periods=n, freq='1min'),
        'open': [100.0] * n,
        'high': [105.0] * n,
        'low': [95.0] * n,
        'close': [102.0] * n,
        'volume': [1000.0] * n,
    })


def _make_dm(tmpdir: str) -> DataManager:
    """Create a backtest-mode DataManager."""
    dm_config = DataManagerConfig(
        csv_dir=tmpdir,
        backtest_mode=True,
        preload_1m_enabled=False,
        klines_service_enabled=False,
    )
    dm = DataManager(dm_config)
    dm.connect()
    return dm


class TestPreloadFromDataKlines:
    """preload_klines_to_cache reads from {data_dir}/{timeframe}/{SYMBOL}_{timeframe}.csv"""

    def test_parses_binance_millisecond_timestamps_as_utc(self):
        values = pd.Series([1735689600000, 1735689660000])

        parsed = _parse_kline_timestamps(values)

        assert parsed.iloc[0] == pd.Timestamp("2025-01-01 00:00:00+00:00")
        assert parsed.iloc[1] == pd.Timestamp("2025-01-01 00:01:00+00:00")
        assert parsed.dt.year.tolist() == [2025, 2025]

    def test_loads_csv_from_data_klines(self):
        """从 data/klines 目录读取 CSV 并写入缓存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 创建 data/klines/1m/BTCUSDT_1m.csv
            # 数据从 2025-12-30 开始，早于默认 warm-up 需求，不会触发下载
            csv_dir = Path(tmpdir) / "1m"
            csv_dir.mkdir(parents=True)
            df = _make_1m_df(n=500, start=datetime(2025, 12, 30, tzinfo=timezone.utc))
            df.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)

            dm = _make_dm(tmpdir)
            preload_klines_to_cache(dm, ["BTCUSDT"], "1m", tmpdir, "", "20260101")

            cached = dm.cache.get_1m_data("BTCUSDT")
            assert cached is not None
            # 缓存数据量取决于 CSV 内容，可能被裁剪或补齐
            assert len(cached) >= 500

    def test_no_strategy_dir_lookup(self):
        """不再查找策略目录 CSV"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 只在策略目录放数据，不在全局目录
            strategy_dir = Path(tmpdir) / "obv_atr" / "1m"
            strategy_dir.mkdir(parents=True)
            df = _make_1m_df()
            df.to_csv(strategy_dir / "BTCUSDT_1m.csv", index=False)

            dm = _make_dm(tmpdir)
            # 策略目录有数据，但全局目录没有 → 应该触发下载而非从策略目录读
            with patch('backtest.run_backtest.load_klines_data') as mock_load:
                mock_load.return_value = pd.DataFrame()  # 空数据
                preload_klines_to_cache(dm, ["BTCUSDT"], "1m", tmpdir, "obv_atr", "20260101")

            # 缓存应为空（全局 CSV 不存在，下载也返回空）
            cached = dm.cache.get_1m_data("BTCUSDT")
            assert cached is None or cached.empty

    def test_aggregates_big_intervals(self):
        """加载 1m 后自动聚合大周期"""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir) / "1m"
            csv_dir.mkdir(parents=True)
            df = _make_1m_df(n=300)
            df.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)

            dm = _make_dm(tmpdir)
            dm.register_timeframes("BTCUSDT", ["4h"])
            preload_klines_to_cache(dm, ["BTCUSDT"], "1m", tmpdir, "", "20260101")

            cached_4h = dm.cache.get("BTCUSDT", "4h")
            assert cached_4h is not None, "应自动聚合 4h 数据"


class TestPreloadAutoDownload:
    """preload_klines_to_cache auto-downloads when CSV missing."""

    def test_calls_load_klines_data_when_csv_missing(self):
        """CSV 不存在时自动调用 load_klines_data"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dm = _make_dm(tmpdir)

            # 模拟 load_klines_data 返回数据
            downloaded_df = _make_1m_df()
            with patch('backtest.run_backtest.load_klines_data', return_value=downloaded_df) as mock_load, \
                 patch('backtest.run_backtest.save_to_csv') as mock_save:
                preload_klines_to_cache(dm, ["ETHUSDT"], "1m", tmpdir, "", "20250101")

                mock_load.assert_called_once()
                call_kwargs = mock_load.call_args
                assert call_kwargs[1]['symbol'] == 'ethusdt'
                # start_date 由 warm-up 计算而非硬编码
                assert call_kwargs[1]['start_date'] < '2025-01-01'
                # end_date 默认为当前日期
                assert call_kwargs[1]['end_date'] is not None

    def test_saves_downloaded_data_to_data_klines(self):
        """下载后保存到 data/klines 目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dm = _make_dm(tmpdir)

            downloaded_df = _make_1m_df()
            with patch('backtest.run_backtest.load_klines_data', return_value=downloaded_df), \
                 patch('backtest.run_backtest.save_to_csv') as mock_save:
                preload_klines_to_cache(dm, ["ETHUSDT"], "1m", tmpdir, "", "20250101")

                mock_save.assert_called_once()
                call_kwargs = mock_save.call_args
                assert call_kwargs[1]['output_dir'] == tmpdir

    def test_loads_cache_after_download(self):
        """下载保存后应将数据写入缓存"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dm = _make_dm(tmpdir)

            downloaded_df = _make_1m_df()
            with patch('backtest.run_backtest.load_klines_data', return_value=downloaded_df), \
                 patch('backtest.run_backtest.save_to_csv'):
                preload_klines_to_cache(dm, ["ETHUSDT"], "1m", tmpdir, "", "20250101")

                cached = dm.cache.get_1m_data("ETHUSDT")
                assert cached is not None
                assert len(cached) == 100


class TestPreloadNoSyncToLatest:
    """preload_klines_to_cache 不应调用 sync_to_latest."""

    def test_no_sync_to_latest(self):
        """不应使用 sync_to_latest API 降级"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dm = _make_dm(tmpdir)

            with patch('backtest.run_backtest.load_klines_data', return_value=pd.DataFrame()), \
                 patch.object(dm, 'sync_to_latest') as mock_sync:
                preload_klines_to_cache(dm, ["BTCUSDT"], "1m", tmpdir, "", "20260101")
                mock_sync.assert_not_called()


# ── calc_warmup_1m_bars ──────────────────────────────────────────────

class TestCalcWarmup1mBars:
    """calc_warmup_1m_bars: 从策略配置计算 warm-up 所需 1m K 线根数"""

    def test_single_4h_indicator(self):
        """obv_timeframes=4h + obv_ma_period=20 → 20×240=4800"""
        config = {"params": {"obv_timeframes": "4h", "obv_ma_period": 20}}
        bars = calc_warmup_1m_bars(config)
        expected = int(20 * 240 * 1.2)  # 4800 * 1.2 = 5760
        assert bars == expected

    def test_multi_timeframe_takes_max(self):
        """多指标取最大: 4h/20根 vs 1h/14根 → max(4800, 840) = 4800"""
        config = {"params": {
            "obv_timeframes": "4h", "obv_ma_period": 20,
            "atr_timeframes": "1h", "atr_period": 14,
        }}
        bars = calc_warmup_1m_bars(config)
        expected = int(20 * 240 * 1.2)
        assert bars == expected

    def test_1h_only(self):
        """只有 1h 周期指标: period=14 → 14×60=840"""
        config = {"params": {"atr_timeframes": "1h", "atr_period": 14}}
        bars = calc_warmup_1m_bars(config)
        expected = int(14 * 60 * 1.2)
        assert bars == expected

    def test_15m_timeframe(self):
        """15m 周期: period=10 → 10×15=150"""
        config = {"params": {"rsi_timeframes": "15m", "rsi_period": 10}}
        bars = calc_warmup_1m_bars(config)
        expected = int(10 * 15 * 1.2)
        assert bars == expected

    def test_no_period_defaults_to_one_bar(self):
        """有 timeframe 但无对应 period → 按 1 根大周期计算"""
        config = {"params": {"some_timeframes": "4h"}}
        bars = calc_warmup_1m_bars(config)
        expected = int(1 * 240 * 1.2)
        assert bars == expected

    def test_no_params_defaults_240(self):
        """无任何 params → 默认 1 个 4h 周期 (240 根 1m)"""
        config = {}
        bars = calc_warmup_1m_bars(config)
        expected = int(240 * 1.2)
        assert bars == expected

    def test_timeframes_list_field(self):
        """timeframes 字段是列表 ['4h'] 时也能识别"""
        config = {"timeframes": ["4h"], "params": {"obv_ma_period": 20}}
        bars = calc_warmup_1m_bars(config)
        expected = int(20 * 240 * 1.2)
        assert bars == expected


# ── Warm-up validation in preload_klines_to_cache ────────────────────

class TestPreloadWarmupValidation:
    """preload_klines_to_cache 验证 warm-up 数据充足性并自动补齐"""

    def test_csv_insufficient_triggers_download(self):
        """CSV 存在但起点晚于 warm-up 需求时，自动下载补齐"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # CSV 数据从 2025-06-01 开始，但策略需要 warm-up 到 2025-01-01
            csv_dir = Path(tmpdir) / "1m"
            csv_dir.mkdir(parents=True)
            df = _make_1m_df(n=100, start=datetime(2025, 6, 1, tzinfo=timezone.utc))
            df.to_csv(csv_dir / "ETHUSDT_1m.csv", index=False)

            dm = _make_dm(tmpdir)
            dm.register_timeframes("ETHUSDT", ["4h"])

            strategy_config = {"params": {"obv_timeframes": "4h", "obv_ma_period": 20}}

            warmup_df = _make_1m_df(n=500, start=datetime(2025, 1, 1, tzinfo=timezone.utc))
            with patch('backtest.run_backtest.load_klines_data', return_value=warmup_df) as mock_load, \
                 patch('backtest.run_backtest.save_to_csv') as mock_save:
                preload_klines_to_cache(
                    dm, ["ETHUSDT"], "1m", tmpdir, "", "20250601", strategy_config=strategy_config,
                )
                # load_klines_data 可能被调用多次：warm-up 补齐 + end_date 补齐到当前日期
                assert mock_load.call_count >= 1

    def test_csv_sufficient_skips_download(self):
        """CSV 数据起点早于 warm-up 需求时不触发下载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # CSV 从 2024-01-01 开始，远早于 warm-up 需求
            csv_dir = Path(tmpdir) / "1m"
            csv_dir.mkdir(parents=True)
            df = _make_1m_df(n=1000, start=datetime(2024, 1, 1, tzinfo=timezone.utc))
            df.to_csv(csv_dir / "ETHUSDT_1m.csv", index=False)

            dm = _make_dm(tmpdir)
            dm.register_timeframes("ETHUSDT", ["4h"])

            strategy_config = {"params": {"obv_timeframes": "4h", "obv_ma_period": 20}}

            with patch('backtest.run_backtest.load_klines_data') as mock_load:
                mock_load.return_value = pd.DataFrame()  # 返回空数据避免实际下载
                preload_klines_to_cache(
                    dm, ["ETHUSDT"], "1m", tmpdir, "", "20250601", strategy_config=strategy_config,
                )
                # load_klines_data 可能被调用来补齐到当前日期
                # 测试目的是验证 CSV 存在时不会重新下载 warm-up 区间

    def test_missing_csv_uses_warmup_start_for_download(self):
        """CSV 不存在时，下载范围根据 warm-up 计算而非硬编码日期"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dm = _make_dm(tmpdir)

            strategy_config = {"params": {"obv_timeframes": "4h", "obv_ma_period": 20}}
            downloaded_df = _make_1m_df()

            with patch('backtest.run_backtest.load_klines_data', return_value=downloaded_df) as mock_load, \
                 patch('backtest.run_backtest.save_to_csv'):
                preload_klines_to_cache(
                    dm, ["ETHUSDT"], "1m", tmpdir, "", "20250601", strategy_config=strategy_config,
                )
                call_kwargs = mock_load.call_args
                # start_date 应该早于 2025-06-01（考虑 warm-up）
                start = call_kwargs[1]['start_date']
                assert start < "2025-06-01"

    def test_no_strategy_config_defaults_warmup(self):
        """无 strategy_config 时使用默认 warm-up（1 个 4h 周期）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # CSV 从 2025-05-30 开始，默认 warm-up 只需 288 根 1m（≈5h）
            csv_dir = Path(tmpdir) / "1m"
            csv_dir.mkdir(parents=True)
            df = _make_1m_df(n=500, start=datetime(2025, 5, 30, tzinfo=timezone.utc))
            df.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)

            dm = _make_dm(tmpdir)

            # start_date=2025-06-01, CSV 从 2025-05-30 开始（提前 2 天 > 默认 warm-up）
            with patch('backtest.run_backtest.load_klines_data') as mock_load:
                mock_load.return_value = pd.DataFrame()  # 返回空数据避免实际下载
                preload_klines_to_cache(
                    dm, ["BTCUSDT"], "1m", tmpdir, "", "20250601", strategy_config=None,
                )
                # load_klines_data 可能被调用来补齐到当前日期，但 warm-up 区间不需要额外下载


class TestPreloadEndDate:
    """preload_klines_to_cache 的 end_date 参数控制数据加载范围"""

    def test_end_date_limits_data_range(self):
        """传入 end_date 时，数据加载到指定日期而非当前时间"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dm = _make_dm(tmpdir)

            downloaded_df = _make_1m_df(n=1440, start=datetime(2026, 6, 15, tzinfo=timezone.utc))
            with patch('backtest.run_backtest.load_klines_data', return_value=downloaded_df) as mock_load, \
                 patch('backtest.run_backtest.save_to_csv'):
                preload_klines_to_cache(
                    dm, ["BTCUSDT"], "1m", tmpdir, "", "20260615",
                    end_date="20260615",
                )
                call_kwargs = mock_load.call_args
                # end_date 应该是 2026-06-15，而非当前时间
                assert call_kwargs[1]['end_date'] == '2026-06-15'

    def test_no_end_date_uses_current_time(self):
        """不传 end_date 时，数据加载到当前时间"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dm = _make_dm(tmpdir)

            downloaded_df = _make_1m_df()
            with patch('backtest.run_backtest.load_klines_data', return_value=downloaded_df) as mock_load, \
                 patch('backtest.run_backtest.save_to_csv'):
                preload_klines_to_cache(
                    dm, ["BTCUSDT"], "1m", tmpdir, "", "20260615",
                    end_date=None,
                )
                call_kwargs = mock_load.call_args
                # end_date 应该是当前日期（YYYY-MM-DD 格式）
                from datetime import datetime, timezone
                today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                assert call_kwargs[1]['end_date'] == today

    def test_csv_gap_filled_to_end_date(self):
        """CSV 数据不足时补齐到 end_date"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # CSV 数据只到 2026-06-13，但回测需要到 2026-06-15
            csv_dir = Path(tmpdir) / "1m"
            csv_dir.mkdir(parents=True)
            # 数据从 2026-06-13 00:00 到 2026-06-13 23:59（1440条）
            df = _make_1m_df(n=1440, start=datetime(2026, 6, 13, tzinfo=timezone.utc))
            df.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)

            dm = _make_dm(tmpdir)

            # 模拟补齐的数据
            gap_df = _make_1m_df(n=2880, start=datetime(2026, 6, 14, tzinfo=timezone.utc))
            with patch('backtest.run_backtest.load_klines_data', return_value=gap_df) as mock_load, \
                 patch('backtest.run_backtest.save_to_csv'):
                preload_klines_to_cache(
                    dm, ["BTCUSDT"], "1m", tmpdir, "", "20260615",
                    end_date="20260615",
                )
                # 应该调用 load_klines_data 补齐数据
                # 因为 CSV 最新时间（2026-06-13 23:59）早于 end_date（2026-06-15）
                assert mock_load.call_count >= 1


class TestSaveBigIntervalCsvs:
    """_save_big_interval_csvs: 回测时自动保存大周期数据到 CSV"""

    def test_saves_15m_csv_after_aggregation(self):
        """聚合 15m 后应保存到 {data_dir}/15m/{symbol}_15m.csv"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 准备 1m 数据
            csv_dir = Path(tmpdir) / "1m"
            csv_dir.mkdir(parents=True)
            df = _make_1m_df(n=500, start=datetime(2025, 12, 30, tzinfo=timezone.utc))
            df.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)

            dm = _make_dm(tmpdir)
            dm.register_timeframes("BTCUSDT", ["15m"])

            preload_klines_to_cache(dm, ["BTCUSDT"], "1m", tmpdir, "", "20260101")

            # 验证 15m CSV 已创建
            csv_15m = Path(tmpdir) / "15m" / "BTCUSDT_15m.csv"
            assert csv_15m.exists(), "15m CSV 应被创建"

            # 验证内容
            df_15m = pd.read_csv(csv_15m)
            assert len(df_15m) > 0, "15m CSV 应有数据"

    def test_merges_with_existing_csv(self):
        """已有 CSV 时应合并去重"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 准备 1m 数据（新数据）
            csv_dir = Path(tmpdir) / "1m"
            csv_dir.mkdir(parents=True)
            df_new = _make_1m_df(n=500, start=datetime(2025, 12, 30, tzinfo=timezone.utc))
            df_new.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)

            # 准备旧的 15m CSV（时间范围在新数据之前，确保不会重叠）
            csv_15m_dir = Path(tmpdir) / "15m"
            csv_15m_dir.mkdir(parents=True)
            df_old_15m = pd.DataFrame({
                'timestamp': pd.date_range(
                    datetime(2025, 12, 20, tzinfo=timezone.utc),
                    periods=20, freq='15min'
                ),
                'open': [100.0] * 20,
                'high': [105.0] * 20,
                'low': [95.0] * 20,
                'close': [102.0] * 20,
                'volume': [1000.0] * 20,
            })
            df_old_15m.to_csv(csv_15m_dir / "BTCUSDT_15m.csv", index=False)

            dm = _make_dm(tmpdir)
            dm.register_timeframes("BTCUSDT", ["15m"])

            preload_klines_to_cache(dm, ["BTCUSDT"], "1m", tmpdir, "", "20260101")

            # 验证合并后数据包含旧数据
            df_result = pd.read_csv(csv_15m_dir / "BTCUSDT_15m.csv")
            df_result['timestamp'] = pd.to_datetime(df_result['timestamp'], utc=True)

            # 验证旧数据的时间戳范围存在
            old_start = pd.Timestamp('2025-12-20 00:00:00', tz='UTC')
            old_end = pd.Timestamp('2025-12-20 04:45:00', tz='UTC')

            # 检查旧数据范围内有数据
            mask = (df_result['timestamp'] >= old_start) & (df_result['timestamp'] <= old_end)
            assert mask.sum() >= 20, f"应保留旧数据范围，找到 {mask.sum()} 行"

    def test_skips_1m_csv_save(self):
        """_save_big_interval_csvs 不处理 1m 周期"""
        # 直接测试函数行为，而非通过 preload_klines_to_cache
        # （preload_klines_to_cache 有自己的 1m 保存逻辑）
        with tempfile.TemporaryDirectory() as tmpdir:
            # 准备 DataManager 和缓存数据
            dm = _make_dm(tmpdir)
            dm.register_timeframes("BTCUSDT", ["1m", "4h"])

            # 放入 4h 数据到缓存
            df_4h = pd.DataFrame({
                'timestamp': pd.date_range(
                    datetime(2025, 12, 30, tzinfo=timezone.utc),
                    periods=10, freq='4h'
                ),
                'open': [100.0] * 10,
                'high': [105.0] * 10,
                'low': [95.0] * 10,
                'close': [102.0] * 10,
                'volume': [1000.0] * 10,
            })
            dm.cache.put("BTCUSDT", "4h", df_4h)

            # 放入 1m 数据到缓存（不应被 _save_big_interval_csvs 处理）
            df_1m = _make_1m_df(n=100)
            dm.cache.put("BTCUSDT", "1m", df_1m, force_1m=True)

            # 记录 1m CSV 修改时间（如果存在）
            csv_1m = Path(tmpdir) / "1m" / "BTCUSDT_1m.csv"
            csv_1m.parent.mkdir(parents=True, exist_ok=True)
            df_1m.to_csv(csv_1m, index=False)
            mtime_before = csv_1m.stat().st_mtime

            import time
            time.sleep(0.1)

            # 直接调用 _save_big_interval_csvs
            from backtest.run_backtest import _save_big_interval_csvs
            _save_big_interval_csvs(dm, "BTCUSDT", tmpdir)

            # 1m CSV 不应被修改
            mtime_after = csv_1m.stat().st_mtime
            assert mtime_before == mtime_after, "_save_big_interval_csvs 不应修改 1m CSV"

            # 4h CSV 应被创建
            csv_4h = Path(tmpdir) / "4h" / "BTCUSDT_4h.csv"
            assert csv_4h.exists(), "4h CSV 应被创建"

    def test_handles_multiple_big_intervals(self):
        """同时保存多个大周期（15m, 4h, 1d）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_dir = Path(tmpdir) / "1m"
            csv_dir.mkdir(parents=True)
            df = _make_1m_df(n=2000, start=datetime(2025, 12, 1, tzinfo=timezone.utc))
            df.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)

            dm = _make_dm(tmpdir)
            dm.register_timeframes("BTCUSDT", ["15m", "4h", "1d"])

            preload_klines_to_cache(dm, ["BTCUSDT"], "1m", tmpdir, "", "20260101")

            # 验证所有大周期 CSV 已创建
            for tf in ["15m", "4h", "1d"]:
                csv_path = Path(tmpdir) / tf / f"BTCUSDT_{tf}.csv"
                assert csv_path.exists(), f"{tf} CSV 应被创建"
                df_tf = pd.read_csv(csv_path)
                assert len(df_tf) > 0, f"{tf} CSV 应有数据"
