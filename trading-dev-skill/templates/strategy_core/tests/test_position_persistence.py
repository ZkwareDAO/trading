#!/usr/bin/env python3
"""仓位持久化模块测试"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import pytest

from strategy_core.position_persistence import PositionPersistence


class TestPositionPersistence:
    """PositionPersistence 单元测试"""

    def test_save_creates_file(self, tmp_path: Path):
        """保存仓位状态应创建 JSON 文件"""
        persistence = PositionPersistence(base_path=tmp_path)
        strategy_name = "test_strategy"
        state = {"position": "long", "entry_price": 31000.0}

        persistence.save(strategy_name, state)

        filepath = tmp_path / f"{strategy_name}.json"
        assert filepath.exists()

    def test_save_includes_updated_at(self, tmp_path: Path):
        """保存时应自动添加 updated_at 时间戳"""
        persistence = PositionPersistence(base_path=tmp_path)
        strategy_name = "test_strategy"
        state = {"position": "long", "entry_price": 31000.0}

        persistence.save(strategy_name, state)

        filepath = tmp_path / f"{strategy_name}.json"
        with open(filepath) as f:
            saved_data = json.load(f)

        assert "updated_at" in saved_data
        # 验证时间戳格式
        datetime.fromisoformat(saved_data["updated_at"])

    def test_save_preserves_all_fields(self, tmp_path: Path):
        """保存应保留所有传入的字段"""
        persistence = PositionPersistence(base_path=tmp_path)
        strategy_name = "test_strategy"
        state = {
            "position": "long",
            "entry_price": 31000.0,
            "entry_time": "2026-05-18T10:30:00Z",
            "peak_price": 31500.0,
            "stop_price": 30500.0,
        }

        persistence.save(strategy_name, state)

        filepath = tmp_path / f"{strategy_name}.json"
        with open(filepath) as f:
            saved_data = json.load(f)

        assert saved_data["position"] == "long"
        assert saved_data["entry_price"] == 31000.0
        assert saved_data["entry_time"] == "2026-05-18T10:30:00Z"
        assert saved_data["peak_price"] == 31500.0
        assert saved_data["stop_price"] == 30500.0

    def test_load_returns_none_when_file_not_exists(self, tmp_path: Path):
        """文件不存在时 load 应返回 None"""
        persistence = PositionPersistence(base_path=tmp_path)

        result = persistence.load("nonexistent_strategy")

        assert result is None

    def test_load_returns_saved_state(self, tmp_path: Path):
        """load 应返回已保存的状态"""
        persistence = PositionPersistence(base_path=tmp_path)
        strategy_name = "test_strategy"
        state = {"position": "long", "entry_price": 31000.0}

        persistence.save(strategy_name, state)
        loaded = persistence.load(strategy_name)

        assert loaded is not None
        assert loaded["position"] == "long"
        assert loaded["entry_price"] == 31000.0

    def test_load_handles_corrupted_json(self, tmp_path: Path):
        """load 应处理损坏的 JSON 文件"""
        persistence = PositionPersistence(base_path=tmp_path)
        strategy_name = "test_strategy"

        # 写入损坏的 JSON
        filepath = tmp_path / f"{strategy_name}.json"
        filepath.write_text("{ invalid json }")

        result = persistence.load(strategy_name)

        assert result is None

    def test_clear_deletes_file(self, tmp_path: Path):
        """clear 应删除持久化文件"""
        persistence = PositionPersistence(base_path=tmp_path)
        strategy_name = "test_strategy"
        state = {"position": "long", "entry_price": 31000.0}

        persistence.save(strategy_name, state)
        filepath = tmp_path / f"{strategy_name}.json"
        assert filepath.exists()

        persistence.clear(strategy_name)

        assert not filepath.exists()

    def test_clear_handles_nonexistent_file(self, tmp_path: Path):
        """clear 应处理不存在的文件（不抛异常）"""
        persistence = PositionPersistence(base_path=tmp_path)

        # 不应抛出异常
        persistence.clear("nonexistent_strategy")

    def test_creates_base_path_if_not_exists(self):
        """初始化时应自动创建 base_path 目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            base_path = Path(tmpdir) / "positions"
            assert not base_path.exists()

            persistence = PositionPersistence(base_path=base_path)

            assert base_path.exists()

    def test_save_handles_datetime_serialization(self, tmp_path: Path):
        """save 应正确序列化 datetime 对象"""
        persistence = PositionPersistence(base_path=tmp_path)
        strategy_name = "test_strategy"
        entry_time = datetime(2026, 5, 18, 10, 30, 0, tzinfo=timezone.utc)
        state = {"position": "long", "entry_time": entry_time}

        persistence.save(strategy_name, state)

        filepath = tmp_path / f"{strategy_name}.json"
        with open(filepath) as f:
            saved_data = json.load(f)

        # datetime 应被序列化为 ISO 格式字符串
        assert isinstance(saved_data["entry_time"], str)
        datetime.fromisoformat(saved_data["entry_time"])

    def test_roundtrip_save_and_load(self, tmp_path: Path):
        """保存后再加载应保持数据一致"""
        persistence = PositionPersistence(base_path=tmp_path)
        strategy_name = "test_strategy"
        original_state = {
            "position": "short",
            "entry_price": 99000.0,
            "entry_time": "2026-05-18T14:00:00Z",
            "peak_price": 98500.0,
            "stop_price": 100000.0,
            "atr_at_entry": 500.0,
        }

        persistence.save(strategy_name, original_state)
        loaded_state = persistence.load(strategy_name)

        # 验证所有原始字段（排除自动添加的 updated_at）
        for key in original_state:
            assert loaded_state[key] == original_state[key]

    def test_multiple_strategies_independent(self, tmp_path: Path):
        """多个策略的持久化文件应独立"""
        persistence = PositionPersistence(base_path=tmp_path)

        persistence.save("strategy_a", {"position": "long", "entry_price": 100.0})
        persistence.save("strategy_b", {"position": "short", "entry_price": 200.0})

        loaded_a = persistence.load("strategy_a")
        loaded_b = persistence.load("strategy_b")

        assert loaded_a["position"] == "long"
        assert loaded_a["entry_price"] == 100.0
        assert loaded_b["position"] == "short"
        assert loaded_b["entry_price"] == 200.0

    def test_clear_one_does_not_affect_others(self, tmp_path: Path):
        """清除一个策略不影响其他策略"""
        persistence = PositionPersistence(base_path=tmp_path)

        persistence.save("strategy_a", {"position": "long"})
        persistence.save("strategy_b", {"position": "short"})

        persistence.clear("strategy_a")

        assert persistence.load("strategy_a") is None
        assert persistence.load("strategy_b") is not None
        assert persistence.load("strategy_b")["position"] == "short"


class TestPositionPersistenceRealtime:
    """实时持久化测试"""

    def test_generate_position_id(self):
        """测试 position_id 生成"""
        position_id = PositionPersistence.generate_position_id(
            strategy_name="obv_atr_v1_1h_BTCUSDT",
            symbol="BTCUSDT",
            entry_timestamp=1716028200,
        )

        assert position_id == "obv_atr_v1_1h_BTCUSDT_BTCUSDT_1716028200"

    def test_position_id_uniqueness_different_timestamp(self):
        """测试不同时间戳生成不同 position_id"""
        id1 = PositionPersistence.generate_position_id(
            "strategy_a", "BTCUSDT", 1716028200
        )
        id2 = PositionPersistence.generate_position_id(
            "strategy_a", "BTCUSDT", 1716028201
        )

        assert id1 != id2

    def test_position_id_uniqueness_different_strategy(self):
        """测试不同策略生成不同 position_id"""
        id1 = PositionPersistence.generate_position_id(
            "strategy_a", "BTCUSDT", 1716028200
        )
        id2 = PositionPersistence.generate_position_id(
            "strategy_b", "BTCUSDT", 1716028200
        )

        assert id1 != id2

    def test_position_id_uniqueness_different_symbol(self):
        """测试不同标的生成不同 position_id"""
        id1 = PositionPersistence.generate_position_id(
            "strategy_a", "BTCUSDT", 1716028200
        )
        id2 = PositionPersistence.generate_position_id(
            "strategy_a", "ETHUSDT", 1716028200
        )

        assert id1 != id2

    def test_save_on_entry_includes_position_id(self, tmp_path: Path):
        """测试开仓时持久化包含 position_id"""
        persistence = PositionPersistence(base_path=tmp_path)

        persistence.save_on_entry(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_1716028200",
            state={
                "position": "long",
                "entry_price": 31000.0,
                "entry_timestamp": 1716028200,
            },
        )

        saved = persistence.load("test_strategy")
        assert saved is not None
        assert saved["position_id"] == "test_strategy_BTCUSDT_1716028200"
        assert saved["position"] == "long"
        assert saved["entry_timestamp"] == 1716028200

    def test_save_on_entry_includes_entry_saved_at(self, tmp_path: Path):
        """测试开仓持久化包含 entry_saved_at 时间戳"""
        persistence = PositionPersistence(base_path=tmp_path)

        persistence.save_on_entry(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_1716028200",
            state={"position": "long"},
        )

        saved = persistence.load("test_strategy")
        assert saved is not None
        assert "entry_saved_at" in saved
        assert isinstance(saved["entry_saved_at"], int)

    def test_update_state_with_matching_position_id(self, tmp_path: Path):
        """测试更新仓位状态（position_id 匹配）"""
        persistence = PositionPersistence(base_path=tmp_path)

        persistence.save_on_entry(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_1716028200",
            state={"position": "long", "entry_price": 31000.0},
        )

        persistence.update_state(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_1716028200",
            updates={"peak_price": 31500.0, "stop_price": 30500.0},
        )

        saved = persistence.load("test_strategy")
        assert saved["peak_price"] == 31500.0
        assert saved["stop_price"] == 30500.0
        assert saved["updated_at"] is not None

    def test_update_state_position_id_mismatch_skips(self, tmp_path: Path):
        """测试 position_id 不匹配时跳过更新"""
        persistence = PositionPersistence(base_path=tmp_path)

        persistence.save_on_entry(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_1716028200",
            state={"position": "long", "peak_price": 31000.0},
        )

        # 使用不匹配的 position_id
        persistence.update_state(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_9999999999",
            updates={"peak_price": 31500.0},
        )

        saved = persistence.load("test_strategy")
        # 原值不变
        assert saved["peak_price"] == 31000.0

    def test_clear_on_exit_with_matching_position_id(self, tmp_path: Path):
        """测试平仓时清除（position_id 匹配）"""
        persistence = PositionPersistence(base_path=tmp_path)

        persistence.save_on_entry(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_1716028200",
            state={"position": "long"},
        )

        persistence.clear_on_exit(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_1716028200",
        )

        assert persistence.load("test_strategy") is None

    def test_clear_on_exit_position_id_mismatch_preserves(self, tmp_path: Path):
        """测试 position_id 不匹配时保留文件"""
        persistence = PositionPersistence(base_path=tmp_path)

        persistence.save_on_entry(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_1716028200",
            state={"position": "long"},
        )

        # 使用不匹配的 position_id
        persistence.clear_on_exit(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_9999999999",
        )

        # 文件应仍然存在
        assert persistence.load("test_strategy") is not None

    def test_clear_on_exit_no_saved_file(self, tmp_path: Path):
        """测试无持久化文件时清除不报错"""
        persistence = PositionPersistence(base_path=tmp_path)

        # 不应抛出异常
        persistence.clear_on_exit(
            strategy_name="test_strategy",
            position_id="test_strategy_BTCUSDT_1716028200",
        )