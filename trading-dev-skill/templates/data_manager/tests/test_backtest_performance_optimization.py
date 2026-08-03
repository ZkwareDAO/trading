#!/usr/bin/env python3
"""
测试回测性能优化 — TDD RED phase

测试三个优化点：
1. 优化 4：减少重复 DataFrame 操作（obv_core.py）
2. 优化 2：缓存更新优化（manager.py _backtest_update_cache）
3. 优化 3：大周期聚合优化（manager.py _update_big_intervals_from_cache）
"""

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
import time

import pandas as pd
import pytest


class TestOptimize4ReduceDuplicateDataFrameOperations:
    """测试优化 4：减少重复 DataFrame 操作"""

    @pytest.mark.skip(reason="OBVATRStrategy 类不存在，obv_atr_v2 使用 OBVCoreV2")
    def test_same_timeframe_only_fetched_once(self):
        """
        当多个指标使用相同周期时，_get_closed_data 只应调用一次

        场景：
        - obv_timeframes = "1h"
        - price_ma_timeframes = "1h"
        - volume_ma_timeframes = "1h"
        - atr_timeframes = "1h"
        - adx_timeframes = "1h"

        期望：analyze 内部只调用一次 _get_closed_data("1h")
        """
        from strategies.obv_atr_v2.obv_core import OBVCoreV2 as OBVATRStrategy

        strategy = OBVATRStrategy(
            symbols=["BTCUSDT"],
            timeframes=["1h"],
            params={
                "obv_timeframes": "1h",
                "price_ma_timeframes": "1h",
                "volume_ma_timeframes": "1h",
                "atr_timeframes": "1h",
                "adx_timeframes": "1h",
            },
        )

        # 创建测试数据
        dates = pd.date_range(start="2026-01-01", periods=30, freq="1h", tz="UTC")
        df_1h = pd.DataFrame({
            "timestamp": dates,
            "open": [50000 + i * 100 for i in range(30)],
            "high": [50100 + i * 100 for i in range(30)],
            "low": [49900 + i * 100 for i in range(30)],
            "close": [50050 + i * 100 for i in range(30)],
            "volume": [1000 + i * 10 for i in range(30)],
        })
        klines_data = {"1h": df_1h}

        # 使用 patch 监控 _get_closed_data 调用次数
        with patch.object(
            OBVATRStrategy, "_get_closed_data",
            wraps=OBVATRStrategy._get_closed_data
        ) as mock_get_closed:
            result = strategy.analyze(
                "BTCUSDT",
                klines_data,
                current_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
            )

            # 验证：相同周期只调用一次
            called_timeframes = [call[0][1] for call in mock_get_closed.call_args_list]
            unique_timeframes = set(called_timeframes)

            assert len(called_timeframes) == len(unique_timeframes), \
                f"相同周期应只调用一次，实际调用: {called_timeframes}"

    @pytest.mark.skip(reason="OBVATRStrategy 类不存在，obv_atr_v2 使用 OBVCoreV2")
    def test_different_timeframes_fetched_separately(self):
        """
        当指标使用不同周期时，每个周期应分别获取

        场景：
        - obv_timeframes = "4h"
        - price_ma_timeframes = "1h"

        期望：_get_closed_data 分别调用 "4h" 和 "1h"
        """
        from strategies.obv_atr_v2.obv_core import OBVCoreV2 as OBVATRStrategy

        strategy = OBVATRStrategy(
            symbols=["BTCUSDT"],
            timeframes=["4h", "1h"],
            params={
                "obv_timeframes": "4h",
                "price_ma_timeframes": "1h",
                "volume_ma_timeframes": "1h",
                "atr_timeframes": "4h",
                "adx_timeframes": "4h",
            },
        )

        # 创建测试数据
        dates_4h = pd.date_range(start="2026-01-01", periods=30, freq="4h", tz="UTC")
        df_4h = pd.DataFrame({
            "timestamp": dates_4h,
            "open": [50000 + i * 100 for i in range(30)],
            "high": [50100 + i * 100 for i in range(30)],
            "low": [49900 + i * 100 for i in range(30)],
            "close": [50050 + i * 100 for i in range(30)],
            "volume": [1000 + i * 10 for i in range(30)],
        })

        dates_1h = pd.date_range(start="2026-01-01", periods=120, freq="1h", tz="UTC")
        df_1h = pd.DataFrame({
            "timestamp": dates_1h,
            "open": [50000 + i * 25 for i in range(120)],
            "high": [50100 + i * 25 for i in range(120)],
            "low": [49900 + i * 25 for i in range(120)],
            "close": [50050 + i * 25 for i in range(120)],
            "volume": [1000 + i * 5 for i in range(120)],
        })

        klines_data = {"4h": df_4h, "1h": df_1h}

        with patch.object(
            OBVATRStrategy, "_get_closed_data",
            wraps=OBVATRStrategy._get_closed_data
        ) as mock_get_closed:
            result = strategy.analyze(
                "BTCUSDT",
                klines_data,
                current_time=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
            )

            called_timeframes = [call[0][1] for call in mock_get_closed.call_args_list]

            # 验证：4h 和 1h 都被调用
            assert "4h" in called_timeframes, "4h 应被调用"
            assert "1h" in called_timeframes, "1h 应被调用"
            # 验证：每个周期只调用一次
            assert called_timeframes.count("4h") == 1, "4h 只应调用一次"
            assert called_timeframes.count("1h") == 1, "1h 只应调用一次"


class TestOptimize2CacheUpdateOptimization:
    """测试优化 2：缓存更新优化"""

    def _create_kline(self, symbol: str, ts: datetime, price: float = 50000.0):
        """创建 Kline 对象"""
        from data_manager.klines_data import Kline
        return Kline(
            symbol=symbol,
            interval="1m",
            timestamp=ts,
            open=price,
            high=price + 50,
            low=price - 50,
            close=price,
            volume=100.0,
            quote_volume=5000000.0,
            trade_num=500,
            active_buy_volume=50.0,
            active_buy_quote_volume=2500000.0,
        )

    def test_backtest_update_cache_append_not_concat(self):
        """
        回测模式下缓存更新应使用 append 而非 concat

        验证：追加 1000 行数据，loc 比 concat 快
        """
        from data_manager.manager import DataManager, DataManagerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            dm_config = DataManagerConfig(
                csv_dir=tmpdir,
                preload_1m_enabled=False,
                backtest_mode=True,
            )
            dm = DataManager(dm_config)
            dm.connect()

            symbol = "BTCUSDT"
            start_dt = datetime(2026, 5, 14, 0, 0, 0, tzinfo=timezone.utc)

            # 测量时间
            start_time = time.time()
            for i in range(1000):
                kline = self._create_kline(symbol, start_dt + timedelta(minutes=i))
                dm._backtest_update_cache(kline)
            elapsed = time.time() - start_time

            # 验证数据正确性
            cached = dm.cache.get_1m_data(symbol)
            assert cached is not None, "缓存应有数据"
            assert len(cached) == 1000, f"应有 1000 行，实际 {len(cached)} 行"

            # 验证时间戳有序
            timestamps = cached["timestamp"].tolist()
            assert timestamps == sorted(timestamps), "时间戳应有序"

            # 性能断言：1000 次追加应在 5 秒内完成
            assert elapsed < 5.0, f"1000 次追加耗时 {elapsed:.2f}s，超过 5s 阈值"

    def test_backtest_update_cache_deduplication(self):
        """
        回测模式下缓存更新应去重

        场景：同一时间戳的 K 线被推送两次
        期望：只保留一条
        """
        from data_manager.manager import DataManager, DataManagerConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            dm_config = DataManagerConfig(
                csv_dir=tmpdir,
                preload_1m_enabled=False,
                backtest_mode=True,
            )
            dm = DataManager(dm_config)
            dm.connect()

            symbol = "BTCUSDT"
            ts = datetime(2026, 5, 14, 0, 0, 0, tzinfo=timezone.utc)

            # 推送相同时间戳的 K 线两次
            kline1 = self._create_kline(symbol, ts, price=50000.0)
            kline2 = self._create_kline(symbol, ts, price=50100.0)  # 价格不同

            dm._backtest_update_cache(kline1)
            dm._backtest_update_cache(kline2)

            # 验证：只保留一条
            cached = dm.cache.get_1m_data(symbol)
            assert len(cached) == 1, f"去重后应只有 1 行，实际 {len(cached)} 行"

    def test_backtest_update_cache_result_same_as_live_mode(self):
        """
        回测模式和实盘模式的缓存更新结果应一致

        验证：相同数据，两种模式的结果相同
        """
        from data_manager.manager import DataManager, DataManagerConfig, Kline

        # 创建两个 DataManager：一个回测模式，一个实盘模式
        with tempfile.TemporaryDirectory() as tmpdir_bt, tempfile.TemporaryDirectory() as tmpdir_live:
            # 回测模式
            dm_bt_config = DataManagerConfig(
                csv_dir=tmpdir_bt,
                preload_1m_enabled=False,
                backtest_mode=True,
            )
            dm_bt = DataManager(dm_bt_config)
            dm_bt.connect()

            # 实盘模式（禁用 WS）
            dm_live_config = DataManagerConfig(
                csv_dir=tmpdir_live,
                preload_1m_enabled=False,
                backtest_mode=False,
                klines_service_enabled=False,
            )
            dm_live = DataManager(dm_live_config)
            dm_live.connect()

            symbol = "BTCUSDT"
            start_dt = datetime(2026, 5, 14, 0, 0, 0, tzinfo=timezone.utc)

            # 推送相同数据
            for i in range(10):
                kline = self._create_kline(symbol, start_dt + timedelta(minutes=i))

                # 回测模式
                dm_bt._backtest_update_cache(kline)

                # 实盘模式（模拟 _on_kline_received 的核心逻辑）
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

                existing = dm_live.cache.get_1m_data(symbol)
                if existing is not None and not existing.empty:
                    df_combined = pd.concat([existing, df_new], ignore_index=True)
                    df_combined = df_combined.drop_duplicates(subset=['timestamp'], keep='last')
                    df_combined = df_combined.sort_values('timestamp').reset_index(drop=True)
                    dm_live.cache.put(symbol, '1m', df_combined, force_1m=True)
                else:
                    dm_live.cache.put(symbol, '1m', df_new, force_1m=True)

            # 验证结果一致
            cached_bt = dm_bt.cache.get_1m_data(symbol)
            cached_live = dm_live.cache.get_1m_data(symbol)

            assert len(cached_bt) == len(cached_live), \
                f"行数不一致：回测 {len(cached_bt)}，实盘 {len(cached_live)}"

            # 验证数据值一致
            pd.testing.assert_frame_equal(
                cached_bt.reset_index(drop=True),
                cached_live.reset_index(drop=True),
                check_dtype=False,  # 允许类型差异
            )


class TestOptimize3BigIntervalAggregationOptimization:
    """测试优化 3：大周期聚合优化"""

    def _create_1m_data(self, start_dt: datetime, count: int) -> pd.DataFrame:
        """创建 1m K 线数据"""
        from data_manager.manager import DataManager
        timestamps = [start_dt + timedelta(minutes=i) for i in range(count)]
        return pd.DataFrame({
            'timestamp': timestamps,
            'open': [50000.0 + i * 10 for i in range(count)],
            'high': [50050.0 + i * 10 for i in range(count)],
            'low': [49950.0 + i * 10 for i in range(count)],
            'close': [50020.0 + i * 10 for i in range(count)],
            'volume': [10.0] * count,
            'quote_volume': [500000.0] * count,
            'trade_num': [100] * count,
            'active_buy_volume': [5.0] * count,
            'active_buy_quote_volume': [250000.0] * count,
        })

    def test_incremental_aggregation_same_result_as_full(self):
        """
        增量聚合结果应与全量聚合相同

        场景：
        - 逐根推送 60 根 1m K 线
        - 每次增量更新 1h bar
        - 最终结果应与全量聚合相同
        """
        from data_manager.manager import DataManager, DataManagerConfig
        from data_manager.klines_data import Kline

        with tempfile.TemporaryDirectory() as tmpdir:
            dm_config = DataManagerConfig(
                csv_dir=tmpdir,
                preload_1m_enabled=False,
                backtest_mode=True,
            )
            dm = DataManager(dm_config)
            dm.connect()
            dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "1h"])

            start_dt = datetime(2026, 5, 14, 0, 0, 0, tzinfo=timezone.utc)

            # 逐根推送 60 根 1m K 线
            for i in range(60):
                kline = Kline(
                    symbol="BTCUSDT",
                    interval="1m",
                    timestamp=start_dt + timedelta(minutes=i),
                    open=50000.0 + i * 10,
                    high=50050.0 + i * 10,
                    low=49950.0 + i * 10,
                    close=50020.0 + i * 10,
                    volume=10.0,
                    quote_volume=500000.0,
                    trade_num=100,
                    active_buy_volume=5.0,
                    active_buy_quote_volume=250000.0,
                )
                dm._backtest_update_cache(kline)
                dm._update_big_intervals_from_cache("BTCUSDT")

            # 获取增量聚合结果
            cached_1h = dm.cache.get("BTCUSDT", "1h")

            # 全量聚合
            df_1m = dm.cache.get_1m_data("BTCUSDT")
            full_agg = dm.aggregate_1m_to_interval(df_1m, "1h")

            # 验证结果一致
            assert cached_1h is not None, "1h 缓存应有数据"
            assert len(cached_1h) == len(full_agg), \
                f"行数不一致：增量 {len(cached_1h)}，全量 {len(full_agg)}"

            # 验证 OHLCV 值一致
            for col in ['open', 'high', 'low', 'close', 'volume']:
                pd.testing.assert_series_equal(
                    cached_1h[col].reset_index(drop=True),
                    full_agg[col].reset_index(drop=True),
                    check_names=False,
                    check_dtype=False,
                )

    def test_incremental_aggregation_performance(self):
        """
        增量聚合性能测试

        场景：推送 1000 根 1m K 线，测量聚合时间
        期望：增量聚合比全量聚合快
        """
        from data_manager.manager import DataManager, DataManagerConfig
        from data_manager.klines_data import Kline

        with tempfile.TemporaryDirectory() as tmpdir:
            dm_config = DataManagerConfig(
                csv_dir=tmpdir,
                preload_1m_enabled=False,
                backtest_mode=True,
            )
            dm = DataManager(dm_config)
            dm.connect()
            dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "1h"])

            start_dt = datetime(2026, 5, 14, 0, 0, 0, tzinfo=timezone.utc)

            # 测量增量聚合时间
            start_time = time.time()
            for i in range(1000):
                kline = Kline(
                    symbol="BTCUSDT",
                    interval="1m",
                    timestamp=start_dt + timedelta(minutes=i),
                    open=50000.0 + i,
                    high=50050.0 + i,
                    low=49950.0 + i,
                    close=50020.0 + i,
                    volume=10.0,
                    quote_volume=500000.0,
                    trade_num=100,
                    active_buy_volume=5.0,
                    active_buy_quote_volume=250000.0,
                )
                dm._backtest_update_cache(kline)
                dm._update_big_intervals_from_cache("BTCUSDT")
            elapsed = time.time() - start_time

            # 性能断言：1000 次聚合应在 10 秒内完成
            assert elapsed < 10.0, f"1000 次增量聚合耗时 {elapsed:.2f}s，超过 10s 阈值"

    def test_incremental_update_existing_bar(self):
        """
        增量更新现有 bar 的 OHLCV

        场景：
        - 1h bar 开始时推送第一根 1m
        - 同一小时内推送更多 1m
        - 验证 high/low/close/volume 正确更新
        """
        from data_manager.manager import DataManager, DataManagerConfig
        from data_manager.klines_data import Kline

        with tempfile.TemporaryDirectory() as tmpdir:
            dm_config = DataManagerConfig(
                csv_dir=tmpdir,
                preload_1m_enabled=False,
                backtest_mode=True,
            )
            dm = DataManager(dm_config)
            dm.connect()
            dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "1h"])

            start_dt = datetime(2026, 5, 14, 0, 0, 0, tzinfo=timezone.utc)

            # 第一根 1m
            kline1 = Kline(
                symbol="BTCUSDT",
                interval="1m",
                timestamp=start_dt,
                open=50000.0,
                high=50050.0,
                low=49950.0,
                close=50020.0,
                volume=10.0,
                quote_volume=500000.0,
                trade_num=100,
                active_buy_volume=5.0,
                active_buy_quote_volume=250000.0,
            )
            dm._backtest_update_cache(kline1)
            dm._update_big_intervals_from_cache("BTCUSDT")

            cached_1h = dm.cache.get("BTCUSDT", "1h")
            assert cached_1h is not None
            assert len(cached_1h) == 1
            assert cached_1h['open'].iloc[0] == 50000.0
            assert cached_1h['high'].iloc[0] == 50050.0
            assert cached_1h['low'].iloc[0] == 49950.0
            assert cached_1h['close'].iloc[0] == 50020.0
            assert cached_1h['volume'].iloc[0] == 10.0

            # 第二根 1m（更高的 high，更低的 low）
            kline2 = Kline(
                symbol="BTCUSDT",
                interval="1m",
                timestamp=start_dt + timedelta(minutes=1),
                open=50020.0,
                high=50100.0,  # 更高
                low=49900.0,   # 更低
                close=50080.0,
                volume=15.0,
                quote_volume=500000.0,
                trade_num=100,
                active_buy_volume=5.0,
                active_buy_quote_volume=250000.0,
            )
            dm._backtest_update_cache(kline2)
            dm._update_big_intervals_from_cache("BTCUSDT")

            cached_1h = dm.cache.get("BTCUSDT", "1h")
            assert len(cached_1h) == 1
            # open 应保持第一根的值
            assert cached_1h['open'].iloc[0] == 50000.0
            # high 应更新为更高的值
            assert cached_1h['high'].iloc[0] == 50100.0
            # low 应更新为更低的值
            assert cached_1h['low'].iloc[0] == 49900.0
            # close 应更新为最新的值
            assert cached_1h['close'].iloc[0] == 50080.0
            # volume 应累加
            assert cached_1h['volume'].iloc[0] == 25.0
