# 回测实盘配置统一规范

> 适用版本：CTA Strategy Core v3.7.0（开源前定稿）
> 文档定位：开源治理 P0。本文不是"使用说明"，是**配置分叉的根因定位 + 收敛方案 + 验收标准**。
>
> **状态：已实施完成（2026-08-17）。**
> §1–§3 描述的是**收敛前的历史状态**——其中提到的 `backtest/config/main.yaml`、
> `backtest/config/strategies.yaml`、`--backtest-config`、`--strategy` 等均已删除，
> 保留作为根因记录与决策依据，**不代表当前代码**。当前用法见
> [SCRIPTS.md](SCRIPTS.md) 与 [../backtest/README.md](../backtest/README.md)。
>
> 验收结果：**数值等价通过**——收敛前后同一命令的 `backtest_result.json`
> 除 3 个时间戳字段外 34/37 字段逐位一致，证明修掉了分叉而未改变策略行为。

---

## 0. TL;DR

**核心问题不是"配置文件太多太复杂"，而是"回测和实盘读两份不同的参数"。**

证据：同一策略 `sar_snt3_v3` 同一交易对 `BTCUSDT`，在 `backtest/config/` 下是
`timeframes=4h / exchange=binance / max_cash=1000 / leverage=5`，在
`strategies/overrides/` 下是 `timeframes=8h / exchange=hyperliquid / max_cash=200 / leverage=1`。
**全部 14 个交易对、5 个关键字段全部冲突**（见 §2.2）。

这意味着：**回测在验证一个实盘根本没有运行的策略配置。** 它的危害等价于 CLAUDE.md
"编码红线"里的未来函数——都让回测结果失去对实盘的预测效力，但当时未被写进红线清单，
长期被当作整洁度问题对待，优先级被系统性低估。

**决策（已拍板）：一刀切删除 legacy 配置族，不保留兼容层。**

收敛目标三层模型：

```
config/settings.yaml        # 系统层：数据源/日志/推送（${VAR} 占位）
config/strategies.yaml      # 编排层：跑哪些策略 × symbol
strategies/<name>/
  config.yaml               # 策略默认参数
  overrides/<SYM>.yaml      # per-symbol 唯一事实来源
```

配置文件类别 7 → 3，`run_backtest.py` CLI 参数 16 → 8，新用户 clone 后 ≤3 条命令跑通回测。

---

## 1. 现状架构：四个入口读什么

### 1.1 入口清单（共 2898 行）

| 入口 | 行数 | 角色 | 读哪个配置 |
|------|------|------|-----------|
| `run_strategies_manager.py` | 819 | 实盘总管：拉起 N 个策略子进程 | `config/settings.yaml` + `config/strategies.yaml` |
| `run_strategy.py` | 644 | 单策略进程（被 manager 拉起，也可独立跑） | `config/settings.yaml` + `strategies/<name>/overrides/<SYM>.yaml` |
| `backtest/run_backtest.py` | 1042 | 单标的回测（16 个 CLI 参数） | CLI + `strategies/<name>/overrides/<SYM>.yaml`（新格式）/ `backtest/config/<name>/<SYM>.yaml`（旧格式） |
| `backtest/batch_runner.py` | 393 | 批量回测，subprocess 调 run_backtest | `config/strategies.yaml` + `backtest/config/main.yaml`（双格式自动检测） |

### 1.2 配置加载链路（实际代码追踪）

**实盘链路（已收敛，健康）**：

```
run_strategies_manager.py
  ├─ --config        → config/settings.yaml        （系统层）
  ├─ --strategies    → config/strategies.yaml      （编排层：name × symbols × trading_mode）
  └─ --run name:sym  → 覆盖登记表，强制读 overrides
        │
        └─ StrategiesLoader.load()  [strategy_core/utils/strategies_loader.py]
              展开 strategies 段 → 每个 symbol 生成 StrategyInstance
              config_path = strategies/<name>/overrides/<symbol>.yaml   ← 单一事实来源
                    │
                    └─ subprocess → run_strategy.py
                          ├─ --config-path  → 上面那个 overrides（CLI 优先）
                          ├─ --global-config → config/settings.yaml
                          └─ interval/version/trading_mode 缺失时从 overrides 的 timeframes[0]/version/trading_mode 补全
```

证据：`strategies_loader.py:343`（per-symbol 路径生成）、`run_strategy.py:516`（默认 overrides 路径）、
`run_strategy.py:529-531`（CLI > overrides > 默认值的优先级）。

**回测链路（分叉，病灶）**：

```
backtest/batch_runner.py
  ├─ --config         → config/strategies.yaml（新格式）或 backtest/config/strategies.yaml（旧）
  ├─ --backtest-config→ backtest/config/main.yaml（回测参数：start/end/data_dir/output_dir）
  └─ 自动检测：config_data["strategies"] 是 dict → 新格式；否则走旧格式分支  [batch_runner.py:77-91]
        │
        ├─ 新格式 _build_tasks_from_loader()    → 读 strategies/overrides（✅ 与实盘同源）
        └─ 旧格式 _build_tasks_from_main_yaml() → 读 backtest/config/<name>/<SYM>.yaml（❌ 分叉源）
                    │
                    └─ subprocess → run_backtest.py --config-path <那个分叉的文件>
```

`run_backtest.py` 的 `--config-path` 指向哪，回测就读哪。新格式指向 `strategies/overrides`
（与实盘同源，健康）；旧格式指向 `backtest/config/<name>/<SYM>.yaml`（与实盘分叉，失真）。

**问题本质**：代码同时存在两条路径，配置文件同时存在两份，靠"自动检测"决定走哪条——
而自动检测的判据是"strategies 段是不是 dict"，与策略参数本身无关。一旦旧文件还在，
回测随时可能读到一个实盘没跑的配置。

---

## 2. 配置分叉全量证据

### 2.1 七类配置文件清单

| # | 文件 | 类别 | 行数/份数 | 归属层（应） | 状态 |
|---|------|------|-----------|-------------|------|
| 1 | `config/settings.yaml` | 系统 | 84 | 系统层 | ✅ 保留（实盘/回测共用） |
| 2 | `config/backtest.yaml` | 系统（回测副本） | 62 | 系统层 | ⚠️ 与 settings.yaml 内容重复，仅 `signal_hub.api_path` 不同，**已无人引用** → 删 |
| 3 | `config/strategies.yaml` | 编排 | 48 | 编排层 | ✅ 保留 |
| 4 | `backtest/config/main.yaml` | run-profile | 45 | run-profile层 | ✅ 已删除，迁为 `config/backtest.yaml` |
| 5 | `backtest/config/strategies.yaml` | 编排（legacy副本） | 301 | 编排层 | ❌ 删（与 #3 重复且含大量注释掉的死策略） |
| 6 | `backtest/config/<name>/<SYM>.yaml` | per-symbol（回测侧） | 25 份 | 策略层 | ❌ 删（与 #7 分叉的根源） |
| 7 | `strategies/<name>/overrides/<SYM>.yaml` | per-symbol（实盘侧） | 14 份 | 策略层 | ✅ 唯一保留 |

### 2.2 分叉全量清单（sar_snt3_v3，14 个 symbol × 5 字段）

逐 symbol 对比 `backtest/config/sar_snt3_v3/<SYM>.yaml`（回测侧）与
`strategies/sar_snt3_v3/overrides/<SYM>.yaml`（实盘侧）关键字段：

| 字段 | 回测侧（backtest/config/） | 实盘侧（overrides/） | 是否冲突 |
|------|--------------------------|---------------------|---------|
| `timeframes` | 4h | 8h | ❌ 冲突 |
| `signal.exchange` | binance | hyperliquid | ❌ 冲突 |
| `capital.max_cash` | 1000 | 200 | ❌ 冲突 |
| `capital.leverage` | 5 | 1 | ❌ 冲突 |
| `trading_mode` | （未设置） | paper_trading（除 BTC 外多数） | ❌ 冲突 |
| `user_id` | （未设置） | 12 | ⚠️ 残留（见 §3.1） |

**14 个 symbol 全部冲突，无一幸免。** 这不是个别配置写错，是整套回测配置与实盘配置
系统性背离——回测在跑 `4h/binance/5x/1000` 的策略，实盘在跑 `8h/hyperliquid/1x/200` 的策略，
两者除了策略名相同，参数完全不同。

### 2.3 孤儿配置

`backtest/config/obv_atr_v2/`（10 份）在实盘侧**完全不存在** overrides，且
`config/strategies.yaml` 也未登记 `obv_atr_v2`。

**含义**：这是一个"只回测、从未实盘"的策略。其回测结果无法用实盘验证，反过来也成立——
这类配置在开源版里属于"无人能解释它对不对"的死代码，应随 legacy 一起清理，或
显式迁入 `strategies/obv_atr_v2/overrides/` 并在 strategies.yaml 登记（需策略 owner 确认参数）。

---

## 3. 开源就绪审计

### 3.1 密钥与部署残留（P0，发版前必修）

| 位置 | 类型 | 处理 |
|------|------|------|
| `strategies/sar_snt3_v3/overrides/*.yaml`（14 处） | `user_id: 12` | 脱敏为占位或删除字段 |
| `backtest/config/obv_atr_v2/*.yaml`（10 处） | `user_id: 6` | 随 legacy 删除 |
| `ARCHITECTURE.md:318,329,330,338,459,460,470`（7 处） | 真实内网 IP（本文示例已脱敏为 RFC5737 地址） + 端口 | 改为 `${VAR}` 占位 |
| `.env` | 全注释/空值 | ✅ 无泄漏，但需确认开源时不入库（.gitignore 已覆盖） |

**注**：`config/settings.yaml` 与 `config/backtest.yaml` 本身已全部 `${VAR}` 占位，无泄漏。
风险集中在 `ARCHITECTURE.md`（文档里贴了真实 IP）和 overrides 里的 `user_id`。

### 3.2 闭源依赖耦合度（P1，影响"开箱即用"）

框架对四个外部服务的依赖，耦合点与降级行为：

| 外部服务 | 环境变量 | 耦合代码 | 未配置时行为 | 回测是否需要 |
|---------|---------|---------|------------|------------|
| cta-factory-service | `FACTORY_ENDPOINT` | `strategy_core/factory_client.py:119` | `factory_enabled=False`，跳过 RPC 注册/心跳/回调，返回 `{"status":"skipped"}` | ❌ 不需要 |
| Position 代理 | `POSITION_PROXY_URL` | `factory_client.py` 同上 | 远程仓位不可用，回退本地持久化仓位 | ❌ 不需要 |
| Signal Hub | `SIGNAL_HUB_ENDPOINT` | `signal_logging/http_sender.py` | `enabled` 仍为 true 会 HTTP 推送失败重试 | ❌ 不需要 |
| Kafka | `KAFKA_BOOTSTRAP_SERVERS` | `signal_logging/` | `kafka.enabled=false` 已默认禁用 | ❌ 不需要 |

**结论**：四个服务**全部可选**，未配置时优雅降级。回测链路（`run_backtest.py`/`batch_runner.py`）
不依赖任何 factory RPC——回测本就不该依赖实盘进程管理服务。

**但有一个坑**：`config/settings.yaml` 里 `signal_hub.enabled: true`，而 `endpoint` 是
`${SIGNAL_HUB_ENDPOINT}` 占位符。占位符解析逻辑（`run_strategy.py:50-57`）在环境变量未设时
返回 `None`，**但 `enabled` 仍是 true**——开源用户 clone 后跑实盘/模拟，HTTP 推送会
反复失败重试刷日志。**run-profile 应把 `signal_hub.enabled` 也纳入 profile 控制，回测默认关。**

### 3.3 开源版最小可运行闭环判定

| 场景 | clone 后能否跑通 | 前置条件 |
|------|----------------|---------|
| 一次回测 | ✅ 能 | 仅需本地 CSV 数据（`data/klines/`），不依赖任何外部服务 |
| paper_trading | ✅ 能 | 需 Binance 公共源可达（`KLINES_*_URL` 不设即回退 fstream），factory 不配 |
| live 实盘 | ⚠️ 需自备 | 用户需自配交易所 API + 可选 factory；框架不内置下单密钥 |

### 3.4 文档一致性（P0，发版前必修）

`ARCHITECTURE.md` 第 5 章「配置管理」整章描述的是**已不存在的旧格式**，与现码严重不符：

| 文档描述（ARCHITECTURE.md） | 实际代码 | 差异 |
|---------------------------|---------|------|
| `factory_endpoint: "http://192.0.2.23:8888"` (318行) | `${FACTORY_ENDPOINT}` 占位 | 内网 IP 泄漏 + 未脱敏 |
| `klines_service_ws_url: "ws://127.0.0.1:17081/..."` (329行) | `${KLINES_WS_URL}` 占位 | 真实端口泄漏 |
| `bootstrap_servers: "192.0.2.23:9092"` (338行) | `${KAFKA_BOOTSTRAP_SERVERS}` 占位 | 内网 IP 泄漏 |
| settings.yaml 内嵌 `strategies:` 列表（341-349行） | strategies 已拆到独立 `config/strategies.yaml` | 格式过时 |
| `config_path: "config/strategies/cta_ict_v3/BTCUSDT.yaml"` | 实际在 `strategies/<name>/overrides/<SYM>.yaml` | 路径过时 |
| `config.dev.yaml / config.test.yaml / config.prod.yaml` 多环境 (381行) | 代码无此加载逻辑 | 幻觉特性 |

**同类问题**：`docs/SCRIPTS.md`（8 处引用 `backtest/config/main.yaml`）、`backtest/README.md`
（5 处引用 legacy）、若干测试文件。

本文档是配置收敛的 P0 落地版；P2 候选事项（如 `scripts/validate_config.py`
配置校验脚本）见下方问题清单，立项时再细化。

### 3.5 许可证与第三方合规（P2）

- LICENSE = Apache-2.0 ✅
- `requirements.txt` 依赖抽查：`aiohttp`(Apache-2.0)/`pyyaml`(MIT)/`pandas`(BSD)/
  `numpy`(BSD)/`python-binance`(MIT)/`kafka-python-ng`(Apache-2.0)/`defusedxml`(BSD)——
  **无 GPL/AGPL 传染性依赖**，与 Apache-2.0 兼容。
- Apache-2.0 建议补 `NOTICE` 文件（P2）。
- 交易所 API 使用条款、投资免责声明：需在 README 补"本框架不提供投资建议，使用者自负盈亏"（P1）。

### 3.6 阻塞项总览

| 级别 | 项 | 证据 | 动作 |
|------|---|------|------|
| P0 | 配置分叉（回测 vs 实盘读两份参数） | §2.2 全量清单 | 删 legacy，统一 overrides（§4） |
| P0 | ARCHITECTURE.md 内网 IP 泄漏 + 整章过时 | §3.4 | 改占位 + 重写第 5 章 |
| P0 | overrides 内 `user_id` 残留 | §3.1 | 脱敏 |
| P0 | backtest.yaml/settings.yaml 的 `signal_hub.enabled=true` 误导 | §3.2 | 纳入 profile，回测默认关 |
| P1 | 文档 legacy 引用（SCRIPTS.md/backtest README 等） | §3.4 | 收敛后同步更新 |
| P1 | 投资免责声明 | §3.5 | README 补充 |
| P2 | NOTICE 文件 | §3.5 | 新增 |
| P2 | 配置校验脚本 | 新增 `scripts/validate_config.py`（尚未立项） | 落地 |

---

## 4. 三层配置模型定义

### 4.1 层次与职责边界

```
┌─────────────────────────────────────────────────────────┐
│ 第 0 层  环境变量  .env（不入库，仅 .env.example）        │
│   服务地址 / 密钥实际值。运行时 source .env 注入。        │
├─────────────────────────────────────────────────────────┤
│ 第 1 层  系统层    config/settings.yaml                   │
│   数据源/信号日志/引擎全局参数。${VAR} 占位，实盘回测共用。 │
│   不含策略列表，不含策略参数。                            │
├─────────────────────────────────────────────────────────┤
│ 第 2 层  编排层    config/strategies.yaml                  │
│   跑哪些策略 × 哪些 symbol × 什么 trading_mode。           │
│   实盘回测共用同一份。不重复策略参数。                     │
├─────────────────────────────────────────────────────────┤
│ 第 3 层  策略层    strategies/<name>/                      │
│   config.yaml              策略默认参数                   │
│   overrides/<SYM>.yaml     per-symbol 唯一事实来源         │
│   回测与实盘都读这一份。参数差异只能通过 run-profile 表达。 │
├─────────────────────────────────────────────────────────┤
│ 第 4 层  run-profile  config/backtest.yaml（仅回测）      │
│   回测运行方式：时间范围/初始资金/手续费/输出/并发数。       │
│   绝不含策略参数；键与 settings.yaml 不相交。              │
└─────────────────────────────────────────────────────────┘
```

**字段归属判定规则**（一个字段该放哪层）：

| 字段示例 | 归属层 | 判定理由 |
|---------|--------|---------|
| `timeframes`, `sar_step`, `adx_threshold` | 策略层 overrides | 决定策略行为，回测实盘必须一致 |
| `max_cash`, `leverage`, `stop_loss_pct` | 策略层 overrides | 资金/风控参数，回测实盘必须一致 |
| `exchange` | 策略层 overrides | 数据源/执行所，回测实盘必须一致 |
| `trading_mode` | 编排层 strategies.yaml | 运行模式，可 per-symbol 覆盖 |
| `start`, `end`, `commission`, `cash` | run-profile backtest | 仅回测需要 |
| `factory_endpoint`, `callback_port` | run-profile live | 仅实盘需要 |
| `signal_hub.enabled` | run-profile（回测关/实盘开） | 避免回测刷失败重试日志 |

### 4.2 合并优先级（高 → 低）

```
1. CLI 参数（--start / --strategies / --trading-mode）
2. run-profile（config/backtest.yaml，仅回测）
3. per-symbol overrides（strategies/<name>/overrides/<SYM>.yaml）  ← 策略参数单一事实来源
4. 策略默认（strategies/<name>/config.yaml）
5. 代码默认值
```

**关键不变量**：策略参数（timeframes/资金/风控/交易所）**永远只从第 3 层读取**，
CLI 和 run-profile 都不得覆盖策略参数本身——它们只能覆盖 run-profile 范畴的字段
（时间范围、并发、外部服务开关）。这是消除分叉的硬约束：**回测实盘策略参数同源的物理保证**。

### 4.3 run-profile 示例

`config/backtest.yaml`：

```yaml
# 回测 run-profile —— 只承载回测的运行方式，不含策略参数

# 时间范围（CLI --start/--end 可覆盖）
start: "20260601"
end: "20260811"        # 不设则用当前时间

# 资金与费用（回测专有，覆盖策略层 capital 用于回测核算 —— 见 §4.4 说明）
cash: 5000
commission: 0.0004    # 币安合约 taker

# 数据与输出（data_dir 必须与 settings.yaml 的 data_manager.csv_dir 一致，启动时校验）
data_dir: "./data/klines"
output_dir: "./backtest_output"
use_today_as_output_date: true
log_level: "INFO"

# 并发
max_workers: 4
```

**只写有代码消费的键。** 初版曾在此写 `mode: backtest` 以及
`signal_hub.enabled: false` / `strategy_engine.factory_enabled: false`，
意图是"文档化回测关闭外部服务"。实施后核查发现这三个键**没有任何消费者**：
回测链路根本不读 `settings.yaml`，也不初始化推送与 factory 客户端，
"回测不推送"由链路本身保证。而 `settings.yaml` 中 `signal_hub.enabled` 是
`true` —— 同一开关在两个文件里写着相反的值、且两个都不生效，正是本文档要消除的
分叉假象。故已删除，由 `test_profile_contains_no_unconsumed_keys` 防止回退。

**实盘没有 run-profile。** 初版设计了 `config/live.yaml`，但
`run_strategies_manager.py` 没有 `--profile` 参数、从不读取它，其中的
`callback_port` / `sync_history_days` / `signal_hub.enabled` 全部不生效
（真正生效的是 `config/settings.yaml` 的同名键）。一份没人读、又与真实来源
重复的配置文件是纯负债，故删除；回测/实盘差异对照见 §4.5。若将来要给 manager
加 `--profile`，必须同时删掉 `settings.yaml` 中的重复键，否则又会出现
"两处配置、谁生效不明"。

### 4.5 两处配置为什么不重复

| | `config/settings.yaml` | `config/backtest.yaml` |
|---|---|---|
| 内容 | 实盘设施：factory / signal_hub / WS / 数据目录 | 回测运行方式：时间范围 / 资金 / 费率 / 输出 / 并发 |
| 谁读 | `run_strategies_manager.py`（实盘） | `run_backtest.py`、`batch_runner.py`（回测） |
| 键集合 | **与右列完全不相交**（`test_profile_keys_disjoint_from_settings` 保证） | |

回测**不读** `settings.yaml`，实盘**不读** profile，因此不存在覆盖关系，也就不存在
"谁生效不明"。唯一的语义重复是 `data_dir` ↔ `settings.data_manager.csv_dir`：回测既然
不读 settings，就只能自己存一份。二者必须指向同一目录，否则实盘往 A 目录写、回测从 B
目录读，回测会基于过时数据得出结论 —— 属于回测失真，由
`verify_data_dir_consistency()` 在启动时校验，不一致直接退出（不靠注释约定）。

### 4.4 关于 `cash`/`commission` 的归层说明

`max_cash`（策略资金上限）属于策略层，回测实盘应一致；但回测的"初始核算资金"`cash`
和"手续费率"`commission` 是回测引擎专有的核算口径（默认 5000 / 0.0004），与策略的
`capital.max_cash`（单笔上限）语义不同。**收敛原则**：

- 策略层保留 `capital.max_cash`（决定下单规模，回测实盘一致）
- run-profile `cash`/`commission` 仅用于回测 PnL 核算起点
- 若需让回测核算口径对齐策略资金，profile 里 `cash` 引用策略值或显式标注，不删字段、不默改

这一条是收敛中最易引入数值偏差的点，迁移时必须做 §6 的等价验收。

---

## 5. 统一入口设计

### 5.1 命令格式（精简后）

| 场景 | 命令 |
|------|------|
| 实盘（全部登记策略） | `python3 run_strategies_manager.py` |
| 实盘（指定清单） | `python3 run_strategies_manager.py --run sar_snt3_v3:BTCUSDT` |
| 单策略实盘 | `python3 run_strategy.py --name sar_snt3_v3 --symbol BTCUSDT` |
| 单标的回测 | `python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260601` |
| 批量回测 | `python3 -m backtest.batch_runner` |

**回测与实盘命令对齐点**：都用 `--strategies name:symbol` 格式，都自动读
`strategies/<name>/overrides/<symbol>.yaml`。差异只在 `--profile` 选 backtest 还是 live。

### 5.2 新用户 clone 到跑通回测（≤3 条命令）

```bash
pip install -r requirements.txt
# 准备 CSV 数据（或用仓库自带示例数据）
python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260601 --end 20260811
```

0 次改配置——因为策略参数已在 `strategies/sar_snt3_v3/overrides/BTCUSDT.yaml`，
回测参数在 `config/backtest.yaml`，无需新建任何文件。

### 5.3 CLI 参数收敛：16 → 8

`run_backtest.py` 现有 16 个 `add_argument`。收敛后保留 8 个，其余下放到 profile 或删除：

| 参数 | 处置 | 理由 |
|------|------|------|
| `--strategies` | ✅ 保留 | 与实盘对齐的运行清单 |
| `--start` | ✅ 保留 | 高频覆盖项 |
| `--end` | ✅ 保留 | 高频覆盖项 |
| `--profile` | ✅ 新增 | 选 `backtest`/`live`，替代散落的回测参数 |
| `--config-path` | ✅ 保留 | 覆盖默认 overrides 路径（高级用法） |
| `--overrides` | ✅ 保留 | JSON 覆盖特定字段（高级用法） |
| `--log-level` | ✅ 保留 | 调试用 |
| `--symbol` | ✅ 保留（仅 `--strategy` 旧模式） | 向后兼容收尾 |
| `--strategy` | ❌ 删 | 已标 `[已弃用]`，统一用 `--strategies` |
| `--config` | ❌ 删 | `--config-path` 别名 |
| `--timeframe` | ❌ 删（下放 profile） | 默认 1m 写进 profile，回测不该手填 |
| `--data-dir` | ❌ 删（下放 profile） | profile `data_dir` |
| `--output-dir` | ❌ 删（下放 profile） | profile `output_dir` |
| `--cash` | ❌ 删（下放 profile） | profile `cash` |
| `--commission` | ❌ 删（下放 profile） | profile `commission` |
| `--use-today-as-output-date` | ❌ 删（下放 profile） | profile 布尔 |
| `--use-end-date-as-output-date` | ❌ 删 | 上项的反义，冗余 |

`batch_runner.py` 同步收敛：`--config`/`--backtest-config` 双参数 → 单个 `--profile`。

### 5.4 双格式自动检测的删除

`batch_runner.py:77-91` 的 `use_strategies_config` 自动检测分支、`_build_tasks_from_main_yaml()`
（143-175行）整体删除。只保留 `_build_tasks_from_loader()` 一条路径。

`backtest/config_loader.py` 中 `build_config_path`（72行）、`resolve_strategy_config_path`
（166行）等仅为旧格式服务的函数一并清理。

---

## 6. 迁移步骤与验收

### 6.1 迁移步骤（有序，每步可独立验证）

**Step 1　冻结基线（低风险）**
- 跑一次当前回测，保存 `backtest_output/sar_snt3_v3/.../BTCUSDT/backtest_result.json` 作为 baseline
- 命令：`python3 -m backtest.batch_runner --config config/strategies.yaml`
- 验证：baseline 文件存在且含完整 metrics

**Step 2　新建 run-profile（低风险）**
- 从 `backtest/config/main.yaml` 抽取 `start/end/data_dir/output_dir/max_workers/log_level/use_today_as_output_date`
  → 写入 `config/backtest.yaml`（按 §4.3 模板）
- 验证：YAML 语法正确，字段无遗漏

**Step 3　改造入口（中风险）**
- `run_backtest.py`：删 8 个 CLI 参数，新增 `--profile`，回测参数从 profile 读
- `batch_runner.py`：删双格式检测与 `_build_tasks_from_main_yaml`，`--profile` 替代 `--config/--backtest-config`
- `run_strategies_manager.py`：可选加 `--profile live`（默认即 live 行为，向后兼容）
- 验证：`python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260601` 能跑通

**Step 4　删 legacy 配置（中风险，需 §6.2 等价验收）**
- 删 `backtest/config/main.yaml`
- 删 `backtest/config/strategies.yaml`
- 删 `backtest/config/sar_snt3_v3/*.yaml`（14 份）
- 删 `backtest/config/obv_atr_v2/*.yaml`（10 份）——或先迁入 `strategies/obv_atr_v2/overrides/` 并登记（需 owner 确认）
- 删 `config/backtest.yaml`（无人引用）
- 验证：`grep -rn "backtest/config/main\|backtest/config/strategies\|BACKTEST_CONFIG_PATH" --include="*.py"` 无命中

**Step 5　清理代码（低风险）**
- 删 `batch_runner.py` 的双格式检测、`_build_tasks_from_main_yaml`
- 删 `backtest/config_loader.py` 中 `build_config_path`/`resolve_strategy_config_path`
- 验证：`python3 -m pytest backtest/tests/ data_manager/tests/ -v` 全绿

**Step 6　修文档（P0）**
- 重写 `ARCHITECTURE.md` 第 5 章（按 §4 三层模型），删内网 IP（§3.1）
- 更新 `docs/SCRIPTS.md`、`backtest/README.md` 中 legacy 引用（§3.4）
- 更新 `README.md` 命令示例为 §5.1 格式
- 验证：`grep -rn "backtest/config/main\|192\.168\." docs/ README.md ARCHITECTURE.md` 无命中

**Step 7　脱敏与免责（P0/P1）**
- 删/占位 overrides 的 `user_id`（14 处）
- README 补投资免责声明
- 验证：`grep -rn "user_id:" strategies/` 无命中（或全为占位）

### 6.2 数值等价验收（核心红线）

**目的**：证明收敛后回测结果未变。这是"修分叉"和"改策略行为"的唯一区分手段。

**方法**：

```bash
# 1. 收敛前 baseline（Step 1 已存）
cat backtest_output/sar_snt3_v3/<旧日期>/BTCUSDT/backtest_result.json | jq '.metrics'

# 2. 收敛后重跑（用新格式，读 strategies/overrides）
python3 -m backtest.run_backtest \
  --strategies sar_snt3_v3:BTCUSDT \
  --start 20260601 --end 20260811 \
  --profile backtest
cat backtest_output/sar_snt3_v3/<新日期>/BTCUSDT/backtest_result.json | jq '.metrics'

# 3. 对比关键字段（必须完全一致）
#    total_return / total_pnl / trade_count / win_rate / max_drawdown
```

**判定标准**：`total_pnl`、`trade_count`、`max_drawdown` 三项**完全一致**
（浮点 `total_return` 允许 1e-9 级误差）。一致 → 收敛未改策略行为，通过；
不一致 → 停，回溯是 Step 3 的参数读取还是 Step 4 的 cash/commission 归层引入了偏差。

**为什么这一步是红线**：本次收敛的物理意义是"回测与实盘读同一份参数"。如果收敛过程
本身改变了回测数值，那"修好了分叉"和"改变了策略"就分不清——验收就失效。
CLAUDE.md「禁止未来函数」那条红线的底层逻辑，在这里是"禁止用收敛之名行改参之实"。

---

## 7. 不做什么（scope 边界）

- **不做**配置框架替换（不引入 Hydra / Pydantic Settings）——YAML + 现有 loader 足够
- **不做**回测引擎性能优化——本轮只碰配置与入口编排
- **不做**策略逻辑改动——BaseStrategy 契约不破坏，`analyze()`/`check_realtime_exit()` 不碰
- **不做**渐进迁移/兼容层——已拍板一刀切，legacy 删除后不保留 DeprecationWarning 分支
- **不做** obv_atr_v2 参数猜测——若需保留该策略，由 owner 确认参数后迁入 overrides，不自行编造

---

## 8. 附录：关键证据索引

| 证据 | 位置 |
|------|------|
| 四入口行数 | `wc -l backtest/batch_runner.py backtest/run_backtest.py run_strategies_manager.py run_strategy.py` → 393/1042/819/644 |
| per-symbol 单一来源 | `strategies_loader.py:343`（路径生成）、`run_strategy.py:516`（默认路径） |
| CLI > overrides > 默认 优先级 | `run_strategy.py:529-531` |
| 双格式自动检测 | `batch_runner.py:77-91` |
| 旧格式分支 | `batch_runner.py:143-175`（`_build_tasks_from_main_yaml`） |
| 占位符解析 | `run_strategy.py:39-58`（`_resolve_env_placeholders`） |
| factory 降级 | `factory_client.py:119-169`（`factory_enabled`/`register` 返回 skipped） |
| 回测不依赖 factory | `grep factory backtest/run_backtest.py` 无命中 |
| settings vs backtest.yaml 重复 | `diff config/settings.yaml config/backtest.yaml`（仅 api_path 与注释差异） |
| 分叉全量 | §2.2（14 symbol × 5 字段全冲突） |
| 内网 IP 泄漏 | `ARCHITECTURE.md:318,329,330,338,459,460,470` |
| user_id 残留 | `strategies/sar_snt3_v3/overrides/*.yaml`（14）、`backtest/config/obv_atr_v2/*.yaml`（10） |
| 文档过时 | `ARCHITECTURE.md` 第 5 章（314-381行）整章描述旧格式 |

---

*本文档与 memory `config-fork-is-backtest-distortion` / `strategy-template-open-source-plan` 对齐。
实施阶段二（代码改动）由 P9-A 承接，本文档先于代码定稿，确保"先对齐再动手"。*
