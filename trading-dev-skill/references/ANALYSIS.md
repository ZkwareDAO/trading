# Trading Dev Skill — 功能说明与时序分析

## 一、定位

`trading-dev` 是一个 **CTA 策略开发全生命周期 skill**，覆盖从"一句话策略描述"到"可交付的 benchmark 报告"的完整链路：

```
项目脚手架 → 策略编码 → 回测验证 → benchmark 输出
```

核心特色是 **loop-engineering**：Phase 2（开发）与 Phase 3（回测）形成跨 Phase 大闭环，回测不达标自动回退改策略再回测，最多 5 轮。

支持两个正交维度：`STRATEGY_LANG`（python / rust）与 `STRATEGY_MARKET`（crypto / futures）。
期货**仅 Rust 模式**支持（Python 模板无 contracts/整数手/时段能力），且**不提供数据下载**，
必须先由用户给出 1m K 线路径（逐合约目录或已生成 CSV）；
Rust 模式的模板、目录、配置与命令全部以 `strategy-template-rs` 的 workspace 为准。

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
无参数 `/trading-dev` 时进入，3 步引导：问子命令 → 问策略来源 → 问语言/市场（期货追加 K 线路径/交易所/初始权益）→ 汇总确认 → 转 Phase 0。原则是"缺啥补啥、一步一问、不报错"。

### Phase 0：环境预检 + 策略信息获取
- **Step 0 主机级环境预检**（按语言/市场分叉；项目级检查在 Phase 1 复制模板后执行）：
  - Python 模式：Python 3.10+（阻塞）、pip（阻塞）、ta-lib（非阻塞降级）、磁盘≥2G（非阻塞）。
  - Rust 模式：`cargo`/`rustc` 按 `rust-toolchain.toml`（阻塞）、磁盘≥2G（非阻塞）；
    workspace 解析与 `config/contracts.yaml`（期货）在 Phase 1 Step 2 校验（阻塞）。
  - crypto 数据：Phase 1 Step 3 自动准备（非阻塞）；期货数据：用户必须提供 1m K 线路径（Phase 0 **阻塞**）。
- **Step 1 策略信息获取**：按输入形态（文件/目录/URL/自然语言/多轮对话）解析，统一收敛为策略规格 `.strategy-spec.yaml`（含 `market`/`data_source`/`backtest`；Python 落 `strategies/{name}/`，Rust 落 `docs/strategy/specs/`）。
- **Step 3 执行确认**：全自动直接跑，交互式展示后等确认。

### Phase 1：项目脚手架创建（一次性）
- Python：复制 `strategy_core/`、`backtest/`、`data_manager/`、`scripts/`、`config/`、`docs/`、入口脚本；创建 venv + 安装依赖；准备 crypto 1m 数据（symlink/下载）。
- Rust：镜像复制 workspace（`crates/core|engine|strategies|data|signals|positions|store|broker|indicators|app`、`config/`、`scripts/`、`docs/`）；复制后先 `cargo metadata` 校验 workspace、期货校验 `contracts.yaml`，再 `cargo fetch` + 基线 `fmt/clippy/test`；从 `config/_global.example.yaml` 生成本地 `_global.yaml`。
- 共同：复制时排除模板 `.git`，`git init` + 首次 commit 生成独立历史；期货数据按用户路径落位（`roll_build` 或直接复制），缺失即停，禁止下载/mock。
- 输出就绪报告。

### Phase 2：策略开发
- **强制先读规范文档**：Python（QUICKSTART/DEVELOPMENT_GUIDE/AI_CONSTRAINTS/REVIEW_CHECKLIST/EXAMPLES）；
  Rust（AI_WORKFLOW/AI_CONSTRAINTS/CONFIG_REFERENCE/CRYPTO_VS_FUTURES/DEVELOPMENT_GUIDE/XSEC_GUIDE/POSITION_MODEL/REVIEW_CHECKLIST/STRATEGY_SPEC）。
- Python 生成 `strategy.py`、`{prefix}_core.py`、`__init__.py`、per-symbol overrides、`config/strategies.yaml`、测试。
- Rust 生成 `crates/strategies/src/{name}.rs`（`Params` + `CrossSectionalStrategyPort` + `register_strategy!` + 测试）、`config/<group>/strategy.yaml`、spec；不改 `build.rs`/`registry.rs`。
- 验证配置（Rust: `cargo fmt/clippy/test` + 回测加载）、跑 REVIEW_CHECKLIST、重写/同步 README。

### Phase 3：回测验证
- Python：短期/中期/长期三轮回测，统一用 `scripts/run_backtest_batch.sh`，只换 `--start/--end`。
- Rust：`cargo run -p strategy-app -- backtest --config config/<group>/strategy.yaml --start/--end`，
  批量用 `scripts/run_backtest_matrix.sh`；输出 `backtest_output/<strategy_type>/<date>/<time>/<strategy_id>/`。
- 验收标准：至少一个标的费后收益 ≥ 20%；期货区间按用户数据覆盖范围调整并注明。
- 解析 `backtest_result.json` 的 `metrics`；Step 5 输出 `benchmark.md`（可指向 Obsidian）。

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
 │   │  Step0 主机级预检(工具链/磁盘;期货用户数据路径)               │
 │   │   └─主机级阻塞失败 → 退出；workspace/契约在 Phase 1 校验      │
 │   │  Step1 解析来源(文件/目录/URL/NL/对话) → 策略规格             │
 │   │  Step3 确认(全自动自动过 / 交互等y)                           │
 │   └────────────────────────────┬────────────────────────────────┘
 │                                ▼
 │   ┌─────────────────────────────────────────────────────────────┐
 │   │ Phase 1: 脚手架创建（一次性）                                 │
 │   │  复制模板 → workspace/契约校验 → 环境初始化 → 数据 → git init │
 │   └────────────────────────────┬────────────────────────────────┘
 │                                ▼
 │   ┌───────────────────── Loop (最多 5 轮) ─────────────────────┐
 │   │                                                             │
 │   │  Phase 2: 策略开发                                          │
 │   │   读规范 → 生成代码 → 验证 → 审查 → README                  │
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

3. **阻塞点按阶段分叉**：Phase 0（主机级）阻塞 Python 3.10+/pip（Python 模式）、cargo/rustc（Rust 模式）、期货用户 K 线路径；Phase 1 Step 2（项目级）阻塞 workspace 解析与 `config/contracts.yaml`（期货）。ta-lib、crypto 数据、磁盘为非阻塞（降级/自动修复/警告）。

4. **Loop 终止条件**（三选一）：
   - 长期回测 ≥ 20% → 达标，输出 benchmark
   - 未达标但未到 5 轮 → 诊断后回 Phase 2
   - 达到 5 轮 → 输出当前最佳 + 未达标标记

5. **调参时序约束**：每轮只改一个主维度（可归因）；首次步长 ±20%；连续 2 轮同维度无改善须换维度；回撤 >30% 优先处理风控再处理收益。

6. **数据流时序**：策略规格 `.strategy-spec.yaml`（Phase 0 产出，含 `market`/`data_source`/`backtest`；Python 落 `strategies/{name}/`，Rust 落 `docs/strategy/specs/`）→ 驱动 Phase 2 代码生成 → 参数落点按语言分叉（Python: per-symbol `overrides/{SYMBOL}.yaml`；Rust: `config/<group>/strategy.yaml` 的 `params`）→ 回测产物 `backtest_result.json` 的 `metrics` 段 → 驱动 Loop 诊断。期货的 `data_source` 必须来自用户，缺失即停。

7. **配置时序**：Python v3.7 收敛为 `config/` 三层（settings/strategies/backtest.yaml run-profile），回测参数来源是 `--strategies name:symbol` + overrides。Rust 收敛为 `config/<group>/strategy.yaml`（策略级）+ `config/<group>/_global.yaml`（运行基线）+ 仓库根 `config/contracts.yaml`（期货合约参数）；旧 per-symbol 已退役，`backtest` 只接受 `strategy.yaml` / 单组配置。

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

### 语言与市场

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `STRATEGY_LANG` | `python` | `python` / `rust` |
| `STRATEGY_MARKET` | `crypto` | `crypto` / `futures` |
| `DATA_PATH` | `./data/klines` | K 线根目录（Python csv_dir；Rust `--data-dir`） |
| `KLINE_DATA_DIR` | `./data/klines` | 共享 K 线数据源（symlink 目标） |
| `CTA_ENV` | `dev` | 运行环境（dev/test/prod） |
| `BENCHMARK_OUTPUT_PATH` | `./benchmark_output` | benchmark 报告输出路径 |

### 模板来源

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `STRATEGY_TEMPLATE_TAG` | Python `v1.0.0` / Rust 空（跟 main） | 模板 tag；Rust 新模板尚未打 tag |
| `TRADING_DEV_TEMPLATE_DIR` | （空） | 本地模板目录，设置后优先使用 |

### 期货模式（数据必须由用户提供）

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `FUTURES_EXCHANGE` | `SHFE` | `SHFE` / `DCE` / `CZCE` / `INE` |
| `FUTURES_SYMBOL` | `CU` | 品种代码，必须已在 `config/contracts.yaml` 声明 |
| `FUTURES_KLINES_DIR` | （空） | 用户提供的 K 线根目录或 1m CSV 路径（**不下载**） |
| `FUTURES_INITIAL_CASH` | （空） | 初始权益（元），也可写 `_global.yaml` 的 `initial_cash` |

### 实盘/paper（Rust）

`run` 的外部服务地址不走环境变量，统一在 `config/_global.yaml` 的
`services.trading` 配置（`ws_url`/`exchange`/`account`/`strategy_secret` 等），
缺失即 fail-fast；`.env` 只放 `STRATEGY_SECRET` 与代理，不入库。
Python 模板的直连下单凭证仍走 `BINANCE_API_KEY` / `BINANCE_API_SECRET`。

---

## 七、回测验收标准

| 周期 | 时间范围（crypto 默认） | 验收标准 |
|------|----------|----------|
| 短期 | 20260601-20260709 | 至少一个标的费后收益 ≥ 20% |
| 中期 | 20260101-20260709 | 至少一个标的费后收益 ≥ 20% |
| 长期 | 20250101-20260709 | 至少一个标的费后收益 ≥ 20% |

- **Python + crypto**：三周期都用 `scripts/run_backtest_batch.sh`，只换 `--start/--end`；
  参数自动读 `strategies/{strategy_name}/overrides/<SYMBOL>.yaml`。
- **Rust + crypto**：`cargo run -p strategy-app -- backtest --config config/<group>/strategy.yaml`
  （批量用 `scripts/run_backtest_matrix.sh`）；参数读 `strategy.yaml` 的 `params`。
- **期货**：标的取配置 `universe`；三个窗口必须落在用户提供的 1m 数据覆盖范围内，
  覆盖不足时改用可用区间的短/中/长三段，并在 benchmark 注明"区间按数据可用性调整"；
  不得用其他品种/区间顶替。

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

### Rust 编码红线（模板 AI_CONSTRAINTS.md，23 禁 + 12 必，摘要）

| # | 约束 | 原因 |
|---|------|------|
| 1 | 禁止 `now()`/系统时间，只用 `snapshot.bar.open_time` | 回测可复现 |
| 2 | 禁止未闭合 K 线/绕过 `snapshot.closed`，只用 `closed(tf)` | 隔离未来函数 |
| 3 | 禁止策略内 IO | 策略是纯计算 |
| 4 | 禁止改 `build.rs`/`registry.rs`/`lib.rs` | 接线区冻结 |
| 5 | `Params` 必须 `deny_unknown_fields + Default` | 配置拼错启动即报错 |
| 6 | `timeframes()` 必须含 `M1` | 聚合入口 |
| 7 | 主路径禁止 `unwrap()/expect()` | 静默降级 |
| 8 | 禁止自持仓位账本/总仓状态 | 引擎持有 `MasterPosition`/`SubPosition` |
| 9 | 禁止 `strategy_type`/注册名/配置名不一致 | signal_id 与报表路径分裂 |
| 10 | 禁止期货 `params` 写乘数/保证金/费率/时段 | 唯一来源 `config/contracts.yaml` |
| 11 | 禁止期货 symbol 未声明就回测 | 静默退化为 crypto 兼容模式 |
| 12 | 禁止用户未提供期货 K 线就回测/用 mock 顶替 | 结果不可信 |
| 必须 | `register_strategy!` 恰好一次；文件尾调用 | 注册表自动发现 |
| 必须 | 期货显式 `initial_cash`，等分后够开 1 手 | 否则开不出仓 |
| 必须 | 期货用例覆盖 `multiplier != 1`、整数手、时段 | 换品种即错 |

### 开源约束

| # | 约束 |
|---|------|
| 1 | 禁止硬编码内网 IP（`192.168.x.x`），必须走环境变量 |
| 2 | 禁止硬编码个人路径（`/home/xxx`），用相对路径或 `DATA_PATH` 环境变量 |
| 3 | 禁止在代码中写入 API Key / Secret，用 `.env` + `.gitignore` |
| 4 | `config/settings.yaml` 不进模板，用 `settings.example.yaml` 替代 |
| 5 | 测试中 mock IP 可保留，但需加注释说明是假数据 |
