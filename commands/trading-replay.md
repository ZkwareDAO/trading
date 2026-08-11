---
name: trading-replay
description: 每日策略代码备份 + 回放回测 skill。从实盘机器 SCP 拉取策略代码快照，按日期/策略/模型执行回测，输出回测结果。
---

Execute the trading-replay skill with the user's arguments. Route to the SKILL.md at `trading-replay-skill/SKILL.md` for full phase definitions and behavior.

## Quick Reference

| Command | Description |
|---------|-------------|
| `/trading-replay run` | Execute full daily flow (sync + replay) |
| `/trading-replay run --date YYYYMMDD` | Execute for specified date |
| `/trading-replay sync` | Strategy code backup only (sync-exee.py) |
| `/trading-replay sync --date YYYYMMDD` | Backup to specified date directory |
| `/trading-replay replay` | Replay backtest only (replay.sh) |
| `/trading-replay replay --date YYYYMMDD` | Replay specified date snapshot |
| `/trading-replay summary` | View latest replay results summary |
| `/trading-replay summary --date YYYYMMDD` | View specified date summary |

Pass any arguments after `/trading-replay` directly to the skill execution.
