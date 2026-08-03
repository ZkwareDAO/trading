---
name: trading-dev
description: "CTA 量化策略开发全生命周期 skill。用于创建新 CTA/加密交易策略、运行回测、生成 benchmark、或创建策略脚手架项目。"
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

## Phase 流程

### Phase 0: 环境预检
- 验证 Python 3.10+、ta-lib、数据可用性
- 收集策略规格信息

### Phase 1: 脚手架
- 创建项目目录结构
- 复制模板（strategy_core、backtest、data_manager、scripts）
- 生成配置文件

### Phase 2: 策略开发
- 根据规格生成策略代码
- 实现指标、入场/出场信号、风控
- 编写单元测试

### Phase 3: 回测验证
- 使用生成的配置运行回测
- 分析结果（总收益、夏普比率、最大回撤）
- 未达标 → 回到 Phase 2

### Phase 4: Benchmark 输出
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
