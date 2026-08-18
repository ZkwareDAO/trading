---
name: trading-discovery
description: 指定代币/策略/时间范围的回测探索 skill。支持多代币×多策略×自定义时间范围组合回测，输出对比报告。
---

Execute the trading-discovery skill with the user's arguments. Route to the SKILL.md at `trading-discovery-skill/SKILL.md` for full phase definitions and behavior.

## Quick Reference

| Command | Description |
|---------|-------------|
| `/trading-discovery run --symbols S1,S2 --strategies ST1,ST2 --start DATE --end DATE` | Run discovery backtest with specified symbols, strategies, and date range |
| `/trading-discovery run --all-strategies --symbols S1,S2 --start DATE` | All strategies × specified symbols |
| `/trading-discovery compare --date YYYYMMDD` | View discovery results comparison |
| `/trading-discovery report --date YYYYMMDD` | Generate discovery comparison report |

Time format: `YYYYMMDD` (e.g. `20260601`) or Unix timestamp (e.g. `1748736000`).

Pass any arguments after `/trading-discovery` directly to the skill execution.
