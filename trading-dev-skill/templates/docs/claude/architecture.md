# 架构参考

## 系统边界

| 功能 | Strategy Core | cta-factory-service | Go 交易系统 |
|------|---------------|---------------------|-------------|
| 策略逻辑实现 | ✅ | ❌ | ❌ |
| 策略启停控制 | 执行 | 管理 | ❌ |
| K 线数据获取 | ✅ (CSV + WS) | ❌ | ❌ |
| 信号生成 | ✅ | ❌ | ❌ |
| 信号持久化 | ✅ (CSV + Kafka) | ❌ | ❌ |
| 订单执行 | ❌ | ❌ | ✅ |

## 核心组件

**strategy_core/** - 核心框架
- `base/` - 策略三层基类（详见 [docs/strategy/DEVELOPMENT_GUIDE.md](../strategy/DEVELOPMENT_GUIDE.md)）
- `base/indicators.py` - 共享指标计算（优先 TA-Lib，回退手动计算）
- `strategy_engine/` - 策略发现、加载、生命周期管理、数据分发
- `signal_logging/` - 信号持久化 (CSV)、HTTP/Kafka 集成（熔断器、去重 TTL、指数退避重试、失败信号持久化队列）
- `factory_client.py` - Factory 通信封装（XML-RPC + 回调服务器 + 远程仓位查询）
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
- `cta_ict_v3/` - ICT 市场结构策略 (1d/4h/15m, 多标的)
- `cta_ict_v4/` - ICT 市场结构策略 v4 (1d/4h/15m, 多标的)
- `cta_ict_v5/` - ICT 市场结构策略 v5 (1h/15m, 多标的)
- `cta_rbreaker_v3/` - R-Breaker 突破/反转策略 (15m, 多标的)
- `dolphin_trading_v2/` - Dolphin 通道+KD 策略 (4h/1h/15m, 多标的)
- `obv_atr_v2/` - OBV+ATR 趋势策略 (4h/1h, 多标的)
- `obv_atr_v3/` - OBV+ATR 趋势策略 v3 (4h, 多标的)
- `obv_atr_v4/` - OBV+ATR 趋势策略 v4 (4h/1h, 多标的)
- `cta_trend/` - 双均线交叉趋势策略 (15m)
- `cta_trend_strength/` - 趋势强度策略 (1d/4h/15m, 多标的)
- `delphi_aggressive/` - Delphi II 激进策略 (6h/15m, 单标的)
- `regime_donchian_atr/` - Regime Donchian ATR 策略 (4h, 多标的)
- `ema_rsi_pullback/` - EMA RSI 回调策略 (2h, 多标的)
- `new_obv/` - New OBV 突破策略 (4h, 多标的)
- `new_ict/` - New ICT 流动性扫荡策略 (15m/4h, 多标的)
- `new_delphi/` - New Delphi ATR 通道突破策略 (1d/1h, 多标的)
- `new_dolphin/` - New Dolphin 自适应波浪策略 (4h/1h, 多标的)
- `vwap_channel_momentum/` - VWAP 通道动量突破策略 (15m, 多标的)
- `volume_vwap_reversion/` - Volume VWAP 回归策略 (1h, 多标的)
- `advanced_obv_efi/` - Advanced OBV EFI 共振策略 (1h, 多标的)
- `obs_divergence/` - OBS 背离策略 (5m, 单标的)
- `vpvr_spot/` - VPVR 现货策略 (1h, 单标的)

**旧架构**：`bollinger_daily/`, `cta_bollinger_oscillator/`

<!-- /AUTO-GENERATED -->

## 关键设计决策

1. **独立进程架构**: 每个策略运行在独立进程中，由 factory 管理启停
2. **CSV 数据持久化**: 所有 K 线数据和信号都存储在 CSV 中，便于与外部 Go 系统集成
3. **时间戳为主键**: CSV 以时间戳为唯一主键，新覆盖旧，确保多路径写入一致性
4. **数据完整性阻断**: 启动时扫描 CSV gap 并补齐，不完整则降级为 CSV 轮询
5. **增量返回**: `get_klines()` 仅返回上次调用后的新数据
6. **多时间框架聚合**: KlineRepository 自动将 1m 聚合成 4h/1h/15m
7. **策略自主性**: 策略从各自的 `config.yaml` 加载配置，不依赖外部 ID
8. **Kafka 熔断器**: 连续失败达到阈值自动熔断，超时后尝试恢复
9. **WS 无限重连**: 退避上限 120s，心跳 30s
10. **仓位持久化**: 策略重启后从 JSON 文件恢复仓位，避免重复开仓。v3.7.1 起 `_notify_exit_and_clear` 无条件清理持久化文件（即使 `position_id=None`）
11. **确定性 signal_id**: 基于 K 线时间戳生成，实盘和回测 ID 一致
12. **远程仓位同步**: 策略启动时查询远程仓位状态，若远程已平仓则清除本地状态
13. **平仓信号防重复**: 60秒冷却期，防止同一 K 线周期内重复发送平仓信号

## 外部依赖

- **cta-factory-service**: Go 策略管理服务（XML-RPC：register/start/stop/list）
- **Go 交易系统**: 读取信号 CSV，执行风控检查，通过 Kafka 执行订单
- **klines_service**: K 线推送服务（WS 实时推送 + HTTP API 历史下载）
