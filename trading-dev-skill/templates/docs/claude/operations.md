# 运维参考

## 配置

**系统配置**: `config/settings.yaml`
- `strategy_engine.factory_endpoint` - factory-service 的 RPC 端点
- `strategy_engine.callback_port` - XML-RPC 回调服务端口
- `strategy_engine.position_proxy_url` - Position 代理地址（端口 8889）
- `strategy_engine.position_api_path` - 仓位查询 API 路径（默认 `/api/cta/v1/user-order-positions`）
- `strategy_engine.use_bar_high_low_for_exit` - 止损止盈检测模式（默认 true）
  - `true`: 使用 bar_high/bar_low（闭合 K 线的最高/最低价，更准确检测 K 线内价格波动）
  - `false`: 使用 current_price（K 线收盘价，简单但可能遗漏 K 线内的止损触发）
- `data_manager` - CSV 目录、WS 地址、缓存配置
- `signal_logging` - 信号存储目录、Kafka 配置
- `signal_hub` - HTTP 信号推送配置
  - `enabled` - 是否启用 HTTP 推送
  - `endpoint` - HTTP 端点地址
  - `api_path` - API 路径（默认 `/api/v1/kafka/message`）
    - V1 路径（如 `/api/v1/kafka/message`）：payload 包装为 `{"topic": "...", "message": "..."}`
    - V2+ 路径（如 `/api/v2/signals`）：payload 直接为 `cta_signal.to_json()`
- `strategies` - 策略列表（每个配置项对应一个独立进程）

**策略配置**: `strategies/{name}/config.yaml` 或 `config/strategies/{name}/{SYMBOL}.yaml`
```yaml
cta_ict_v3:
  enabled: true
  version: '3'
  symbols: ["BTCUSDT"]
  timeframes: ["1d", "4h", "15m"]
  direction: neutral
  params:
    stop_loss_roi_pct: 0.2
  signal:
    min_strength: 0.4
    cooldown_ms: 60000
    api_path: "/api/v2/signals"  # 可选，覆盖全局 signal_hub.api_path
  capital:
    max_cash: 100
    max_parts: 1
    leverage: 5
```

**API 路径优先级**: `signal.api_path`（策略级） > `signal_hub.api_path`（全局） > `/api/v1/kafka/message`（默认）

**多环境配置**: `config.yaml` / `config.dev.yaml` / `config.test.yaml` / `config.prod.yaml`

**策略运行时命名**: `{PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}_{MODE}`，如 `ICT_4H_V2_BTCUSDT_LIVE`

## 策略 ID 与数据隔离

**strategy_name_for()**: 返回不含 trading_mode 的名称，用于 Factory 注册和远程仓位查询
- 格式: `{PREFIX}_{INTERVAL}_{VERSION}_{SYMBOL}`
- 用途: Factory 注册、信号路由、仓位查询

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

## 远程仓位同步

策略每根 K 线检查本地持仓时，先同步远程仓位状态：

**同步流程**:
```
on_kline()
  → 有本地持仓?
    → _sync_remote_position()
      → factory_client.is_position_open()
        → HTTP 查询 Position 代理 (8889)
```

**返回值含义**:
| 返回值 | 含义 | 处理 |
|--------|------|------|
| `(True, dict)` | 远程开启 | 保持本地状态，继续检查出场 |
| `(False, dict)` | 远程已关闭 | 清除本地状态，记录历史 |
| `(False, None)` | 远程无仓位记录 | 清除本地状态 |
| `(None, None)` | 无法判断 | **保持本地状态**（保守策略） |

**无法判断的场景**:
- HTTP 请求失败（404/500/超时）
- JSON 解析失败
- `deleted` 字段缺失

**核心原则**: 只有 API 明确返回"已关闭"或"无仓位记录"时才清除本地状态，无法判断时保守保持。

**字段名兼容**: 自动兼容大小写字段名（`Deleted`/`deleted`、`ID`/`id` 等）。

## 常见问题

| 问题 | 解决方案 |
|------|----------|
| 策略加载失败 | 检查策略目录内是否存在 `strategy.py` |
| 无信号生成 | 检查日志确认 K 线更新，验证信号强度 >= min_strength |
| 数据未同步 | 检查 klines_service 是否运行，WS 连接状态 |
| CSV 格式错误 | 检查列重复，运行数据修复脚本 |
| 仓位未恢复 | 检查 data/positions/ 下 JSON 文件 |
| 远程仓位同步失败 | 检查 position_proxy_url 配置和 Position 代理服务状态 |
| 需要下载历史 K 线 | 使用 klines_service HTTP API 或 `klines_loader.py` |
