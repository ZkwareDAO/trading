#!/usr/bin/env python3
"""从 Go 项目数据源加载 ETHUSDT 1m 数据并保存到回测目录。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_manager.klines_loader import load_klines_data, save_to_csv

df = load_klines_data(
    symbol="ethusdt",
    start_date="2025-01-01",
    end_date="2026-03-31",
    frequency="1m",
    instrument_type="um",
)

if df.empty:
    print("错误：未能加载任何数据", file=sys.stderr)
    sys.exit(1)

save_to_csv(df, symbol="ETHUSDT", frequency="1m", output_dir="./data/klines",
           exchange="binance", instrument_type="um")
print(f"完成：已保存 {len(df)} 条记录")
