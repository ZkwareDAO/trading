---
name: trading-dev
description: "CTA 量化策略开发全生命周期 skill（Python/Rust；crypto/期货，期货仅 Rust）。用于创建新 CTA/加密/期货交易策略、运行回测、生成 benchmark、或创建策略脚手架项目。期货不提供下载，K 线路径必须由用户提供。"
---

# Trading Dev — CTA 策略开发全生命周期

脚手架 → 策略编码 → 回测验证 → benchmark 输出，loop-engineering 跨 Phase 大闭环。

## 何时激活

- 用户提到创建新的 CTA/加密交易策略
- 用户想要创建策略项目脚手架
- 用户想要运行回测或 benchmark
- 用户输入 `$trading-dev` 或 `/prompts:trading-dev`
- 任务涉及量化策略开发

## 三种模式

| 模式 | 触发方式 | 行为 |
|------|---------|------|
| 全自动 | `$trading-dev new --from <source>` | 零交互端到端执行 |
| 交互 | `$trading-dev new` | 逐步确认 |
| 单步 | `$trading-dev scaffold/develop/backtest/benchmark` | 只执行指定 Phase |

## Loop-Engineering

Phase 2（策略开发）和 Phase 3（回测验证）形成跨 Phase 大闭环：
- 回测指标未达标 → 自动返回 Phase 2
- 修改策略逻辑 → 重新运行 Phase 3
- 循环直到达标或达到最大轮次

## 语言与市场（先定）

| 维度 | 取值 | 影响 |
|------|------|------|
| `STRATEGY_LANG` | `python`（默认）/ `rust` | 模板仓库、脚手架目录、代码文件、回测命令 |
| `STRATEGY_MARKET` | `crypto`（默认）/ `futures` | 数据获取、合约口径、配置体系 |

- **期货（仅 Rust）**：不执行任何下载命令；必须先拿到用户提供的 1m K 线路径
  （逐合约 CSV 目录或已生成 CSV）。`config/contracts.yaml` 必须声明品种，
  并显式配置 `initial_cash`；缺失即停止，不得用 mock/其他品种顶替。
- Rust 模板以 `strategy-template-rs` workspace 为准；`config/<group>/strategy.yaml`
  + `config/contracts.yaml` + `docs/strategy/` 规范集。

## Phase 流程

### Phase 0: 主机级环境预检
- Python 模式：Python 3.10+、pip、ta-lib（可选）。
- Rust 模式：`cargo`/`rustc`（以 `rust-toolchain.toml` 为准）。
- crypto 在 Phase 1 Step 3 自动下载；期货必须用户给 K 线路径（Phase 0 阻塞）。
- 项目级检查（`cargo metadata`、`contracts.yaml`）在 Phase 1 复制模板后执行。
- 收集策略规格（含 `market`/`data_source`/`backtest`；Python 落 `strategies/{name}/`，
  Rust 落 `docs/strategy/specs/`）。

### Phase 1: 脚手架
- Python：复制 `strategy_core/`、`backtest/`、`data_manager/`、`scripts/`、`config/`、`docs/`。
- Rust：镜像复制 workspace（`crates/*`、`config/`、`scripts/`、`docs/`），
  复制后先 `cargo metadata` 校验 workspace、期货校验 `contracts.yaml`，
  再 `cargo fetch` + 基线 `fmt/clippy/test`，从 `_global.example.yaml` 生成本地 `_global.yaml`。
- 数据：crypto symlink/下载；期货按用户路径落位（`roll_build` 或直接复制）。

### Phase 2: 策略开发
- 先读对应语言的规范文档与参考实现，只实现用户逻辑。
- Python：`strategies/{name}/strategy.py` + `{prefix}_core.py` + overrides + 测试。
- Rust：`crates/strategies/src/{name}.rs`（`Params` + `CrossSectionalStrategyPort` +
  `register_strategy!` + `#[cfg(test)]`）+ `config/<group>/strategy.yaml` + spec；
  不改 `build.rs`/`registry.rs`/`lib.rs`。

### Phase 3: 回测验证
- Python：`scripts/run_backtest_batch.sh`（短期/中期/长期，只换 `--start/--end`）。
- Rust：`cargo run -p strategy-app -- backtest --config config/<group>/strategy.yaml
  --start ... --end ...`；批量用 `scripts/run_backtest_matrix.sh`。
- 输出 `backtest_result.json` 的 `metrics`；期货区间必须落在用户数据覆盖范围内。
- 未达标 → 回到 Phase 2（每轮只改一个主维度）。

### Phase 4: Benchmark 输出（主流程的 Phase 3 Step 5）
- 生成结构化 benchmark 报告
- 输出为 markdown 含指标摘要

## 命令速查

```
$trading-dev new                          → 交互式全流程
$trading-dev new --from <file|url|desc>   → 全自动从来源
$trading-dev scaffold                     → 仅 Phase 1
$trading-dev develop                      → 仅 Phase 2
$trading-dev backtest                     → 仅 Phase 3
$trading-dev benchmark                    → 仅 Phase 4
```
