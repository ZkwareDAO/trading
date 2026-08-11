---
name: trading-deploy
description: 策略部署上线 skill。git pull 拉取策略代码 → AI 分析 → WebSocket 验证 → K线准备 → 启动策略。
---

Execute the trading-deploy skill at `trading-deploy-skill/SKILL.md`.

## Quick Reference

| Command | Description |
|---------|-------------|
| `/trading-deploy run` | Full deployment (Phase 0→5) |
| `/trading-deploy run --strategy NAME` | Deploy specified strategy |
| `/trading-deploy run --git-url URL` | Deploy from git URL |
| `/trading-deploy analyze` | Analyze strategy only (Phase 2) |
| `/trading-deploy prepare-data` | Prepare K-line data only (Phase 3) |
| `/trading-deploy start --strategy NAME` | Start strategy only (Phase 5) |
| `/trading-deploy status` | View running strategy status |
