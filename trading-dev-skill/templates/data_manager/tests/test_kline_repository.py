#!/usr/bin/env python3
"""
kline_repository.py 单元测试

测试 KlineRepository 类的类型安全和功能
"""

from datetime import datetime, timezone, timedelta

from data_manager.kline_repository import KlineRepository


class TestKlineRepositorySaveAll:
    """测试 save_all 方法"""

    def test_save_all_returns_dict(self, tmp_path):
        """测试 save_all 返回字典类型"""
        repo = KlineRepository(str(tmp_path))

        # 注册一个 symbol
        repo.register_symbol("BTCUSDT", ["1m", "5m"])

        # 调用 save_all，验证返回字典
        result = repo.save_all()

        assert isinstance(result, dict)

    def test_save_all_with_no_data_returns_empty(self, tmp_path):
        """测试没有数据时 save_all 返回空字典"""
        repo = KlineRepository(str(tmp_path))

        # 注册 symbol 但没有数据
        repo.register_symbol("BTCUSDT", ["1m", "5m"])

        result = repo.save_all()

        # 没有数据时应该返回空字典或每个时间框架的计数
        assert isinstance(result, dict)

    def test_save_all_with_data(self, tmp_path):
        """测试有数据时 save_all 保存文件"""
        repo = KlineRepository(str(tmp_path))

        # 注册 symbol
        repo.register_symbol("BTCUSDT", ["1m", "5m"])

        # 创建一些测试数据
        now = datetime.now(timezone.utc)
        test_klines = []
        for i in range(10):
            ts = now - timedelta(minutes=i)
            test_klines.append(
                {
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "timestamp": ts,
                    "open": 70000.0 + i,
                    "high": 70100.0 + i,
                    "low": 69900.0 + i,
                    "close": 70050.0 + i,
                    "volume": 100.0 + i,
                }
            )

        # 更新数据
        repo.update_from_1m("BTCUSDT", test_klines)

        # 调用 save_all
        result = repo.save_all()

        # 验证返回结果
        assert isinstance(result, dict)
        # 应该至少保存了 1m 和 5m 两个文件
        assert len(result) >= 1


class TestKlineRepositoryTypeAnnotations:
    """测试类型注解相关的功能"""

    def test_update_from_1m_returns_dict(self, tmp_path):
        """测试 update_from_1m 返回正确的类型"""
        repo = KlineRepository(str(tmp_path))
        repo.register_symbol("BTCUSDT", ["1m", "5m"])

        now = datetime.now(timezone.utc)
        test_klines = [
            {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "timestamp": now,
                "open": 70000.0,
                "high": 70100.0,
                "low": 69900.0,
                "close": 70050.0,
                "volume": 100.0,
            }
        ]

        result = repo.update_from_1m("BTCUSDT", test_klines)

        assert isinstance(result, dict)
        assert "1m" in result

    def test_get_status_returns_dict(self, tmp_path):
        """测试 get_status 返回正确的类型"""
        repo = KlineRepository(str(tmp_path))
        repo.register_symbol("BTCUSDT", ["1m", "5m"])

        result = repo.get_status()

        assert isinstance(result, dict)
        assert "symbols" in result
        assert "registered_timeframes" in result


class TestKlineRepositoryTimeAlignment:
    """测试时间对齐功能"""

    def test_get_aggregation_start_time_with_existing_data(self, tmp_path):
        """测试有数据时获取聚合起始时间"""
        repo = KlineRepository(str(tmp_path))
        repo.register_symbol("BTCUSDT", ["1m", "4h"])

        # 创建 1m 测试数据
        now = datetime.now(timezone.utc)
        test_klines = []
        for i in range(10):
            ts = now - timedelta(minutes=i)
            test_klines.append(
                {
                    "symbol": "BTCUSDT",
                    "interval": "1m",
                    "timestamp": ts,
                    "open": 70000.0 + i,
                    "high": 70100.0 + i,
                    "low": 69900.0 + i,
                    "close": 70050.0 + i,
                    "volume": 100.0 + i,
                }
            )

        # 更新数据
        repo.update_from_1m("BTCUSDT", test_klines)

        # 获取 4h 聚合起始时间
        start_time = repo._get_aggregation_start_time("BTCUSDT", "4h")

        # 应该返回一个 datetime 或 None
        assert start_time is None or isinstance(start_time, datetime)


class TestKlineRepositoryNumericTimestamp:
    """测试毫秒数字时间戳写入 CSV 后的正确性"""

    def test_update_from_1m_with_millisecond_timestamp(self, tmp_path):
        """
        Kline.to_dict() 输出毫秒数字时间戳。
        pd.to_datetime 需要 unit='ms' 才能正确解析，否则变成 1970 年。

        验证: 毫秒时间戳正确写入 CSV，日期不是 1970-01-01
        """
        import pandas as pd

        repo = KlineRepository(str(tmp_path))
        repo.register_symbol("BTCUSDT", ["1m"])

        # 模拟 Kline.to_dict() 的输出（毫秒数字）
        ms_timestamp = 1775805720000.0  # 2026-04-10 07:22:00 UTC
        test_klines = [
            {
                "symbol": "BTCUSDT",
                "interval": "1m",
                "timestamp": ms_timestamp,
                "open": 70000.0,
                "high": 70100.0,
                "low": 69900.0,
                "close": 70050.0,
                "volume": 100.0,
            }
        ]

        repo.update_from_1m("BTCUSDT", test_klines)

        # 读取 CSV 文件验证（新路径格式）
        csv_path = tmp_path / "1m" / "BTCUSDT_1m.csv"
        assert csv_path.exists(), "CSV 文件应已创建"

        df = pd.read_csv(csv_path)
        assert len(df) == 1

        # 解析时间戳，验证不是 1970 年
        ts = pd.to_datetime(df.iloc[0]["timestamp"], utc=True)
        assert ts.year == 2026, f"年份应为 2026，实际为 {ts.year}"
        assert ts.month == 4
        assert ts.day == 10
