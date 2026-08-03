"""
KlineRepository 边界条件测试

覆盖:
- register_symbol 重复注册
- _get_file_path 路径查找（子目录/根目录）
- _get_dataframe 空文件/不存在
- update_from_1m 空数据/单条数据
- _get_interval_hours 各种格式
- get_status 空/有数据
- clear 单个/全部
- save_all
"""

import tempfile
import shutil
from pathlib import Path
from datetime import datetime, timezone


from data_manager.kline_repository import KlineRepository


class TestRegisterSymbol:
    """注册 symbol 测试"""

    def test_register_new_symbol(self):
        """注册新 symbol"""
        repo = KlineRepository()
        repo.register_symbol("BTCUSDT", ["1h", "4h"])

        assert "BTCUSDT" in repo._states
        assert "1h" in repo._states["BTCUSDT"].registered_timeframes
        assert "4h" in repo._states["BTCUSDT"].registered_timeframes

    def test_register_duplicate_timeframes(self):
        """重复注册时间框架（合并）"""
        repo = KlineRepository()
        repo.register_symbol("BTCUSDT", ["1h", "4h"])
        repo.register_symbol("BTCUSDT", ["4h", "15m"])

        state = repo._states["BTCUSDT"]
        assert state.registered_timeframes == {"1h", "4h", "15m"}

    def test_register_multiple_symbols(self):
        """注册多个 symbol"""
        repo = KlineRepository()
        repo.register_symbol("BTCUSDT", ["1h"])
        repo.register_symbol("ETHUSDT", ["1h", "4h"])

        assert "BTCUSDT" in repo._states
        assert "ETHUSDT" in repo._states
        assert repo._states["BTCUSDT"].registered_timeframes == {"1h"}
        assert repo._states["ETHUSDT"].registered_timeframes == {"1h", "4h"}


class TestGetFilePath:
    """CSV 文件路径测试"""

    def test_file_path_fixed_format(self):
        """固定路径格式，不回退旧路径"""
        tmpdir = tempfile.mkdtemp()
        try:
            repo = KlineRepository(csv_dir=tmpdir)
            filepath = repo._get_file_path("BTCUSDT", "1h")
            assert filepath == Path(tmpdir) / "1h" / "BTCUSDT_1h.csv"
        finally:
            shutil.rmtree(tmpdir)

    def test_file_path_fallback_removed(self):
        """旧路径回退已移除，即使旧文件存在也返回新路径"""
        tmpdir = tempfile.mkdtemp()
        try:
            repo = KlineRepository(csv_dir=tmpdir)
            # 创建旧格式根目录文件
            root_file = Path(tmpdir) / "BTCUSDT_1h.csv"
            root_file.touch()

            filepath = repo._get_file_path("BTCUSDT", "1h")
            # 仍然返回新路径
            assert filepath == Path(tmpdir) / "1h" / "BTCUSDT_1h.csv"
            assert filepath != root_file
        finally:
            shutil.rmtree(tmpdir)

    def test_file_path_lowercase_timeframe(self):
        """时间框架转小写"""
        tmpdir = tempfile.mkdtemp()
        try:
            repo = KlineRepository(csv_dir=tmpdir)
            filepath = repo._get_file_path("BTCUSDT", "1H")
            assert "1h" in str(filepath)
        finally:
            shutil.rmtree(tmpdir)


class TestGetIntervalHours:
    """时间周期解析测试"""

    def setup_method(self):
        self.repo = KlineRepository()

    def test_hourly(self):
        assert self.repo._get_interval_hours("1h") == 1
        assert self.repo._get_interval_hours("4h") == 4

    def test_minute(self):
        assert self.repo._get_interval_hours("1m") == 0
        assert self.repo._get_interval_hours("15m") == 0

    def test_daily(self):
        assert self.repo._get_interval_hours("1d") == 24

    def test_weekly(self):
        assert self.repo._get_interval_hours("1w") == 24 * 7

    def test_invalid(self):
        assert self.repo._get_interval_hours("xyz") is None
        assert self.repo._get_interval_hours("") is None


class TestGetStatus:
    """状态查询测试"""

    def test_empty_status(self):
        """空仓库状态"""
        repo = KlineRepository()
        status = repo.get_status()

        assert status["symbols"] == []
        assert status["registered_timeframes"] == {}
        assert status["last_update"] == {}

    def test_status_with_symbols(self):
        """注册 symbol 后的状态"""
        repo = KlineRepository()
        repo.register_symbol("BTCUSDT", ["1h", "4h"])

        status = repo.get_status()
        assert "BTCUSDT" in status["symbols"]
        assert set(status["registered_timeframes"]["BTCUSDT"]) == {"1h", "4h"}


class TestClear:
    """清除状态测试"""

    def test_clear_single_symbol(self):
        """清除单个 symbol"""
        repo = KlineRepository()
        repo.register_symbol("BTCUSDT", ["1h"])
        repo.register_symbol("ETHUSDT", ["1h"])
        repo.clear("BTCUSDT")

        assert "BTCUSDT" not in repo._states
        assert "ETHUSDT" in repo._states

    def test_clear_all(self):
        """清除所有状态"""
        repo = KlineRepository()
        repo.register_symbol("BTCUSDT", ["1h"])
        repo.register_symbol("ETHUSDT", ["1h"])
        repo.clear()

        assert len(repo._states) == 0


class TestSaveAll:
    """保存状态测试"""

    def test_save_all_empty(self):
        """空仓库 save_all"""
        repo = KlineRepository()
        result = repo.save_all()
        assert result == {}

    def test_save_all_no_data(self):
        """有注册但无 CSV 文件"""
        tmpdir = tempfile.mkdtemp()
        try:
            repo = KlineRepository(csv_dir=tmpdir)
            repo.register_symbol("BTCUSDT", ["1h"])
            result = repo.save_all()
            assert result["BTCUSDT"] == 0
        finally:
            shutil.rmtree(tmpdir)


class TestUpdateFrom1m:
    """1m 更新测试"""

    def test_update_empty_klines(self):
        """空 K 线列表"""
        tmpdir = tempfile.mkdtemp()
        try:
            repo = KlineRepository(csv_dir=tmpdir)
            repo.register_symbol("BTCUSDT", ["1h"])
            result = repo.update_from_1m("BTCUSDT", [])
            assert result == {}
        finally:
            shutil.rmtree(tmpdir)

    def test_update_single_kline(self):
        """单条 1m K 线更新"""
        tmpdir = tempfile.mkdtemp()
        try:
            repo = KlineRepository(csv_dir=tmpdir)
            repo.register_symbol("BTCUSDT", ["1h"])

            klines = [{
                'timestamp': int(datetime(2026, 4, 10, 10, 0, tzinfo=timezone.utc).timestamp() * 1000),
                'open': 100.0,
                'high': 105.0,
                'low': 95.0,
                'close': 102.0,
                'volume': 10.0,
            }]
            result = repo.update_from_1m("BTCUSDT", klines)
            assert result["1m"] is True
        finally:
            shutil.rmtree(tmpdir)

    def test_update_missing_column(self):
        """缺少必要列"""
        tmpdir = tempfile.mkdtemp()
        try:
            repo = KlineRepository(csv_dir=tmpdir)
            klines = [{'open': 100.0}]  # 缺少 timestamp 等列
            result = repo.update_from_1m("BTCUSDT", klines)
            assert result["1m"] is False
        finally:
            shutil.rmtree(tmpdir)


class TestGetAggregationStartTime:
    """聚合起始时间测试"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.repo = KlineRepository(csv_dir=self.tmpdir)

    def teardown_method(self):
        shutil.rmtree(self.tmpdir)

    def test_no_target_csv_returns_none(self):
        """目标 CSV 不存在时返回 None"""
        result = self.repo._get_aggregation_start_time("BTCUSDT", "1h")
        assert result is None

    def test_hourly_alignment(self):
        """4h 周期对齐"""
        # 创建目标 CSV 文件（新路径格式）
        import pandas as pd
        filepath = Path(self.tmpdir) / "4h" / "BTCUSDT_4h.csv"
        filepath.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame({
            'timestamp': [datetime(2026, 4, 10, 8, 0, tzinfo=timezone.utc)],
            'open': [100.0], 'high': [105.0], 'low': [95.0],
            'close': [102.0], 'volume': [10.0],
        })
        df.to_csv(filepath, index=False)

        result = self.repo._get_aggregation_start_time("BTCUSDT", "4h")
        assert result is not None
        # 应该回退一个 4h 周期
        assert result.hour in (0, 4, 8, 12, 16, 20)
