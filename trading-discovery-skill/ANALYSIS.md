# Trading Discovery Skill — 功能说明与时序分析

## 一、定位

`trading-discovery` 是 **指定代币/策略/时间范围的回测探索 skill**，用于对比策略在不同代币或时间范围下的表现：

```
自然语言触发 → 初始化检查 → git clone 拉取策略 → 配置校验（init_overrides 兜底）→ 批量回测 → 结果通知
```

首要原则：参数不全或环境未就绪时，逐步引导用户补齐，不报错甩给用户。

## 二、触发方式

用自然语言发起回测探索指令即可，例如：
- 「探索回测 sar_snt，代币 BTCUSDT ETHUSDT，从 6 月到现在」
- 「对比 ema_rsi 和 ict_v4 在 BTCUSDT 上的表现」
- 首次运行时给出 git 仓库地址 + 期望代币

解析出**策略来源、代币、时间范围**后进入 Phase 1。触发词：`@skill`、`/trading-discovery`，或「探索回测」「对比策略」「多代币回测」等关键词。

## 三、Phase 构成（功能分解）

### Phase 1：任务触发与初始化检查
- **1.1 自然语言输入**：输入通常包含策略来源（git_url）、期望代币、时间范围。
- **1.2 触发词检测**：识别关键词后激活 skill。
- **1.3 初始化 SKILL 模板检查**：确认 `templates/` 下脚本配置齐全（`fetch_strategies.py`/`discovery.py`/`download_data.py`/`init_overrides.py`/`config.example.yaml`/`backtest.example.yaml`/`.env.example`），以及工作目录是否已有用户配置（`config.yaml` 存在且至少一个已 clone 策略目录）。
  - 已初始化 → 跳到 Phase 2.2
  - 未初始化 → 进 Phase 1.4

### Phase 1.4：首次环境准备（仅首次/重置）
- **1.4.1 AI 分析必要内容**：提取策略来源（git_url）和期望代币；未提供则逐步询问补齐（缺啥问啥，不报错）。
- **1.4.2 记录策略仓库信息**：
  1. 将策略及 git_url 记录在 `config.yaml`（顶层 key = 策略目录名，值含 `git_url`）。
  2. 根据期望代币生成 `strategies.yaml`（`strategies` 段，列策略包名 + symbols）。
- 完成后回 Phase 1.3 复检，通过进 Phase 2。

### Phase 2：信息确认与代码获取
- **2.1 确认仓库与策略信息**：展示 `config.yaml` 中仓库策略信息供用户确认。不准确 → 用户改 `config.yaml` → 回 2.1 重确认；准确 → 进代码拉取。
- **2.2 确认并 Git Clone**：`fetch_strategies.py` 克隆/更新到本地。自适应：目录已存在且含 `.git` → `git pull`；目录不存在 → `git clone`；`git_url` 空 → 告警跳过。

### Phase 3：配置校验与预处理
- **3.1 结合 strategies.yaml 输出配置**：读 `strategies.yaml`，遍历克隆的策略目录，检查 `(策略目录)/strategies/(策略名)/overrides` 下代币配置文件是否齐全。**容错**：某代币配置不存在 → 自动调 `init_overrides.py` 复制同策略已有代币配置作兜底。
  - **注意路径层级**：`init_overrides.py --strategy-dir` 指向含 `overrides/` 的那层 = `(策略目录)/strategies/(策略名)/`，不是 clone 顶层。
- **3.2 确认配置文件信息**：检查完整性。不完整 → 用户改 → 回 3.2 重确认；完整 → 进核心执行。

### Phase 4：回测执行与结果通知
- **4.1 执行回测脚本**：遍历策略目录，分别执行其自带 `run_backtest_batch.sh`，**控制并发防止资源耗尽**。
- 主要运行 `discovery.py`：
  1. 遍历策略目录，从 `(策略目录)/config/strategies.yaml` 读代币清单。
  2. 每策略一份 `output_dir = discovery_outputs/{策略目录}/`。
  3. 在策略目录内执行 `scripts/run_backtest_batch.sh`，`--yes` 跳过交互确认。
  4. 并发由 `backtest.yaml` 的 `max_workers` 控制（写入 run-profile）。

---

## 四、时序分析

### 时序图（完整执行流）

```
用户
 │
 ├─ 自然语言触发（探索回测/对比策略/多代币回测）
 │   解析出: 策略来源(git_url) + 代币 + 时间范围
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 1: 任务触发与初始化检查                      │
 │   │  1.1 自然语言输入 → 1.2 触发词检测 → 1.3 模板检查  │
 │   │                          │                        │
 │   │            ┌─────────────┴──────────────┐         │
 │   │            ▼                            ▼         │
 │   │      已初始化?                       未初始化        │
 │   │      → 跳 Phase 2.2                → Phase 1.4     │
 │   └──────────────────────────────────────────────────┘
 │                          │
 │   (未初始化)              ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 1.4: 首次环境准备（仅首次/重置）              │
 │   │  1.4.1 AI 分析提取 git_url + 代币（缺啥问啥）       │
 │   │  1.4.2 记录 config.yaml + 生成 strategies.yaml     │
 │   │  → 回 Phase 1.3 复检 → 通过进 Phase 2              │
 │   └──────────────────────────────────────────────────┘
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 2: 信息确认与代码获取                        │
 │   │  2.1 确认仓库/策略信息                              │
 │   │      不准确→用户改config.yaml→回2.1                 │
 │   │      准确→↓                                        │
 │   │  2.2 fetch_strategies.py (pull/clone/跳过空url)    │
 │   └──────────────────────┬───────────────────────────┘
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 3: 配置校验与预处理                          │
 │   │  3.1 读 strategies.yaml → 遍历策略 overrides        │
 │   │      缺代币配置? → init_overrides.py 兜底复制       │
 │   │      （--strategy-dir 指向 strategies/<pkg>/ 层）   │
 │   │  3.2 确认配置完整                                   │
 │   │      不完整→用户改→回3.2 / 完整→↓                  │
 │   └──────────────────────┬───────────────────────────┘
 │                          ▼
 │   ┌──────────────────────────────────────────────────┐
 │   │ Phase 4: 回测执行与结果通知                        │
 │   │  discovery.py 遍历策略目录                         │
 │   │   ├─ 读 (策略目录)/config/strategies.yaml 代币清单  │
 │   │   ├─ output_dir = discovery_outputs/{策略目录}/     │
 │   │   ├─ 执行 scripts/run_backtest_batch.sh --yes      │
 │   │   └─ 并发由 backtest.yaml max_workers 控制         │
 │   └──────────────────────┬───────────────────────────┘
 │                          ▼
 └─ 完成: discovery_outputs/{策略目录}/ 回测结果
```

### 时序关键点

1. **首次/重置才走 Phase 1.4**：已初始化环境直接跳到 Phase 2.2，避免重复引导。初始化判定 = `config.yaml` 存在且至少一个已 clone 策略目录。

2. **两个确认回环**：Phase 2.1（仓库策略信息）和 Phase 3.2（配置完整性）都是"不通过 → 用户改 → 回到本步重确认"的循环，直到通过才前进。

3. **init_overrides 兜底时序**：必须在 Phase 3（回测前）完成，兜底机制保证每个期望代币都有 overrides 配置。注意 `--strategy-dir` 路径层级是含 `overrides/` 的那层，不是 clone 顶层。

4. **并发控制**：Phase 4 遍历多策略多代币回测，并发由 `backtest.yaml` 的 `max_workers` 控制，防止资源耗尽。

5. **数据流转时序**：`config.yaml`（git_url）→ `fetch_strategies.py` clone → `strategies.yaml`（代币清单）→ `init_overrides.py` 兜底配置 → `run_backtest_batch.sh` 回测 → `discovery_outputs/`。

6. **git 自适应时序**：`fetch_strategies.py` 对每个策略自适应——有 `.git` 则 pull，无则 clone，`git_url` 空则告警跳过（不阻塞其它策略）。

---

## 五、目录结构

```
workspace/
├── config.yaml                        ← 策略登记表（git_url，fetch_strategies 读）
├── backtest.yaml                       ← 回测 run-profile（data_dir/output_dir/并发）
├── sar_snt/                            ← 策略目录（git clone 目标，= config.yaml 顶层 key）
│   ├── config/strategies.yaml          ← 代币清单（仓库自带，clone 后才有）
│   ├── strategies/sar_snt/overrides/   ← per-symbol 配置（init_overrides 兜底）
│   └── scripts/run_backtest_batch.sh    ← 批量回测 wrapper
│
├── data/klines/1m/                     ← K线数据（download_data.py 写入，回测读）
│
└── discovery_outputs/sar_snt/          ← 回测结果（discovery.py 写入）
    └── ...
```

---

## 六、配置文件结构

### config.yaml（策略登记表）

```yaml
sar_snt:                              # 顶层 key = 策略目录名 = git clone 目标 basename
  git_url: git@github.com:user/sar_snt.git
obv_atr:
  git_url: https://github.com/user/obv_atr.git
```

| 字段 | 说明 |
|------|------|
| 顶层 key | 策略目录名，同时作为 git clone 目标文件夹名 |
| `git_url` | 策略代码仓库地址（可空，空则跳过该策略） |

### backtest.yaml（回测 run-profile）

```yaml
start: "20260601"        # 回测时间范围（CLI --start/--end 可覆盖）
end: ""
cash: 5000               # 初始资金
commission: 0.0004        # 手续费（币安合约 taker 0.04%）
data_dir: "./data/klines"      # K线目录（必须与 settings.yaml csv_dir 一致）
output_dir: "./discovery_outputs"   # 产物根（discovery.py 每策略覆盖为子目录）
max_workers: 4           # 并发数
```

---

## 七、脚本说明

### fetch_strategies.py — 策略代码获取
```bash
python3 fetch_strategies.py [--config config.yaml] [--strategies-dir .] [--strategies sar_snt,obv_atr] [--no-list]
```
自适应：有 `.git` → pull；无 → clone；`git_url` 空 → 告警跳过。

### init_overrides.py — per-symbol 配置兜底
```bash
python3 init_overrides.py --strategy-dir ./strategies/sar_snt/strategies/sar_snt --symbols BTCUSDT,ETHUSDT [--force] [--dry-run]
```
`--strategy-dir` 指向含 `overrides/` 的那层（`strategies/<pkg>/`）。

### discovery.py — 回测执行
```bash
python3 discovery.py --start 20260601 [--end 20260801] [--config config.yaml] [--backtest-config backtest.yaml] [--strategies-dir .] [--output-root ./discovery_outputs] [--strategies sar_snt] [--log-level INFO]
```

---

## 八、边界（四个 skill 协作）

> **dev 写 → discovery 测 → deploy 跑 → replay 管**

| skill | 职责 |
|-------|------|
| `trading-dev` | 写策略（开发全生命周期） |
| `trading-discovery` | 测策略（回测探索） |
| `trading-deploy` | 跑策略（部署上线） |
| `trading-replay` | 管策略（每日备份+回放） |
