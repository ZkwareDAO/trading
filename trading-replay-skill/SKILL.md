---
name: trading-replay
description: 每日策略代码备份 + 回放回测 skill。从实盘机器 SCP 拉取策略代码快照，按日期/策略/模型执行回测，输出回测结果。支持定时任务和指定日期重新回放。
origin: trading
---

# Trading Replay — 每日策略代码备份 + 回放回测

从实盘机器备份策略代码 → 按日期快照存储 → 每日回放回测 → 输出回测结果，一条链路闭环。

**核心行为**：每日定时执行，也支持指定日期重新回放。

## When to Activate

- 用户执行 `/trading-replay run` — 执行当日完整流程（sync + replay）
- 用户执行 `/trading-replay run --date 20260801` — 指定日期执行
- 用户执行 `/trading-replay sync` — 只执行策略代码备份
- 用户执行 `/trading-replay replay` — 只执行回放回测
- 用户执行 `/trading-replay replay --date 20260801` — 重新回放指定日期
- 用户说"回放回测"、"每日回测"、"备份策略代码"

## Commands

| 命令 | 说明 |
|------|------|
| `/trading-replay run` | 执行当日完整流程（sync + replay） |
| `/trading-replay run --date YYYYMMDD` | 指定日期执行完整流程 |
| `/trading-replay sync` | 策略代码备份（含远程发现 + 用户确认） |
| `/trading-replay sync --date YYYYMMDD` | 备份到指定日期目录 |
| `/trading-replay sync --skip-discovery` | 跳过远程发现，直接备份全部策略 |
| `/trading-replay discover` | 只执行远程策略发现（不备份） |
| `/trading-replay replay` | 只执行回放回测（replay.sh），默认回测近 30 天 |
| `/trading-replay replay --date YYYYMMDD` | 回放指定日期的快照，默认回测近 30 天 |
| `/trading-replay replay --start 20260101 --end 20260801` | 自定义回测时间范围 |
| `/trading-replay replay --skip-analysis` | 跳过策略分析阶段，直接回测 |
| `/trading-replay summary` | 查看最近回测结果摘要 |
| `/trading-replay summary --date YYYYMMDD` | 查看指定日期回测结果摘要 |

---

## Phase 0: 环境预检

### Step 0: 检查运行环境

```bash
# 1. 检查 SCP 连接（ping 目标机器）
SCP_HOST="${SCP_HOST:-}"
if [ -n "$SCP_HOST" ]; then
    if ping -c 1 -W 3 "$SCP_HOST" &>/dev/null; then
        echo "✅ SCP 目标可达: $SCP_HOST"
    else
        echo "⚠ SCP 目标不可达: $SCP_HOST（备份将失败，回测仍可执行）"
    fi
else
    echo "⚠ SCP_HOST 未配置（策略备份不可用）"
fi

# 2. 检查回测引擎
PYTHON_CMD="${PYTHON_CMD:-python3}"
if $PYTHON_CMD -m backtest.run_backtest --help &>/dev/null; then
    echo "✅ 回测引擎可用"
else
    echo "❌ 回测引擎不可用（阻塞项）"
fi

# 3. 检查 K 线数据
KLINE_DIR="${KLINE_DATA_DIR:-./data/strategies/1m}"
if [ -d "$KLINE_DIR" ] && [ -f "$KLINE_DIR/BTCUSDT_1m.csv" ]; then
    echo "✅ K 线数据就绪: $KLINE_DIR"
else
    echo "⚠ K 线数据未就绪（回测将失败）"
fi

# 4. 检查 snapshot 目录
SNAPSHOT_DIR="${SNAPSHOT_DIR:-./snapshot}"
if [ -d "$SNAPSHOT_DIR" ]; then
    echo "✅ snapshot 目录存在: $SNAPSHOT_DIR"
else
    echo "ℹ snapshot 目录不存在，将在 Phase 1 创建"
fi
```

**阻塞 vs 非阻塞**：

| 检测项 | 不达标时 | 原因 |
|--------|----------|------|
| 回测引擎 | **阻塞** — 无法执行回测 | 核心依赖 |
| K 线数据 | **阻塞** — 回测无数据 | 核心依赖 |
| SCP 连接 | **非阻塞** — 可只执行 replay | 备份可后补 |
| snapshot 目录 | **非阻塞** — 自动创建 | 可自动修复 |

---

## Phase 1: 配置初始化

### Step 1: 读取配置

优先级：`.env` > `config.yaml` > 默认值

```bash
# 加载 .env
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# 读取 config.yaml（Python 解析）
if [ -f "config.yaml" ]; then
    echo "✅ 加载 config.yaml"
else
    echo "⚠ config.yaml 不存在，使用 .env 和默认值"
fi
```

### Step 2: 验证必需配置

| 配置项 | 来源 | 必需场景 | 默认值 |
|--------|------|----------|--------|
| `SCP_HOST` | .env / config.yaml | sync | 无 |
| `SCP_PORT` | .env / config.yaml | sync | 22 |
| `SCP_USER` | .env / config.yaml | sync | 无 |
| `SCP_STRATEGY_DIR` | .env / config.yaml | sync | 无 |
| `DATA_PATH` | .env | replay | ./data |
| `KLINE_DATA_DIR` | .env | replay | ./data/strategies/1m |
| `SNAPSHOT_DIR` | config.yaml | 全流程 | ./snapshot |
| `LOGS_DIR` | config.yaml | 全流程 | ./logs |
| `REPLAY_OUTPUTS_DIR` | config.yaml | replay | ./replay_outputs |

### Step 3: 创建目录结构

```bash
REPLAY_DATE="${REPLAY_DATE:-$(date +%Y%m%d)}"

mkdir -p "${SNAPSHOT_DIR:-./snapshot}/${REPLAY_DATE}"
mkdir -p "${LOGS_DIR:-./logs}"
mkdir -p "${REPLAY_OUTPUTS_DIR:-./replay_outputs}/${REPLAY_DATE}"
```

---

## Phase 1.5: 远程策略发现（discover_remote.py）

### Step 1: 发现实盘运行的策略

在备份之前，先 SSH 到远程机器列出当前运行的策略，让用户知道实盘在跑什么。

```bash
python3 discover_remote.py --config config.yaml
```

**discover_remote.py 行为**：

1. SSH 连接到 `SCP_HOST`（使用与 sync-exee.py 相同的连接配置）
2. 列出 `$SCP_PROJECT_DIR/strategies/` 下所有策略目录
3. 获取每个策略的文件数、最后修改时间、目录大小
4. 终端输出策略清单

**输出格式**：

```
==============================================================
  远程实盘策略发现
==============================================================
  来源:     trader@192.168.1.100:/home/trader/project/strategies/
  策略数:   3

   1. ema_rsi                      12 files  2026-08-09 14:30    256KB
   2. ict_v4                       15 files  2026-08-09 10:15    320KB
   3. grid_trading                 10 files  2026-08-08 22:00    180KB

--------------------------------------------------------------
  model 类型: product(实盘) | smoking(模拟盘) | paper(纸上交易)
  备份路径:   snapshot/{date}/{strategy}-{model}/
==============================================================
```

**JSON 输出**（`--json` 标志）：

```bash
python3 discover_remote.py --config config.yaml --json --output logs/remote-discovery-${REPLAY_DATE}.json
```

```json
{
  "source": "trader@host:/path/strategies",
  "timestamp": "2026-08-09T18:00:00",
  "strategy_count": 3,
  "strategies": [
    {"name": "ema_rsi", "file_count": 12, "last_modified": "2026-08-09 14:30", "size_kb": 256},
    {"name": "ict_v4", "file_count": 15, "last_modified": "2026-08-09 10:15", "size_kb": 320}
  ]
}
```

**错误处理**：
- SSH 连接失败 → 报告错误，不阻塞（用户可选择跳过发现直接备份全部）
- 远程目录不存在 → 报告错误，退出
- 远程目录为空 → 报告警告，可继续（sync 阶段也会发现无内容）

---

## Phase 1.6: 策略确认

### Step 1: 用户确认备份范围

Phase 1.5 输出远程策略清单后，等待用户确认备份范围。

**交互流程**：

```
📋 发现 3 个实盘策略，是否继续备份？

   y              = 备份全部 3 个策略 × 3 个 model (product/smoking/paper)
   n              = 取消
   ema_rsi,ict_v4 = 只备份指定策略（逗号分隔）
   指定 model     = product:ema_rsi  (只备份 ema_rsi 的 product 模型)
```

**确认后行为**：

| 用户输入 | 备份范围 |
|---------|---------|
| `y` | 全部策略 × 全部 model（3 × 3 = 9 个快照） |
| `n` | 取消，退出流程 |
| `ema_rsi,ict_v4` | 指定策略 × 全部 model（2 × 3 = 6 个快照） |
| `product:ema_rsi` | 指定策略 × 指定 model（1 个快照） |

**model 类型说明**：

| model | 含义 | 典型场景 |
|-------|------|---------|
| `product` | 实盘策略 | 正在运行的策略代码，每日必须备份 |
| `smoking` | 模拟盘策略 | 模拟环境验证中的策略 |
| `paper` | 纸上交易策略 | 仅记录信号不实际下单的策略 |

> **为什么每种策略要备份 3 个 model？**
> 同一策略可能在实盘、模拟盘、纸上交易三种环境下各运行一份，
> 配置参数（资金、杠杆、风控）可能不同。分别备份确保回放时可还原各自环境。

**跳过发现**：

如果已知策略列表，可跳过 Phase 1.5 + 1.6 直接进入 Phase 2：

```bash
# 方式 1：指定 --skip-discovery
/trading-replay sync --skip-discovery

# 方式 2：直接调用 sync-exee.py
python3 sync-exee.py --date 20260801
```

---

## Phase 2: 策略代码备份（sync-exee.py）

### Step 1: 从实盘机器拉取策略代码

```bash
python3 sync-exee.py --date "${REPLAY_DATE}" --config config.yaml
```

**sync-exee.py 行为**：

1. 读取 `config.yaml` 获取 SCP 连接信息和策略目录
2. 通过 SCP 从远程机器拉取策略代码
3. 按 `snapshot/{day}/{strategy}-{model}` 存放
   - `model` 枚举：`product`（实盘）/ `smoking`（模拟盘）/ `paper`（纸上交易）
4. 记录同步结果到 `logs/sync-{day}.log`

**输出目录结构**：

```
snapshot/
└── 20260801/
    ├── ema_rsi-product/        # 实盘策略代码
    │   ├── strategy.py
    │   ├── EMA_RSI_core.py
    │   ├── config.yaml
    │   └── ...
    ├── ema_rsi-smoking/        # 模拟盘策略代码
    │   └── ...
    ├── ict_v4-product/
    │   └── ...
    └── ict_v4-paper/
        └── ...
```

**同步日志格式**（`logs/sync-20260801.log`）：

```
[2026-08-01 00:15:03] START sync-exee.py --date 20260801
[2026-08-01 00:15:05] SCP: trader@your-server:/home/trader/strategies/ema_rsi → snapshot/20260801/ema_rsi-product/
[2026-08-01 00:15:08] ✅ ema_rsi-product: 12 files synced
[2026-08-01 00:15:10] SCP: trader@your-server:/home/trader/strategies/ict_v4 → snapshot/20260801/ict_v4-product/
[2026-08-01 00:15:13] ✅ ict_v4-product: 15 files synced
[2026-08-01 00:15:13] END sync-exee.py: 2 strategies synced, 0 errors
```

**错误处理**：
- SCP 连接失败 → retry 3 次（间隔 5s），仍失败则记录错误日志，不阻塞后续策略
- 远程目录不存在 → 记录警告，跳过该策略
- 本地磁盘不足 → 记录错误，停止同步

---

## Phase 2.5: 策略分析（analyze_snapshot.py）

### Step 1: 分析 snapshot 中的策略配置、代码完整性、K线数据

在回测前先分析已同步的策略，确定哪些策略可以回测、配置是否完整、K线数据是否覆盖回测范围。

```bash
python3 analyze_snapshot.py \
    --snapshot-dir "${SNAPSHOT_DIR}/${REPLAY_DATE}" \
    --start "${BT_START}" \
    --end "${BT_END}" \
    --kline-data-dir "${KLINE_DATA_DIR}" \
    --output "${LOGS_DIR}/analysis-${REPLAY_DATE}.json"
```

**分析内容**：

| 检查项 | 说明 | 不达标时 |
|--------|------|----------|
| strategy.py | 策略入口文件是否存在 | 标记 skip |
| *_core.py | 策略核心逻辑文件 | 警告，不阻塞 |
| config.yaml | 策略配置文件（config.test.yaml → config.yaml → config*.yaml） | 标记 skip |
| symbols | 配置中定义的代币列表 | 无 symbols 标记 partial |
| timeframes | 配置中定义的时间框架 | 信息展示 |
| K线数据 | 每个 symbol 的 CSV 是否存在、日期范围是否覆盖回测区间 | 缺失标记 partial |

**策略状态判定**：

| 状态 | 条件 | 后续动作 |
|------|------|----------|
| `ready` | 所有检查通过 | 执行回测 |
| `partial` | 部分检查不通过（如部分 symbol 无数据） | 执行回测（仅有效 symbol） |
| `skip` | 关键检查失败（无配置/无代码/无数据） | 跳过回测 |

**分析报告输出**（终端）：

```
============================================================
  Strategy Analysis Report
============================================================
  Source: replay
  Path:   ./snapshot/20260801
  Range:  20260702 ~ 20260801
  Data:   ./data/strategies/1m

[READY]   ema_rsi (product)
  Config: /path/to/config.test.yaml
  Symbols: BTCUSDT, ETHUSDT, SOLUSDT
  Timeframes: 4h, 1h | Direction: neutral
  Params: obv_period=20, atr_multiplier=2.0
  Code: strategy.py OK | ema_rsi_core.py OK
  Data: BTCUSDT OK | ETHUSDT OK | SOLUSDT OK

[PARTIAL] ict_v4 (product)
  Config: /path/to/config.yaml
  Symbols: BTCUSDT, ETHUSDT
  Data: BTCUSDT OK | ETHUSDT MISSING
  Issues: ETHUSDT 无K线数据

[SKIP]    broken (paper)
  Issues: 无配置文件, strategy.py 缺失

------------------------------------------------------------
Summary: 1 ready, 1 partial, 1 skip | 2 of 3 can proceed
============================================================
```

**JSON 输出**（`logs/analysis-{date}.json`）：

```json
{
  "analysis_version": "1.0",
  "timestamp": "2026-08-01T00:20:00",
  "source": "replay",
  "source_path": "./snapshot/20260801",
  "start_date": "20260702",
  "end_date": "20260801",
  "kline_data_dir": "./data/strategies/1m",
  "strategies": [
    {
      "strategy_name": "ema_rsi",
      "model": "product",
      "status": "ready",
      "config_path": "/path/to/config.test.yaml",
      "symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
      "timeframes": ["4h", "1h"],
      "direction": "neutral",
      "params": {"obv_period": 20, "atr_multiplier": 2.0},
      "code_checks": {"strategy_py": true, "core_py": "ema_rsi_core.py"},
      "kline_data": {
        "BTCUSDT": {"csv_exists": true, "row_count": 43200, "first_date": "20260601", "last_date": "20260801", "covers_range": true, "missing_range": null},
        "ETHUSDT": {"csv_exists": true, "row_count": 43200, "first_date": "20260601", "last_date": "20260801", "covers_range": true, "missing_range": null}
      },
      "issues": []
    }
  ],
  "summary": {"ready": 1, "partial": 1, "skip": 1, "total": 3}
}
```

**向后兼容**：
- `--skip-analysis` 标志跳过此阶段，恢复旧行为
- 分析脚本崩溃时：log 警告，回退到全量回测
- JSON 文件缺失/损坏时：回退到循环内原有 config 解析逻辑

---

## Phase 3: 每日回放回测（replay.sh）

### Step 1: 扫描 snapshot 目录

```bash
# 扫描指定日期的所有策略快照
SNAPSHOT_DAY_DIR="${SNAPSHOT_DIR:-./snapshot}/${REPLAY_DATE}"

if [ ! -d "$SNAPSHOT_DAY_DIR" ]; then
    echo "❌ snapshot 目录不存在: $SNAPSHOT_DAY_DIR"
    echo "  请先执行 /trading-replay sync 或指定有数据的日期"
    exit 1
fi

# 列出所有 {strategy}-{model} 目录
STRATEGY_SNAPSHOTS=()
for dir in "$SNAPSHOT_DAY_DIR"/*/; do
    if [ -d "$dir" ]; then
        basename_dir=$(basename "$dir")
        STRATEGY_SNAPSHOTS+=("$basename_dir")
    fi
done

echo "📋 发现 ${#STRATEGY_SNAPSHOTS[@]} 个策略快照:"
for s in "${STRATEGY_SNAPSHOTS[@]}"; do
    echo "  - $s"
done
```

### Step 2: 对每个策略快照执行回测

```bash
for snapshot in "${STRATEGY_SNAPSHOTS[@]}"; do
    # 解析 strategy 和 model
    strategy_name=$(echo "$snapshot" | rev | cut -d'-' -f2- | rev)
    model=$(echo "$snapshot" | rev | cut -d'-' -f1 | rev)

    echo "🔄 回测: ${strategy_name} (${model})"

    # 回测输出目录
    OUTPUT_DIR="${REPLAY_OUTPUTS_DIR:-./replay_outputs}/${REPLAY_DATE}/${snapshot}"
    mkdir -p "$OUTPUT_DIR"

    # 执行回测（默认: snapshot 日期前 30 天 ~ 当天，可通过 --start/--end 覆盖）
    $PYTHON_CMD -m backtest.run_backtest \
        --strategy "$strategy_name" \
        --start "${BT_START}" \
        --end "${BT_END}" \
        --config "snapshot/${REPLAY_DATE}/${snapshot}/config.yaml" \
        --output "$OUTPUT_DIR" \
        --log-level INFO \
        2>&1 | tee -a "${LOGS_DIR:-./logs}/replay-${REPLAY_DATE}.log"

    # 检查回测结果
    if [ -f "$OUTPUT_DIR/backtest_result.json" ]; then
        echo "✅ ${snapshot}: 回测完成"
    else
        echo "⚠ ${snapshot}: 回测未产出结果"
    fi
done
```

**回测输出目录结构**：

```
replay_outputs/
└── 20260801/
    ├── ema_rsi-product/
    │   ├── BTCUSDT/
    │   │   ├── backtest_result.json
    │   │   ├── trades.csv
    │   │   └── config.yaml
    │   ├── ETHUSDT/
    │   │   ├── backtest_result.json
    │   │   ├── trades.csv
    │   │   └── config.yaml
    │   └── SOLUSDT/
    │       ├── backtest_result.json
    │       ├── trades.csv
    │       └── config.yaml
    ├── ema_rsi-smoking/
    │   └── ...
    ├── ict_v4-product/
    │   └── ...
    └── ict_v4-paper/
        └── ...
```

**回测日志格式**（`logs/replay-20260801.log`）：

```
[2026-08-01 00:30:05] START replay.sh --date 20260801
[2026-08-01 00:30:05] 🔄 回测: ema_rsi (product)
[2026-08-01 00:30:12] ✅ ema_rsi-product: BTCUSDT 回测完成 (return: 2.3%)
[2026-08-01 00:30:18] ✅ ema_rsi-product: ETHUSDT 回测完成 (return: -0.8%)
[2026-08-01 00:30:24] ✅ ema_rsi-product: SOLUSDT 回测完成 (return: 5.1%)
[2026-08-01 00:30:24] 🔄 回测: ict_v4 (product)
[2026-08-01 00:30:35] ✅ ict_v4-product: BTCUSDT 回测完成 (return: 1.7%)
[2026-08-01 00:30:35] END replay.sh: 2 strategies, 6 symbols, 0 errors
```

---

## Phase 4: 结果汇总

### Step 1: 汇总当日回测结果

```bash
python3 -c "
import json, os, glob
from datetime import datetime

date = '${REPLAY_DATE}'
outputs_dir = '${REPLAY_OUTPUTS_DIR:-./replay_outputs}' + '/' + date
summary = []

for strategy_dir in sorted(glob.glob(outputs_dir + '/*')):
    strategy_name = os.path.basename(strategy_dir)
    for symbol_dir in sorted(glob.glob(strategy_dir + '/*')):
        symbol = os.path.basename(symbol_dir)
        result_file = symbol_dir + '/backtest_result.json'
        if os.path.exists(result_file):
            with open(result_file) as f:
                r = json.load(f)
            summary.append({
                'strategy': strategy_name,
                'symbol': symbol,
                'total_return': r.get('total_return', 0),
                'max_drawdown': r.get('max_drawdown', 0),
                'win_rate': r.get('win_rate', 0),
                'total_trades': r.get('total_trades', 0),
            })

# 输出摘要
print(f'📊 回测汇总 - {date}')
print(f'{\"策略\":<25} {\"代币\":<12} {\"收益\":<10} {\"回撤\":<10} {\"胜率\":<10} {\"交易数\":<8}')
print('-' * 75)
for s in summary:
    print(f'{s[\"strategy\"]:<25} {s[\"symbol\"]:<12} {s[\"total_return\"]*100:>8.2f}% {s[\"max_drawdown\"]*100:>8.2f}% {s[\"win_rate\"]*100:>8.1f}% {s[\"total_trades\"]:>6}')
"
```

### Step 2: 写入汇总日志

```bash
# 汇总日志路径
SUMMARY_LOG="${LOGS_DIR:-./logs}/replay-summary-${REPLAY_DATE}.log"

# 将汇总输出写入日志
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Replay Summary - ${REPLAY_DATE}" > "$SUMMARY_LOG"
# ... 追加上述汇总内容
```

---

## 定时任务配置

### crontab 示例

```cron
# 每日 00:15 执行策略代码备份
15 0 * * * cd /path/to/replay && python3 sync-exee.py --date $(date +\%Y\%m\%d) >> logs/cron-sync.log 2>&1

# 每日 00:30 执行回放回测
30 0 * * * cd /path/to/replay && bash replay.sh --date $(date +\%Y\%m\%d) >> logs/cron-replay.log 2>&1
```

**时区说明**：crontab 使用系统时区。如需 UTC，在 crontab 开头设置 `CRON_TZ=UTC`。

---

## 环境变量清单

### 必需配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DATA_PATH` | `./data` | K 线数据存储路径 |
| `KLINE_DATA_DIR` | `${DATA_PATH}/strategies/1m` | 1m K 线数据源目录 |
| `SNAPSHOT_DIR` | `./snapshot` | 策略代码快照目录 |
| `LOGS_DIR` | `./logs` | 日志输出目录 |
| `REPLAY_OUTPUTS_DIR` | `./replay_outputs` | 回测结果输出目录 |
| `PYTHON_CMD` | `python3` | Python 命令路径 |

### SCP 配置（sync 需要）

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `SCP_HOST` | （空） | 实盘机器 IP |
| `SCP_PORT` | `22` | SSH 端口 |
| `SCP_USER` | （空） | SSH 用户名 |
| `SCP_STRATEGY_DIR` | （空） | 远程策略代码目录 |
| `SCP_KEY` | `~/.ssh/id_rsa` | SSH 私钥路径 |
| `SCP_TIMEOUT` | `30` | SCP 超时秒数 |
| `SCP_RETRY` | `3` | SCP 重试次数 |

### .env.example 模板

```bash
# ===== 必需配置 =====
DATA_PATH=./data
KLINE_DATA_DIR=./data/strategies/1m
SNAPSHOT_DIR=./snapshot
LOGS_DIR=./logs
REPLAY_OUTPUTS_DIR=./replay_outputs
PYTHON_CMD=python3

# ===== SCP 连接（sync 需要） =====
SCP_HOST=your-server-ip
SCP_PORT=22
SCP_USER=trader
SCP_STRATEGY_DIR=/home/trader/strategies
SCP_KEY=~/.ssh/id_rsa
SCP_TIMEOUT=30
SCP_RETRY=3
```

---

## Claude Code 权限需求

```json
{
  "permissions": {
    "allow": [
      "Bash(python3:*)",
      "Bash(python:*)",
      "Bash(bash:*)",
      "Bash(scp:*)",
      "Bash(mkdir:*)",
      "Bash(cat:*)",
      "Bash(ping:*)",
      "Bash(date:*)",
      "Bash(wc:*)",
      "Bash(source:*)",
      "Read(*)",
      "Write(*)",
      "Edit(*)"
    ]
  }
}
```

---

## 执行顺序

```
用户输入:
  /trading-replay run              → 完整流程
  /trading-replay run --date XXX   → 指定日期完整流程
  /trading-replay sync             → 只备份
  /trading-replay replay           → 只回测
  /trading-replay replay --date XXX → 重新回放
       ↓
Phase 0: 环境预检
  ├── 检查 SCP 连接
  ├── 检查回测引擎
  ├── 检查 K 线数据
  └── 检查 snapshot 目录
       ↓
Phase 1: 配置初始化
  ├── 读取 .env + config.yaml
  ├── 验证必需配置
  └── 创建目录结构
       ↓
Phase 1.5: 远程策略发现（discover_remote.py）  ← NEW
  ├── SSH 到远程机器
  ├── 列出 strategies/ 下所有策略
  ├── 获取文件数、修改时间、大小
  └── 输出策略清单
       ↓
Phase 1.6: 策略确认  ← NEW
  ├── 等待用户确认备份范围
  ├── 支持: 全部 / 指定策略 / 指定策略+model
  └── 确认后进入 Phase 2
       ↓
Phase 2: 策略代码备份（sync-exee.py）
  ├── SCP 拉取策略代码
  ├── 按 snapshot/{day}/{strategy}-{model} 存放
  └── 记录同步日志
       ↓
Phase 2.5: 策略分析（analyze_snapshot.py）
  ├── 分析策略配置（symbols, timeframes, params）
  ├── 检查代码完整性（strategy.py, *_core.py）
  ├── 检查K线数据可用性（CSV 存在 + 日期范围覆盖）
  ├── 判定策略状态（ready/partial/skip）
  ├── 过滤 skip 策略，只对 ready/partial 执行回测
  └── 输出分析报告 + JSON
       ↓
Phase 3: 每日回放回测（replay.sh）
  ├── 扫描 snapshot/{day}/
  ├── 对每个 {strategy}-{model} 执行回测
  ├── 输出到 replay_outputs/{day}/{strategy}-{model}/
  └── 记录回测日志
       ↓
Phase 4: 结果汇总
  ├── 汇总当日所有策略回测结果
  └── 输出摘要日志
```

---

## Related Skills

- `trading-dev`: CTA 策略开发全生命周期
- `trading-discovery`: 指定代币/策略/时间范围的回测探索
