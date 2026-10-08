# 策略开发指南

**版本**: 3.7.0
**更新日期**: 2026-05-29

> 本文档是策略开发的入门概览。详细开发规范请参考 [docs/strategy/](../docs/strategy/) 目录。

## 参考实现（reference implementation）

**[`example_ma_cross/`](example_ma_cross/) 是本项目的参考实现。新增策略前先完整读一遍，再照着改。**

双均线交叉 + 固定止损，纯 pandas 无 talib 依赖。交易逻辑故意做得很笨——它的用途是把
**框架契约**演示清楚：那些骨架模板里看不出来、写错了又不会报错、只会静默不发信号的约定。
代码里标 ★ 的注释就是重点。

```
example_ma_cross/strategy.py               # 单周期：Strategy 接口层（最简形态，不重写 on_kline）
example_ma_cross/example_ma_cross_core.py  # 单周期：完整入场分支 + 出场 + State
example_ma_cross/overrides/BTCUSDT.yaml    # per-symbol 配置，字段逐条带注释
example_ma_cross/tests/                    # 新策略该测什么的清单

example_mtf_trend/                         # 多周期参考：1d 定方向 + 4h 触发 + 1h RSI 确认
```

> 策略是多周期的（常态）？再读 `example_mtf_trend/`：它演示每个周期分别
> `get_closed_data()` + 单独数据检查的标准写法。

按"我要写什么"查代码的地图见
[QUICKSTART.md → Step 0](../docs/strategy/QUICKSTART.md#step-0先完整读一遍参考实现必做)。

## 快速开始

### 1. 读参考实现

```bash
less strategies/example_ma_cross/example_ma_cross_core.py
python3 -m pytest strategies/example_ma_cross/tests/ -v   # 确认它是活的
```

### 2. 创建策略目录

```bash
mkdir -p strategies/my_strategy/overrides strategies/my_strategy/tests
touch strategies/my_strategy/__init__.py strategies/my_strategy/strategy.py
```

> **策略目录内不放 `config.yaml`**。配置分两处：
> `config/strategies.yaml`（登记表：`symbols` + `trading_mode`）和
> `strategies/my_strategy/overrides/<SYMBOL>.yaml`（per-symbol 参数，唯一事实来源）。

### 3. 实现 Strategy 与 Core 类

参考 [策略开发规范](../docs/strategy/DEVELOPMENT_GUIDE.md) 和 [快速入门](../docs/strategy/QUICKSTART.md)。

### 4. 创建配置文件

在 `config/strategies.yaml` 登记策略，并为每个标的创建
`strategies/my_strategy/overrides/<SYMBOL>.yaml`，模板见
[快速入门](../docs/strategy/QUICKSTART.md)。

### 5. 测试验证

```bash
# 测试导入
python3 -c "from strategies.my_strategy.strategy import Strategy; print('OK')"

# 跑策略自己的测试
python3 -m pytest strategies/my_strategy/tests/ -v

# 回测验证
python -m backtest.run_backtest --strategies my_strategy:BTCUSDT --start 20260610 --end 20260708
```

## 参考文档

| 文档 | 用途 |
|------|------|
| [快速入门](../docs/strategy/QUICKSTART.md) | 新策略开发第一步 |
| [开发规范](../docs/strategy/DEVELOPMENT_GUIDE.md) | 基类功能、平仓、冷却等规范 |
| [AI 编码约束](../docs/strategy/AI_CONSTRAINTS.md) | AI 辅助开发时的硬性规则 |
| [FAQ](../docs/strategy/EXAMPLES.md) | 常见问题、踩坑排查（可复制代码看两个参考实现） |
| [研发检查表](../docs/strategy/REVIEW_CHECKLIST.md) | 提交前自查 |
| [信号格式规范](../docs/SIGNAL_CSV_FORMAT.md) | 信号输出格式（含 `action` 合法取值） |
