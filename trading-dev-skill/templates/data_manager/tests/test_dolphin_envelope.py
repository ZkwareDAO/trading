#!/usr/bin/env python3
"""
测试均线通道（Envelope）计算

验证百分比格式参数是否正确实现
"""

import pytest
import pandas as pd
import numpy as np

from data_manager.indicators import compute_envelope


class TestEnvelopePercentage:
    """测试均线通道百分比计算"""

    def test_upper_channel_with_percentage(self):
        """上轨应为中轨 + 百分比偏移"""
        df = pd.DataFrame({"close": [100.0] * 30})
        # 0.618% 偏移
        result = compute_envelope(df, column="close", period=26, upper_pct=0.618)

        assert result["middle"].iloc[-1] == pytest.approx(100.0)
        # 上轨 = 100 × (1 + 0.618/100) = 100.618
        assert result["upper"].iloc[-1] == pytest.approx(100.618, rel=0.001)

    def test_lower_channel_with_percentage(self):
        """下轨应为中轨 - 百分比偏移"""
        df = pd.DataFrame({"close": [100.0] * 30})
        # 0.618% 偏移
        result = compute_envelope(df, column="close", period=26, lower_pct=0.618)

        assert result["middle"].iloc[-1] == pytest.approx(100.0)
        # 下轨 = 100 × (1 - 0.618/100) = 99.382
        assert result["lower"].iloc[-1] == pytest.approx(99.382, rel=0.001)

    def test_five_percent_envelope(self):
        """5% 偏移的通道"""
        df = pd.DataFrame({"close": [100.0] * 30})
        result = compute_envelope(df, column="close", period=26, upper_pct=5, lower_pct=5)

        assert result["upper"].iloc[-1] == pytest.approx(105.0, rel=0.001)  # 100 × 1.05
        assert result["lower"].iloc[-1] == pytest.approx(95.0, rel=0.001)   # 100 × 0.95

    def test_channel_width_with_percentage(self):
        """通道宽度验证"""
        df = pd.DataFrame({"close": [100.0] * 30})
        result = compute_envelope(df, column="close", period=26, upper_pct=0.618, lower_pct=0.618)

        middle = result["middle"].iloc[-1]
        width_pct = (result["upper"].iloc[-1] - result["lower"].iloc[-1]) / middle * 100

        # 通道宽度 = 0.618% + 0.618% = 1.236%
        assert width_pct == pytest.approx(1.236, rel=0.001)

    def test_with_varying_prices(self):
        """使用变化的价格数据验证"""
        prices = [90, 95, 100, 105, 110] * 6  # 30 个数据点
        df = pd.DataFrame({"close": prices})
        result = compute_envelope(df, column="close", period=26, upper_pct=0.618, lower_pct=0.618)

        # 验证比例关系
        for i in range(26, len(prices)):
            middle = result["middle"].iloc[i]
            upper = result["upper"].iloc[i]
            lower = result["lower"].iloc[i]

            if not np.isnan(middle):
                # upper = middle * (1 + 0.618/100)
                assert upper / middle == pytest.approx(1.00618, rel=0.001)
                # lower = middle * (1 - 0.618/100)
                assert lower / middle == pytest.approx(0.99382, rel=0.001)

    def test_default_parameters(self):
        """默认参数"""
        df = pd.DataFrame({"close": [100.0] * 30})
        result = compute_envelope(df, column="close", period=26)

        # 默认 0.618%
        assert result["upper"].iloc[-1] == pytest.approx(100.618, rel=0.001)
        assert result["lower"].iloc[-1] == pytest.approx(99.382, rel=0.001)


class TestEnvelopeNotMultiplier:
    """确保参数是百分比而非倍数"""

    def test_upper_pct_1_means_1_percent_not_double(self):
        """upper_pct=1 应该表示 1%，而非 2 倍"""
        df = pd.DataFrame({"close": [100.0] * 30})
        result = compute_envelope(df, column="close", period=26, upper_pct=1.0)

        # 正确（百分比）：100 × 1.01 = 101
        # 错误（倍数）：100 × 2.0 = 200
        assert result["upper"].iloc[-1] == pytest.approx(101.0, rel=0.001)
        assert result["upper"].iloc[-1] != pytest.approx(200.0, rel=0.001)

    def test_lower_pct_1_means_1_percent_not_half(self):
        """lower_pct=1 应该表示 1%，而非 0.5 倍"""
        df = pd.DataFrame({"close": [100.0] * 30})
        result = compute_envelope(df, column="close", period=26, lower_pct=1.0)

        # 正确（百分比）：100 × 0.99 = 99
        # 错误（倍数）：100 × 0.5 = 50
        assert result["lower"].iloc[-1] == pytest.approx(99.0, rel=0.001)
        assert result["lower"].iloc[-1] != pytest.approx(50.0, rel=0.001)
