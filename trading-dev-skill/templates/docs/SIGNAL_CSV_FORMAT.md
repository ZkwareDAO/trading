# 策略信号格式规范

**版本**: 2.3
**更新日期**: 2026-09-03

本文档定义了量化交易策略系统输出的交易信号格式标准，用于 Python 策略层与 Go 交易执行层之间的数据交换。

---

## 数据流概述

```
策略生成 Signal 对象
        ↓
CtaSignalCSV.from_signal() 统一生成数据对象
        ↓
   ┌────┴────┐
   ↓         ↓
CSV 存储   直连下单（单体模式唯一信号出口）
```

**关键原则**：CSV、直连下单两种输出使用同一个 `CtaSignalCSV` 对象，确保数据完全一致。

---

## Signal ID 生成机制

### 确定性 ID 生成

`signal_id` 基于 1m K线时间戳 + 策略类型 + 标的 + 信号类型生成，确保实盘和回测生成相同 ID：

```python
def generate_signal_id(
    strategy_type: str,      # 如 "sar_snt3_v3"
    symbol: str,             # 如 "BTCUSDT"
    kline_timestamp: datetime,  # 1m K线时间戳
    signal_type: str,        # "buy"/"sell"/"buy_close"/"sell_close"
) -> str:
    ts_ms = int(kline_timestamp.timestamp() * 1000)
    key = f"{strategy_type.lower()}_{symbol.upper()}_{ts_ms}_{signal_type.lower()}"
    hash_val = hashlib.sha256(key.encode()).hexdigest()[:16]
    return f"sig_{hash_val}"
```

### ID 格式

```
sig_{16位SHA256哈希}
```

示例：`sig_4e6830a085ddbd33`

### 一致性保证

| 场景 | signal_id |
|------|-----------|
| 实盘 CSV | `sig_4e6830a085ddbd33` |
| 实盘 HTTP | `sig_4e6830a085ddbd33` |
| 实盘 HTTP | `sig_4e6830a085ddbd33` |
| 回测 CSV | `sig_4e6830a085ddbd33` |

**相同 K线时间 + 策略 + 标的 + 动作 → 相同 signal_id**

### 向后兼容

不传 `strategy_type` 时，自动使用随机 UUID：

```python
signal = Signal(
    strategy_id="test",
    signal_type=SignalType.BUY,
    symbol="BTCUSDT",
    price=50000.0,
    # 无 strategy_type → UUID
)
# signal.signal_id = "5c724bd7-7e63-4d5c-a752-45eb5155a79c"
```

---

## CSV 文件结构

### 文件路径

```
data/signals/{strategy_id}/{date}.csv
```

- `strategy_id`: 完整策略实例名，格式 `{PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}_{MODE}`
- 与 `data/history_positions/` 目录结构一致，便于信号与仓位对应分析

示例：`data/signals/SARSNT3_8H_3_BTCUSDT_LIVE/20260624.csv`

### CSV 字段定义

| 字段名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `signal_id` | string | 信号唯一标识符 | `sig_abc123def456` |
| `signal_timestamp` | int64 | 信号时间戳 (毫秒) | `1704067200000` |
| `symbol` | string | 交易对 | `BTCUSDT` |
| `pos_type` | int | 仓位类型：1=现货，2=合约 | `2` |
| `strategy_type` | string | 策略类型 | `CTAFutureFactory` |
| `risk_strategy_type` | string | 风控策略类型 | `cta_intraday` |
| `user_id` | int | 用户 ID | `1` |
| `strategy_name` | string | 策略名称 | `SARSNT3_V3` |
| `strategy_version` | string | 策略版本 | `v2` |
| `strategy_internal` | string | K 线周期 | `1m` |
| `strategy_params` | string | 策略参数 (JSON) | `{"threshold":0.005,"StopLossThreshold":-0.02}` |
| `strategy_valid_before` | string | 策略有效时间 | `2030-12-31 08:00:00` |
| `strategy_cash` | float | 策略最大金额 | `1000` |
| `strategy_parts` | int | 策略最大订单数 | `2` |
| `signal_side` | int | 方向：1=买，2=卖 | `1` |
| `signal_action` | string | 信号动作 | `buy`, `sell`, `buy_close`, `sell_close` |
| `signal_exchange` | string | 交易所 | `binance` |
| `signal_valid_before` | string | 订单有效时间 | `2026-05-10 08:00:00` |
| `signal_trigger_price` | float | 触发价格 | `70000.0` |
| `signal_slippage` | float | 滑点 | `0.001` |
| `signal_order_type` | int | 订单类型：1=限价，2=市价 | `1` |
| `signal_quantity` | float | 数量 | `0` |
| `signal_cash` | float | 金额 | `500` |
| `strength` | float | 信号强度 (0~1) | `0.85` |
| `metadata` | string | 附加元数据 (JSON) | `{}` |

---

## JSON 格式（本地备份 / 下单 payload）

单体模式下 JSON 有两个用途：
- **JSON 本地备份**：配置 `json_backup_dir` 时，信号以 `cta.to_json()` 结构写入备份目录
- **直连下单 payload**：`BinanceTrader.execute()` 消费的即是同一份 `CtaSignalCSV.to_json()` 数据

（历史上外层还有 `{"topic": "...", "message": "..."}` 的包装结构，属 signal_hub HTTP
推送通道专用，已随单体化删除。）

### JSON 字段结构

```json
{
  "SignalID": "sig_abc123def456",
  "SignalTimestamp": "2026-05-09 10:30:00",
  "symbol": "BTCUSDT",
  "pos_type": 2,
  "strategy_type": "CTAFutureFactory",
  "risk_strategy_type": "cta_intraday",
  "strategy": {
    "name": "SARSNT3",
    "version": "3",
    "internal": "1m",
    "description": "SARSNT3_V3 strategy",
    "params": {
      "sar_step": 0.015,
      "StopLossThreshold": -0.02,
      "TakeProfitBackThreshold": 0.05,
      "TakeProfitBackDynamicFallPercent": 0.05
    },
    "valid_before": "2030-12-31 08:00:00",
    "cash": 1000,
    "parts": 2
  },
  "user_id": 1,
  "signal": {
    "side": 1,
    "action": "buy",
    "exchange": "binance",
    "valid_before": "2026-05-10 08:00:00",
    "quantity": null,
    "cash": 500,
    "trigger_price": 70000.0,
    "slippage": 0.001,
    "order_type": 1
  }
}
```

---

## 风控字段

### 字段说明

| 字段名 | 类型 | 说明 | 配置示例 | JSON 输出 |
|--------|------|------|----------|------------|
| `StopLossThreshold` | float | 止损阈值（负数） | `2.0` (表示 2%) | `-0.02` |
| `TakeProfitBackThreshold` | float | 止盈回撤激活阈值 | `5.0` (表示 5%) | `0.05` |
| `TakeProfitBackDynamicFallPercent` | float | 止盈回撤百分比 | `20.0` (表示 20%) | `0.2` |

### 格式转换

- **配置文件**：使用百分比整数形式，如 `2.0` 表示 2%
- **内部计算**：`RiskController` 使用百分比形式，便于直观理解
- **JSON 输出**：转换为小数形式，如 `0.02` 表示 2%

### 重要说明

- **StopLossThreshold 始终为负数**：无论配置传入正数还是负数，输出都是负数
- 风控字段同时存在于：
  - CSV 的 `strategy_params` 字段中
  - JSON 的 `strategy.params` 字段中

---

## 数据一致性保证

### 统一生成

所有信号数据通过 `CtaSignalCSV.from_signal()` 方法统一生成：

```python
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV

# 生成一次，多处使用
cta_signal = CtaSignalCSV.from_signal(signal, **strategy_params)

# CSV 写入
csv_writer.write_cta_signal(cta_signal)

# 直连下单（单体模式唯一信号出口）
signal_logger.log_cta_signal(cta_signal)
```

### 数据流

```
engine.py:_log_signal_unified()
    ↓
CtaSignalCSV.from_signal() → 同一对象
    ├── csv_writer.write_cta_signal()
    └── signal_logger.log_cta_signal()
            └── binance_trader.execute()        # direct_trading 通道（单体模式唯一信号出口）
```

注：历史上的 `http_sender.send_cta_signal()`（signal_hub 通道）已随单体化删除。

---

## 配置示例

### 策略配置 (config.yaml)

```yaml
sar_snt3_v3:
  version: '3'
  symbols: ["BTCUSDT"]
  timeframes: ["8h"]
  direction: neutral
  params:
    sar_step: 0.015
    adx_threshold: 25
  risk:
    fixed_stop_loss_pct: 2.0
    trailing_profit_activation: 0.05
    trailing_profit_drawdown: 0.05
  signal:
    min_strength: 0.5
    cooldown_ms: 0
```

### 系统配置 (settings.yaml)

```yaml
signal_logging:
  storage:
    type: "csv"
    path: "./data/signals"

direct_trading:          # 单体模式唯一信号出口：存储后直连交易所下单
  enabled: false
  testnet: false
```

注：历史上的 `signal_hub` 段（HTTP 推送配置）已随单体化删除，凭证统一放 .env
（`BINANCE_API_KEY` / `BINANCE_API_SECRET`），详见 docs/claude/operations.md。

---

## 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| 1.0 | 2025-03 | 初始版本 |
| 1.1 | 2025-03 | 新增 CTA/ICT 策略适配指南 |
| 2.0 | 2026-05-09 | 统一 CSV/HTTP 数据格式，风控字段一致性，StopLossThreshold 负数处理 |
| 2.1 | 2026-05-18 | 新增确定性 signal_id 生成机制，实盘/回测 ID 一致性保证 |
| 2.2 | 2026-06-05 | 风控参数 JSON 输出从百分比整数改为小数形式（20→0.2） |
| 2.3 | 2026-06-26 | 信号目录结构改为完整策略实例名，与 history_positions 一致 |
