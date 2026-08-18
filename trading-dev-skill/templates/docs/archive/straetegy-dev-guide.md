# CTA 策略开发与回测指南

> 本指南基于当前仓库代码和 `ARCHITECTURE.md` 整理。文档示例中的策略名统一使用 `my_strategy`，核心类前缀使用 `My`。

## 1. 系统边界

本项目采用“平台 + 策略插件”架构：

- `DataManager` 负责加载 1m K 线、缓存数据和聚合多时间周期。
- `BaseStrategy` 负责 K 线分发、信号创建、冷却控制和仓位持久化。
- `BaseStrategyCore` 子类负责入场和出场逻辑。
- 回测框架通过 backtrader 调用真实策略逻辑。
- 本项目只生成交易信号；实际下单由外部 Go 交易系统负责。

策略开发应尽量只实现策略特有逻辑，不重复实现生命周期、信号日志、冷却和持久化等平台能力。

## 2. 新策略目录

在 `strategies/` 下创建策略插件：

```text
strategies/my_strategy/
├── __init__.py
├── strategy.py
├── my_core.py
├── state.py
├── config.yaml
├── config.dev.yaml
├── config.test.yaml
└── tests/
    └── test_my_strategy.py
```

关键约束：

- 目录名、`STRATEGY_TYPE`、配置文件顶层键必须一致。
- `strategy.py` 必须导出名为 `Strategy` 的类。
- 回测至少需要 `config.test.yaml`。
- 新策略使用 `BaseStrategy`、`BaseStrategyCore`、`BaseState` 三层基类。

## 3. State：策略状态

`BaseState` 已提供通用字段，包括：

- `position`、`position_id`
- `entry_timestamp`、`entry_time`、`entry_price`
- `peak_price`、`stop_price`
- `stop_loss_date`
- `max_pnl_pct`、`min_pnl_pct`

只需要添加策略特有状态。存在特有字段时，必须实现序列化和恢复。

```python
#!/usr/bin/env python3

from dataclasses import dataclass

from strategy_core.base.state import BaseState


@dataclass
class MyState(BaseState):
    atr_at_entry: float = 0.0
    trail_activated: bool = False

    def to_persist_dict(self) -> dict:
        data = super().to_persist_dict()
        data.update({
            "atr_at_entry": self.atr_at_entry,
            "trail_activated": self.trail_activated,
        })
        return data

    def restore_from_dict(self, data: dict) -> None:
        super().restore_from_dict(data)
        self.atr_at_entry = data.get("atr_at_entry", 0.0)
        self.trail_activated = data.get("trail_activated", False)
```

注意：

- `list`、`dict`、`set` 等可变字段应使用 `field(default_factory=...)`。
- 嵌套对象需要实现 `to_dict()`，并在 `restore_from_dict()` 中重建。
- 不要重复声明 `BaseState` 已有字段。

## 4. Core：入场和出场逻辑

Core 必须实现：

- `_get_state(symbol)`
- `analyze(...)`
- `check_realtime_exit(...)`
- `get_status()`

```python
#!/usr/bin/env python3

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from strategy_core.base.core import BaseStrategyCore
from .state import MyState


class MyCore(BaseStrategyCore[MyState]):
    def __init__(
        self,
        symbols: List[str],
        timeframes: List[str],
        params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(symbols, timeframes, params)
        p = params or {}
        self.signal_timeframe = p.get("signal_timeframes", "1h")
        self.ma_period = int(p.get("ma_period", 20))

    def _get_state(self, symbol: str) -> MyState:
        if symbol not in self._state:
            self._state[symbol] = MyState()
        return self._state[symbol]

    @staticmethod
    def _hold(price: float, reason: str) -> Dict[str, Any]:
        return {
            "action": "hold",
            "price": price,
            "strength": 0.0,
            "metadata": {"reason": reason},
        }

    def analyze(
        self,
        symbol: str,
        klines_data: Dict[str, pd.DataFrame],
        current_time: Optional[datetime] = None,
        realtime_price: Optional[float] = None,
        current_cash: Optional[float] = None,
    ) -> Dict[str, Any]:
        state = self._get_state(symbol)
        price = float(realtime_price or 0.0)

        if state.is_in_position():
            return self._hold(price, "已有持仓")

        today = (
            current_time.date()
            if current_time is not None
            else datetime.now(timezone.utc).date()
        )
        if state.stop_loss_date == today:
            return self._hold(price, "今日已止损，禁止再次开仓")

        closed = self.get_closed_data(
            klines_data,
            self.signal_timeframe,
            min_rows=self.ma_period + 1,
            current_time=current_time,
        )
        if closed.empty:
            return self._hold(price, "已闭合 K 线不足")

        ma = float(closed["close"].rolling(self.ma_period).mean().iloc[-1])
        if pd.isna(ma):
            return self._hold(price, "指标尚未形成")

        if price <= 0:
            price = float(closed["close"].iloc[-1])

        if price > ma:
            state.position = "long"
            state.entry_price = price
            state.entry_time = current_time
            state.entry_timestamp = int(current_time.timestamp()) if current_time else None
            state.peak_price = price
            self._notify_position_enter(symbol, state)
            return {
                "action": "buy",
                "price": price,
                "strength": 0.8,
                "metadata": {"reason": "价格向上突破均线", "ma": ma},
            }

        return self._hold(price, "未满足入场条件")

    def check_realtime_exit(
        self,
        symbol: str,
        current_price: float,
        current_time: Optional[datetime] = None,
        bar_high: Optional[float] = None,
        bar_low: Optional[float] = None,
    ) -> Dict[str, Any]:
        state = self._get_state(symbol)
        if not state.is_in_position():
            return self._hold(current_price, "无持仓")

        state.update_pnl_extremes(current_price)

        stop_loss_pct = float(self.params.get("stop_loss_pct", 0.02))
        if state.position == "long" and current_price <= state.entry_price * (1 - stop_loss_pct):
            return self._close(
                symbol,
                state,
                current_price,
                "固定比例止损",
                is_stop_loss=True,
                current_time=current_time,
            )

        return self._hold(current_price, "继续持仓")

    def _close(
        self,
        symbol: str,
        state: MyState,
        price: float,
        reason: str,
        is_stop_loss: bool = False,
        current_time: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        action = self._notify_exit_and_clear(
            symbol=symbol,
            state=state,
            exit_price=price,
            exit_reason=reason,
            is_stop_loss=is_stop_loss,
            exit_time=current_time,
        )
        state.atr_at_entry = 0.0
        state.trail_activated = False
        return {
            "action": action,
            "price": price,
            "strength": 0.8,
            "metadata": {"reason": reason, "is_stop_loss": is_stop_loss},
        }

    def get_status(self) -> Dict[str, Any]:
        return {
            "symbols": self.symbols,
            "timeframes": self.timeframes,
            "states": {
                symbol: self._get_state(symbol).to_persist_dict()
                for symbol in self.symbols
            },
        }
```

以上代码只是结构示例，实际策略需要补充空头、止盈、风控和指标有效性检查。

## 5. Strategy：平台接口

`Strategy` 类保持精简，不在这里计算技术指标。

```python
#!/usr/bin/env python3

from strategy_core.base.strategy import BaseStrategy
from .my_core import MyCore


class Strategy(BaseStrategy):
    STRATEGY_TYPE = "my_strategy"
    STRATEGY_PREFIX = "MY"
    DEFAULT_TIMEFRAME = "1h"

    def _create_core(self):
        return MyCore(
            symbols=self.symbols,
            timeframes=self.timeframes,
            params=self.params,
        )

    def _get_indicator_timeframes(self) -> set:
        timeframes = set(self.timeframes)
        params = self.params or {}
        timeframes.add(params.get("signal_timeframes", "1h"))
        return timeframes
```

`__init__.py`：

```python
from .strategy import Strategy
from .my_core import MyCore
from .state import MyState

__all__ = ["Strategy", "MyCore", "MyState"]
```

## 6. 配置文件

`config.yaml`、`config.dev.yaml` 和 `config.test.yaml` 使用相同结构：

```yaml
my_strategy:
  enabled: true
  version: "1"

  symbols:
    - BTCUSDT

  timeframes:
    - 1h

  cooldown_timeframe: 1h
  direction: neutral

  params:
    signal_timeframes: 1h
    ma_period: 20
    stop_loss_pct: 0.02

  signal:
    min_strength: 0.5
    cooldown_ms: 60000
    diagnostic_log_level: INFO

  capital:
    max_cash: 5000
    max_parts: 1
    leverage: 1
```

配置原则：

- 每个指标周期使用明确的 `*_timeframes` 字段。
- 多周期分析不要依赖 `timeframes` 数组顺序。
- `cooldown_timeframe` 应是实际入场周期。
- 回测参数放在 `config.test.yaml`，不要直接修改生产配置。

## 7. K 线和时间规则

### 7.1 数据使用

- 回测和实盘都由 1m K 线驱动。
- 指标计算只能使用 `get_closed_data()` 返回的已闭合 K 线。
- 多周期策略必须对每个周期分别调用 `get_closed_data()`。
- 数据不足、指标为 NaN 或价格无效时返回 `hold`。

### 7.2 入场和出场价格

- 入场判断优先使用 `analyze()` 的 `realtime_price`。
- `realtime_price` 不可用时，才能回退到最后一根已闭合 K 线。
- 出场判断使用 `check_realtime_exit()` 的 `current_price`。
- 不要使用尚未闭合的大周期 K 线收盘价作为入场依据。

### 7.3 时间戳

- 全部时间使用 UTC。
- `entry_timestamp` 使用 10 位秒级时间戳。
- 信号时间使用当前 K 线时间，不使用无时区的 `datetime.now()`。

## 8. 仓位、冷却和退出

- 同一入场周期 K 线的重复触发由 `BaseStrategy` 控制。
- 止损日冷却由 Core 的 `analyze()` 检查 `state.stop_loss_date`。
- `check_realtime_exit()` 持仓时必须先调用 `update_pnl_extremes()`。
- 所有退出路径统一调用 `_notify_exit_and_clear()`。
- 需要在退出后使用的策略字段，应在 `_notify_exit_and_clear()` 前保存。
- 实盘仓位保存到 `data/positions/{strategy_name}.json`。
- 回测模式自动禁用实盘仓位持久化。

## 9. 测试

先验证模块能够导入：

```powershell
python -c "from strategies.my_strategy.strategy import Strategy; print('OK')"
```

运行策略单元测试：

```powershell
python -m pytest strategies/my_strategy/tests -v
```

最低测试范围：

- 多头和空头入场。
- 多头和空头退出。
- 止损日冷却。
- 已闭合 K 线边界。
- 数据不足和 NaN 指标。
- 状态序列化与恢复。
- 多标的状态隔离。

## 10. 准备回测数据

当前 CLI 默认数据目录为 `./data/strategies`，目录结构为：

```text
data/strategies/
├── 1m/
│   ├── BTCUSDT_1m.csv
│   └── ETHUSDT_1m.csv
├── 15m/
├── 1h/
├── 4h/
└── 1d/
```

1m CSV 至少包含：

```text
timestamp,open,high,low,close,volume
```

建议保留完整格式：

```text
timestamp,open,high,low,close,volume,quote_volume,count,taker_buy_volume,taker_buy_quote_volume
```

时间戳示例：

```text
2026-04-01 00:00:00+00:00
```

回测框架会从 1m 数据聚合所需的大周期数据。数据应覆盖：

- 指定回测区间。
- 回测开始前的指标预热区间。

## 11. 运行单策略回测

新策略直接使用完整目录名，不需要先添加 CLI 简称：

```powershell
python -m backtest.run_backtest --strategy my_strategy --start 20260101 --end 20260331 --symbol BTCUSDT --data-dir ./data/strategies --config strategies/my_strategy/config.test.yaml --log-level WARNING
```

常用参数：

| 参数 | 说明 |
|------|------|
| `--strategy` | 策略简称或完整目录名 |
| `--start` | 开始日期，支持 YYYYMMDD、秒或毫秒时间戳 |
| `--end` | 结束日期，省略时使用当前时间 |
| `--symbol` | 交易对；CLI 支持逗号分隔 |
| `--data-dir` | K 线根目录，默认 `./data/strategies` |
| `--output-dir` | 输出目录，默认 `./backtest_output` |
| `--cash` | 初始资金，CLI 默认 5000 |
| `--commission` | 手续费率，默认 0.0004 |
| `--config` | 策略配置路径 |
| `--overrides` | JSON 格式的临时配置覆盖 |
| `--log-level` | DEBUG、INFO、WARNING 或 ERROR |

临时覆盖参数示例：

```powershell
python -m backtest.run_backtest --strategy my_strategy --start 20260101 --end 20260331 --symbol BTCUSDT --config strategies/my_strategy/config.test.yaml --overrides '{"params":{"ma_period":50}}'
```

回测输出通常包括：

- `*_report.txt`：可读摘要。
- `*_result.json`：完整指标。
- `*_equity.csv`：权益曲线。
- `*_trades.csv`：交易和信号明细。

## 12. 批量回测

批量回测入口：

```powershell
python -m backtest.batch_runner
```

配置文件为 `backtest/config/main.yaml`：

```yaml
start: "20260101"
end: "20260331"
data_dir: "./data/strategies"
output_dir: "./backtest_output"
max_workers: 4
log_level: "WARNING"

strategies:
  - name: my_strategy
    symbols:
      - BTCUSDT
      - ETHUSDT
    enabled: true
```

CLI 可以覆盖时间：

```powershell
python -m backtest.batch_runner --start 20260101 --end 20260331
```

## 13. 提交前检查

- [ ] 目录名、`STRATEGY_TYPE` 和配置顶层键一致。
- [ ] `Strategy`、Core、State 使用新架构基类。
- [ ] `Strategy` 类不计算技术指标。
- [ ] 每个指标周期都加入 `_get_indicator_timeframes()`。
- [ ] 指标只使用已闭合 K 线。
- [ ] 入场使用 `realtime_price`。
- [ ] 出场先更新盈亏极值。
- [ ] 退出统一调用 `_notify_exit_and_clear()`。
- [ ] UTC、秒级时间戳和 K 线时间使用正确。
- [ ] 特有状态可以序列化和恢复。
- [ ] `config.test.yaml` 存在且可加载。
- [ ] 导入测试和单元测试通过。
- [ ] 至少完成一次包含预热数据的回测。
- [ ] 检查回测报告、交易明细、回撤和手续费配置。

## 14. 当前代码与旧文档的差异

开发和回测时以当前代码为准：

- 当前 `analyze()` 参数包含 `realtime_price` 和 `current_cash`。
- 当前 CLI 默认资金为 5000，默认手续费率为 0.0004。
- 当前 CLI 默认数据目录为 `./data/strategies`。
- 部分内置简称仍指向旧策略目录；测试新策略时应传完整目录名。
- 当前数据查找路径是 `{data_dir}/{timeframe}/{SYMBOL}_{timeframe}.csv`。

## 15. 参考入口

- `ARCHITECTURE.md`
- `docs/strategy/QUICKSTART.md`
- `docs/strategy/DEVELOPMENT_GUIDE.md`
- `docs/strategy/REVIEW_CHECKLIST.md`
- `strategy_core/base/strategy.py`
- `strategy_core/base/core.py`
- `strategy_core/base/state.py`
- `backtest/run_backtest.py`
- `backtest/README.md`
