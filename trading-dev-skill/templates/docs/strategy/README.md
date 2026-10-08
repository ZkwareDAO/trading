# 策略文档索引

> **版本**: 3.7.0 | **更新日期**: 2026-09-10

本目录包含 CTA 策略开发的完整文档，按用途拆分为多个独立文件，便于 AI 上下文加载和人工查阅。

---

## 参考实现（reference implementation）

本项目自带两个参考实现，纯 pandas，逻辑故意做得很笨——用途是把**框架契约**演示清楚。
**新增策略前先完整读一遍，再照着改。**

| 参考实现 | 适用 |
|----------|------|
| [`strategies/example_ma_cross/`](../../strategies/example_ma_cross/) | 单周期入门：完整入场分支、止损、持久化 |
| [`strategies/example_mtf_trend/`](../../strategies/example_mtf_trend/) | **多周期（常见情形）**：1d+4h+1h 三周期共振 |

本目录的文档给的是占位符骨架和硬性规则，部分约定（`action` 取值、入场分支写法、
下单量字段）只存在于代码里。代码地图见 [QUICKSTART.md → Step 0](QUICKSTART.md#step-0先完整读一遍参考实现必做)。

---

## 文档列表

| 文件 | 定位 | 适用场景 |
|------|------|----------|
| [QUICKSTART.md](QUICKSTART.md) | 快速入门 | 新策略开发第一步 |
| [DEVELOPMENT_GUIDE.md](DEVELOPMENT_GUIDE.md) | 开发规范 | 编写/修改策略代码时查阅 |
| [REVIEW_CHECKLIST.md](REVIEW_CHECKLIST.md) | 研发检查表 | 提交前自查、代码审查 |
| [AI_CONSTRAINTS.md](AI_CONSTRAINTS.md) | AI 编码约束 | AI 辅助开发时的硬性规则 |
| [EXAMPLES.md](EXAMPLES.md) | 常见问题 FAQ | "为什么这么写"、踩坑排查；可复制代码看两个参考实现 |
| [STRATEGY_SPEC.md](STRATEGY_SPEC.md) | 策略规格 schema | 编写/生成 `.strategy-spec.yaml` 时查阅 |

---

## 使用指南

### 按角色选择文档

| 角色 | 推荐阅读 |
|------|----------|
| **新策略开发者** | `strategies/example_ma_cross/` → QUICKSTART → DEVELOPMENT_GUIDE → EXAMPLES |
| **代码审查者** | REVIEW_CHECKLIST |
| **AI 辅助开发** | AI_CONSTRAINTS（作为 system prompt 加载）+ `strategies/example_ma_cross/`（作为参考实现） |
| **日常开发查询** | DEVELOPMENT_GUIDE |

### 按场景选择

| 场景 | 推荐文档 |
|------|----------|
| 创建新策略 | `strategies/example_ma_cross/` + QUICKSTART + EXAMPLES |
| 修改已有策略 | DEVELOPMENT_GUIDE |
| 提交前检查 | REVIEW_CHECKLIST |
| AI 编码约束 | AI_CONSTRAINTS |
| 查询代码模板 | EXAMPLES |

---

## 配置位置

策略不使用目录内 `config.yaml`，配置分两处：

| 文件 | 内容 |
|------|------|
| `config/strategies.yaml` | 策略登记表：`symbols` + `trading_mode` |
| `strategies/<name>/overrides/<SYMBOL>.yaml` | per-symbol 周期、指标参数、资金、风控（唯一事实来源） |

## 架构

所有策略基于 **BaseStrategy 基类继承**：最简策略 strategy.py 约 35 行
（只实现 `_create_core()` + `_get_indicator_timeframes()`，不重写 `on_kline()`；
需要自定义 K 线闭合边界判断时可在子类重写）。
