"""preload_klines_to_cache 测试：数据源、缺口规划、覆盖校验。

自动下载走 scripts/download_data.download_range（Binance 归档 + fapi）。
早期实现走 data_manager.load_klines_data，那条路径只扫本地按日 ZIP 解包目录，
干净环境下永远返回空 → 「自动下载」不联网，回测在过时数据上静默跑出零成交报告。
本文件的 TestDataCoverageVerification 是那个缺陷的回归锚点。
"""

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from data_manager import DataManager, DataManagerConfig
from backtest.run_backtest import (
    _parse_kline_timestamps,
    _plan_download_gaps,
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
        realtime_enabled=False,
    )
    dm = DataManager(dm_config)
    dm.connect()
    return dm


@pytest.fixture(autouse=True)
def no_network():
    """拦截 download_range —— 任何用例都不得真发网络请求。

    autouse 而非逐个 patch：漏掉一处会让该用例静默走真实 Binance，
    在无网环境挂几十秒后才失败（重构期间就这么挂过一次整个 suite）。
    需要断言下载行为的用例直接把本 fixture 作为参数取用返回的 mock。
    """
    with patch('backtest.run_backtest.download_range') as mock:
        yield mock


def _covering_csv(tmpdir: str, symbol: str = "BTCUSDT", n: int = 3000,
                  start: datetime = None) -> Path:
    """写一份覆盖 [2025-12-30, 2026-01-01 02:00] 的 1m CSV。

    默认 start_date=20260101 的用例需要数据覆盖 warm-up 起点与回测窗口起点，
    否则会被覆盖校验判定为数据不足而 exit 1（那是生产上的正确行为）。
    """
    if start is None:
        start = datetime(2025, 12, 30, tzinfo=timezone.utc)
    csv_dir = Path(tmpdir) / "1m"
    csv_dir.mkdir(parents=True, exist_ok=True)
    path = csv_dir / f"{symbol}_1m.csv"
    _make_1m_df(n=n, start=start).to_csv(path, index=False)
    return path


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
            _covering_csv(tmpdir)

            dm = _make_dm(tmpdir)
            preload_klines_to_cache(
                dm, ["BTCUSDT"], "1m", tmpdir, "", "20260101", end_date="20260101",
            )

            cached = dm.cache.get_1m_data("BTCUSDT")
            assert cached is not None
            assert len(cached) >= 3000

    def test_no_strategy_dir_lookup(self, no_network):
        """不再查找策略目录 CSV —— 全局目录没有就该触发下载"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 只在策略目录放数据，不在全局目录
            strategy_dir = Path(tmpdir) / "obv_atr" / "1m"
            strategy_dir.mkdir(parents=True)
            _make_1m_df().to_csv(strategy_dir / "BTCUSDT_1m.csv", index=False)

            dm = _make_dm(tmpdir)

            # 下载是 no-op（fixture），故 CSV 仍不存在 → 覆盖校验 exit 1
            with pytest.raises(SystemExit):
                preload_klines_to_cache(
                    dm, ["BTCUSDT"], "1m", tmpdir, "obv_atr", "20260101",
                    end_date="20260101",
                )

            assert no_network.called, "全局 CSV 缺失时应尝试下载，而非读策略目录"

    def test_aggregates_big_intervals(self):
        """加载 1m 后自动聚合大周期"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _covering_csv(tmpdir)

            dm = _make_dm(tmpdir)
            dm.register_timeframes("BTCUSDT", ["4h"])
            preload_klines_to_cache(
                dm, ["BTCUSDT"], "1m", tmpdir, "", "20260101", end_date="20260101",
            )

            cached_4h = dm.cache.get("BTCUSDT", "4h")
            assert cached_4h is not None, "应自动聚合 4h 数据"


class TestPreloadNoSyncToLatest:
    """preload_klines_to_cache 不应调用 sync_to_latest."""

    def test_no_sync_to_latest(self):
        """不应使用 sync_to_latest API 降级"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _covering_csv(tmpdir)
            dm = _make_dm(tmpdir)

            with patch.object(dm, 'sync_to_latest') as mock_sync:
                preload_klines_to_cache(
                    dm, ["BTCUSDT"], "1m", tmpdir, "", "20260101", end_date="20260101",
                )
                mock_sync.assert_not_called()


# ── 数据源：download_range 是唯一下载路径 ─────────────────────────

class TestDownloadSourceIsDownloadRange:
    """自动下载必须走 scripts/download_data.download_range（联网）。

    旧实现走 load_klines_data（只扫本地 ZIP 目录），干净环境永远返回空。
    """

    def test_no_local_zip_loader_reference(self):
        """run_backtest 不得再引用 load_klines_data / save_to_csv。

        它们是「不联网的自动下载」的来源；留着任何一处引用都意味着
        存在第二条产出格式不同的落盘路径。
        """
        import backtest.run_backtest as rb

        assert not hasattr(rb, "load_klines_data")
        assert not hasattr(rb, "save_to_csv")

    def test_missing_csv_downloads_warmup_to_sync_end(self, no_network):
        """CSV 不存在 → 下载 [warmup_start, sync_end)"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dm = _make_dm(tmpdir)
            strategy_config = {"params": {"obv_timeframes": "4h", "obv_ma_period": 20}}

            with pytest.raises(SystemExit):
                preload_klines_to_cache(
                    dm, ["ETHUSDT"], "1m", tmpdir, "", "20260601",
                    strategy_config=strategy_config, end_date="20260601",
                )

            args = no_network.call_args[0]
            assert args[0] == "ETHUSDT"
            assert args[1] == "1m"
            # warm-up = 20 根 4h × 1.2 = 5760 分钟
            expected_start = (
                datetime(2026, 6, 1, tzinfo=timezone.utc) - timedelta(minutes=5760)
            )
            assert args[2] == expected_start
            assert args[3] <= datetime(2026, 6, 1, 23, 59, 59, tzinfo=timezone.utc)

    def test_no_download_when_data_already_covers_range(self, no_network):
        """数据已覆盖区间时不得发起任何下载。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 覆盖 2025-12-30 ~ 2026-01-01 02:00，回测 20260101 且 end 也在范围内
            _covering_csv(tmpdir)
            dm = _make_dm(tmpdir)

            # sync_end 取 CSV 末根之前，制造"完全覆盖"
            with patch('backtest.run_backtest.datetime') as mock_dt:
                mock_dt.now.return_value = datetime(2026, 1, 1, 1, 0, tzinfo=timezone.utc)
                mock_dt.strptime = datetime.strptime
                preload_klines_to_cache(
                    dm, ["BTCUSDT"], "1m", tmpdir, "", "20260101", end_date="20260101",
                )

            no_network.assert_not_called()


# ── 缺口规划（纯函数） ───────────────────────────────────────────

class TestPlanDownloadGaps:
    """_plan_download_gaps: 只补「需要且缺失」的子区间"""

    def test_empty_csv_downloads_whole_range(self):
        gaps = _plan_download_gaps(
            None,
            datetime(2026, 8, 12, tzinfo=timezone.utc),
            datetime(2026, 8, 24, tzinfo=timezone.utc),
        )

        assert len(gaps) == 1
        assert gaps[0][0] == datetime(2026, 8, 12, tzinfo=timezone.utc)
        assert gaps[0][1] == datetime(2026, 8, 24, tzinfo=timezone.utc)

    def test_tail_gap_starts_at_csv_last_bar_itself(self):
        """尾部缺口起点必须是末根**本身**，而非末根 + 1 分钟。

        崩溃时未闭合就落盘的残缺末根（volume/high 不全）需要被重新拉取的
        完整值覆盖；+1min 起点会让它永久污染，并顺着聚合污染大周期。
        """
        df = _make_1m_df(n=10, start=datetime(2026, 8, 1, tzinfo=timezone.utc))

        gaps = _plan_download_gaps(
            df,
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 24, tzinfo=timezone.utc),
        )

        assert len(gaps) == 1
        # 末根 = 2026-08-01 00:09
        assert gaps[0][0] == datetime(2026, 8, 1, 0, 9, tzinfo=timezone.utc)

    def test_head_gap_when_warmup_earlier_than_csv(self):
        """warm-up 起点早于 CSV 起点 → 补头部，终点不越过 CSV 起点。"""
        df = _make_1m_df(n=10, start=datetime(2026, 8, 10, tzinfo=timezone.utc))

        gaps = _plan_download_gaps(
            df,
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 24, tzinfo=timezone.utc),
        )

        head = [g for g in gaps if "头部" in g[2]]
        assert len(head) == 1
        assert head[0][0] == datetime(2026, 8, 1, tzinfo=timezone.utc)
        assert head[0][1] == datetime(2026, 8, 10, tzinfo=timezone.utc)

    def test_only_missing_subrange_not_whole_span(self):
        """只补缺失部分 —— 这是 12 天 vs 47 天的差别。

        报障 case：CSV 覆盖 06-02~07-08，warm-up 起点 08-12。旧实现从 CSV 末根
        (07-08) 一路要到今天 = 47 天；实际只有 08-12 之后是回测需要的。
        """
        df = _make_1m_df(n=10, start=datetime(2026, 6, 2, tzinfo=timezone.utc))

        gaps = _plan_download_gaps(
            df,
            datetime(2026, 8, 12, tzinfo=timezone.utc),
            datetime(2026, 8, 24, tzinfo=timezone.utc),
        )

        assert len(gaps) == 1
        # 起点取 max(csv_max, warmup_start) = 08-12，不是 06-02
        assert gaps[0][0] == datetime(2026, 8, 12, tzinfo=timezone.utc)
        span_days = (gaps[0][1] - gaps[0][0]).days
        assert span_days == 12, f"应只补 12 天，实际 {span_days} 天"

    def test_no_gap_when_fully_covered(self):
        df = _make_1m_df(n=1440, start=datetime(2026, 8, 1, tzinfo=timezone.utc))

        gaps = _plan_download_gaps(
            df,
            datetime(2026, 8, 1, tzinfo=timezone.utc),
            datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc),
        )

        assert gaps == []


# ── sync_end 不得超过当前时刻 ────────────────────────────────────

class TestSyncEndClampedToNow:
    """end_date 取当天时不得向交易所索要未来 K 线。

    `parse_date_input(end_date).replace(hour=23, minute=59, second=59)` 在
    end_date=今天 时会算出比"现在"晚十几小时的终点，让尾部缺口判据恒真 ——
    每次回测都白跑一次注定拿不到数据的下载。
    """

    def test_today_end_date_does_not_request_future_bars(self, no_network):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_now = datetime(2026, 8, 24, 8, 30, tzinfo=timezone.utc)
            _covering_csv(
                tmpdir, n=10, start=datetime(2026, 8, 12, tzinfo=timezone.utc),
            )
            dm = _make_dm(tmpdir)

            with patch('backtest.run_backtest.datetime') as mock_dt:
                mock_dt.now.return_value = fake_now
                mock_dt.strptime = datetime.strptime
                with pytest.raises(SystemExit):
                    preload_klines_to_cache(
                        dm, ["BTCUSDT"], "1m", tmpdir, "", "20260820",
                        end_date="20260824",
                    )

            gap_end = no_network.call_args[0][3]
            assert gap_end <= fake_now, (
                f"下载终点 {gap_end} 晚于当前时刻 {fake_now} —— 在索要未来 K 线"
            )


# ── 覆盖校验：不足即硬失败（本次报障的核心） ──────────────────────

class TestDataCoverageVerification:
    """数据不覆盖回测区间时必须 exit 1，不得静默产出零成交报告。

    报障现场：CSV 只到 2026-07-08，回测窗口 2026-08-20 起，窗口内零根 K 线。
    旧实现只打 WARNING 继续跑，产出「处理 K 线数：0」的报告且退出码 0 ——
    看起来像"策略没触发信号"，实则一根数据都没有。
    """

    def _run(self, tmpdir, dm, start="20260820", end="20260824"):
        return preload_klines_to_cache(
            dm, ["BTCUSDT"], "1m", tmpdir, "", start, end_date=end,
        )

    def test_window_with_zero_bars_exits_1(self):
        """回测窗口内零根 K 线 → exit 1（就是本次报障的 case）。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # CSV 到 2026-07-08，回测从 2026-08-20 起
            _covering_csv(
                tmpdir, n=100, start=datetime(2026, 7, 8, 22, 20, tzinfo=timezone.utc),
            )
            dm = _make_dm(tmpdir)

            with pytest.raises(SystemExit) as exc:
                self._run(tmpdir, dm)

            assert exc.value.code == 1

    def test_error_message_reports_gap_days(self, caplog):
        """错误信息必须含需要/实有/缺口天数，否则用户无从判断该做什么。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _covering_csv(
                tmpdir, n=100, start=datetime(2026, 7, 8, 22, 20, tzinfo=timezone.utc),
            )
            dm = _make_dm(tmpdir)

            with caplog.at_level("ERROR"):
                with pytest.raises(SystemExit):
                    self._run(tmpdir, dm)

            text = caplog.text
            assert "需要" in text and "实有" in text
            assert "缺口" in text
            assert "2026-07-08" in text, "应打印实有数据范围"
            assert "download_data.py" in text, "应给出手动补数的命令"

    def test_empty_data_exits_1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            dm = _make_dm(tmpdir)

            with pytest.raises(SystemExit) as exc:
                self._run(tmpdir, dm)

            assert exc.value.code == 1

    def test_insufficient_warmup_exits_1(self):
        """warm-up 不足 → exit 1。

        指标数据不足是静默的（只 warn 不阻断），跑完会得到一份指标全程失真
        却毫无提示的报告，比直接失败更危险。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            # 数据覆盖回测窗口，但起点晚于 warm-up 需求
            _covering_csv(
                tmpdir, n=3000, start=datetime(2026, 8, 19, tzinfo=timezone.utc),
            )
            dm = _make_dm(tmpdir)
            strategy_config = {"params": {"obv_timeframes": "4h", "obv_ma_period": 20}}

            with pytest.raises(SystemExit) as exc:
                preload_klines_to_cache(
                    dm, ["BTCUSDT"], "1m", tmpdir, "", "20260820",
                    strategy_config=strategy_config, end_date="20260821",
                )

            assert exc.value.code == 1

    def test_short_tail_gap_only_warns(self, caplog):
        """尾部短几小时只 WARNING —— 末根未闭合/归档延迟属常态，不该阻断。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 覆盖 warm-up 与窗口起点，末根停在 08-21 02:00
            _covering_csv(
                tmpdir, n=5000, start=datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc),
            )
            dm = _make_dm(tmpdir)

            with caplog.at_level("WARNING"):
                preload_klines_to_cache(
                    dm, ["BTCUSDT"], "1m", tmpdir, "", "20260820", end_date="20260821",
                )

            assert "尾部数据缺失" in caplog.text
            cached = dm.cache.get_1m_data("BTCUSDT")
            assert cached is not None, "尾部短缺不该阻断，数据仍应入缓存"

    def test_mid_sequence_holes_do_not_fail(self):
        """中部空洞不校验 —— 交易所停机是常态。

        现有 BTCUSDT CSV 在 06-02~07-08 间就缺 523 根。端点覆盖才是可执行的信号；
        中部连续性由 data_manager 的定时扫描负责。
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            df = pd.concat([
                _make_1m_df(n=2000, start=datetime(2026, 8, 17, 15, 0, tzinfo=timezone.utc)),
                _make_1m_df(n=3000, start=datetime(2026, 8, 19, 6, 0, tzinfo=timezone.utc)),
            ], ignore_index=True)
            csv_dir = Path(tmpdir) / "1m"
            csv_dir.mkdir(parents=True)
            df.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)

            dm = _make_dm(tmpdir)

            # 不抛 SystemExit
            preload_klines_to_cache(
                dm, ["BTCUSDT"], "1m", tmpdir, "", "20260820", end_date="20260821",
            )

            assert dm.cache.get_1m_data("BTCUSDT") is not None


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


class TestSaveBigIntervalCsvs:
    """_save_big_interval_csvs: 回测时自动保存大周期数据到 CSV"""

    def test_saves_15m_csv_after_aggregation(self):
        """聚合 15m 后应保存到 {data_dir}/15m/{symbol}_15m.csv"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _covering_csv(tmpdir)

            dm = _make_dm(tmpdir)
            dm.register_timeframes("BTCUSDT", ["15m"])

            preload_klines_to_cache(
                dm, ["BTCUSDT"], "1m", tmpdir, "", "20260101", end_date="20260101",
            )

            csv_15m = Path(tmpdir) / "15m" / "BTCUSDT_15m.csv"
            assert csv_15m.exists(), "15m CSV 应被创建"
            assert len(pd.read_csv(csv_15m)) > 0, "15m CSV 应有数据"

    def test_merges_with_existing_csv(self):
        """已有大周期 CSV 时应合并去重，保留历史"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _covering_csv(tmpdir)

            # 旧的 15m CSV（时间范围在新数据之前，确保不重叠）
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

            preload_klines_to_cache(
                dm, ["BTCUSDT"], "1m", tmpdir, "", "20260101", end_date="20260101",
            )

            df_result = pd.read_csv(csv_15m_dir / "BTCUSDT_15m.csv")
            df_result['timestamp'] = pd.to_datetime(df_result['timestamp'], utc=True)

            old_start = pd.Timestamp('2025-12-20 00:00:00', tz='UTC')
            old_end = pd.Timestamp('2025-12-20 04:45:00', tz='UTC')
            mask = (df_result['timestamp'] >= old_start) & (df_result['timestamp'] <= old_end)
            assert mask.sum() >= 20, f"应保留旧数据范围，找到 {mask.sum()} 行"

    def test_skips_1m_csv_save(self):
        """_save_big_interval_csvs 不处理 1m 周期"""
        with tempfile.TemporaryDirectory() as tmpdir:
            dm = _make_dm(tmpdir)
            dm.register_timeframes("BTCUSDT", ["1m", "4h"])

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

            df_1m = _make_1m_df(n=100)
            dm.cache.put("BTCUSDT", "1m", df_1m, force_1m=True)

            csv_1m = Path(tmpdir) / "1m" / "BTCUSDT_1m.csv"
            csv_1m.parent.mkdir(parents=True, exist_ok=True)
            df_1m.to_csv(csv_1m, index=False)
            mtime_before = csv_1m.stat().st_mtime

            import time
            time.sleep(0.1)

            from backtest.run_backtest import _save_big_interval_csvs
            _save_big_interval_csvs(dm, "BTCUSDT", tmpdir)

            assert csv_1m.stat().st_mtime == mtime_before, \
                "_save_big_interval_csvs 不应修改 1m CSV"

            csv_4h = Path(tmpdir) / "4h" / "BTCUSDT_4h.csv"
            assert csv_4h.exists(), "4h CSV 应被创建"

    def test_handles_multiple_big_intervals(self):
        """同时保存多个大周期（15m, 4h, 1d）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _covering_csv(
                tmpdir, n=5000, start=datetime(2025, 12, 29, tzinfo=timezone.utc),
            )

            dm = _make_dm(tmpdir)
            dm.register_timeframes("BTCUSDT", ["15m", "4h", "1d"])

            preload_klines_to_cache(
                dm, ["BTCUSDT"], "1m", tmpdir, "", "20260101", end_date="20260101",
            )

            for tf in ["15m", "4h", "1d"]:
                csv_path = Path(tmpdir) / tf / f"BTCUSDT_{tf}.csv"
                assert csv_path.exists(), f"{tf} CSV 应被创建"
                assert len(pd.read_csv(csv_path)) > 0, f"{tf} CSV 应有数据"


# ── 缺口时长渲染 ─────────────────────────────────────────────────

class TestHumanizeGap:
    """_humanize_gap: 不足一天的缺口不能显示成「0 天」。

    原用 `(a - b).days`，6h28m 的缺口打印「缺口 0 天」却同时 exit 1 ——
    读者会以为没缺东西、怀疑是误报，从而忽略真实的数据不足。
    实测触发场景：用 100 行(1h40m)的小样本 CSV 跑回测。
    """

    @pytest.mark.parametrize("minutes,expected", [
        (30, "30 分钟"),
        (59, "59 分钟"),
        (60, "1 小时 0 分钟"),
        (388, "6 小时 28 分钟"),      # 实测撞到的那个缺口
        (1439, "23 小时 59 分钟"),
        (1440, "1 天 0 小时"),
        (2880, "2 天 0 小时"),
        (3600, "2 天 12 小时"),
    ])
    def test_renders_sub_day_gaps(self, minutes, expected):
        from backtest.run_backtest import _humanize_gap
        assert _humanize_gap(timedelta(minutes=minutes)) == expected

    def test_never_reports_zero_for_nonzero_gap(self):
        """任何非零缺口都不得渲染出「0 天」这种自相矛盾的信息。"""
        from backtest.run_backtest import _humanize_gap
        for minutes in range(1, 1440, 37):
            out = _humanize_gap(timedelta(minutes=minutes))
            assert not out.startswith("0 "), f"{minutes}min → {out}"
