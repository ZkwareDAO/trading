# CLAUDE.md

CTA Strategy Core v3.7.0 - 模块化量化交易策略执行框架，**平台 + 插件**架构。每个策略独立进程，由 `cta-factory-service` 管理。

## 运行命令

```bash
pip install -r requirements.txt -r requirements-dev.txt            # 安装依赖（运行时 + 测试）
python3 run_strategies_manager.py                                  # 启动策略管理器
python3 run_strategy.py --name cta_ict_v3 --symbol BTCUSDT --interval 4h --version v2 --trading-mode live
python3 -m pytest data_manager/tests/ -v                           # 数据管理器测试
python -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260610 --end 20260708
```

## 核心架构

- **入口**: `run_strategies_manager.py` → factory 回调 → `run_strategy.py` 独立进程
- **策略基类**: `BaseStrategy` / `BaseStrategyCore` / `BaseState`（`strategy_core/base/`），新增策略只需实现 `analyze()` + `check_realtime_exit()`
- **数据层**: `data_manager/`（CSV + WS + 缓存 + 多时间框架聚合 + 指标计算）
- **信号层**: `strategy_core/signal_logging/`（CSV 持久化 + Kafka/HTTP 推送）
- **配置**: `config/settings.yaml`（系统 + 策略列表），`strategies/{name}/config.yaml`（策略配置）

## 开发指南（按场景）

| 场景 | 必读文档 |
|------|----------|
| 新增策略 | [docs/strategy/QUICKSTART.md](docs/strategy/QUICKSTART.md) → [DEVELOPMENT_GUIDE.md](docs/strategy/DEVELOPMENT_GUIDE.md) |
| 修改策略逻辑 | [docs/strategy/DEVELOPMENT_GUIDE.md](docs/strategy/DEVELOPMENT_GUIDE.md) |
| 提交前检查 | [docs/strategy/REVIEW_CHECKLIST.md](docs/strategy/REVIEW_CHECKLIST.md) |
| AI 辅助编码 | [docs/strategy/AI_CONSTRAINTS.md](docs/strategy/AI_CONSTRAINTS.md)（**必须遵守**） |
| 架构/设计决策 | [docs/claude/architecture.md](docs/claude/architecture.md) |
| 配置/信号格式/数据完整性 | [docs/claude/operations.md](docs/claude/operations.md) |

## 编码红线（来自 AI_CONSTRAINTS.md，完整版见链接）

- **禁止**在入场判断中使用未闭合 K 线（未来函数，回测失真）
- **禁止**使用 `datetime.now()` 作为信号时间戳（用 K 线时间，保证可重现）
- **禁止**在 Strategy 类中计算技术指标（指标在 Core.analyze() 内用已闭合 K 线计算）
- **禁止**跳过数据不足检查
- **禁止**在回测模式启用 K 线冷却
- **禁止**在 State 中使用可变默认值（`[]`, `{}`共享状态，用 `field(default_factory=list)`）
- **禁止**缓存字段写入 to_persist_dict()（缓存不持久化）
- **禁止**多周期策略直接用原始 K 线入场（必须对每个时间框架调用 `get_closed_data()`）
- **禁止**自定义止损计数字段（使用 BaseState.stop_loss_date）

## Skills（AI 辅助工具）

项目自定义 skills 位于 `skills/` 目录，提供 AI 辅助开发工具：

| Skill | 功能 | 调用方式 |
|-------|------|----------|
| 策略开发 | 一站式策略开发（逻辑确认 + 代码生成） | `/zk_cta-strategy-dev` |
| 策略逻辑确认 | 输出策略规格文件 | `/zk_cta-strategy-logic-refine` |
| 策略实现 | 根据规格文件生成代码 | `/zk_cta-strategy-implement` |
| 回测执行 | 对话式回测，支持参数修改 | `/zk_cta-backtest-run` |
| 回测配置 | 快速新增/复制策略配置 | `/zk_cta-backtest-config` |
| 信号回放 | 实盘信号与回测信号对比 | `/zk_cta-signal-replay` |

## 六大规则
- 修bug主动检查相关代码
- 编辑后跑类型检查
- 回复简洁不废话
- 大改动先输出计划
- 不确定主动说
- 新功能必须有测试
