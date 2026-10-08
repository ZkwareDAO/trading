# 架构参考

**更新日期**: 2026-09-03

## 系统边界

| 功能 | Strategy Core |
|------|---------------|
| 策略逻辑实现 | ✅ |
| 策略启停控制 | ✅（run_strategies_manager 进程监督） |
| K 线数据获取 | ✅ (CSV + Binance WS 直连) |
| 信号生成 | ✅ |
| 信号持久化 | ✅ (CSV) |
| 订单执行 | ✅ (direct_trading 直连下单) |

## 核心组件

**strategy_core/** - 核心框架
- `base/` - 策略三层基类（详见 [docs/strategy/DEVELOPMENT_GUIDE.md](../strategy/DEVELOPMENT_GUIDE.md)）
- `base/indicators.py` - 共享指标计算（优先 TA-Lib，回退手动计算）
- `signal_logging/` - 信号持久化 (CSV)、信号参数构建、交易所直连下单
- `position_persistence.py` - 仓位状态持久化（JSON，重启恢复）

**data_manager/** - 通用数据接入层
- `manager.py` - DataManager 5 个核心方法 + 辅助方法
- `kline_repository.py` - 多时间框架聚合 (1m → 4h/1h/15m)
- `klines_ws_client.py` - WebSocket 实时 K 线接收（无限重连、退避上限 120s）
- `indicators.py` - 技术指标计算（ADX, EMA, RSI, MACD, BOLL, ATR, KD, Envelope）

**backtest/** - backtrader 集成回测框架

## 策略列表

<!-- AUTO-GENERATED: strategy-list — do not edit manually, update from strategies/ directory -->

**新架构（推荐）**：继承 `BaseStrategy`/`BaseStrategyCore`/`BaseState`
- `sar_snt3_v3/` - SAR + 情绪指标趋势策略 (1m→多周期聚合, 多标的)

> 模板仓库只保留 sar_snt3_v3 一个参考实现（历史版本含 20+ 策略，开源时移除）。
> 新增策略后请同步更新本清单（生成源：`strategies/` 目录）。

<!-- /AUTO-GENERATED -->

## 关键设计决策

1. **独立进程架构**: 每个策略运行在独立进程中，由 run_strategies_manager 监督启停
2. **CSV 数据持久化**: 所有 K 线数据和信号都存储在 CSV 中，便于与外部 Go 系统集成
3. **时间戳为主键**: CSV 以时间戳为唯一主键，新覆盖旧，确保多路径写入一致性
4. **数据完整性阻断**: 启动时扫描 CSV gap 并补齐，不完整则降级为 CSV 轮询
5. **增量返回**: `get_klines()` 仅返回上次调用后的新数据
6. **多时间框架聚合**: KlineRepository 自动将 1m 聚合成 4h/1h/15m
7. **策略自主性**: 策略从各自的 `config.yaml` 加载配置，不依赖外部 ID
8. **HTTP 重试**: 网络异常与 5xx 指数退避重试，4xx 不重试
9. **WS 无限重连**: 退避上限 120s，心跳 30s
10. **仓位持久化**: 策略重启后从 JSON 文件恢复仓位，避免重复开仓。v3.7.1 起 `_notify_exit_and_clear` 无条件清理持久化文件（即使 `position_id=None`）
11. **确定性 signal_id**: 基于 K 线时间戳生成，实盘和回测 ID 一致
13. **平仓信号防重复**: 60秒冷却期，防止同一 K 线周期内重复发送平仓信号

## 外部依赖

- **Binance 公共源**: K 线 WS 实时推送 + fapi REST 历史下载（单体模式内置，无中间服务）
