# Trading Dev Skill — 功能说明与时序分析

## 一、定位

`trading-dev` 是一个 **CTA 策略开发全生命周期 skill**，覆盖从"一句话策略描述"到"可交付的 benchmark 报告"的完整链路：

```
项目脚手架 → 策略编码 → 回测验证 → benchmark 输出
```

核心特色是 **loop-engineering**：Phase 2（开发）与 Phase 3（回测）形成跨 Phase 大闭环，回测不达标自动回退改策略再回测，最多 5 轮。

## 二、三种运行模式

| 模式 | 触发 | 行为 |
|------|------|------|
| **全自动** | `/trading-dev new --from <source>` 或 `/trading-dev new <描述>` | 零交互跑到底，每步静默执行，仅阻塞项报错 |
| **交互** | `/trading-dev new` | 逐步展示结果、每步等用户确认 |
| **半交互** | `/trading-dev new --interactive --from <source>` | 自动解析策略信息，但每步前确认 |
| **单步** | `/trading-dev scaffold\|develop\|backtest\|benchmark` | 只跑指定 Phase |

`--from` 接受 4 种输入形态：文件路径、策略目录（逆向提取 spec）、URL（WebFetch）、自然语言描述。

## 三、Phase 构成（功能分解）

### Phase -1：交互式引导（仅无参数时）
无参数 `/trading-dev` 时进入，3 步引导：问子命令 → 问策略来源 → 汇总确认 → 转 Phase 0。原则是"缺啥补啥、一步一问、不报错"。

### Phase 0：环境预检 + 策略信息获取
- **Step 0 环境预检**：Python 3.10+（阻塞）、ta-lib C 库（非阻塞降级）、pip（阻塞）、K线数据（非阻塞自动修复）、磁盘≥2G（非阻塞警告）。
- **Step 1 策略信息获取**：按输入形态（文件/目录/URL/自然语言/多轮对话）解析，统一收敛为策略规格 `.strategy-spec.yaml`。
- **Step 3 执行确认**：全自动直接跑，交互式展示后等确认。

### Phase 1：项目脚手架创建（一次性）
- 复制模板全量代码（`strategy_core/`、`backtest/`、`data_manager/`、`scripts/`、`config/`、`docs/`、入口脚本）。
- 创建 venv + 安装依赖（ta-lib 缺失自动降级）。
- 准备 1m K线数据：优先 symlink 已有数据，否则运行 `scripts/download_data.py` 从 Binance 下载。
- git init + 首次 commit。
- 输出就绪报告。

### Phase 2：策略开发
- **强制先读规范文档**（QUICKSTART/DEVELOPMENT_GUIDE/AI_CONSTRAINTS/REVIEW_CHECKLIST/EXAMPLES）。
- 生成 `strategy.py`（~35行接口类）、`{prefix}_core.py`（State + Core.analyze/exit）、`__init__.py`、per-symbol overrides YAML、编排登记 `config/strategies.yaml`、测试文件。
- v3.7 关键设计：**每个 (策略,代币) 一份 `overrides/{SYMBOL}.yaml`，实盘回测共用同一份参数**（消除回测失真根源）。
- 注册策略、验证配置格式、跑 REVIEW_CHECKLIST。

### Phase 3：回测验证
- 短期/中期/长期三轮回测，统一用 `scripts/run_backtest_batch.sh`，只换 `--start/--end`。
- 验收标准：至少一个代币费后收益 ≥ 20%。
- 解析 `backtest_result.json` 的 `metrics` 段。
- Step 5 输出 `benchmark.md`（可指向 Obsidian）。

### Loop-Engineering（跨 Phase 2↔3 大闭环）
回测未达标时进入动态诊断式调参：
1. 解析回测 metrics + trades 提取诊断数据
2. 读取策略代码提取可调参数 + 硬编码阈值
3. 症状模式匹配（10 种症状→诊断→调整方向表）
4. 生成修改方案，**每轮只改一个主维度**，确保可归因
5. 回到 Phase 2 改代码 → Phase 3 重测，最多 5 轮

---

## 四、时序分析

### 时序图（完整执行流）

```
用户
 │
 ├─ /trading-dev [无参数] ──────────────────────────────┐
 │                                                      ▼
 │                                              ┌────────────────┐
 │                                              │ Phase -1 引导  │
 │                                              │ 问子命令→来源  │
 │                                              │ →汇总确认      │
 │                                              └───────┬────────┘
 │                                                      │
 ├─ /trading-dev new --from X (全自动) ────────────────►│
 ├─ /trading-dev new (交互) ───────────────────────────►│
 ├─ /trading-dev scaffold|develop|backtest|benchmark ──►│(单步直达对应Phase)
 │                                                      ▼
 │   ┌─────────────────────────────────────────────────────────────┐
 │   │ Phase 0: 环境预检 + 策略信息获取                              │
 │   │  Step0 预检(Python/ta-lib/pip/K线/磁盘)                       │
 │   │    └─阻塞项(Python/pip)失败 → 报错退出                        │
 │   │  Step1 解析来源(文件/目录/URL/NL/对话) → 策略规格             │
 │   │  Step3 确认(全自动自动过 / 交互等y)                           │
 │   └────────────────────────────┬────────────────────────────────┘
 │                                ▼
 │   ┌─────────────────────────────────────────────────────────────┐
 │   │ Phase 1: 脚手架创建（一次性）                                 │
 │   │  复制模板 → venv+依赖 → K线数据(symlink/下载) → git init     │
 │   └────────────────────────────┬────────────────────────────────┘
 │                                ▼
 │   ┌───────────────────── Loop (最多 5 轮) ─────────────────────┐
 │   │                                                             │
 │   │  Phase 2: 策略开发                                          │
 │   │   读规范文档 → 生成代码 → 注册 → 验证配置 → 审查检查表       │
 │   │                          │                                  │
 │   │                          ▼                                  │
 │   │  Phase 3: 回测验证                                          │
 │   │   短期(06.01-07.09) → 中期(01.01-07.09) → 长期(2025.01-...) │
 │   │   解析 backtest_result.json                                 │
 │   │                          │                                  │
 │   │            ┌─────────────┴──────────────┐                   │
 │   │            ▼                            ▼                   │
 │   │      达标(≥20%)?                    未达标                    │
 │   │      → 输出 benchmark.md         → 动态诊断                   │
 │   │         + 完成              1.解析metrics+trades              │
 │   │                              2.提取可调参数                   │
 │   │                              3.症状模式匹配                   │
 │   │                              4.生成修改方案(每轮1主维度)       │
 │   │                                  │                           │
 │   │                                  └──► 回 Phase 2 (下一轮)    │
 │   │                                                             │
 │   │   达最大轮次 → 输出最佳结果 + 未达标标记                       │
 │   └─────────────────────────────────────────────────────────────┘
 │                                ▼
 └─ 完成: benchmark.md 路径 + 回测结果摘要
```

### 时序关键点

1. **单步模式跳过引导与前置 Phase**：`scaffold` 直达 Phase 1；`develop` 直达 Phase 2（需已有脚手架 + spec）；`backtest` 直达 Phase 3（需已有代码 + K线）。

2. **Phase 1 只执行一次**：Loop 闭环只在 Phase 2↔3 之间，脚手架不重复创建。

3. **阻塞点只有两个**：Python 3.10+ 和 pip。其余（ta-lib、K线数据、磁盘）均为非阻塞，自动降级或修复。

4. **Loop 终止条件**（三选一）：
   - 长期回测 ≥ 20% → 达标，输出 benchmark
   - 未达标但未到 5 轮 → 诊断后回 Phase 2
   - 达到 5 轮 → 输出当前最佳 + 未达标标记

5. **调参时序约束**：每轮只改一个主维度（可归因）；首次步长 ±20%；连续 2 轮同维度无改善须换维度；回撤 >30% 优先处理风控再处理收益。

6. **数据流时序**：策略规格 `.strategy-spec.yaml`（Phase 0 产出）→ 驱动 Phase 2 代码生成 → per-symbol `overrides/{SYMBOL}.yaml` 同时供实盘 `run_strategy.py` 与回测 `run_backtest.py` 读取（单一事实来源）→ 回测产物 `backtest_result.json` 的 `metrics` 段 → 驱动 Loop 诊断。

7. **配置时序（v3.7 收敛）**：`backtest/config/` 整族已删，配置收敛为 `config/` 三层（settings/strategies/backtest.yaml run-profile），全部入库；私有值走 `.env`。回测 CLI 收敛为 7 个参数，`--config/--symbol/--output` 已删，参数来源是 `--strategies name:symbol` + overrides。

---

## 五、命令速查

| 命令 | 模式 | 说明 |
|------|------|------|
| `/trading-dev` | 引导 | 无参数 → 进入交互式引导 |
| `/trading-dev new` | 交互 | 逐步确认策略信息、环境变量、每步执行 |
| `/trading-dev new --from <source>` | 全自动 | 从文件/目录/URL/描述提取策略信息，零交互跑到底 |
| `/trading-dev new <描述文本>` | 全自动 | 从自然语言提取策略信息，零交互跑到底 |
| `/trading-dev new --interactive --from <source>` | 半交互 | 自动解析策略信息，但每步前确认 |
| `/trading-dev scaffold` | 单步 | 只创建脚手架（Phase 1） |
| `/trading-dev develop` | 单步 | 只生成策略代码（Phase 2） |
| `/trading-dev backtest` | 单步 | 只跑回测验证（Phase 3） |
| `/trading-dev benchmark` | 单步 | 只输出 benchmark 报告（Phase 3 Step 5） |

### `--from` 支持的输入形态

| 输入形态 | 示例 | 解析策略 |
|----------|------|----------|
| 文件路径 | `--from /path/to/strategy_doc.md` | Read 文件，解析内容 |
| 策略目录 | `--from /path/to/cta_ict_v4/` | 读已有策略代码，逆向提取 spec |
| URL | `--from https://...` | WebFetch 抓取 |
| 自然语言 | `/trading-dev new 开发一个 EMA 交叉策略，4h，BTCUSDT` | 从描述提取 |
| 省略 | `/trading-dev new` | 进入多轮对话收集策略信息 |

---

## 六、环境变量清单

### 必需配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DATA_PATH` | `./data` | K线数据存储路径 |
| `CTA_ENV` | `dev` | 运行环境（dev/test/prod） |
| `BENCHMARK_OUTPUT_PATH` | `./benchmark_output` | benchmark 报告输出路径 |
| `KLINE_DATA_DIR` | `${DATA_PATH}/strategies/1m` | 1m K线数据源目录（symlink 目标） |

### 服务配置（实盘模式需要）

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `FACTORY_ENDPOINT` | `http://127.0.0.1:8888` | 策略工厂服务地址 |
| `POSITION_PROXY_URL` | `http://127.0.0.1:8889` | 仓位代理服务地址 |
| `CALLBACK_PORT` | `8892` | 策略回调端口 |
| `CALLBACK_HOST` | `0.0.0.0` | 回调监听地址 |
| `KLINES_WS_URL` | `ws://127.0.0.1:17081/ws/klines` | K线 WebSocket 地址 |
| `KLINES_HTTP_URL` | `http://127.0.0.1:17081` | K线 HTTP 地址 |

### 可选服务配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `KAFKA_BROKERS` | `127.0.0.1:9092` | Kafka 集群地址 |
| `KAFKA_TOPIC` | `biance_klines` | Kafka 主题 |
| `SIGNAL_HUB_ENDPOINT` | `http://127.0.0.1:18888` | 信号推送中心 |
| `OPENVIKING_SERVER_URL` | `http://127.0.0.1:1933` | OpenViking 服务器 |
| `OPENVIKING_ROOT_API_KEY` | （空） | OpenViking API Key |
| `POLYMARKET_WALLET_KEY` | （空） | Polymarket 钱包私钥 |
| `POLYMARKET_FUNDER_ADDRESS` | （空） | Polymarket 资金方地址 |
| `DERIBIT_API_KEY` | （空） | Deribit API Key |
| `DERIBIT_API_SECRET` | （空） | Deribit API Secret |

---

## 七、回测验收标准

| 周期 | 时间范围 | 验收标准 |
|------|----------|----------|
| 短期 | 20260601-20260709 | 至少一个代币费后收益 ≥ 20% |
| 中期 | 20260101-20260709 | 至少一个代币费后收益 ≥ 20% |
| 长期 | 20250101-20260709 | 至少一个代币费后收益 ≥ 20% |

三个周期都用同一条批量命令，只换 `--start` / `--end`，经 `scripts/run_backtest_batch.sh` 调用。并发由 `config/backtest.yaml` 的 `max_workers` 控制；策略参数自动读 `strategies/{strategy_name}/overrides/<SYMBOL>.yaml`。

---

## 八、Loop-Engineering 调参诊断表

| 症状模式 | 诊断 | 可能的调整方向 |
|----------|------|---------------|
| `total_trades < 10` 且 `trading_days > 90` | 入场条件过严或信号稀疏 | 放宽入场阈值 / 增加辅助确认指标 / 缩短指标周期 |
| `total_trades < 5` 且 `trading_days > 90` | 几乎没有触发信号 | 多周期条件互斥 / 指标周期过长 |
| `win_rate < 30%` 且 `profit_factor < 1.0` | 入场逻辑方向性错误 | 检查信号方向 / 入场条件逻辑是否取反 |
| `win_rate < 30%` 且 `profit_factor > 1.5` | 少数大赢覆盖多数小亏，胜率低 | 收紧止损 / 加宽止盈 |
| `max_drawdown > 30%` 且 `win_rate > 50%` | 单笔亏损过大 | 收紧止损倍数 / 减小单笔仓位 |
| `max_drawdown > 30%` 且 `win_rate < 40%` | 连续亏损累积 | 增加冷却期 / 增加趋势过滤 |
| `profit_factor < 1.0` 且 `total_trades > 30` | 频繁交易但平均亏损 | 提高入场门槛 / 加大止盈空间 |
| `total_return < 0` 且手续费占比 > 50% | 手续费吃掉利润 | 减少交易频率 / 提高单笔最低收益 |
| `短期好长期差` | 策略过拟合或市场结构变化 | 放宽参数 / 增加市场状态识别 |
| `单币种好其他差` | 参数只适配特定品种 | 分币种调参 / 增加品种自适应 |

### 修改规则
1. **每轮只改一个主维度**，辅维度最多一个，确保可归因
2. **参数修改幅度**：首次调整步长为当前值的 ±20%（或参数合理范围的 1/3），后续轮次根据上轮效果缩放步长
3. **代码修改优先级**：优先调参（改 overrides YAML）→ 调阈值（改 core.py 硬编码）→ 调逻辑（改 core.py 条件判断）
4. **禁止归因模糊**：连续 2 轮修改同维度无改善，换一个本质不同的维度
5. **回撤优先**：`max_drawdown > 30%` 时优先处理风控（止损/仓位/冷却），再处理收益

---

## 九、关键约束

### 编码红线（来自 AI_CONSTRAINTS.md）

| # | 约束 | 原因 |
|---|------|------|
| 1 | 禁止入场用未闭合 K 线 | 未来函数，回测失真 |
| 2 | 禁止 `datetime.now()` 做时间戳 | 用 K 线时间，保证可重现 |
| 3 | 禁止 Strategy 类算指标 | 指标在 Core.analyze() 内用已闭合 K 线 |
| 4 | 禁止跳过数据不足检查 | 指标计算错误 |
| 5 | 禁止回测模式启用 K 线冷却 | 回测信号缺失 |
| 6 | 禁止可变默认值 | `[]`, `{}` 共享状态 |
| 7 | 禁止缓存字段持久化 | 缓存不进 `to_persist_dict()` |
| 8 | 禁止自定义止损计数字段 | 用 `BaseState.stop_loss_date` |
| 9 | 禁止直接用原始 K 线入场 | 多周期必须 `get_closed_data()` |

### 开源约束

| # | 约束 |
|---|------|
| 1 | 禁止硬编码内网 IP（`192.168.x.x`），必须走环境变量 |
| 2 | 禁止硬编码个人路径（`/home/xxx`），用相对路径或 `DATA_PATH` 环境变量 |
| 3 | 禁止在代码中写入 API Key / Secret，用 `.env` + `.gitignore` |
| 4 | `config/settings.yaml` 不进模板，用 `settings.example.yaml` 替代 |
| 5 | 测试中 mock IP 可保留，但需加注释说明是假数据 |
