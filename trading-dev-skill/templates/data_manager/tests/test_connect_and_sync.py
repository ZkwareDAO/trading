#!/usr/bin/env python3
"""
测试: DataManager.connect_and_sync 启动同步流程

覆盖:
- CSV 不存在 → 下载完整历史 + init_today_realtime
- CSV 有部分数据 → 计算 gap → 补齐缺失
- CSV 数据完整 → 跳过下载
- 部分下载失败 → 仍返回结果
"""

import pytest
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

from data_manager.manager import DataManager, DataManagerConfig


class TestConnectAndSync:

    def _make_manager(self, tmp_path: Path) -> DataManager:
        config = DataManagerConfig(
            csv_dir=str(tmp_path / "klines"),
            klines_service_enabled=True,
            klines_service_http_url="http://127.0.0.1:17081",
            klines_service_ws_url="ws://127.0.0.1:17081/ws/klines",
        )
        dm = DataManager(config)
        dm.enable_kline_repository()
        return dm

    def _make_old_csv(self, tmp_path: Path, symbol: str, days_ago: int, rows=10):
        """创建指定天数的旧 CSV 文件"""
        csv_dir = tmp_path / "klines" / "1m"
        csv_dir.mkdir(parents=True, exist_ok=True)
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=days_ago, minutes=rows)
        data = []
        for i in range(rows):
            ts = start + timedelta(minutes=i)
            data.append({
                'timestamp': ts.strftime('%Y-%m-%d %H:%M:%S+00:00'),
                'open': 50000.0 + i, 'high': 50100.0 + i,
                'low': 49900.0 + i, 'close': 50050.0 + i,
                'volume': 100.0 + i,
            })
        df = pd.DataFrame(data)
        df.to_csv(csv_dir / f"{symbol}_1m.csv", index=False)

    @pytest.mark.asyncio
    async def test_connect_and_sync_no_csv_downloads_history(self, tmp_path):
        """无本地 CSV 时，下载完整历史 + init_today"""
        dm = self._make_manager(tmp_path)

        call_log = []

        async def fake_batch(symbol, days=30):
            call_log.append(("batch", symbol, days))
            return {f"2026-04-{d:02d}": True for d in range(1, days + 1)}

        async def fake_init(symbol):
            call_log.append(("init", symbol))
            return True

        with patch.object(dm, 'batch_download_history', side_effect=fake_batch):
            with patch.object(dm, 'init_today_realtime', side_effect=fake_init):
                results = await dm.connect_and_sync(["BTCUSDT"], history_days=7)

        assert results["BTCUSDT"] is True
        assert call_log[0][0] == "batch"
        assert call_log[0][1] == "BTCUSDT"
        assert call_log[0][2] == 6  # 7 - 1 = 6，排除今天
        assert call_log[1][0] == "init"

    @pytest.mark.asyncio
    async def test_connect_and_sync_partial_data_fills_gap(self, tmp_path):
        """有部分数据时，只补齐 gap 天数"""
        dm = self._make_manager(tmp_path)
        # 创建 10 天前的数据
        self._make_old_csv(tmp_path, "ETHUSDT", days_ago=10, rows=5)

        call_log = []

        async def fake_batch(symbol, days=30):
            call_log.append(("batch", symbol, days))
            return {f"2026-04-{d:02d}": True for d in range(1, days + 1)}

        async def fake_init(symbol):
            call_log.append(("init", symbol))
            return True

        with patch.object(dm, 'batch_download_history', side_effect=fake_batch):
            with patch.object(dm, 'init_today_realtime', side_effect=fake_init):
                results = await dm.connect_and_sync(["ETHUSDT"], history_days=30)

        assert results["ETHUSDT"] is True
        # gap 约 10 天，batch 应该下载 9 天（排除今天）
        assert call_log[0][0] == "batch"
        assert call_log[0][2] == 10  # 10 - 1 = 9, 向上取整为 10

    @pytest.mark.asyncio
    async def test_connect_and_sync_fresh_data_skips_download(self, tmp_path):
        """数据完整时，跳过下载"""
        dm = self._make_manager(tmp_path)
        # 创建 1 分钟前的数据（视为完整）
        self._make_old_csv(tmp_path, "BTCUSDT", days_ago=0, rows=5)

        call_log = []

        async def fake_batch(symbol, days=30):
            call_log.append(("batch", symbol, days))
            return {}

        async def fake_init(symbol):
            call_log.append(("init", symbol))
            return True

        with patch.object(dm, 'batch_download_history', side_effect=fake_batch):
            with patch.object(dm, 'init_today_realtime', side_effect=fake_init):
                results = await dm.connect_and_sync(["BTCUSDT"], history_days=30)

        assert results["BTCUSDT"] is True
        # 数据完整，不应调用 batch_download_history
        batch_calls = [c for c in call_log if c[0] == "batch"]
        assert len(batch_calls) == 0

    @pytest.mark.asyncio
    async def test_connect_and_sync_caps_at_history_days(self, tmp_path):
        """缺失天数超过上限时，裁剪到 history_days"""
        dm = self._make_manager(tmp_path)
        # 创建 60 天前的数据
        self._make_old_csv(tmp_path, "BNBUSDT", days_ago=60, rows=5)

        call_log = []

        async def fake_batch(symbol, days=30):
            call_log.append(("batch", symbol, days))
            return {}

        async def fake_init(symbol):
            call_log.append(("init", symbol))
            return True

        with patch.object(dm, 'batch_download_history', side_effect=fake_batch):
            with patch.object(dm, 'init_today_realtime', side_effect=fake_init):
                results = await dm.connect_and_sync(["BNBUSDT"], history_days=15)

        assert results["BNBUSDT"] is True
        # 缺失 61 天，上限 15 天，batch 调用传 15-1=14
        assert call_log[0][2] == 14

    @pytest.mark.asyncio
    async def test_connect_and_sync_multiple_symbols(self, tmp_path):
        """多个 symbol 并行同步"""
        dm = self._make_manager(tmp_path)
        # BTC 有数据，SOL 无数据
        self._make_old_csv(tmp_path, "BTCUSDT", days_ago=0, rows=5)

        async def fake_batch(symbol, days=30):
            return {}

        async def fake_init(symbol):
            return True

        with patch.object(dm, 'batch_download_history', side_effect=fake_batch):
            with patch.object(dm, 'init_today_realtime', side_effect=fake_init):
                results = await dm.connect_and_sync(["BTCUSDT", "SOLUSDT"], history_days=7)

        assert "BTCUSDT" in results
        assert "SOLUSDT" in results

    @pytest.mark.asyncio
    async def test_connect_and_sync_partial_download_still_succeeds(self, tmp_path):
        """部分下载失败，整体仍成功"""
        dm = self._make_manager(tmp_path)

        call_count = 0

        async def flaky_batch(symbol, days=30):
            nonlocal call_count
            call_count += 1
            # 一半成功一半失败
            return {f"d{i}": i % 2 == 0 for i in range(days)}

        async def fake_init(symbol):
            return True

        with patch.object(dm, 'batch_download_history', side_effect=flaky_batch):
            with patch.object(dm, 'init_today_realtime', side_effect=fake_init):
                results = await dm.connect_and_sync(["BTCUSDT"], history_days=5)

        assert results["BTCUSDT"] is True

    @pytest.mark.asyncio
    async def test_connect_and_sync_preloads_big_interval_cache(self, tmp_path):
        """sync 后大周期数据聚合到内存"""
        dm = self._make_manager(tmp_path)

        # 注册大周期
        dm.register_timeframes_for_symbol("BTCUSDT", ["1m", "15m", "1h", "4h"])

        async def fake_batch(symbol, days=30):
            return {}

        async def fake_init(symbol):
            # init_today_realtime 会放一些 1m 数据到缓存
            df = pd.DataFrame({
                'timestamp': pd.date_range('2026-04-13 00:00', periods=120, freq='min', tz='UTC'),
                'open': 70000.0, 'high': 70100.0, 'low': 69900.0,
                'close': 70050.0, 'volume': 100.0,
                'quote_volume': 7005000.0, 'trade_num': 10,
                'active_buy_volume': 60.0, 'active_buy_quote_volume': 4203000.0,
            })
            dm.cache.put("BTCUSDT", "1m", df, force_1m=True)
            return True

        with patch.object(dm, 'batch_download_history', side_effect=fake_batch):
            with patch.object(dm, 'init_today_realtime', side_effect=fake_init):
                results = await dm.connect_and_sync(["BTCUSDT"], history_days=7)

        assert results["BTCUSDT"] is True
        # 验证大周期已聚合到缓存
        assert dm.cache.get("BTCUSDT", "15m") is not None
        assert dm.cache.get("BTCUSDT", "1h") is not None
        assert dm.cache.get("BTCUSDT", "4h") is not None
