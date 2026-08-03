#!/usr/bin/env python3
"""
验证 ta-lib 和 pandas-ta 数值一致性测试

用于重构前后对比验证，确保替换为 ta-lib 后数值精度一致。
"""

import numpy as np
import pandas as pd
import pytest


def make_kline_df(n: int = 100) -> pd.DataFrame:
    """生成模拟 K 线数据（足够长以产生有效值）"""
    import math
    ts = pd.date_range("2026-04-20", periods=n, freq="1min", tz="UTC")
    base = 100.0
    rows = []
    for i in range(n):
        noise = math.sin(i * 0.1) * 2
        close = base + i * 0.1 + noise
        high = close + 0.5 + abs(noise) * 0.2
        low = close - 0.5 - abs(noise) * 0.2
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


class TestTaLibPandasTaConsistency:
    """验证 ta-lib 和 pandas-ta 数值一致性"""

    @pytest.fixture(scope="class")
    def sample_df(self):
        return make_kline_df(100)

    def test_rsi_wilder_consistency(self, sample_df):
        """RSI Wilder 方法：ta-lib 和 pandas-ta 应一致"""
        import pandas_ta as pta
        import talib

        # pandas-ta Wilder (mamode='rma')
        pta_rsi = pta.rsi(sample_df['close'], length=14, mamode='rma')

        # ta-lib RSI (默认 Wilder)
        talib_rsi = talib.RSI(sample_df['close'], timeperiod=14)

        # 验证有效值接近（允许 1% 相对误差）
        valid_idx = ~pta_rsi.isna() & ~np.isnan(talib_rsi)
        if valid_idx.any():
            diff = np.abs(pta_rsi[valid_idx] - talib_rsi[valid_idx])
            max_diff = diff.max()
            assert max_diff < 1.0, f"RSI max diff: {max_diff}"

    def test_atr_wilder_consistency(self, sample_df):
        """ATR Wilder 方法：ta-lib 和 pandas-ta 应一致"""
        import pandas_ta as pta
        import talib

        # pandas-ta Wilder (mamode='rma')
        pta_atr = pta.atr(sample_df['high'], sample_df['low'], sample_df['close'], length=14, mamode='rma')

        # ta-lib ATR (默认 Wilder)
        talib_atr = talib.ATR(sample_df['high'], sample_df['low'], sample_df['close'], timeperiod=14)

        # 验证有效值接近（ATR 是价格相关，允许 5% 相对误差）
        valid_idx = ~pta_atr.isna() & ~np.isnan(talib_atr)
        if valid_idx.any():
            rel_diff = np.abs(pta_atr[valid_idx] - talib_atr[valid_idx]) / talib_atr[valid_idx]
            max_rel_diff = rel_diff.max()
            assert max_rel_diff < 0.05, f"ATR max relative diff: {max_rel_diff}"

    def test_ema_consistency(self, sample_df):
        """EMA：ta-lib 和 pandas-ta 应一致"""
        import pandas_ta as pta
        import talib

        pta_ema = pta.ema(sample_df['close'], length=20)
        talib_ema = talib.EMA(sample_df['close'], timeperiod=20)

        valid_idx = ~pta_ema.isna() & ~np.isnan(talib_ema)
        if valid_idx.any():
            rel_diff = np.abs(pta_ema[valid_idx] - talib_ema[valid_idx]) / talib_ema[valid_idx]
            max_rel_diff = rel_diff.max()
            assert max_rel_diff < 0.01, f"EMA max relative diff: {max_rel_diff}"

    def test_sma_consistency(self, sample_df):
        """SMA：ta-lib 和 pandas-ta 应完全一致"""
        import pandas_ta as pta
        import talib

        pta_sma = pta.sma(sample_df['close'], length=20)
        talib_sma = talib.SMA(sample_df['close'], timeperiod=20)

        valid_idx = ~pta_sma.isna() & ~np.isnan(talib_sma)
        if valid_idx.any():
            diff = np.abs(pta_sma[valid_idx] - talib_sma[valid_idx])
            max_diff = diff.max()
            assert max_diff < 1e-6, f"SMA max diff: {max_diff}"

    def test_macd_consistency(self, sample_df):
        """MACD：ta-lib 和 pandas-ta 应一致"""
        import pandas_ta as pta
        import talib

        # pandas-ta
        pta_result = pta.macd(sample_df['close'], fast=12, slow=26, signal=9)

        # ta-lib 返回 tuple (macd, signal, hist)
        talib_macd, talib_signal, talib_hist = talib.MACD(
            sample_df['close'], fastperiod=12, slowperiod=26, signalperiod=9
        )

        # 提取 pandas-ta 列
        prefix = "_12_26_9"
        pta_macd = pta_result[f"MACD{prefix}"]
        pta_signal = pta_result[f"MACDs{prefix}"]
        pta_hist = pta_result[f"MACDh{prefix}"]

        # 验证 macd 线
        valid_idx = ~pta_macd.isna() & ~np.isnan(talib_macd)
        if valid_idx.any():
            diff = np.abs(pta_macd[valid_idx] - talib_macd[valid_idx])
            assert diff.max() < 0.1, f"MACD max diff: {diff.max()}"

    def test_bbands_consistency(self, sample_df):
        """布林带：ta-lib 和 pandas-ta 应一致"""
        import pandas_ta as pta
        import talib

        # pandas-ta
        pta_result = pta.bbands(sample_df['close'], length=20, std=2.0)

        # ta-lib 返回 tuple (upper, middle, lower)
        talib_upper, talib_middle, talib_lower = talib.BBANDS(
            sample_df['close'], timeperiod=20, nbdevup=2, nbdevdn=2
        )

        # 提取 pandas-ta 列
        pta_upper = pta_result[[c for c in pta_result.columns if c.startswith("BBU_")][0]]
        pta_middle = pta_result[[c for c in pta_result.columns if c.startswith("BBM_")][0]]
        pta_lower = pta_result[[c for c in pta_result.columns if c.startswith("BBL_")][0]]

        # 验证中轨（SMA 应完全一致）
        valid_idx = ~pta_middle.isna() & ~np.isnan(talib_middle)
        if valid_idx.any():
            diff = np.abs(pta_middle[valid_idx] - talib_middle[valid_idx])
            assert diff.max() < 1e-6, f"BBANDS middle max diff: {diff.max()}"

    def test_stoch_consistency(self, sample_df):
        """STOCH (KD)：ta-lib 和 pandas-ta 应一致"""
        import pandas_ta as pta
        import talib

        # pandas-ta
        pta_result = pta.stoch(sample_df['high'], sample_df['low'], sample_df['close'], k=14, d=3)

        # ta-lib 返回 tuple (slowk, slowd)
        talib_k, talib_d = talib.STOCH(
            sample_df['high'], sample_df['low'], sample_df['close'],
            fastk_period=14, slowk_period=3, slowd_period=3
        )

        # 提取 pandas-ta 列
        pta_k = pta_result[[c for c in pta_result.columns if c.startswith("STOCHk")][0]]
        pta_d = pta_result[[c for c in pta_result.columns if c.startswith("STOCHd")][0]]

        # 验证 K 值
        valid_idx = ~pta_k.isna() & ~np.isnan(talib_k)
        if valid_idx.any():
            diff = np.abs(pta_k[valid_idx] - talib_k[valid_idx])
            assert diff.max() < 1.0, f"STOCH K max diff: {diff.max()}"

    def test_adx_components_exist(self, sample_df):
        """验证 ta-lib 有 ADX 相关函数"""
        import talib

        # ta-lib 需要分别调用
        adx = talib.ADX(sample_df['high'], sample_df['low'], sample_df['close'], timeperiod=14)
        plus_di = talib.PLUS_DI(sample_df['high'], sample_df['low'], sample_df['close'], timeperiod=14)
        minus_di = talib.MINUS_DI(sample_df['high'], sample_df['low'], sample_df['close'], timeperiod=14)

        # 验证返回值形状正确
        assert len(adx) == len(sample_df)
        assert len(plus_di) == len(sample_df)
        assert len(minus_di) == len(sample_df)


class TestTaLibMethodSupport:
    """验证 ta-lib 不支持 ewm 方法的影响"""

    def test_rsi_ewm_not_supported(self):
        """ta-lib RSI 只支持 Wilder，不支持 EWM"""
        import talib

        # ta-lib 没有 mamode 参数，只有 Wilder 方法
        df = make_kline_df(100)
        rsi = talib.RSI(df['close'], timeperiod=14)

        # 验证有效值
        assert not np.all(np.isnan(rsi))

    def test_atr_ewm_not_supported(self):
        """ta-lib ATR 只支持 Wilder，不支持 EWM"""
        import talib

        df = make_kline_df(100)
        atr = talib.ATR(df['high'], df['low'], df['close'], timeperiod=14)

        # 验证有效值
        assert not np.all(np.isnan(atr))


class TestTaLibAPICompatibility:
    """验证 ta-lib API 可替代 pandas-ta"""

    def test_return_types(self):
        """ta-lib 返回 numpy 数组，需要转换为 pandas"""
        import talib

        df = make_kline_df(50)
        sma = talib.SMA(df['close'], timeperiod=20)

        # ta-lib 返回 numpy 数组
        assert isinstance(sma, np.ndarray) or hasattr(sma, '__array__')

        # 可以转换为 pandas Series
        sma_series = pd.Series(sma, index=df.index)
        assert isinstance(sma_series, pd.Series)

    def test_tuple_returns(self):
        """MACD, BBANDS, STOCH 返回 tuple"""
        import talib

        df = make_kline_df(100)

        # MACD 返回 tuple
        macd_result = talib.MACD(df['close'], fastperiod=12, slowperiod=26, signalperiod=9)
        assert isinstance(macd_result, tuple)
        assert len(macd_result) == 3

        # BBANDS 返回 tuple
        boll_result = talib.BBANDS(df['close'], timeperiod=20)
        assert isinstance(boll_result, tuple)
        assert len(boll_result) == 3

        # STOCH 返回 tuple
        stoch_result = talib.STOCH(df['high'], df['low'], df['close'])
        assert isinstance(stoch_result, tuple)
        assert len(stoch_result) == 2