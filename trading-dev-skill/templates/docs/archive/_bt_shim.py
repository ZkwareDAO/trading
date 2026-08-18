"""Local wrapper: stub data-fetching (network + subprocesses are unavailable
in this sandbox) then delegate to backtest.run_backtest.main.

Our CSVs already cover 2025-01-01 → 2026-07-10, so any additional sync is a
no-op for the requested date ranges.
"""
import sys, os, pandas as pd

# Stub the network/subprocess loader before it's imported anywhere else.
import data_manager.klines_loader as kl

def _stub_load_klines_data(**kwargs):
    return pd.DataFrame()

kl.load_klines_data = _stub_load_klines_data

# Also stub in run_backtest module namespace
from backtest import run_backtest as rb
rb.load_klines_data = _stub_load_klines_data
rb.save_to_csv = lambda *a, **kw: None

if __name__ == "__main__":
    rb.main()
