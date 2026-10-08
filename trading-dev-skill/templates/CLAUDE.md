# CLAUDE.md

CTA Strategy Core v3.7.0 - 模块化量化交易策略执行框架，**单体模式**。每个策略独立进程，直连 Binance 行情与下单（CCXT）。

## 运行命令

```bash
pip install -r requirements.txt -r requirements-dev.txt            # 安装依赖（运行时 + 测试）
python3 run_strategies_manager.py                                  # 启动策略管理器
python3 run_strategy.py --name example_ma_cross --symbol BTCUSDT --trading-mode live
python3 -m pytest data_manager/tests/ -v                           # 数据管理器测试
python -m backtest.run_backtest --strategies example_ma_cross:BTCUSDT --start 20260610 --end 20260708
```

## 核心架构

- **入口**: `run_strategies_manager.py`（进程监督者）→ `run_strategy.py` 独立进程
- **策略基类**: `BaseStrategy` / `BaseStrategyCore` / `BaseState`（`strategy_core/base/`），新增策略只需实现 `analyze()` + `check_realtime_exit()`
- **数据层**: `data_manager/`（CSV + WS + 缓存 + 多时间框架聚合 + 指标计算）
- **信号层**: `strategy_core/signal_logging/`（CSV 持久化 + 交易所直连下单）
- **配置**: `config/strategies.yaml`（策略登记表：symbols + trading_mode），`strategies/{name}/overrides/{SYMBOL}.yaml`（per-symbol 策略参数，**唯一事实来源**），`config/settings.yaml`（系统级配置）。**策略目录内不放 config.yaml**
- **参考实现**: [`strategies/example_ma_cross/`](strategies/example_ma_cross/) —— 新增策略前先完整读一遍，再照着改

## 开发指南（按场景）

| 场景 | 必读文档 |
|------|----------|
| 新增策略 | `strategies/example_ma_cross/`（参考实现，先读） → [docs/strategy/QUICKSTART.md](docs/strategy/QUICKSTART.md) → [DEVELOPMENT_GUIDE.md](docs/strategy/DEVELOPMENT_GUIDE.md) |
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
- **注意**：基类**没有**入场侧 K 线冷却 —— 无持仓时每根 1m K 线都会调 `analyze()`。需要"大周期收线才入场"必须自己重写 `on_kline()`；自己实现的冷却必须在回测模式跳过
- **禁止**在 State 中使用可变默认值（`[]`, `{}`共享状态，用 `field(default_factory=list)`）
- **禁止**缓存字段写入 to_persist_dict()（缓存不持久化）
- **禁止**多周期策略直接用原始 K 线入场（必须对每个时间框架调用 `get_closed_data()`）
- **禁止**自定义止损计数字段（使用 BaseState.stop_loss_date）

## Skills（AI 辅助工具，外部提供）

下列 `/zk_cta-*` 命令由**外部 skill 包**提供（全局插件方式安装，**不在本仓库的
`skills/` 目录内**——模板仓库不附带这些 skill）。命令在当前环境不可用时属正常情况，
直接按 `docs/strategy/` 的文档流程操作即可（规格文件格式见
[docs/strategy/STRATEGY_SPEC.md](docs/strategy/STRATEGY_SPEC.md)）：

| Skill | 功能 | 调用方式（需已安装外部 skill 包） |
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
