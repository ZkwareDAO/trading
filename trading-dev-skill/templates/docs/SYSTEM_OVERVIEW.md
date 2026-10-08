# CTA Strategy Core 系统概览

**版本**: 3.7.0
**更新日期**: 2026-09-06

> 详细架构信息请参考 [ARCHITECTURE.md](../ARCHITECTURE.md)。

---

## 系统简介

Strategy Core 是模块化量化交易策略执行框架，**单体模式**，直连 Binance 行情与下单。

**核心能力**:
- 多策略独立进程并行运行，run_strategies_manager 监督启停
- K 线数据单体直连 Binance（公共 WS 实时 + fapi 历史）+ 多时间框架自动聚合
- 信号 CSV 持久化 + 直连交易所下单
- 仓位持久化，策略重启后自动恢复
- BaseStrategy 三层基类，新增策略只需实现入场/出场逻辑

---

## 系统架构概览

```
┌──────────────────────────────────────────────────────────────────┐
│              run_strategies_manager.py (进程监督者)               │
│  解析策略清单 → 启动 run_strategy.py 独立子进程 → 监控退出        │
└──────────────────────────┬───────────────────────────────────────┘
                           │ 每策略独立进程
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                     run_strategy.py (策略进程)                     │
│  ┌─────────────────────┐ ┌─────────────────────┐                │
│  │SignalLogger         │ │BaseStrategy         │                │
│  │(CSV+直连下单)       │ │(基类+分发)          │                │
│  └─────────────────────┘ └──────────┬──────────┘                │
│  ┌──────────────────────────────────────┴───────────────────┐    │
│  │       DataManager (CSV + Binance WS + 缓存 + 聚合)        │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
         │                              │                    │
         ▼                              ▼                    ▼
  data/signals/                        data/klines/
  (信号CSV)                            (K线CSV)
                                                         ↑
                                                  Binance 公共源
                                                  (WS实时推送)
```

---

## 数据流

```
Binance 公共 WS 推送 / fapi REST 轮询
    ↓
DataManager 刷新缓存 + 多时间框架聚合
    ↓
get_klines() 增量返回新K线
    ↓
BaseStrategy 分发到策略 Core
    ↓
Core.analyze() 入场 / Core.check_realtime_exit() 出场
    ↓
Signal → SignalLogger → CSV 存储 + direct_trader 直连下单
```

---

## 核心组件

| 组件 | 入口文件 | 职责 |
|------|----------|------|
| 策略管理器 | `run_strategies_manager.py` | 解析策略清单、拉起/监控子进程、优雅停止 |
| 策略进程 | `run_strategy.py` | 独立进程运行单个策略 |
| 策略基类 | `strategy_core/base/` | BaseStrategy/Core/State 三层基类 |
| 策略参数构建 | `strategy_core/signal_logging/signal_params.py` | overrides 配置 → CtaSignalCSV 参数 |
| 数据管理 | `data_manager/` | CSV+WS 数据接入、缓存、聚合、指标 |
| 信号日志 | `strategy_core/signal_logging/` | CSV 持久化、直连下单 |
| 仓位持久化 | `strategy_core/position_persistence.py` | JSON 文件存储仓位状态 |
| 回测框架 | `backtest/` | backtrader 集成、批量回测、分析报告 |

---

## 已实现策略

<!-- AUTO-GENERATED: strategy-list — do not edit manually, update from strategies/ directory -->

| 策略 | 基类架构 | 时间周期 | 多标的 |
|------|----------|----------|--------|
| sar_snt3_v3 | ✅ BaseStrategyCore | 1m→多周期 | ✅ |

> 模板仓库只保留 sar_snt3_v3 一个参考实现（历史版本含 20+ 策略，开源时移除）。
> 新增策略后请同步更新本表（生成源：`strategies/` 目录）。

<!-- /AUTO-GENERATED -->

---

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| 策略加载失败 | 检查策略目录是否有 strategy.py |
| 信号未生成 | 检查日志确认 K 线更新、信号强度阈值 |
| 实时数据中断 | Binance 公共 WS 自动重连（退避上限 120s）+ fapi REST 轮询回退，检查网络/代理 |
| 仓位未恢复 | 检查 data/positions/ 下 JSON 文件 |
| 下单失败 | 检查进程日志；确认凭证、网络/代理、单向持仓模式 |
