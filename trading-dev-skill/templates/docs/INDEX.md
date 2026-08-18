# Strategy Core 文档索引

**版本**: 3.7.0
**更新日期**: 2026-08-17

---

## 快速导航

### 新手入门
1. [README.md — 快速开始（开箱即用）](../README.md#快速开始开箱即用) - **唯一开箱入口**：安装 → 用自带示例数据跑通回测
2. [docs/strategy/QUICKSTART.md](strategy/QUICKSTART.md) - 策略开发第一步（新增策略时看）

> 开箱步骤只在 README 维护一份，不另设 `docs/QUICKSTART.md`——避免两处说明各自过期。

### 深入理解
1. [ARCHITECTURE.md](../ARCHITECTURE.md) - 系统架构详细文档
2. [docs/SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) - 系统概览和数据流
3. [data_manager/README.md](../data_manager/README.md) - 数据管理器使用指南

### 策略开发
1. [docs/strategy/DEVELOPMENT_GUIDE.md](strategy/DEVELOPMENT_GUIDE.md) - 开发规范
2. [docs/strategy/AI_CONSTRAINTS.md](strategy/AI_CONSTRAINTS.md) - AI 编码约束
3. [docs/strategy/EXAMPLES.md](strategy/EXAMPLES.md) - 参考示例
4. [docs/strategy/REVIEW_CHECKLIST.md](strategy/REVIEW_CHECKLIST.md) - 研发检查表

### 技术规范
1. [docs/CONFIG_UNIFICATION_SPEC.md](CONFIG_UNIFICATION_SPEC.md) - **配置三层模型与回测实盘统一规范（P0）**
2. [docs/SIGNAL_CSV_FORMAT.md](SIGNAL_CSV_FORMAT.md) - 信号格式规范
3. [docs/claude/operations.md](claude/operations.md) - 配置格式、数据完整性

### 运维参考
1. [docs/SCRIPTS.md](SCRIPTS.md) - 脚本参考（所有 CLI 命令与参数）
2. [backtest/README.md](../backtest/README.md) - 回测框架（含成交模型简化说明）

---

## 文档清单

### 根目录
- [CLAUDE.md](../CLAUDE.md) - Claude Code 指导
- [README.md](../README.md) - 项目 README
- [LICENSE](../LICENSE) - Apache-2.0 许可证
- [CONTRIBUTING.md](../CONTRIBUTING.md) - 贡献指南
- [ARCHITECTURE.md](../ARCHITECTURE.md) - 系统架构文档
- [CHANGELOG.md](../CHANGELOG.md) - 变更日志

### docs/ 目录
- [INDEX.md](INDEX.md) - 文档索引（本文档）
- [SYSTEM_OVERVIEW.md](SYSTEM_OVERVIEW.md) - 系统概览
- [SIGNAL_CSV_FORMAT.md](SIGNAL_CSV_FORMAT.md) - 信号格式规范
- [SCRIPTS.md](SCRIPTS.md) - 脚本参考
- [CONFIG_UNIFICATION_SPEC.md](CONFIG_UNIFICATION_SPEC.md) - 配置三层模型与回测实盘统一规范
- [OPEN_SOURCE_CONFIG_CI.md](OPEN_SOURCE_CONFIG_CI.md) - 配置收敛与 CI 方案
- [archive/](archive/) - 归档历史文件
- [claude/architecture.md](claude/architecture.md) - 架构参考
- [claude/operations.md](claude/operations.md) - 运维参考

### docs/strategy/ 目录
- [README.md](strategy/README.md) - 策略文档索引
- [QUICKSTART.md](strategy/QUICKSTART.md) - 快速入门
- [DEVELOPMENT_GUIDE.md](strategy/DEVELOPMENT_GUIDE.md) - 开发规范
- [AI_CONSTRAINTS.md](strategy/AI_CONSTRAINTS.md) - AI 编码约束
- [EXAMPLES.md](strategy/EXAMPLES.md) - 参考示例
- [REVIEW_CHECKLIST.md](strategy/REVIEW_CHECKLIST.md) - 研发检查表

### strategies/ 目录
- [README.md](../strategies/README.md) - 策略开发入门指南

### data_manager/ 目录
- [README.md](../data_manager/README.md) - 使用指南
- [ARCHITECTURE.md](../data_manager/ARCHITECTURE.md) - 架构文档
- [KLINE_REPOSITORY.md](../data_manager/KLINE_REPOSITORY.md) - K 线仓库设计

### 其他模块
- [backtest/README.md](../backtest/README.md) - 回测框架

---

## 文档维护原则

1. **单一事实源**: 每个主题只在一个地方维护，避免重复
2. **代码即文档**: 优先通过代码注释和类型注解表达意图
3. **及时更新**: 修改代码时同步更新相关文档
