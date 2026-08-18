# 策略文档索引

> **版本**: 3.7.0 | **更新日期**: 2026-05-29

本目录包含 CTA 策略开发的完整文档，按用途拆分为多个独立文件，便于 AI 上下文加载和人工查阅。

---

## 文档列表

| 文件 | 定位 | 适用场景 |
|------|------|----------|
| [QUICKSTART.md](QUICKSTART.md) | 快速入门 | 新策略开发第一步 |
| [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | 开发规范 | 编写/修改策略代码时查阅 |
| [REVIEW_CHECKLIST.md](REVIEW_CHECKLIST.md) | 研发检查表 | 提交前自查、代码审查 |
| [AI_CONSTRAINTS.md](AI_CONSTRAINTS.md) | AI 编码约束 | AI 辅助开发时的硬性规则 |
| [EXAMPLES.md](EXAMPLES.md) | 参考示例 | 代码模板、常见问题 FAQ |

---

## 使用指南

### 按角色选择文档

| 角色 | 推荐阅读 |
|------|----------|
| **新策略开发者** | QUICKSTART → DEVELOPMENT_GUIDE → EXAMPLES |
| **代码审查者** | REVIEW_CHECKLIST |
| **AI 辅助开发** | AI_CONSTRAINTS（作为 system prompt 加载） |
| **日常开发查询** | DEVELOPMENT_GUIDE |

### 按场景选择

| 场景 | 推荐文档 |
|------|----------|
| 创建新策略 | QUICKSTART + EXAMPLES |
| 修改已有策略 | DEVELOPMENT_GUIDE |
| 提交前检查 | REVIEW_CHECKLIST |
| AI 编码约束 | AI_CONSTRAINTS |
| 查询代码模板 | EXAMPLES |

---

## 架构版本

当前推荐使用 **新架构（BaseStrategy 基类继承）**，strategy.py 仅需 ~35 行。

旧架构策略可保持不变，新策略统一使用新架构。
