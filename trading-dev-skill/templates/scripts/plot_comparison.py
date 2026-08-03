#!/usr/bin/env python3
"""
绘制 BTC 价格与 ETH 回测权益曲线对比图
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

# 读取 BTC 日线数据
btc_df = pd.read_csv('data/strategies/1d/BTCUSDT_1d.csv')
btc_df['timestamp'] = pd.to_datetime(btc_df['timestamp']).dt.tz_localize(None)
btc_df = btc_df.sort_values('timestamp')

# 读取权益曲线 - 2025-01-01 ~ 2026-05-22
equity_long = pd.read_csv('backtest_output/cta_rbreaker_v2/20260522/backtest_cta_rbreaker_v2_ETHUSDT_20260522_135629_equity.csv')
equity_long['date'] = pd.to_datetime(equity_long['date'])

# 读取权益曲线 - 2026-01-01 ~ 2026-05-22
equity_short = pd.read_csv('backtest_output/cta_rbreaker_v2/20260522/backtest_cta_rbreaker_v2_ETHUSDT_20260522_140254_equity.csv')
equity_short['date'] = pd.to_datetime(equity_short['date'])

# 创建图表
fig, axes = plt.subplots(3, 1, figsize=(14, 12), sharex=True)

# 图1: BTC 价格走势
ax1 = axes[0]
ax1.plot(btc_df['timestamp'], btc_df['close'], 'b-', linewidth=1.5, label='BTC Price')
ax1.set_ylabel('BTC Price (USDT)', fontsize=12)
ax1.set_title('BTCUSDT Daily Price', fontsize=14, fontweight='bold')
ax1.legend(loc='upper left')
ax1.grid(True, alpha=0.3)
ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:,.0f}'))

# 图2: ETH 回测权益曲线 (17个月)
ax2 = axes[1]
ax2.plot(equity_long['date'], equity_long['equity'], 'g-', linewidth=1.5, label='Equity (2025-01-01 ~ 2026-05-22)')
ax2.axhline(y=100000, color='gray', linestyle='--', alpha=0.5, label='Initial Capital')
ax2.fill_between(equity_long['date'], 100000, equity_long['equity'],
                  where=equity_long['equity'] >= 100000, alpha=0.3, color='green')
ax2.fill_between(equity_long['date'], 100000, equity_long['equity'],
                  where=equity_long['equity'] < 100000, alpha=0.3, color='red')
ax2.set_ylabel('Equity (USDT)', fontsize=12)
ax2.set_title('ETHUSDT Backtest Equity - 17 Months (11.82% Return, 47.16% Max Drawdown)', fontsize=14, fontweight='bold')
ax2.legend(loc='upper left')
ax2.grid(True, alpha=0.3)
ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:,.0f}'))

# 标注关键点
max_equity_long = equity_long['equity'].max()
max_date_long = equity_long.loc[equity_long['equity'].idxmax(), 'date']
min_equity_long = equity_long['equity'].min()
min_date_long = equity_long.loc[equity_long['equity'].idxmin(), 'date']
ax2.annotate(f'Peak: {max_equity_long:,.0f}', xy=(max_date_long, max_equity_long),
             xytext=(10, 10), textcoords='offset points', fontsize=9, color='green')
ax2.annotate(f'Trough: {min_equity_long:,.0f}', xy=(min_date_long, min_equity_long),
             xytext=(10, -20), textcoords='offset points', fontsize=9, color='red')

# 图3: ETH 回测权益曲线 (5个月)
ax3 = axes[2]
ax3.plot(equity_short['date'], equity_short['equity'], 'purple', linewidth=1.5, label='Equity (2026-01-01 ~ 2026-05-22)')
ax3.axhline(y=100000, color='gray', linestyle='--', alpha=0.5, label='Initial Capital')
ax3.fill_between(equity_short['date'], 100000, equity_short['equity'],
                  where=equity_short['equity'] >= 100000, alpha=0.3, color='green')
ax3.fill_between(equity_short['date'], 100000, equity_short['equity'],
                  where=equity_short['equity'] < 100000, alpha=0.3, color='red')
ax3.set_ylabel('Equity (USDT)', fontsize=12)
ax3.set_xlabel('Date', fontsize=12)
ax3.set_title('ETHUSDT Backtest Equity - 5 Months (21.84% Return, 20.64% Max Drawdown)', fontsize=14, fontweight='bold')
ax3.legend(loc='upper left')
ax3.grid(True, alpha=0.3)
ax3.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:,.0f}'))

# 标注关键点
max_equity_short = equity_short['equity'].max()
max_date_short = equity_short.loc[equity_short['equity'].idxmax(), 'date']
min_equity_short = equity_short['equity'].min()
min_date_short = equity_short.loc[equity_short['equity'].idxmin(), 'date']
ax3.annotate(f'Peak: {max_equity_short:,.0f}', xy=(max_date_short, max_equity_short),
             xytext=(10, 10), textcoords='offset points', fontsize=9, color='green')
ax3.annotate(f'Trough: {min_equity_short:,.0f}', xy=(min_date_short, min_equity_short),
             xytext=(10, -20), textcoords='offset points', fontsize=9, color='red')

# 设置 x 轴格式
for ax in axes:
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m'))

plt.tight_layout()
plt.savefig('backtest_output/comparison_chart.png', dpi=150, bbox_inches='tight')
print(f"图表已保存到: backtest_output/comparison_chart.png")

# 打印统计信息
print("\n" + "="*60)
print("数据统计")
print("="*60)
print(f"\nBTC 价格范围: {btc_df['close'].min():,.0f} ~ {btc_df['close'].max():,.0f}")
print(f"BTC 数据时间: {btc_df['timestamp'].min()} ~ {btc_df['timestamp'].max()}")

print(f"\n17个月回测权益: {equity_long['equity'].min():,.0f} ~ {equity_long['equity'].max():,.0f}")
print(f"17个月回测时间: {equity_long['date'].min()} ~ {equity_long['date'].max()}")

print(f"\n5个月回测权益: {equity_short['equity'].min():,.0f} ~ {equity_short['equity'].max():,.0f}")
print(f"5个月回测时间: {equity_short['date'].min()} ~ {equity_short['date'].max()}")
