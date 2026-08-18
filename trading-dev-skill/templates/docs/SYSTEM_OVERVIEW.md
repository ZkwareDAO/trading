# CTA Strategy Core 系统概览

**版本**: 3.7.0
**更新日期**: 2026-07-22

> 详细架构信息请参考 [ARCHITECTURE.md](../ARCHITECTURE.md)。

---

## 系统简介

Strategy Core 是模块化量化交易策略执行框架，**平台 + 插件**架构，与外部 `cta-factory-service` 配合工作。

**核心能力**:
- 多策略独立进程并行运行，factory 统一管理启停
- K 线数据 WS 实时推送 + CSV 轮询降级 + 多时间框架自动聚合
- 信号 CSV 持久化 + Kafka/HTTP 推送
- 仓位持久化，策略重启后自动恢复
- BaseStrategy 三层基类，新增策略只需实现入场/出场逻辑

---

## 系统架构概览

```
┌──────────────────────────────────────────────────────────────────┐
│              run_strategies_manager.py (管理器)                   │
│  注册策略 → factory 回调 → 启动 run_strategy.py 独立进程          │
└──────────────────────────┬───────────────────────────────────────┘
                           │ 每策略独立进程
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│                     run_strategy.py (策略进程)                     │
│  ┌────────────┐ ┌──────────────┐ ┌──────────────┐               │
│  │StrategyEngine│ │SignalLogger  │ │BaseStrategy  │               │
│  │(引擎+通信)  │ │(CSV+Kafka)  │ │(基类+分发)   │               │
│  └────────────┘ └──────────────┘ └──────┬───────┘               │
│  ┌──────────────────────────────────────┴───────────────────┐    │
│  │                  DataManager (CSV+WS+缓存+聚合+指标)      │    │
│  └──────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────┘
         │                              │                    │
         ▼                              ▼                    ▼
  cta-factory-service            data/signals/          data/klines/
  (策略管理)                     (信号CSV)              (K线CSV)
                                                         ↑
                                                  klines_service
                                                  (WS实时推送)
```

---

## 数据流

```
klines_service WS推送 / CSV轮询
    ↓
DataManager 刷新缓存 + 多时间框架聚合
    ↓
get_klines() 增量返回新K线
    ↓
BaseStrategy 分发到策略 Core
    ↓
Core.analyze() 入场 / Core.check_realtime_exit() 出场
    ↓
Signal → SignalLogger → CSV + Kafka/HTTP
    ↓
Go交易系统读取CSV → 风控 → 下单
```

---

## 核心组件

| 组件 | 入口文件 | 职责 |
|------|----------|------|
| 策略管理器 | `run_strategies_manager.py` | 注册策略到 factory、接收回调、心跳上报 |
| 策略进程 | `run_strategy.py` | 独立进程运行单个策略 |
| 策略基类 | `strategy_core/base/` | BaseStrategy/Core/State 三层基类 |
| 策略引擎 | `strategy_core/strategy_engine/` | 策略加载、生命周期、K 线分发 |
| 数据管理 | `data_manager/` | CSV+WS 数据接入、缓存、聚合、指标 |
| 信号日志 | `strategy_core/signal_logging/` | CSV 持久化、Kafka/HTTP 推送 |
| 仓位持久化 | `strategy_core/position_persistence.py` | JSON 文件存储仓位状态 |
| 回测框架 | `backtest/` | backtrader 集成、批量回测、分析报告 |

---

## 已实现策略

<!-- AUTO-GENERATED: strategy-list — do not edit manually, update from strategies/ directory -->

| 策略 | 基类架构 | 时间周期 | 多标的 |
|------|----------|----------|--------|
| cta_ict_v3 | ✅ BaseStrategyCore | 1d/4h/15m | ✅ |
| cta_ict_v4 | ✅ BaseStrategyCore | 1d/4h/15m | ✅ |
| cta_ict_v5 | ✅ BaseStrategyCore | 1h/15m | ✅ |
| cta_rbreaker_v3 | ✅ BaseStrategyCore | 15m | ✅ |
| dolphin_trading_v2 | ✅ BaseStrategyCore | 4h/1h/15m | ✅ |
| obv_atr_v2 | ✅ BaseStrategyCore | 4h/1h | ✅ |
| obv_atr_v3 | ✅ BaseStrategyCore | 4h | ✅ |
| obv_atr_v4 | ✅ BaseStrategyCore | 4h/1h | ✅ |
| cta_trend | ✅ BaseStrategyCore | 15m | ✅ |
| cta_trend_strength | ✅ BaseStrategyCore | 1d/4h/15m | ✅ |
| delphi_aggressive | ✅ BaseStrategyCore | 6h/15m | 单标的 |
| regime_donchian_atr | ✅ BaseStrategyCore | 4h | ✅ |
| ema_rsi_pullback | ✅ BaseStrategyCore | 2h | ✅ |
| new_obv | ✅ BaseStrategyCore | 4h | ✅ |
| new_ict | ✅ BaseStrategyCore | 15m/4h | ✅ |
| new_delphi | ✅ BaseStrategyCore | 1d/1h | ✅ |
| new_dolphin | ✅ BaseStrategyCore | 4h/1h | ✅ |
| vwap_channel_momentum | ✅ BaseStrategyCore | 15m | ✅ |
| volume_vwap_reversion | ✅ BaseStrategyCore | 1h | ✅ |
| advanced_obv_efi | ✅ BaseStrategyCore | 1h | ✅ |
| obs_divergence | ✅ BaseStrategyCore | 5m | 单标的 |
| vpvr_spot | ✅ BaseStrategyCore | 1h | 单标的 |
| bollinger_daily | 旧架构 | 5m | 单标的 |
| cta_bollinger_oscillator | 旧架构 | 15m | 单标的 |

<!-- /AUTO-GENERATED -->

---

## 故障排查

| 问题 | 解决方案 |
|------|----------|
| 策略加载失败 | 检查策略目录是否有 strategy.py |
| 信号未生成 | 检查日志确认 K 线更新、信号强度阈值 |
| 数据未同步 | 检查 klines_service 是否运行、WS 连接状态 |
| 仓位未恢复 | 检查 data/positions/ 下 JSON 文件 |
| WS 频繁断连 | 系统自动重连（退避上限 120s），检查网络 |
