---
name: trading-discovery
description: 指定代币/策略/时间范围的回测探索 skill。自然语言触发 → 初始化检查 → git clone 拉取策略 → 配置校验 → 批量回测 → 结果通知。
origin: trading
---

# Trading Discovery — 指定代币/策略/时间范围的回测探索

AI Skill 自动化回测工作流：自然语言触发 → 初始化检查 → 首次环境准备 → 信息确认与代码获取 → 配置校验 → 回测执行 → 结果通知。

**首要原则**：参数不全或环境未就绪时，逐步引导用户补齐，不报错甩给用户。

## When to Activate

- 用户说「探索回测」「对比策略」「多代币回测」
- 用户想看某个策略在不同代币或时间范围下的表现对比
- 用户执行 `/trading-discovery`

## 触发输入

用户用自然语言发起回测探索指令即可，例如：

- 「探索回测 sar_snt，代币 BTCUSDT ETHUSDT，从 6 月到现在」
- 「对比 ema_rsi 和 ict_v4 在 BTCUSDT 上的表现」
- 首次运行时给出 git 仓库地址 + 期望代币

解析出策略来源、代币、时间范围后进入 Phase 1。

---

## 工作流总览

```
Phase 1   → 任务触发与初始化检查
Phase 1.4 → 首次环境准备（仅首次/重置）
Phase 2   → 信息确认与代码获取（git clone）
Phase 3   → 配置校验与预处理（init_overrides 兜底）
Phase 4   → 回测执行与结果通知
```

---

## Phase 1: 任务触发与初始化检查

### 1.1 用户自然语言输入

用户通过自然语言向 AI Skill 发起 discovery（回测探索）指令。输入通常包含：策略来源（git 仓库地址）、期望回测代币、时间范围。

### 1.2 触发词检测

系统识别输入中的触发词（`@skill`、`/trading-discovery`，或「探索回测」「对比策略」「多代币回测」等关键词）后激活本 skill。

### 1.3 初始化 SKILL 模板检查

系统解析指令后，检查 SKILL 模板是否已就绪。

**判断逻辑**：确认 `trading-discovery-skill/templates/` 下脚本与配置模板是否齐全（`fetch_strategies.py`、`discovery.py`、`download_data.py`、`init_overrides.py`、`config.example.yaml`、`backtest.example.yaml`、`.env.example`），以及工作目录是否已有用户配置（`config.yaml` 存在且至少有一个已 clone 的策略目录）。

| 判断 | 流向 |
|------|------|
| 是（已初始化） | 跳过环境准备，直接进入 Phase 2.2 |
| 否（未初始化） | 进入 Phase 1.4 进行首次环境准备 |

---

## Phase 1.4: 首次环境准备（仅限首次或重置）

> 此阶段由 AI 主导完成基础环境搭建。仅当 Phase 1.3 判定未初始化时执行。

### 1.4.1 AI 分析必要内容

- **动作**：AI 分析用户自然语言输入，提取两类信息：
  1. 策略来源：用户是否提供了策略仓库地址（git_url）
  2. 期望代币：用户期望回测运行的代币（Token）清单

若用户未提供，AI 逐步询问补齐（缺啥问啥，不报错）。

### 1.4.2 记录策略仓库信息

- **核心动作**：
  1. 将解析出的策略及其 git 仓库地址记录在 `config.yaml` 中（顶层 key = 策略目录名，值含 `git_url`）。
  2. 根据用户期望代币，生成该策略的清单文件 `strategies.yaml`（`strategies` 段，列出策略包名 + symbols）。

完成后回到 Phase 1.3 复检，通过则进入 Phase 2。

---

## Phase 2: 信息确认与代码获取

### 2.1 确认仓库与策略信息

- **动作**：系统展示记录在 `config.yaml` 中的仓库信息和策略信息，供用户确认。

**判断条件**：信息是否准确。

| 判断 | 流向 |
|------|------|
| 否 | 用户介入，确认并修改 `config.yaml`，随后重新回到 2.1 确认 |
| 是 | 信息确认无误，进入代码拉取阶段 |

### 2.2 确认并开始 Git Clone 代码

- **动作**：用户确认后，直接调用 `fetch_strategies.py` 脚本，将远程策略代码仓库克隆/更新到本地。

```bash
python3 fetch_strategies.py --config config.yaml --strategies-dir .
```

脚本对每个策略自适应：目录已存在且含 `.git` → `git pull`；目录不存在 → `git clone`；`git_url` 为空 → 告警跳过。

---

## Phase 3: 配置校验与预处理

### 3.1 结合 strategies.yaml 输出配置

- **动作**：系统读取 `strategies.yaml`，遍历刚克隆的策略目录。
- **详细逻辑**：
  1. 检查每个策略目录下的路径 `(策略目录)/strategies/(策略名)/overrides`，确认是否存在所有必需的代币（Token）配置文件。
  2. 容错机制：如果发现某个代币配置文件不存在，系统会自动调用 `init_overrides.py` 复制一份同策略已有的代币配置作为兜底。

```bash
python3 init_overrides.py \
    --strategy-dir ./strategies/sar_snt/strategies/sar_snt \
    --symbols BTCUSDT,ETHUSDT
```

**注意路径层级**：`init_overrides.py` 的 `--strategy-dir` 指向含 `overrides/` 的那层 = `(策略目录)/strategies/(策略名)/`，不是 clone 顶层目录。

### 3.2 确认配置文件信息

- **判断条件**：系统检查生成的配置文件是否完整且符合运行要求。

| 判断 | 流向 |
|------|------|
| 否 | 用户介入，确认并修改配置文件，修复后重新回到 3.2 确认 |
| 是 | 配置文件准备完毕，进入核心执行阶段 |

---

## Phase 4: 回测执行与结果通知

### 4.1 执行回测脚本

- **动作**：系统遍历所有准备好的策略目录，分别执行其中的 `run_backtest_batch.sh` 脚本。
- **执行要求**：注意并发逻辑，系统需要控制同时运行的回测进程数量，防止资源耗尽。

- **主要运行** `discovery.py`。

```bash
python3 discovery.py --start 20260601 --end 20260801
```

**具体操作项**：

1. 遍历策略目录，从 `(策略目录)/config/strategies.yaml` 读取代币清单。
2. 每个策略一份 `output_dir = discovery_outputs/{策略目录}/`。
3. 在策略目录内执行其自带的 `scripts/run_backtest_batch.sh`，`--yes` 跳过交互确认。
4. 并发由 `backtest.yaml` 的 `max_workers` 控制（写入 run-profile）。

---

## 目录结构

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

**数据流转**：`config.yaml`（git_url）→ `fetch_strategies.py` clone → `strategies.yaml`（代币）→ `init_overrides.py` 兜底配置 → `run_backtest_batch.sh` 回测 → `discovery_outputs/`。

---

## config.yaml 结构

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

---

## backtest.yaml 结构

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

## 脚本说明

### fetch_strategies.py — 策略代码获取

```bash
python3 fetch_strategies.py [--config config.yaml] [--strategies-dir .] [--strategies sar_snt,obv_atr] [--no-list]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--config` | `config.yaml` | 策略登记表（顶层 key=策略目录名，含 git_url） |
| `--strategies-dir` | `.` | 策略目录父目录（clone 目标在其下） |
| `--strategies` | 全部 | 只处理指定策略（逗号分隔目录名） |
| `--no-list` | - | 跳过末尾可用策略列表展示 |

### init_overrides.py — per-symbol 配置兜底

```bash
python3 init_overrides.py --strategy-dir ./strategies/sar_snt/strategies/sar_snt --symbols BTCUSDT,ETHUSDT [--force] [--dry-run]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--strategy-dir` | 必需 | 含 overrides/ 的那层（`strategies/<pkg>/`） |
| `--symbols` | 必需 | 逗号分隔代币列表 |
| `--force` | 否 | 覆盖已存在的配置（默认跳过） |
| `--dry-run` | 否 | 只报告将创建哪些，不写盘 |

### discovery.py — 回测执行

```bash
python3 discovery.py --start 20260601 [--end 20260801] [--config config.yaml] [--backtest-config backtest.yaml] [--strategies-dir .] [--output-root ./discovery_outputs] [--strategies sar_snt] [--log-level INFO]
```

| 参数 | 默认 | 说明 |
|------|------|------|
| `--start` | 必需 | 回测开始时间 YYYYMMDD 或 Unix 时间戳 |
| `--end` | 当前 | 回测结束时间 |
| `--config` | `config.yaml` | 策略登记表（不存在则扫 --strategies-dir） |
| `--backtest-config` | `backtest.yaml` | 回测 run-profile |
| `--strategies-dir` | `.` | 策略目录父目录 |
| `--output-root` | `./discovery_outputs` | 产物根目录 |
| `--strategies` | 全部 | 只回测指定策略 |
| `--log-level` | `INFO` | 透传给 wrapper 的日志级别 |

---

## Claude Code 权限需求

```json
{
  "permissions": {
    "allow": [
      "Bash(python3:*)",
      "Bash(python:*)",
      "Bash(bash:*)",
      "Bash(git:*)",
      "Bash(mkdir:*)",
      "Read(*)",
      "Write(*)",
      "Edit(*)"
    ]
  }
}
```

---

## Related Skills

- `trading-dev`: CTA 策略开发全生命周期
- `trading-replay`: 每日策略代码备份 + 回放回测
