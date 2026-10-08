# CTA Strategy Core - 量化交易策略核心系统

模块化量化交易策略执行框架，**单体模式**，支持多策略并行运行。每个策略独立进程，直连 Binance 行情与下单。

**版本**: 3.7.0
**许可证**: Apache-2.0

---

## 快速开始（开箱即用）

仓库自带 30 天 BTCUSDT 示例数据，**无需配置、无需外部服务，两条命令跑通一次回测**。

### 1. 安装依赖

```bash
pip install -r requirements.txt                  # 运行时依赖
pip install -r requirements-dev.txt              # 测试依赖（跑 pytest 才需要）
```

> **TA-Lib 安装**：技术指标计算依赖 TA-Lib C 库，需先装系统库再装 Python 包。
> ```bash
> # Ubuntu/Debian
> sudo apt-get install ta-lib && pip install TA-Lib
> # macOS
> brew install ta-lib && pip install TA-Lib
> ```
> 若 `pip install TA-Lib` 报找不到头文件，说明系统库未装成功——先确认 `ta_lib.h` 存在于
> `/usr/include/ta-lib/` 或 `$(brew --prefix)/include/ta-lib/`。

### 2. 跑一次回测（用自带示例数据）

```bash
python -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260610 --end 20260708
```

结果输出到 `backtest_output/sar_snt3_v3/<日期>/BTCUSDT/`，含权益曲线、交易明细、信号 CSV 与图表。

回测**不依赖任何外部服务**——回测链路不初始化任何交易所客户端（由代码保证，非配置开关）。

### 3. 下载更多数据（可选）

```bash
# 从 Binance 公共 API 下载，无需 API key
python scripts/download_data.py --symbol ETHUSDT --interval 1m --days 30

# 国内网络需在 .env 配置代理：HTTPS_PROXY=http://<host>:<port>
```

数据落到 `data/klines/{interval}/{SYMBOL}_{interval}.csv`，与回测/实盘读取路径一致。

### 4. 批量回测

```bash
# 全量：按 config/strategies.yaml 登记的策略 × symbol 并发
python3 -m backtest.batch_runner

# 只跑部分（不改登记表），格式与实盘 --run 一致
python3 -m backtest.batch_runner --run sar_snt3_v3:BTCUSDT,sar_snt3_v3:ETHUSDT
```

单次 `run_backtest` 只跑一个 `name:symbol`；多个一律走 `batch_runner`。

### 5. 模拟盘 / 实盘（可选）

```bash
cp .env.example .env
# 编辑 .env，按需填代理地址（可留空：留空则直连 Binance 公共源）

source .env && python3 run_strategies_manager.py
```

`trading_mode` 在 `config/strategies.yaml` 或 per-symbol overrides 中设置：
`paper_trading`（模拟盘，跑真实数据流但不下单）/ `live`（实盘）/ `smoking`（冒烟）。

---

## 配置体系（三层模型）

回测与实盘**共用同一份策略参数**，这是"回测可信"的物理保证。

| 层 | 文件 | 职责 |
|----|------|------|
| 环境变量 | `.env`（不入库） | 服务地址、密钥实际值 |
| 系统层 | `config/settings.yaml` | 数据源 / 信号日志 / 引擎（`${VAR}` 占位） |
| 编排层 | `config/strategies.yaml` | 跑哪些策略 × symbol × trading_mode |
| 策略层 | `strategies/<name>/overrides/<SYM>.yaml` | **per-symbol 参数唯一事实来源** |
| run-profile | `config/backtest.yaml` | 回测运行方式（时间范围 / 资金 / 费率 / 并发） |

**关键约束**：策略参数（周期 / 资金 / 风控 / 交易所）只从策略层读取；CLI 与 profile
不得覆盖策略参数，只能覆盖时间范围、并发数、输出位置。

> **回测读两份配置**：`config/settings.yaml`（与实盘共用）+ `config/backtest.yaml`
> （回测运行方式）。前者提供顶层 `use_bar_high_low_for_exit` —— 决定止损
> 止盈用 K 线 high/low 还是收盘价判定，**直接影响成交次数与 PnL**，因此必须回测实盘
> 一致，放在共用层是正确的。
>
> 两份配置的键集合**不相交**（由 `test_profile_keys_disjoint_from_settings` 保证），
> 故不存在覆盖关系。唯一的语义重复是 `data_dir` ↔ `settings.data_manager.csv_dir`，
> 二者必须指向同一目录，启动时校验，不一致直接退出。
>
> 实盘没有 `--profile` 参数：`run_strategies_manager.py` 只读 `config/settings.yaml`
> 与 `config/strategies.yaml`。

完整规范见 [docs/CONFIG_UNIFICATION_SPEC.md](docs/CONFIG_UNIFICATION_SPEC.md)。

---

## 免责声明

本项目是**量化策略研究与执行框架**，不构成任何投资建议。

- 回测结果基于历史数据与简化的成交模型（无滑点、信号价直接成交、假设充足流动性），**不代表未来表现**
- 加密货币衍生品交易具有高杠杆风险，可能导致本金全部损失
- 使用者需自行承担全部交易决策与盈亏结果
- 作者与贡献者不对使用本框架产生的任何损失负责

在投入真实资金前，请充分理解策略逻辑、在 `paper_trading` 模式下长期验证，并自行评估风险。

---

## 项目结构

```
cta-strategy-code/
├── run_strategies_manager.py  # 策略运行时管理器（入口）
├── run_strategy.py            # 策略独立进程入口
├── strategy_core/             # 核心框架
│   ├── base/                  # 策略基类
│   │   ├── strategy.py        #   BaseStrategy - 策略基类
│   │   ├── core.py            #   BaseStrategyCore - 核心逻辑基类
│   │   ├── state.py           #   BaseState - 状态基类
│   │   └── indicators.py      #   共享指标计算（ADX, EMA 等）
│   ├── signal_logging/        # 信号日志 + 信号参数构建
│   │   ├── storage.py         #   Signal 数据模型
│   │   ├── csv_adapter.py     #   CSV/JSON 格式转换
│   │   ├── signal_params.py   #   信号参数构建（overrides → CtaSignalCSV）
│   │   ├── logger.py          #   SignalStorage + SignalLogger
│   │   └── binance_trader.py  #   直连下单执行器（单体模式唯一信号出口）
│   ├── position_persistence.py# 仓位持久化
│   └── utils/                 # 工具模块
│       ├── config_loader.py   #   多环境配置加载
│       ├── strategy_loader.py #   策略加载器
│       └── strategy_naming.py #   策略命名工具
├── data_manager/              # 数据管理器
│   ├── manager.py             #   DataManager 核心（5 个核心方法）
│   ├── kline_repository.py    #   多时间框架聚合（1m→4h/1h/15m）
│   ├── klines_ws_client.py    #   WebSocket 实时 K 线接收
│   ├── klines_loader.py       #   K 线加载、重采样、CSV 持久化
│   ├── indicators.py          #   技术指标计算（ADX, RSI, MACD, BOLL...）
│   └── cache.py               #   分层缓存（1m 常驻 + 大周期 LRU）
├── strategies/                # 策略插件（每个策略一个目录）
│   └── sar_snt3_v3/           #   SAR + 情绪指标策略（参考实现）
│       ├── strategy.py        #     BaseStrategy 子类
│       ├── core.py            #     BaseStrategyCore：analyze() 信号逻辑
│       ├── state.py           #     BaseState 子类：持仓与风控状态
│       ├── config.yaml        #     策略默认参数
│       └── overrides/         #     per-symbol 参数（唯一事实来源）
├── backtest/                  # 回测框架（backtrader 适配层）
├── data/                      # 数据目录
│   ├── klines/                #   K 线数据 (CSV)，含 BTCUSDT 示例数据
│   ├── signals/               #   信号日志 (CSV)
│   └── positions/             #   仓位持久化 (JSON)
├── config/                    # 配置文件
│   ├── settings.yaml          #   系统层：数据源 / 信号 / 引擎
│   └── strategies.yaml        #   编排层：跑哪些策略 × symbol
├── scripts/                   # 工具脚本（含 download_data.py）
└── docs/                      # 文档
```

---

## 参考策略

| 策略 | 说明 | 基类架构 | 时间周期 | 多标的 |
|------|------|----------|----------|--------|
| **sar_snt3_v3** | SAR + 情绪指标趋势策略 | ✅ BaseStrategy | 1m→多周期 | ✅ |

本仓库作为**模板**发布，只保留一个完整的参考实现。新增策略请看
[docs/strategy/QUICKSTART.md](docs/strategy/QUICKSTART.md)——照 `sar_snt3_v3` 的结构，
实现 `analyze()` + `check_realtime_exit()` 两个方法即可接入回测与实盘。

---

## 文档导航

| 文档 | 说明 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 系统架构详细文档 |
| [docs/SYSTEM_OVERVIEW.md](docs/SYSTEM_OVERVIEW.md) | 系统概览和数据流 |
| [docs/SCRIPTS.md](docs/SCRIPTS.md) | 脚本和命令行工具参考 |
| [docs/SIGNAL_CSV_FORMAT.md](docs/SIGNAL_CSV_FORMAT.md) | 信号格式规范 |
| [docs/strategy/](docs/strategy/) | 策略开发文档目录 |
| [strategies/README.md](strategies/README.md) | 策略开发指南 |
| [data_manager/README.md](data_manager/README.md) | 数据管理器使用指南 |
| [backtest/README.md](backtest/README.md) | 回测框架使用指南 |

---

## 测试

```bash
# 数据管理器测试
python3 -m pytest data_manager/tests/ -v

# 回测框架测试
python3 -m backtest.tests.test_core


```

---

## 许可证

Apache License 2.0 — 见 [LICENSE](LICENSE)。

## 贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。
