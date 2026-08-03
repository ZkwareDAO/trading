import numpy as np
import pandas as pd

from data_manager.klines_loader import resample_ohlcv


def _base_1m_frame() -> pd.DataFrame:
    timestamps = pd.date_range("2026-07-19 00:00:00", periods=4, freq="min", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [101.0, 102.0, 103.0, 104.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [100.5, 101.5, 102.5, 103.5],
            "volume": [10.0, 20.0, 30.0, 40.0],
            "quote_volume": [1_000.0, 2_000.0, 3_000.0, 4_000.0],
            "count": [1, 2, 3, 4],
        }
    )


def test_resample_preserves_historical_taker_buy_schema() -> None:
    frame = _base_1m_frame()
    frame["taker_buy_volume"] = [1.0, 2.0, 3.0, 4.0]
    frame["taker_buy_quote_volume"] = [100.0, 200.0, 300.0, 400.0]

    result = resample_ohlcv(frame, "1h", datetime_column="timestamp")

    assert result.loc[0, "taker_buy_volume"] == 10.0
    assert result.loc[0, "taker_buy_quote_volume"] == 1_000.0
    assert "active_buy_volume" not in result.columns
    assert "active_buy_quote_volume" not in result.columns


def test_resample_preserves_realtime_active_buy_schema() -> None:
    frame = _base_1m_frame()
    frame["active_buy_volume"] = [1.0, 2.0, 3.0, 4.0]
    frame["active_buy_quote_volume"] = [100.0, 200.0, 300.0, 400.0]

    result = resample_ohlcv(frame, "1h", datetime_column="timestamp")

    assert result.loc[0, "active_buy_volume"] == 10.0
    assert result.loc[0, "active_buy_quote_volume"] == 1_000.0
    assert "taker_buy_volume" not in result.columns
    assert "taker_buy_quote_volume" not in result.columns


def test_resample_coalesces_mixed_aliases_row_by_row_before_aggregation() -> None:
    frame = _base_1m_frame()
    frame["taker_buy_volume"] = [1.0, np.nan, 3.0, np.nan]
    frame["active_buy_volume"] = [np.nan, 2.0, np.nan, 4.0]
    frame["taker_buy_quote_volume"] = [100.0, np.nan, 300.0, np.nan]
    frame["active_buy_quote_volume"] = [np.nan, 200.0, np.nan, 400.0]

    result = resample_ohlcv(frame, "1h", datetime_column="timestamp")

    assert result.loc[0, "taker_buy_volume"] == 10.0
    assert result.loc[0, "active_buy_volume"] == 10.0
    assert result.loc[0, "taker_buy_quote_volume"] == 1_000.0
    assert result.loc[0, "active_buy_quote_volume"] == 1_000.0
    assert result.loc[0, "volume"] == 100.0
    assert result.loc[0, "open"] == 100.0
    assert result.loc[0, "close"] == 103.5
