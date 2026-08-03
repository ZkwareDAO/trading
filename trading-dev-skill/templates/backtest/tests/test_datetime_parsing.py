"""Test that backtrader CSV datetime parsing preserves time-of-day.

Bug: GenericCSVData defaults to timeframe=TimeFrame.Days and
sessionend=23:59:59.999990. When timeframe >= Days, backtrader replaces
the parsed datetime with sessionend, turning every intraday bar into
23:59:59.999990.

Fix: pass explicit timeframe=TimeFrame.Minutes and sessionend=None.
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, time

import backtrader as bt
import pandas as pd
import pytest

from backtest.run_backtest import _parse_kline_timestamps

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


class TestDatetimeParsing:
    """Verify backtrader CSV datetime parsing preserves hours/minutes."""

    def test_default_generic_csv_replaces_time_with_sessionend(self):
        """Bug reproduction: default timeframe=Days causes sessionend overwrite."""
        csv_path = self._write_csv(
            "bug_default_params.csv",
            [
                "2026-03-30 00:00:00+00:00,100,105,95,102,1000",
                "2026-03-30 00:01:00+00:00,102,108,100,106,1200",
                "2026-03-30 00:02:00+00:00,106,110,104,108,800",
            ],
        )

        timestamps = self._load_csv_timestamps(csv_path)

        # BUG: all timestamps are 23:59:59.999990 instead of 00:00, 00:01, 00:02
        assert timestamps[0].minute == 59  # bug: should be 0
        assert timestamps[1].minute == 59  # bug: should be 1
        assert timestamps[2].minute == 59  # bug: should be 2

    def test_intraday_csv_with_minutes_timeframe_has_correct_timestamps(self):
        """Passing timeframe=Minutes + sessionend=None preserves time-of-day."""
        csv_path = self._write_csv(
            "fixed_minutes_tf.csv",
            [
                "2026-03-30 00:00:00+00:00,100,105,95,102,1000",
                "2026-03-30 00:01:00+00:00,102,108,100,106,1200",
                "2026-03-30 00:02:00+00:00,106,110,104,108,800",
            ],
        )

        timestamps = self._load_csv_timestamps(
            csv_path,
            timeframe=bt.TimeFrame.Minutes,
            sessionend=None,
        )

        # FIXED: minutes are correct
        assert timestamps[0].minute == 0
        assert timestamps[1].minute == 1
        assert timestamps[2].minute == 2

    def test_ict_style_4h_data_preserves_hours(self):
        """4h candles should keep their hour component, not become 23:59."""
        csv_path = self._write_csv(
            "ict_4h.csv",
            [
                "2026-03-30 00:00:00+00:00,100,105,95,102,1000",
                "2026-03-30 04:00:00+00:00,102,108,100,106,1200",
                "2026-03-30 08:00:00+00:00,106,110,104,108,800",
            ],
        )

        timestamps = self._load_csv_timestamps(
            csv_path,
            timeframe=bt.TimeFrame.Minutes,
            sessionend=None,
        )

        assert timestamps[0].hour == 0
        assert timestamps[1].hour == 4
        assert timestamps[2].hour == 8

    def test_mixed_timestamp_parser_accepts_epoch_and_iso_files(self):
        epoch = _parse_kline_timestamps(pd.Series([1735689600000]))
        iso = _parse_kline_timestamps(pd.Series(["2025-01-01 00:00:00+00:00"]))

        assert epoch.iloc[0] == pd.Timestamp("2025-01-01 00:00:00+00:00")
        assert iso.iloc[0] == pd.Timestamp("2025-01-01 00:00:00+00:00")

    def _write_csv(self, filename: str, rows: list[str]) -> str:
        """Write a temporary CSV file and return its path."""
        tmp_dir = Path(__file__).parent / "tmp"
        tmp_dir.mkdir(exist_ok=True)
        path = tmp_dir / filename
        header = "datetime,open,high,low,close,volume"
        path.write_text(f"{header}\n" + "\n".join(rows) + "\n")
        return str(path)

    def _load_csv_timestamps(
        self,
        csv_path: str,
        timeframe=bt.TimeFrame.Days,  # default to expose the bug
        sessionend=time(23, 59, 59, 999990),
    ) -> list[datetime]:
        """Load a CSV with backtrader and return parsed datetimes."""
        timestamps: list[datetime] = []

        class Capture(bt.Strategy):
            def next(self_):
                timestamps.append(self_.datas[0].datetime.datetime(0))

        cerebro = bt.Cerebro()
        kwargs = {
            "dataname": csv_path,
            "dtformat": "%Y-%m-%d %H:%M:%S+00:00",
            "datetime": 0,
            "open": 1,
            "high": 2,
            "low": 3,
            "close": 4,
            "volume": 5,
            "openinterest": -1,
        }
        if timeframe is not None:
            kwargs["timeframe"] = timeframe
        if sessionend is not None:
            kwargs["sessionend"] = sessionend

        data = bt.feeds.GenericCSVData(**kwargs)
        cerebro.adddata(data)
        cerebro.addstrategy(Capture)
        cerebro.run()

        return timestamps
