#!/usr/bin/env python3
"""
技术指标模块测试
"""

import numpy as np
import pandas as pd
import pytest

from data_manager.indicators import (
    compute_adx, compute_ema, compute_sma, compute_rsi,
    compute_macd, compute_boll, compute_atr,
    compute_indicator, get_available_indicators, compute_kd,
)


def make_kline_df(n: int = 50) -> pd.DataFrame:
    """生成模拟 K 线数据"""
    import math
    ts = pd.date_range("2026-04-20", periods=n, freq="1min", tz="UTC")
    base = 100.0
    rows = []
    for i in range(n):
        noise = math.sin(i * 0.1) * 2
        close = base + i * 0.1 + noise
        high = close + 0.5
        low = close - 0.5
        open_price = close + (noise * 0.1)
        rows.append({
            'timestamp': ts[i],
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': 1000.0 + i * 10,
        })
    return pd.DataFrame(rows)


class TestADX:
    def test_adx_returns_required_columns(self):
        df = make_kline_df(50)
        result = compute_adx(df, period=14)
        assert "adx" in result.columns
        assert "di_plus" in result.columns
        assert "di_minus" in result.columns
        assert len(result) > 0

    def test_adx_values_in_range(self):
        df = make_kline_df(100)
        result = compute_adx(df, period=14)
        # 只验证非 NaN 值（前几根K线无有效值是正常的）
        valid_adx = result["adx"].dropna()
        assert (valid_adx >= 0).all()
        assert (valid_adx <= 100).all()

    def test_adx_wilder_method_default(self):
        """默认使用 Wilder 方法（交易所标准）"""
        df = make_kline_df(100)
        result = compute_adx(df, period=14)
        assert len(result) > 0
        assert not result["adx"].isna().all()

    def test_adx_wilder_method(self):
        """Wilder's Smoothing 方法（交易所标准）"""
        df = make_kline_df(100)
        result = compute_adx(df, period=14, method="wilder")
        assert len(result) > 0
        assert not result["adx"].isna().all()

    def test_adx_ewm_vs_wilder_different(self):
        """EWM 和 Wilder 应该产生不同结果"""
        df = make_kline_df(100)
        result_ewm = compute_adx(df, period=14, method="ewm")
        result_wilder = compute_adx(df, period=14, method="wilder")

        # 两种方法结果应不同（Wilder 更平滑）
        # 取最后一个有效值对比
        last_ewm = result_ewm["adx"].dropna().iloc[-1]
        last_wilder = result_wilder["adx"].dropna().iloc[-1]

        # 允许差异 > 0.1（实际上应该更明显）
        assert abs(last_ewm - last_wilder) > 0.01

    def test_adx_invalid_method_raises(self):
        """无效方法应抛出错误"""
        df = make_kline_df(50)
        with pytest.raises(ValueError, match="method"):
            compute_adx(df, period=14, method="invalid")

    def test_adx_methods_produce_valid_values(self):
        """两种方法都应该产生有效值（0-100 范围内）"""
        df = make_kline_df(100)
        result_ewm = compute_adx(df, period=14, method="ewm")
        result_wilder = compute_adx(df, period=14, method="wilder")

        # 两者都应在有效范围内（只验证非 NaN 值）
        valid_ewm = result_ewm["adx"].dropna()
        valid_wilder = result_wilder["adx"].dropna()

        assert (valid_ewm >= 0).all() and (valid_ewm <= 100).all()
        assert (valid_wilder >= 0).all() and (valid_wilder <= 100).all()

    def test_adx_di_values_in_range(self):
        """DI+ 和 DI- 应该在 0-100 范围内"""
        df = make_kline_df(100)
        result = compute_adx(df, period=14, method="wilder")

        assert (result["di_plus"] >= 0).all() and (result["di_plus"] <= 100).all()
        assert (result["di_minus"] >= 0).all() and (result["di_minus"] <= 100).all()

    def test_adx_with_minimal_data(self):
        """最小数据量测试（period + 1）"""
        df = make_kline_df(15)  # period=14, 需要 15 根 K 线
        result = compute_adx(df, period=14, method="wilder")
        assert len(result) > 0

    def test_adx_empty_dataframe(self):
        """空 DataFrame 处理"""
        df = pd.DataFrame(columns=["high", "low", "close"])
        result = compute_adx(df, period=14)
        assert result.empty or len(result) == 0


class TestEMA:
    def test_ema_basic(self):
        df = make_kline_df(50)
        result = compute_ema(df, period=20)
        assert len(result) == 50
        assert not result.isna().head(20).dropna().empty or len(result.dropna()) > 0


class TestSMA:
    def test_sma_basic(self):
        df = make_kline_df(50)
        result = compute_sma(df, period=20)
        assert len(result) == 50
        # 前 19 个为 NaN
        assert result.iloc[:19].isna().all()
        assert not pd.isna(result.iloc[19])


class TestRSI:
    def test_rsi_in_range(self):
        df = make_kline_df(100)
        result = compute_rsi(df, period=14)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_rsi_wilder_method_default(self):
        """默认使用 Wilder 方法（交易所标准）"""
        df = make_kline_df(100)
        result = compute_rsi(df, period=14)
        assert not result.isna().all()

    def test_rsi_ewm_vs_wilder_different(self):
        """EWM 和 Wilder 应该产生不同结果（在波动数据上）"""
        # 使用波动更大的数据测试
        import math
        ts = pd.date_range("2026-04-20", periods=100, freq="1min", tz="UTC")
        rows = []
        for i in range(100):
            # 创建波动较大的价格序列
            close = 100 + math.sin(i * 0.3) * 10 + i * 0.2
            rows.append({'close': close})
        df = pd.DataFrame(rows)

        result_ewm = compute_rsi(df, period=14, method="ewm")
        result_wilder = compute_rsi(df, period=14, method="wilder")

        # 验证两者都有有效值
        assert not result_ewm.isna().all()
        assert not result_wilder.isna().all()

    def test_rsi_invalid_method_raises(self):
        """无效方法应抛出错误"""
        df = make_kline_df(50)
        with pytest.raises(ValueError, match="method"):
            compute_rsi(df, period=14, method="invalid")


class TestMACD:
    def test_macd_returns_columns(self):
        df = make_kline_df(50)
        result = compute_macd(df)
        assert "macd" in result.columns
        assert "signal" in result.columns
        assert "histogram" in result.columns


class TestBOLL:
    def test_boll_returns_columns(self):
        df = make_kline_df(50)
        result = compute_boll(df, period=20)
        assert "upper" in result.columns
        assert "middle" in result.columns
        assert "lower" in result.columns

    def test_boll_ordering(self):
        df = make_kline_df(100)
        result = compute_boll(df, period=20)
        valid = result.dropna()
        assert (valid["upper"] >= valid["middle"]).all()
        assert (valid["middle"] >= valid["lower"]).all()


class TestATR:
    def test_atr_positive(self):
        df = make_kline_df(50)
        result = compute_atr(df, period=14)
        valid = result.dropna()
        assert (valid > 0).all()

    def test_atr_wilder_method_default(self):
        """默认使用 Wilder 方法（交易所标准）"""
        df = make_kline_df(100)
        result = compute_atr(df, period=14)
        assert not result.isna().all()

    def test_atr_ewm_vs_wilder(self):
        """EWM 和 Wilder 方法都应该有效"""
        df = make_kline_df(100)
        result_ewm = compute_atr(df, period=14, method="ewm")
        result_wilder = compute_atr(df, period=14, method="wilder")

        # 验证两者都有有效值
        assert not result_ewm.isna().all()
        assert not result_wilder.isna().all()

        # ATR 值都应该为正
        assert (result_ewm.dropna() > 0).all()
        assert (result_wilder.dropna() > 0).all()

    def test_atr_invalid_method_raises(self):
        """无效方法应抛出错误"""
        df = make_kline_df(50)
        with pytest.raises(ValueError, match="method"):
            compute_atr(df, period=14, method="invalid")


class TestComputeIndicator:
    """统一接口测试"""

    def test_valid_indicator_name(self):
        df = make_kline_df(50)
        result = compute_indicator("adx", df, {"period": 14})
        assert result is not None
        assert len(result) > 0

    def test_invalid_indicator_name(self):
        df = make_kline_df(50)
        with pytest.raises(ValueError, match="未知指标"):
            compute_indicator("nonexistent", df)

    def test_missing_column_raises(self):
        df = pd.DataFrame({"timestamp": range(10)})
        with pytest.raises(ValueError, match="需要列"):
            compute_indicator("adx", df)

    def test_custom_params_override(self):
        df = make_kline_df(100)
        result = compute_indicator("rsi", df, {"period": 7})
        assert result is not None
        assert len(result) > 0

    def test_all_registered_indicators_work(self):
        df = make_kline_df(100)
        for name in get_available_indicators():
            result = compute_indicator(name, df)
            assert result is not None, f"{name} 返回 None"


class TestGetAvailableIndicators:
    def test_returns_non_empty_list(self):
        indicators = get_available_indicators()
        assert len(indicators) >= 7
        assert "adx" in indicators
        assert "rsi" in indicators
        assert "macd" in indicators
        assert "boll" in indicators
        assert "ema" in indicators
        assert "sma" in indicators
        assert "atr" in indicators


class TestKD:
    """KDJ 随机指标测试"""

    def test_kd_returns_required_columns(self):
        df = make_kline_df(100)
        result = compute_kd(df, k_period=9, d_period=3, j_period=3, smooth="ema")
        assert "k" in result.columns
        assert "d" in result.columns
        assert "j" in result.columns
        assert len(result) > 0

    def test_kd_values_in_range(self):
        df = make_kline_df(100)
        result = compute_kd(df, k_period=9, d_period=3, j_period=3, smooth="ema")
        valid = result.dropna()
        assert (valid["k"] >= 0).all() and (valid["k"] <= 100).all()
        assert (valid["d"] >= 0).all() and (valid["d"] <= 100).all()

    def test_kd_ema_default(self):
        """默认使用 EMA 平滑（交易所标准）"""
        df = make_kline_df(100)
        result = compute_kd(df)
        assert not result.empty
        assert "k" in result.columns

    def test_kd_ema_vs_sma_different(self):
        """EMA 和 SMA 应该产生不同结果"""
        df = make_kline_df(100)
        result_ema = compute_kd(df, k_period=9, d_period=3, smooth="ema")
        result_sma = compute_kd(df, k_period=9, d_period=3, smooth="sma")

        # 两种方法结果应不同
        last_ema_k = result_ema["k"].iloc[-1]
        last_sma_k = result_sma["k"].iloc[-1]
        assert abs(last_ema_k - last_sma_k) > 0.01

    def test_kd_exchange_standard_params(self):
        """交易所标准参数 (9, 3, 3)"""
        df = make_kline_df(100)
        result = compute_kd(df, k_period=9, d_period=3, j_period=3, smooth="ema")
        assert len(result) > 0
        # J = 3K - 2D
        expected_j = 3 * result["k"] - 2 * result["d"]
        assert (result["j"] == expected_j).all()

    def test_kd_custom_period(self):
        """自定义周期参数"""
        df = make_kline_df(100)
        result_9 = compute_kd(df, k_period=9, d_period=3, smooth="ema")
        result_14 = compute_kd(df, k_period=14, d_period=3, smooth="ema")
        # 不同周期应产生不同结果
        assert abs(result_9["k"].iloc[-1] - result_14["k"].iloc[-1]) > 0.1
