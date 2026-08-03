#!/usr/bin/env python3
"""
测试: DataManager.get_klines() 统一对外接口

覆盖:
- 基本功能：1m 从缓存/CSV 读取
- 增量返回：首次返回基准，后续只返回新增
- 大周期从 1m 实时聚合
- CSV 回退：缓存未命中时从 CSV 加载
"""

import tempfile
import shutil
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pandas as pd
import asyncio
import pytest

from data_manager.manager import DataManager, DataManagerConfig


def make_df(base_ts: datetime, count: int) -> pd.DataFrame:
    """生成带时间戳的测试 DataFrame"""
    rows = []
    for i in range(count):
        ts = base_ts + timedelta(minutes=i)
        rows.append({
            'timestamp': ts,
            'open': 70000.0 + i,
            'high': 70100.0 + i,
            'low': 69900.0 + i,
            'close': 70050.0 + i,
            'volume': 100.0 + i,
            'quote_volume': 7005000.0 + i,
            'trade_num': 10 + i,
            'active_buy_volume': 60.0 + i,
            'active_buy_quote_volume': 4203000.0 + i,
        })
    return pd.DataFrame(rows)


class TestGetKlines:

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        config = DataManagerConfig(
            csv_dir=self.tmpdir,
            preload_1m_enabled=False,
            klines_service_enabled=False,
        )
        self.dm = DataManager(config)
        self.dm.connect()

    def teardown_method(self):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.dm.close())
            loop.close()
        except Exception:
            pass
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_get_klines_no_data_returns_empty(self):
        """无任何数据时返回空"""
        result = self.dm.get_klines("BTCUSDT", "1m", limit=10)
        assert result == []

    def test_get_klines_first_call_returns_baseline(self):
        """首次调用返回最后一条作为基准"""
        base_ts = datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc)
        df = make_df(base_ts, 5)
        self.dm.cache.put("BTCUSDT", "1m", df)

        result = self.dm.get_klines("BTCUSDT", "1m", limit=10)
        assert len(result) == 1
        assert result[0].timestamp == base_ts + timedelta(minutes=4)

    def test_get_klines_incremental(self):
        """后续调用只返回新增数据"""
        base_ts = datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc)
        df = make_df(base_ts, 5)
        self.dm.cache.put("BTCUSDT", "1m", df)

        # 首次
        r1 = self.dm.get_klines("BTCUSDT", "1m", limit=10)
        assert len(r1) == 1

        # 追加
        new_ts = base_ts + timedelta(minutes=5)
        combined = pd.concat([df, make_df(new_ts, 3)], ignore_index=True)
        self.dm.cache.put("BTCUSDT", "1m", combined)

        # 第二次
        r2 = self.dm.get_klines("BTCUSDT", "1m", limit=10)
        assert len(r2) == 3

    def test_get_klines_big_interval_from_1m(self):
        """大周期从 1m 缓存聚合"""
        base_ts = datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc)
        df = make_df(base_ts, 120)  # 2 小时
        self.dm.cache.put("BTCUSDT", "1m", df)

        result = self.dm.get_klines("BTCUSDT", "1h", limit=10)
        assert len(result) >= 1

    def test_get_klines_csv_fallback(self):
        """缓存未命中时从 CSV 加载"""
        base_ts = datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc)
        df = make_df(base_ts, 10)

        # 直接写 CSV（不经过缓存）
        csv_dir = Path(self.tmpdir) / "1m"
        csv_dir.mkdir(parents=True, exist_ok=True)
        save_df = df.copy()
        save_df['timestamp'] = save_df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S+00:00')
        save_df.to_csv(csv_dir / "BTCUSDT_1m.csv", index=False)

        # 缓存为空
        assert self.dm.cache.get_1m_data("BTCUSDT") is None

        result = self.dm.get_klines("BTCUSDT", "1m", limit=10)
        # 应从 CSV 加载并返回基准
        assert len(result) == 1

    def test_get_klines_limit_applied(self):
        """limit 参数生效"""
        base_ts = datetime(2026, 4, 8, 0, 0, tzinfo=timezone.utc)
        df = make_df(base_ts, 100)
        self.dm.cache.put("BTCUSDT", "1m", df)

        result = self.dm.get_klines("BTCUSDT", "1m", limit=5)
        # 首次只返回基准 1 条
        assert len(result) == 1

        # 重置追踪后再获取
        self.dm.reset_kline_tracking("BTCUSDT", "1m")
        result = self.dm.get_klines("BTCUSDT", "1m", limit=5)
        # 有 limit 限制时最多返回 5 条
        assert len(result) <= 5
