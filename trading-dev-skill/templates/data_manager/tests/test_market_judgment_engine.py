#!/usr/bin/env python3
"""
市场状态判断引擎单元测试

测试内容:
- judge_timeframe() 函数的各种输入输出
- calculate_market_state() 的多周期判断逻辑
- 边界条件测试（数据不足、指标为空等）
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import sys
from pathlib import Path

# 添加父目录到路径，避免通过 __init__.py 导入
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data_manager.market_judgment_engine import (
    MarketJudgmentEngine,
    MarketState,
)


class TestJudgeTimeframe:
    """测试 judge_timeframe 方法"""

    def setup_method(self):
        """每个测试前的 setup"""
        self.engine = MarketJudgmentEngine(adx_trend_threshold=25.0)

    def test_no_data(self):
        """测试没有数据的情况"""
        result = self.engine.judge_timeframe(
            adx=None, plus_di=None, minus_di=None, rsi=None
        )
        assert result["direction"] == "ranging"
        assert result["is_trending"] is False

    def test_adx_below_threshold(self):
        """测试 ADX 低于阈值"""
        result = self.engine.judge_timeframe(
            adx=20.0, plus_di=30.0, minus_di=20.0, rsi=60.0
        )
        assert result["direction"] == "ranging"
        assert result["is_trending"] is False

    def test_adx_above_threshold_bullish(self):
        """测试 ADX 高于阈值且看涨"""
        result = self.engine.judge_timeframe(
            adx=30.0, plus_di=35.0, minus_di=20.0, rsi=60.0
        )
        assert result["direction"] == "bullish"
        assert result["is_trending"] is True

    def test_adx_above_threshold_bearish(self):
        """测试 ADX 高于阈值且看跌"""
        result = self.engine.judge_timeframe(
            adx=30.0, plus_di=20.0, minus_di=35.0, rsi=40.0
        )
        assert result["direction"] == "bearish"
        assert result["is_trending"] is True

    def test_adx_above_threshold_equal_di(self):
        """测试 ADX 高于阈值但 DI 相等"""
        result = self.engine.judge_timeframe(
            adx=30.0, plus_di=25.0, minus_di=25.0, rsi=50.0
        )
        assert result["direction"] == "ranging"
        assert result["is_trending"] is True

    def test_rsi_not_required_for_direction(self):
        """测试 RSI 不是必需的，DI 交叉优先"""
        result = self.engine.judge_timeframe(
            adx=30.0, plus_di=35.0, minus_di=20.0, rsi=None
        )
        assert result["direction"] == "bullish"
        assert result["is_trending"] is True


class TestJudge:
    """测试 judge 方法（多周期判断）"""

    def setup_method(self):
        self.engine = MarketJudgmentEngine(
            primary_timeframes=["1d", "4h", "15m"],
            adx_trend_threshold=25.0,
        )

    def test_all_trending_same_direction_bullish(self):
        """测试所有周期都是看涨趋势"""
        indicators = {
            "1d": {"adx": 30.0, "plus_di": 35.0, "minus_di": 20.0, "rsi": 60.0},
            "4h": {"adx": 28.0, "plus_di": 32.0, "minus_di": 18.0, "rsi": 55.0},
            "15m": {"adx": 26.0, "plus_di": 30.0, "minus_di": 15.0, "rsi": 58.0},
        }
        state = self.engine.judge(indicators)
        assert state.market_type == "trend_market"
        assert state.direction == "bullish"
        assert state.confidence == 1.0

    def test_all_trending_same_direction_bearish(self):
        """测试所有周期都是看跌趋势"""
        indicators = {
            "1d": {"adx": 30.0, "plus_di": 20.0, "minus_di": 35.0, "rsi": 40.0},
            "4h": {"adx": 28.0, "plus_di": 18.0, "minus_di": 32.0, "rsi": 45.0},
            "15m": {"adx": 26.0, "plus_di": 15.0, "minus_di": 30.0, "rsi": 42.0},
        }
        state = self.engine.judge(indicators)
        assert state.market_type == "trend_market"
        assert state.direction == "bearish"
        assert state.confidence == 1.0

    def test_mixed_directions(self):
        """测试混合方向"""
        indicators = {
            "1d": {"adx": 30.0, "plus_di": 35.0, "minus_di": 20.0, "rsi": 60.0},
            "4h": {"adx": 28.0, "plus_di": 18.0, "minus_di": 32.0, "rsi": 45.0},
            "15m": {"adx": 26.0, "plus_di": 30.0, "minus_di": 15.0, "rsi": 58.0},
        }
        state = self.engine.judge(indicators)
        assert state.market_type == "ranging_market"
        assert state.direction == "bullish"  # 2 bullish vs 1 bearish

    def test_all_ranging(self):
        """测试所有周期都是震荡"""
        indicators = {
            "1d": {"adx": 20.0, "plus_di": 25.0, "minus_di": 24.0, "rsi": 50.0},
            "4h": {"adx": 18.0, "plus_di": 22.0, "minus_di": 21.0, "rsi": 48.0},
            "15m": {"adx": 15.0, "plus_di": 20.0, "minus_di": 19.0, "rsi": 52.0},
        }
        state = self.engine.judge(indicators)
        assert state.market_type == "ranging_market"
        assert state.direction == "ranging"  # 没有趋势方向

    def test_missing_timeframe(self):
        """测试缺少某个周期的数据"""
        indicators = {
            "1d": {"adx": 30.0, "plus_di": 35.0, "minus_di": 20.0, "rsi": 60.0},
            "4h": {"adx": 28.0, "plus_di": 32.0, "minus_di": 18.0, "rsi": 55.0},
            # 缺少 15m
        }
        state = self.engine.judge(indicators)
        # 只有 2 个周期，无法达到 3 个一致
        assert state.market_type == "ranging_market"


class TestCalculateMarketStateForRow:
    """测试 calculate_market_state_for_row 方法"""

    def setup_method(self):
        self.engine = MarketJudgmentEngine()
        self.base_time = pd.Timestamp("2026-01-15 12:00:00", tz="UTC")

    def create_test_df(self, data):
        """创建测试 DataFrame"""
        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        return df

    def test_basic_calculation(self):
        """测试基本计算"""
        df_1d = self.create_test_df([
            {"timestamp": self.base_time - timedelta(days=1), "adx": 30.0, "plus_di": 35.0, "minus_di": 20.0, "rsi": 60.0},
        ])
        df_4h = self.create_test_df([
            {"timestamp": self.base_time - timedelta(hours=4), "adx": 28.0, "plus_di": 32.0, "minus_di": 18.0, "rsi": 55.0},
        ])
        df_15m = self.create_test_df([
            {"timestamp": self.base_time - timedelta(minutes=15), "adx": 26.0, "plus_di": 30.0, "minus_di": 15.0, "rsi": 58.0},
        ])

        market_type, direction = self.engine.calculate_market_state_for_row(
            self.base_time, df_1d, df_4h, df_15m
        )

        assert market_type == "trend_market"
        assert direction == "bullish"

    def test_empty_dataframes(self):
        """测试空 DataFrame"""
        df_empty = pd.DataFrame(columns=["timestamp", "adx", "plus_di", "minus_di", "rsi"])
        df_empty["timestamp"] = pd.to_datetime(df_empty["timestamp"], utc=True)

        market_type, direction = self.engine.calculate_market_state_for_row(
            self.base_time, df_empty, df_empty, df_empty
        )

        assert market_type == "ranging_market"
        assert direction == "ranging"

    def test_partial_data(self):
        """测试部分数据"""
        df_1d = self.create_test_df([
            {"timestamp": self.base_time - timedelta(days=1), "adx": 30.0, "plus_di": 35.0, "minus_di": 20.0, "rsi": 60.0},
        ])
        df_4h = pd.DataFrame(columns=["timestamp", "adx", "plus_di", "minus_di", "rsi"])
        df_4h["timestamp"] = pd.to_datetime(df_4h["timestamp"], utc=True)
        df_15m = self.create_test_df([
            {"timestamp": self.base_time - timedelta(minutes=15), "adx": 26.0, "plus_di": 30.0, "minus_di": 15.0, "rsi": 58.0},
        ])

        market_type, direction = self.engine.calculate_market_state_for_row(
            self.base_time, df_1d, df_4h, df_15m
        )

        # 缺少 4h 数据，无法达到 3 周期一致
        assert market_type == "ranging_market"


class TestMarketStateDataclass:
    """测试 MarketState 数据类"""

    def test_default_values(self):
        """测试默认值"""
        state = MarketState()
        assert state.market_type == "ranging_market"
        assert state.direction == "ranging"
        assert state.confidence == 0.0
        assert state.primary_timeframes == []
        assert state.details == {}

    def test_custom_values(self):
        """测试自定义值"""
        state = MarketState(
            market_type="trend_market",
            direction="bullish",
            confidence=0.95,
            primary_timeframes=["1d", "4h"],
            details={"1d": {"adx": 30.0}},
        )
        assert state.market_type == "trend_market"
        assert state.direction == "bullish"
        assert state.confidence == 0.95
        assert state.primary_timeframes == ["1d", "4h"]
        assert state.details == {"1d": {"adx": 30.0}}


class TestEdgeCases:
    """测试边界条件"""

    def test_adx_exactly_at_threshold(self):
        """测试 ADX 正好等于阈值"""
        engine = MarketJudgmentEngine(adx_trend_threshold=25.0)
        result = engine.judge_timeframe(
            adx=25.0, plus_di=35.0, minus_di=20.0, rsi=60.0
        )
        # 25.0 > 25.0 是 False
        assert result["is_trending"] is False
        assert result["direction"] == "ranging"

    def test_very_high_adx(self):
        """测试非常高的 ADX 值"""
        engine = MarketJudgmentEngine(adx_trend_threshold=25.0)
        result = engine.judge_timeframe(
            adx=60.0, plus_di=45.0, minus_di=15.0, rsi=70.0
        )
        assert result["is_trending"] is True
        assert result["direction"] == "bullish"

    def test_nan_values(self):
        """测试 NaN 值"""
        engine = MarketJudgmentEngine()
        result = engine.judge_timeframe(
            adx=np.nan, plus_di=np.nan, minus_di=np.nan, rsi=np.nan
        )
        # NaN 比较会返回 False，所以应该返回 ranging
        assert result["direction"] == "ranging"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
