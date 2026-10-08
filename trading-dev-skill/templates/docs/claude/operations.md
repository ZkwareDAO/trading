# 运维参考

**更新日期**: 2026-09-03

## 配置

**系统配置**: `config/settings.yaml`
- `use_bar_high_low_for_exit` - 止损止盈检测模式（顶层键，默认 true）
  - `true`: 使用 bar_high/bar_low（闭合 K 线的最高/最低价，更准确检测 K 线内价格波动）
  - `false`: 使用 current_price（K 线收盘价，简单但可能遗漏 K 线内的止损触发）
- `data_manager` - K 线 CSV 目录与缓存配置（实时数据单体直连 Binance，见 `realtime_enabled`）
- `signal_logging` - 信号 CSV 存储目录与保留天数
- `direct_trading` - 直连交易所下单配置（单体模式唯一信号出口，详见下节）
- `strategies` - 策略列表（每个配置项对应一个独立进程）

### 直连交易所下单（direct_trading）
单体模式唯一信号出口：信号写入 CSV 存储后，由策略进程直接调用
Binance U 本位合约 API 下单。

```yaml
direct_trading:
  enabled: false        # 默认关闭
  exchange: "binance"   # 目前仅支持 binance U 本位合约
  testnet: false        # true → testnet.binancefuture.com
  recv_window: 5000     # 签名请求有效窗口（毫秒）
  timeout: 10.0         # 单次请求超时（秒）
  max_retries: 2        # 仅对网络异常与 5xx 重试；4xx 一律不重试
```

**凭证只放 `.env`**（配置文件里连 `${VAR}` 占位都不写，避免误填明文被提交）：

```
BINANCE_API_KEY=
BINANCE_API_SECRET=
```

**历史沿革**：早期版本支持 signal_hub HTTP 推送与 Kafka 直推，均已随单体化移除，
不再存在双通道配置。`direct_trading` 是唯一的下单通道。

**行为约定**：

| 项 | 行为 |
|---|---|
| 下单量 | `signal_cash × leverage / price`，按 `exchangeInfo` 的 stepSize **向下**取整；显式 `signal_quantity` 优先 |
| 开仓订单类型 | 尊重 `signal.order_type`（1=LIMIT GTC，2=MARKET） |
| 平仓订单类型 | **一律 MARKET + reduceOnly**，忽略 `order_type`（限价平仓挂单不成交会让本地仓位与交易所永久分叉） |
| 平仓数量 | 取 `positionRisk` 的实际持仓量，不看信号里的数量 |
| 反手 | `reverse_*` 先平后开；平仓失败则放弃开仓 |
| 幂等 | `newClientOrderId = signal_id`（确定性哈希），重复信号被交易所以重复单拒绝 |
| 无持仓时平仓 | 记 warning 并视为成功（幂等），不发单 |

**拒绝下单的情形**（记 error 日志，信号仍写 CSV）：

- `paper_trading` 模式（双重防线：`run_strategy` 不构造执行器，执行器内再校验一次）
- 信号 `signal.exchange != binance`（如 `hyperliquid`）—— 不同交易所合约规格不同
- 账户为双向持仓模式（Hedge Mode）—— 仅支持单向持仓（One-way Mode）
- 下单量低于 `minQty` 或名义价值低于 `minNotional`
- 平仓方向与交易所实际持仓不一致（避免误平同账户其他策略的反向仓位）

**⚠️ trading_mode 与下单的关系**（这是本功能最容易误判的一点）：

| trading_mode | 是否向交易所下真单 |
|---|---|
| `live` | **会下真单** |
| `smoking` | **会下真单**（冒烟模式的设计意图就是用真单验证全链路） |
| `paper_trading` | 不下单（唯一有防线的模式） |

`smoking` 字面上像"只是测试"，但它**会真实成交**。只有 `paper_trading` 被拦。
不想下真单时必须用 `paper_trading`，不要指望 `smoking` 能兜住。

**上线前检查**：API key 只开合约交易权限（**切勿开提现**）、绑定 IP 白名单、
账户切单向持仓、先用 `testnet: true` 验证。缺凭证时策略进程**启动即失败**，
不静默降级 —— 开着直连却发不出单等于策略在"以为已成交"的状态下继续跑。

**per-symbol overrides 必改项**：`strategies/<name>/overrides/<SYMBOL>.yaml` 里的
`signal.exchange` 必须是 `binance`（否则拒单），且建议 `signal.order_type: 2`（市价）。

**已知限制**：LIMIT 开仓挂单不成交时，框架本地仓位账本会认为已持仓，与交易所分叉。
实盘建议 `signal.order_type: 2`（市价）。本功能不含启动时与交易所的仓位对账。

**策略配置**: `config/strategies.yaml`（登记表：symbols + trading_mode）
+ `strategies/{name}/overrides/{SYMBOL}.yaml`（per-symbol 参数，**唯一事实来源**，
见 CONFIG_UNIFICATION_SPEC）。**策略目录内不放 `config.yaml`。**

```yaml
sar_snt3_v3:
  enabled: true
  version: '3'
  symbols: ["BTCUSDT"]
  timeframes: ["8h"]
  direction: neutral
  params:
    sar_step: 0.015
    adx_threshold: 25
  signal:
    min_strength: 0.5
    cooldown_ms: 0
    exchange: "binance"  # 必须，否则该 symbol 拒单
    order_type: 2        # 建议，市价单（LIMIT 挂单不成交会让仓位分叉）
  capital:
    max_cash: 200
    max_parts: 1
    leverage: 1
```

**多环境配置**: `config.yaml` / `config.dev.yaml` / `config.test.yaml` / `config.prod.yaml`

**策略运行时命名**: `{PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}_{MODE}`，如 `SARSNT3_8H_3_BTCUSDT_LIVE`

## 策略 ID 与数据隔离

**strategy_name_for()**: 返回不含 trading_mode 的名称
- 格式: `{PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}`
- 用途: 信号路由、外部对账

**strategy_id_for()**: 返回含 trading_mode 的完整 ID，用于数据存储路径
- 格式: `{PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}_{MODE}`
- 用途: 仓位持久化、历史仓位、信号存储
- 实现实盘/模拟盘/回测数据隔离

| 模式 | 数据路径示例 |
|------|--------------|
| live | `data/positions/RBREAKER_15M_V3_BTCUSDT_LIVE.json` |
| paper_trading | `data/positions/RBREAKER_15M_V3_BTCUSDT_PAPER.json` |
| backtest | `data/positions/RBREAKER_15M_V3_BTCUSDT_BACKTEST.json` |

## 平仓冷却机制

平仓后使用 K 线时间判断冷却期，防止同一根 K 线重复发送平仓信号：
- 使用 `_current_kline_timestamp`（K 线时间）而非 `datetime.now()`（真实时间）
- 确保回测和实盘行为一致
- 同一根 K 线内跳过出场检查

## 止损冷却机制

止损后当日禁止再次开仓，防止连续止损：

**存储路径**: `data/stop_loss_cool_down/{strategy_id}.json`
```json
{
  "stop_loss_date": "2026-06-26",
  "updated_at": "2026-06-26T15:30:00+00:00"
}
```

**判断逻辑**:
- 远程平仓时检查 `PnlValue < 0` 且 `CloseTime.date() == today`
- 只有**今天的亏损**才设置止损冷却，历史亏损不影响

**过期清理**:
- 策略启动时检查 `stop_loss_date < today` → 自动清除过期文件
- 次日即可正常开仓

**独立存储**: 止损冷却文件与仓位持久化文件隔离，平仓删除仓位文件时不会丢失止损冷却状态

## 信号 CSV 格式

信号写入 `data/signals/{strategy_id}/{date}.csv`（与 history_positions 目录结构一致）:

| 字段 | 类型 | 说明 |
|------|------|------|
| `signal_id` | string | 确定性 ID（strategy_type+symbol+1m时间戳+signal_type 的 SHA256） |
| `signal_timestamp` | int | 毫秒时间戳 |
| `symbol` | string | 交易对 |
| `pos_type` | int | 1=现货，2=合约 |
| `strategy_type` | string | 策略类型 |
| `risk_strategy_type` | string | 风控策略类型 |
| `user_id` | int | 用户 ID |
| `strategy_name` | string | 策略名称 |
| `strategy_version` | string | 策略版本 |
| `strategy_internal` | string | K 线周期 |
| `strategy_params` | json | 策略参数 |
| `strategy_valid_before` | string | 策略有效时间 |
| `strategy_cash` | float | 策略最大金额 |
| `strategy_parts` | int | 策略最大订单数 |
| `leverage` | int | 杠杆倍数 |
| `signal_side` | int | 1=buy, 2=sell |
| `signal_action` | string | buy, sell, buy_close, sell_close |
| `signal_exchange` | string | 交易所 |
| `signal_valid_before` | string | 信号有效时间 |
| `signal_trigger_price` | float | 触发价格 |
| `signal_slippage` | float | 滑点 |
| `signal_order_type` | int | 1=限价，2=市价 |
| `signal_quantity` | float | 数量 |
| `signal_cash` | float | 金额 |
| `strength` | float | 信号强度 (0-1) |
| `metadata` | json | 附加数据 |
| `trading_mode` | string | 运行模式 (live / paper_trading / smoking / backtest) |

## 历史仓位 CSV 格式

历史仓位写入 `data/history_positions/{strategy_name}/{date}.csv`:

| 字段 | 类型 | 说明 |
|------|------|------|
| `position_id` | string | 仓位唯一标识 |
| `strategy_name` | string | 策略名称 |
| `symbol` | string | 交易对 |
| `position_type` | string | long / short |
| `entry_price` | float | 开仓价格 |
| `exit_price` | float | 平仓价格 |
| `entry_time` | datetime | 开仓时间 |
| `exit_time` | datetime | 平仓时间 |
| `entry_timestamp` | int | 开仓时间戳（秒） |
| `exit_timestamp` | int | 平仓时间戳（秒） |
| `peak_price` | float | 持仓期间最高/最低价 |
| `stop_price` | float | 止损价格 |
| `max_pnl_pct` | float | 最大盈利百分比 |
| `min_pnl_pct` | float | 最大亏损百分比 |
| `exit_reason` | string | 平仓原因 |
| `is_stop_loss` | bool | 是否止损 |
| `price_diff` | float | 价格差 |
| `pnl_pct` | float | 盈亏百分比 |
| `duration_seconds` | int | 持仓时长（秒） |
| `atr_at_entry` | float | 入场时 ATR |
| `trail_activated` | bool | 是否触发移动止盈 |
| `trading_mode` | string | 运行模式 (live / paper_trading / smoking / backtest) |

## 当前仓位 JSON 格式

当前仓位写入 `data/positions/{strategy_name}.json`:

| 字段 | 类型 | 说明 |
|------|------|------|
| `position_id` | string | 仓位唯一标识 |
| `position` | string | long / short / flat |
| `entry_price` | float | 开仓价格 |
| `entry_time` | datetime | 开仓时间 |
| `entry_timestamp` | int | 开仓时间戳（秒） |
| `peak_price` | float | 持仓期间最高/最低价 |
| `stop_price` | float | 止损价格 |
| `trading_mode` | string | 运行模式 (live / paper_trading / smoking / backtest) |

## 数据完整性保障

### 启动流程

```
connect()
  → connect_and_sync()
      1. 预加载 1m 数据
      2. 扫描中间 gap（相邻行时间差 > 120 秒）
      3. 调用 API 补齐 gap
      4. 补齐"最后一行 → 现在"的数据
  → is_data_complete()
      1. 缓存中有数据
      2. 最新数据距今 < 5 分钟
      3. CSV 无中间 gap
  → _data_ready = all(complete)
      → True: 开启 WS 实时推送
      → False: 降级为 CSV 轮询
```

### WS 推送时完整性验证

```
_on_kline_received(kline):
  差值 == 60 秒 → 正常，追加
  差值 > 90 秒  → 调用 API 补齐中间缺失 → 合并到缓存
```

### 统一 CSV 持久化

所有写入路径统一使用 `save_klines_to_csv`：
1. 读取现有 CSV → 2. 合并新旧数据 → 3. 按时间戳去重（新覆盖旧） → 4. 按时间戳排序 → 5. 写回 CSV

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| 策略加载失败 | 检查策略目录内是否存在 `strategy.py` |
| 无信号生成 | 检查日志确认 K 线更新，验证信号强度 >= min_strength |
| 实时数据中断 | 检查 Binance 公共 WS 连接状态；`realtime_enabled=false` 时只用本地 CSV |
| CSV 格式错误 | 检查列重复，运行数据修复脚本 |
| 仓位未恢复 | 检查 data/positions/ 下 JSON 文件 |
| 下单失败 | 检查进程日志；确认凭证、网络/代理、单向持仓模式；失败会如实上报不静默 |
