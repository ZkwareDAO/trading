# 策略开发指南

**版本**: 3.7.0
**更新日期**: 2026-05-29

> 本文档是策略开发的入门概览。详细开发规范请参考 [docs/strategy/](../docs/strategy/) 目录。

## 快速开始

### 1. 创建策略目录

```bash
mkdir -p strategies/my_strategy
cd strategies/my_strategy
touch __init__.py strategy.py config.yaml
```

### 2. 实现 Strategy 类

参考 [策略开发规范](../docs/strategy/DEVELOPMENT_GUIDE.md) 和 [快速入门](../docs/strategy/QUICKSTART.md)。

### 3. 创建配置文件

在策略目录内创建 `config.yaml`，参考 [快速入门](../docs/strategy/QUICKSTART.md) 中的配置模板。

### 4. 测试验证

```bash
# 测试导入
python3 -c "from strategies.my_strategy.strategy import Strategy; print('OK')"

# 测试完整功能
python3 test_full_framework.py
```

## 参考文档

| 文档 | 用途 |
|------|------|
| [快速入门](../docs/strategy/QUICKSTART.md) | 新策略开发第一步 |
| [开发规范](../docs/strategy/DEVELOPMENT_GUIDE.md) | 基类功能、平仓、冷却等规范 |
| [AI 编码约束](../docs/strategy/AI_CONSTRAINTS.md) | AI 辅助开发时的硬性规则 |
| [参考示例](../docs/strategy/EXAMPLES.md) | 代码模板和 FAQ |
| [研发检查表](../docs/strategy/REVIEW_CHECKLIST.md) | 提交前自查 |
| [信号格式规范](../docs/SIGNAL_CSV_FORMAT.md) | 信号输出格式 |
