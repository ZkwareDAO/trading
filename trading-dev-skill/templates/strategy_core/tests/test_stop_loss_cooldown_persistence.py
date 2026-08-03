#!/usr/bin/env python3
"""
测试 StopLossCoolDownPersistence 止损冷却持久化

验证：
1. 保存和加载止损日期
2. 清除止损冷却
3. 文件不存在时返回 None
4. 无效数据时返回 None
"""

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from strategy_core.stop_loss_cooldown_persistence import StopLossCoolDownPersistence


class TestStopLossCoolDownPersistence:
    """止损冷却持久化测试"""

    def test_save_and_load_stop_loss_date(self, tmp_path: Path):
        """测试保存和加载止损日期"""
        persistence = StopLossCoolDownPersistence(base_path=tmp_path)

        strategy_id = "OBVATR_4H_2_DOGEUSDT_LIVE"
        stop_loss_date = date(2026, 6, 26)

        # 保存
        persistence.save(strategy_id, stop_loss_date)

        # 加载
        loaded = persistence.load(strategy_id)
        assert loaded == stop_loss_date

    def test_clear_stop_loss_cooldown(self, tmp_path: Path):
        """测试清除止损冷却"""
        persistence = StopLossCoolDownPersistence(base_path=tmp_path)

        strategy_id = "OBVATR_4H_2_ETHUSDT_LIVE"
        stop_loss_date = date(2026, 6, 26)

        # 保存
        persistence.save(strategy_id, stop_loss_date)
        assert persistence.load(strategy_id) == stop_loss_date

        # 清除
        persistence.clear(strategy_id)
        assert persistence.load(strategy_id) is None

    def test_load_returns_none_when_file_not_exists(self, tmp_path: Path):
        """文件不存在时返回 None"""
        persistence = StopLossCoolDownPersistence(base_path=tmp_path)

        loaded = persistence.load("NON_EXISTENT_STRATEGY")
        assert loaded is None

    def test_load_returns_none_on_invalid_json(self, tmp_path: Path):
        """无效 JSON 时返回 None"""
        persistence = StopLossCoolDownPersistence(base_path=tmp_path)

        # 创建无效 JSON 文件
        filepath = tmp_path / "INVALID_STRATEGY.json"
        filepath.write_text("not a valid json")

        loaded = persistence.load("INVALID_STRATEGY")
        assert loaded is None

    def test_load_returns_none_on_missing_stop_loss_date_field(self, tmp_path: Path):
        """缺少 stop_loss_date 字段时返回 None"""
        persistence = StopLossCoolDownPersistence(base_path=tmp_path)

        # 创建缺少 stop_loss_date 字段的文件
        filepath = tmp_path / "MISSING_FIELD.json"
        filepath.write_text(json.dumps({"updated_at": "2026-06-26T15:00:00+00:00"}))

        loaded = persistence.load("MISSING_FIELD")
        assert loaded is None

    def test_load_returns_none_on_invalid_date_format(self, tmp_path: Path):
        """无效日期格式时返回 None"""
        persistence = StopLossCoolDownPersistence(base_path=tmp_path)

        # 创建无效日期格式的文件
        filepath = tmp_path / "INVALID_DATE.json"
        filepath.write_text(json.dumps({"stop_loss_date": "not-a-date"}))

        loaded = persistence.load("INVALID_DATE")
        assert loaded is None

    def test_save_overwrites_existing_date(self, tmp_path: Path):
        """保存会覆盖已有的止损日期"""
        persistence = StopLossCoolDownPersistence(base_path=tmp_path)

        strategy_id = "OVERWRITE_TEST"
        first_date = date(2026, 6, 25)
        second_date = date(2026, 6, 26)

        # 第一次保存
        persistence.save(strategy_id, first_date)
        assert persistence.load(strategy_id) == first_date

        # 第二次保存（覆盖）
        persistence.save(strategy_id, second_date)
        assert persistence.load(strategy_id) == second_date

    def test_file_content_structure(self, tmp_path: Path):
        """验证文件内容结构"""
        persistence = StopLossCoolDownPersistence(base_path=tmp_path)

        strategy_id = "STRUCTURE_TEST"
        stop_loss_date = date(2026, 6, 26)

        persistence.save(strategy_id, stop_loss_date)

        # 读取文件内容
        filepath = tmp_path / f"{strategy_id}.json"
        with open(filepath, "r") as f:
            data = json.load(f)

        assert "stop_loss_date" in data
        assert data["stop_loss_date"] == "2026-06-26"
        assert "updated_at" in data

    def test_clear_does_not_fail_when_file_not_exists(self, tmp_path: Path):
        """清除不存在的文件时不会失败"""
        persistence = StopLossCoolDownPersistence(base_path=tmp_path)

        # 不应该抛出异常
        persistence.clear("NON_EXISTENT_STRATEGY")
