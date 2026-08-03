---
name: trading-dev
description: "CTA quantitative strategy development lifecycle skill. Use when creating new CTA/crypto trading strategies, running backtests, generating benchmarks, or scaffolding strategy projects."
---

# Trading Dev — CTA Strategy Development Lifecycle

Scaffold → strategy coding → backtest verification → benchmark output, with loop-engineering cross-phase closure.

## When to Activate

- User mentions creating a new CTA/crypto trading strategy
- User wants to scaffold a strategy project
- User wants to run backtests or benchmarks
- User types `$trading-dev` or `/prompts:trading-dev`
- Task involves quantitative strategy development

## Three Modes

| Mode | Trigger | Behavior |
|------|---------|----------|
| Full-auto | `$trading-dev new --from <source>` | Zero-interaction end-to-end |
| Interactive | `$trading-dev new` | Step-by-step confirmation |
| Single-step | `$trading-dev scaffold/develop/backtest/benchmark` | Execute one phase only |

## Loop-Engineering

Phase 2 (strategy development) and Phase 3 (backtest verification) form a cross-phase loop:
- Backtest metrics below target → auto-return to Phase 2
- Modify strategy logic → re-run Phase 3
- Loop until target met or max iterations reached

## Phases

### Phase 0: Environment Pre-check
- Verify Python 3.10+, ta-lib, data availability
- Collect strategy specification

### Phase 1: Scaffold
- Create project directory structure
- Copy templates (strategy_core, backtest, data_manager, scripts)
- Generate config files

### Phase 2: Strategy Development
- Generate strategy code from specification
- Implement indicators, entry/exit signals, risk management
- Write unit tests

### Phase 3: Backtest Verification
- Run backtest with generated config
- Analyze results (total return, Sharpe, max drawdown)
- If below target → loop back to Phase 2

### Phase 4: Benchmark Output
- Generate structured benchmark report
- Output to markdown with metrics summary

## Commands Quick Reference

```
$trading-dev new                          → Interactive full pipeline
$trading-dev new --from <file|url|desc>   → Full-auto from source
$trading-dev scaffold                     → Phase 1 only
$trading-dev develop                      → Phase 2 only
$trading-dev backtest                     → Phase 3 only
$trading-dev benchmark                    → Phase 4 only
```
