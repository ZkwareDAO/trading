---
name: trading-dev
description: CTA 策略开发全生命周期 skill。支持交互/全自动/单步三种模式。一句话输入策略逻辑 → 自动脚手架 → 策略编码 → 回测验证 → benchmark 输出。
---

Execute the trading-dev skill with the user's arguments. Route to the SKILL.md at `trading-dev-skill/SKILL.md` for full phase definitions and behavior.

## Quick Reference

| Command | Mode | Description |
|---------|------|-------------|
| `/trading-dev new` | Interactive | Step-by-step strategy project creation |
| `/trading-dev new --from <source>` | Full-auto | Zero-interaction from file/URL/description |
| `/trading-dev new <description>` | Full-auto | From natural language description |
| `/trading-dev scaffold` | Single-step | Scaffold only (Phase 1) |
| `/trading-dev develop` | Single-step | Strategy coding only (Phase 2) |
| `/trading-dev backtest` | Single-step | Backtest verification only (Phase 3) |
| `/trading-dev benchmark` | Single-step | Benchmark report only (Phase 3 Step 5) |

Pass any arguments after `/trading-dev` directly to the skill execution.
