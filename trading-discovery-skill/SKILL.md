---
name: trading-discovery
description: 指定代币/策略/时间范围的回测探索 skill。支持 git pull 拉取策略 → 代币确认 → K线需求计算 → 多代币×多策略×自定义时间范围组合回测 → 后台执行，输出对比报告。
origin: trading
---

# Trading Discovery — 指定代币/策略/时间范围的回测探索

输入代币列表 + 策略列表 + 时间范围 → 组合回测 → 输出对比报告，一条链路闭环。

**核心行为**：灵活指定回测维度，探索策略在不同代币和时间范围下的表现。

## When to Activate

- 用户执行 `/trading-discover run --symbols BTCUSDT,ETHUSDT --strategies ema_rsi,ict_v4 --start 20260601 --end 20260701`
- 用户执行 `/trading-discover run --all-strategies --symbols BTCUSDT --start 20260101`
- 用户说"探索回测"、"对比策略"、"多代币回测"
- 用户想看某个策略在不同代币或时间范围下的表现对比

## Commands

| 命令 | 说明 |
|------|------|
| `/trading-discover run --symbols S1,S2 --strategies ST1,ST2 --start DATE --end DATE` | 指定代币×策略×时间范围回测 |
| `/trading-discover run --all-strategies --symbols S1,S2 --start DATE` | 所有策略×指定代币回测 |
| `/trading-discover run --symbols S1 --all-timeframes --start DATE --end DATE` | 指定代币×所有时间框架回测 |
| `/trading-discover run --strategies ST1 --start DATE` | 不指定 symbols，从策略配置读取 |
| `/trading-discover run --symbols S1 --strategies ST1 --start DATE --skip-analysis` | 跳过策略分析阶段 |
| `/trading-discover run --background` | 后台执行回测（nohup + &） |
| `/trading-discover compare --date YYYYMMDD` | 查看指定日期的 discovery 结果对比 |
| `/trading-discover report --date YYYYMMDD` | 生成 discovery 对比报告 |

### 时间格式

| 格式 | 示例 | 说明 |
|------|------|------|
| YYYYMMDD | `20260601` | 日期字符串 |
| Unix 时间戳 | `1748736000` | 秒级时间戳 |

两种格式均支持，脚本自动识别。

---

## Phase 0: 环境预检

### Step 0: 检查运行环境

```bash
# 1. 检查回测引擎
PYTHON_CMD="${PYTHON_CMD:-python3}"
if $PYTHON_CMD -m backtest.run_backtest --help &>/dev/null; then
    echo "✅ 回测引擎可用"
else
    echo "❌ 回测引擎不可用（阻塞项）"
fi

# 2. 检查 K 线数据
KLINE_DIR="${KLINE_DATA_DIR:-./data/strategies/1m}"
if [ -d "$KLINE_DIR" ] && [ -f "$KLINE_DIR/BTCUSDT_1m.csv" ]; then
    echo "✅ K 线数据就绪: $KLINE_DIR"
else
    echo "❌ K 线数据未就绪（阻塞项）"
fi

# 3. 检查策略目录
STRATEGIES_DIR="${STRATEGIES_DIR:-./strategies}"
if [ -d "$STRATEGIES_DIR" ]; then
    strategy_count=$(ls -1d "$STRATEGIES_DIR"/*/ 2>/dev/null | wc -l)
    echo "✅ 策略目录: $STRATEGIES_DIR (${strategy_count} strategies)"
else
    echo "❌ 策略目录不存在: $STRATEGIES_DIR"
fi
```

**阻塞 vs 非阻塞**：

| 检测项 | 不达标时 | 原因 |
|--------|----------|------|
| 回测引擎 | **阻塞** | 核心依赖 |
| K 线数据 | **阻塞** | 核心依赖 |
| 策略目录 | **阻塞** | 无策略无法回测 |

---

## Phase 0.5: 策略代码获取（git pull） ← NEW

### Step 1: 确认 git 仓库地址

在回测前先拉取最新的策略代码。

**读取 git 地址**（优先级）：
1. 用户在命令中指定 `--git-url`
2. 从 `config.yaml` 的 `strategies.git_url` 读取
3. 从 `.env` 的 `STRATEGIES_GIT_URL` 读取
4. 都没有 → 询问用户输入

```bash
# 展示 git 地址供用户确认
echo "📋 策略代码来源:"
echo "  Git URL: ${STRATEGIES_GIT_URL}"
echo "  本地路径: ${STRATEGIES_DIR:-./strategies}"
echo ""
echo "确认拉取？(y/n/修改地址: git@github.com:user/other.git)"
```

### Step 2: 执行 git clone / pull

```bash
STRATEGIES_DIR="${STRATEGIES_DIR:-./strategies}"

if [ -d "${STRATEGIES_DIR}/.git" ]; then
    echo "📥 git pull..."
    cd "$STRATEGIES_DIR" && git pull
else
    echo "📥 git clone ${STRATEGIES_GIT_URL} → ${STRATEGIES_DIR}"
    git clone "$STRATEGIES_GIT_URL" "$STRATEGIES_DIR"
fi

# 验证
if [ $? -ne 0 ]; then
    echo "❌ git 操作失败，请检查地址和权限"
    exit 1
fi

echo "✅ 策略代码就绪: ${STRATEGIES_DIR}"
```

### Step 3: 列出可用策略

```bash
echo ""
echo "📋 可用策略:"
for d in "${STRATEGIES_DIR}"/*/; do
    name=$(basename "$d")
    [ "$name" = ".git" ] && continue
    cfg_count=$(find "$d" -name "config*.yaml" -o -name "config/*.yaml" 2>/dev/null | wc -l)
    echo "  - ${name} (${cfg_count} configs)"
done
```

---

## Phase 0.6: 代币配置确认 ← NEW

### Step 1: 展示代币配置并等待确认

策略分析完成后，输出代币配置摘要，让用户确认或调整。

**交互流程**：

```
📋 策略代币配置确认

ema_rsi (config.test.yaml):
  Symbols:   BTCUSDT, ETHUSDT, SOLUSDT
  Timeframes: 4h, 1h
  Direction: neutral

ict_v4 (config/BTCUSDT.yaml):
  Symbols:   BTCUSDT, ETHUSDT
  Timeframes: 1h
  Direction: long

是否需要调整代币配置？
  n              = 使用以上配置继续
  y              = 进入编辑模式
  指定修改       = ema_rsi +DOGEUSDT -SOLUSDT, ict_v4 +BNBUSDT
```

**支持的操作**：

| 语法 | 含义 |
|------|------|
| `+SYMBOL` | 添加代币 |
| `-SYMBOL` | 移除代币 |
| `SYMBOL1=SYMBOL2` | 替换代币 |

---

## Phase 0.7: K线数据需求计算（calc_data_requirements.py） ← NEW

### Step 1: 计算策略所需的最小K线数据天数

根据策略配置中的技术指标参数，计算至少需要提前准备多少天 K 线数据。

```bash
for strategy in $STRATEGIES; do
    python3 calc_data_requirements.py \
        --strategy-dir "${STRATEGIES_DIR}/${strategy}" \
        --start "$START_DATE" \
        --end "$END_DATE" \
        --kline-data-dir "$KLINE_DATA_DIR"
done
```

**输出示例**：

```
==============================================================
  K线数据需求分析
==============================================================
  策略:       ema_rsi
  配置:       ./strategies/ema_rsi/config.test.yaml
  代币:       BTCUSDT, ETHUSDT, SOLUSDT
  时间框架:   4h, 1h

  最大指标周期: 200 根K线
  最坏时间框架: 4h (240分钟/根)
  最少需要K线:  200 根
  最少数据天数: 34 天
  建议准备天数: 41 天 (+20% 安全边际)

  --- 本地K线数据状态 ---
  BTCUSDT: ✅ 20260101 ~ 20260809
  ETHUSDT: ✅ 20260101 ~ 20260809
  SOLUSDT: ✅ 20260615 ~ 20260809

  数据充足: ✅ 是
  Gap: 数据充足
==============================================================
```

**计算逻辑**：

1. 从策略配置 `params` 中提取所有技术指标周期参数
   - 识别关键字：`period`, `length`, `window`, `fast`, `slow`, `signal`, `ma`, `ema`, `atr`, `rsi` 等
2. 取最大周期值 `max_period`
3. 从 `timeframes` 中取最长时间框架
   - 例如 `4h` = 240 分钟/根
4. `最少数据天数 = ceil(max_period × 最坏timeframe分钟数 / 1440)`
5. `建议准备天数 = 最少天数 × 1.2 + 1`（+20% 安全边际）

**阻塞规则**：

| 检查结果 | 行为 |
|---------|------|
| 数据充足 | 继续进入 Phase 1 |
| 数据不足 | ⚠ 警告，给出缺少数天数和缺失 symbol 清单 |
| 完全无数据 | ❌ 阻塞，需要先下载K线数据 |

---

## Phase 1: 参数解析

### Step 1: 解析输入参数

**必需参数**：

| 参数 | 格式 | 说明 |
|------|------|------|
| `--strategies` | 逗号分隔 或 `--all-strategies` | 策略列表 |
| `--start` | YYYYMMDD 或时间戳 | 回测开始时间 |

**条件必需参数**：

| 参数 | 格式 | 说明 |
|------|------|------|
| `--symbols` | 逗号分隔 | 代币列表。`--skip-analysis` 时必需；否则可选，从策略配置读取 |

**可选参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--end` | 当天 | 回测结束时间 |
| `--config` | `config.yaml` | 配置文件路径 |
| `--output-dir` | `./discovery_outputs` | 输出目录 |
| `--parallel` | `1` | 并行回测数 |
| `--python` | `python3` | Python 命令 |
| `--skip-analysis` | `false` | 跳过策略分析阶段 |

### Step 2: 时间格式自动识别

```python
def parse_time(time_str: str) -> str:
    """解析时间输入，统一输出为 YYYYMMDD 格式"""
    # 纯数字且长度=10 → Unix 时间戳
    if time_str.isdigit() and len(time_str) == 10:
        from datetime import datetime
        dt = datetime.fromtimestamp(int(time_str))
        return dt.strftime("%Y%m%d")
    # YYYYMMDD 格式
    if time_str.isdigit() and len(time_str) == 8:
        return time_str
    raise ValueError(f"无法识别的时间格式: {time_str}，支持 YYYYMMDD 或 Unix 时间戳")
```

### Step 3: 验证策略存在性

```bash
for strategy in $STRATEGIES; do
    if [ ! -d "${STRATEGIES_DIR}/${strategy}" ]; then
        echo "❌ 策略不存在: ${strategy}"
        exit 1
    fi
done
```

### Step 4: 列出回测组合

```
📋 Discovery 回测计划:

  代币: BTCUSDT, ETHUSDT, SOLUSDT
  策略: ema_rsi, ict_v4
  时间: 20260601 - 20260701

  回测组合 (6):
    1. ema_rsi × BTCUSDT
    2. ema_rsi × ETHUSDT
    3. ema_rsi × SOLUSDT
    4. ict_v4 × BTCUSDT
    5. ict_v4 × ETHUSDT
    6. ict_v4 × SOLUSDT
```

---

## Phase 1.5: 策略分析（analyze_strategies.py）

### Step 1: 分析策略配置、代码完整性、K线数据

在回测前先分析策略，确定哪些策略可以回测、配置是否完整、K线数据是否覆盖回测范围。
当 `--symbols` 未指定时，从策略配置中读取默认 symbols。

```bash
python3 analyze_strategies.py \
    --strategies "$STRATEGIES" \
    --strategies-dir "$STRATEGIES_DIR" \
    --symbols "$SYMBOLS" \
    --start "$START_DATE" \
    --end "$END_DATE" \
    --kline-data-dir "$KLINE_DATA_DIR" \
    --output "${LOGS_DIR}/discovery-analysis-${START_DATE}.json"
```

**分析内容**：

| 检查项 | 说明 | 不达标时 |
|--------|------|----------|
| strategy.py | 策略入口文件是否存在 | 标记 skip |
| *_core.py | 策略核心逻辑文件 | 警告，不阻塞 |
| config/{symbol}.yaml 或 config.test.yaml | 策略配置文件 | 标记 skip |
| symbols | 配置中定义的代币列表（`--symbols` 未指定时从此读取） | 无 symbols 标记 partial |
| timeframes | 配置中定义的时间框架 | 信息展示 |
| K线数据 | 每个 symbol 的 CSV 是否存在、日期范围是否覆盖回测区间 | 缺失标记 partial |

**策略状态判定**：

| 状态 | 条件 | 后续动作 |
|------|------|----------|
| `ready` | 所有检查通过 | 执行回测 |
| `partial` | 部分检查不通过（如部分 symbol 无数据） | 执行回测（仅有效 symbol） |
| `skip` | 关键检查失败（无配置/无代码/无数据） | 跳过回测 |

**--symbols 可选行为**：

- 指定 `--symbols`：覆盖配置中的 symbols，只回测指定代币
- 不指定 `--symbols`：从每个策略的配置文件中读取 symbols 列表
- `--skip-analysis` + 不指定 `--symbols`：报错退出（无分析阶段无法读取配置）

**分析报告输出**（终端）：

```
============================================================
  Strategy Analysis Report
============================================================
  Source: discovery
  Path:   ./strategies
  Range:  20260601 ~ 20260701
  Data:   ./data/strategies/1m

[READY]   ema_rsi
  Config: /path/to/config.test.yaml
  Symbols: BTCUSDT, ETHUSDT, SOLUSDT
  Timeframes: 4h, 1h | Direction: neutral
  Params: obv_period=20, atr_multiplier=2.0
  Code: strategy.py OK | ema_rsi_core.py OK
  Data: BTCUSDT OK | ETHUSDT OK | SOLUSDT OK

[PARTIAL] ict_v4
  Config: /path/to/config/BTCUSDT.yaml
  Symbols: BTCUSDT, ETHUSDT
  Data: BTCUSDT OK | ETHUSDT MISSING
  Issues: ETHUSDT 无K线数据

------------------------------------------------------------
Summary: 1 ready, 1 partial, 0 skip | 2 of 2 can proceed
============================================================
```

**JSON 输出**（`logs/discovery-analysis-{date}.json`）：

结构与 replay Phase 2.5 相同，`source` 字段为 `"discovery"`。

**向后兼容**：
- `--skip-analysis` 标志跳过此阶段，恢复旧行为（此时 `--symbols` 必需）
- 分析脚本崩溃时：log 警告，回退到全量回测
- JSON 文件缺失/损坏时：回退到循环内原有 config 解析逻辑

---

## Phase 2: 执行回测

### Step 0: 后台执行模式

**`--background` 标志**：回测在后台执行，不阻塞终端。

```bash
# 后台执行
nohup bash discover.sh --strategies "$STRATEGIES" --symbols "$SYMBOLS" \
    --start "$START_DATE" --end "$END_DATE" \
    > "${LOGS_DIR}/discovery-${START_DATE}.log" 2>&1 &

echo "✅ 回测已在后台启动 (PID: $!)"
echo "   日志: ${LOGS_DIR}/discovery-${START_DATE}.log"
echo "   查看进度: tail -f ${LOGS_DIR}/discovery-${START_DATE}.log"
```

### Step 1: 对每个 (策略, 代币) 组合执行回测

```bash
for strategy in $STRATEGIES; do
    for symbol in $SYMBOLS; do
        echo "🔄 回测: ${strategy} × ${symbol}"

        OUTPUT_DIR="${DISCOVERY_OUTPUTS_DIR}/${strategy}/${symbol}/${START_DATE}-${END_DATE}"
        mkdir -p "$OUTPUT_DIR"

        # 查找策略配置
        STRATEGY_CONFIG="${STRATEGIES_DIR}/${strategy}/config/${symbol}.yaml"
        if [ ! -f "$STRATEGY_CONFIG" ]; then
            STRATEGY_CONFIG="${STRATEGIES_DIR}/${strategy}/config.test.yaml"
        fi

        # 执行回测
        $PYTHON_CMD -m backtest.run_backtest \
            --strategy "$strategy" \
            --start "$START_DATE" \
            --end "$END_DATE" \
            --symbol "$symbol" \
            --config "$STRATEGY_CONFIG" \
            --output "$OUTPUT_DIR" \
            --log-level INFO \
            2>&1 | tee -a "${LOGS_DIR}/discovery-${START_DATE}.log"
    done
done
```

**并行控制**：

```bash
# --parallel N 控制并发数
PARALLEL="${PARALLEL:-1}"
if [ "$PARALLEL" -gt 1 ]; then
    echo "$COMBINATIONS" | xargs -P "$PARALLEL" -I {} bash -c '
        strategy=$(echo {} | cut -d: -f1)
        symbol=$(echo {} | cut -d: -f2)
        # ... 执行回测
    '
fi
```

**输出目录结构**：

```
discovery_outputs/
├── ema_rsi/
│   ├── BTCUSDT/
│   │   └── 20260601-20260701/
│   │       ├── backtest_result.json
│   │       ├── trades.csv
│   │       └── config.yaml
│   ├── ETHUSDT/
│   │   └── 20260601-20260701/
│   │       └── ...
│   └── SOLUSDT/
│       └── 20260601-20260701/
│           └── ...
└── ict_v4/
    ├── BTCUSDT/
    │   └── 20260601-20260701/
    │       └── ...
    ├── ETHUSDT/
    │   └── 20260601-20260701/
    │       └── ...
    └── SOLUSDT/
        └── 20260601-20260701/
            └── ...
```

---

## Phase 3: 结果汇总

### Step 1: 汇总所有回测结果

```python
import json, os, glob

summary = []
for strategy_dir in sorted(glob.glob("discovery_outputs/*")):
    strategy = os.path.basename(strategy_dir)
    for symbol_dir in sorted(glob.glob(f"{strategy_dir}/*")):
        symbol = os.path.basename(symbol_dir)
        for date_range_dir in sorted(glob.glob(f"{symbol_dir}/*")):
            date_range = os.path.basename(date_range_dir)
            result_file = f"{date_range_dir}/backtest_result.json"
            if os.path.exists(result_file):
                with open(result_file) as f:
                    r = json.load(f)
                summary.append({
                    "strategy": strategy,
                    "symbol": symbol,
                    "date_range": date_range,
                    "total_return": r.get("total_return", 0),
                    "max_drawdown": r.get("max_drawdown", 0),
                    "win_rate": r.get("win_rate", 0),
                    "total_trades": r.get("total_trades", 0),
                    "sharpe_ratio": r.get("sharpe_ratio", 0),
                    "profit_factor": r.get("profit_factor", 0),
                })
```

### Step 2: 输出对比报告

```
📊 Discovery 回测对比报告

时间范围: 20260601 - 20260701

=== 按策略对比 ===

ema_rsi:
  BTCUSDT:  +2.3%  | 回撤 8.2%  | 胜率 45.0% | 交易 23 | 夏普 1.2
  ETHUSDT:  -0.8%  | 回撤 12.1% | 胜率 38.5% | 交易 18 | 夏普 0.6
  SOLUSDT:  +5.1%  | 回撤 6.5%  | 胜率 52.0% | 交易 31 | 夏普 1.8

ict_v4:
  BTCUSDT:  +1.7%  | 回撤 9.8%  | 胜率 42.1% | 交易 19 | 夏普 0.9
  ETHUSDT:  +3.2%  | 回撤 7.3%  | 胜率 48.0% | 交易 25 | 夏普 1.4
  SOLUSDT:  -1.5%  | 回撤 15.2% | 胜率 35.0% | 交易 14 | 夏普 0.3

=== 按代币对比 ===

BTCUSDT: ema_rsi (+2.3%) > ict_v4 (+1.7%)
ETHUSDT: ict_v4 (+3.2%) > ema_rsi (-0.8%)
SOLUSDT: ema_rsi (+5.1%) > ict_v4 (-1.5%)

=== 最佳组合 ===
  策略×代币: ema_rsi × SOLUSDT (+5.1%)
  策略×代币: ict_v4 × ETHUSDT (+3.2%)
```

### Step 3: 写入报告文件

```bash
REPORT_FILE="${DISCOVERY_OUTPUTS_DIR}/discovery-report-${START_DATE}-${END_DATE}.md"
# 将上述对比报告写入 $REPORT_FILE
```

---

## 环境变量清单

### 必需配置

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `DATA_PATH` | `./data` | K 线数据存储路径 |
| `KLINE_DATA_DIR` | `${DATA_PATH}/strategies/1m` | 1m K 线数据源目录 |
| `STRATEGIES_DIR` | `./strategies` | 策略代码目录 |
| `DISCOVERY_OUTPUTS_DIR` | `./discovery_outputs` | Discovery 结果输出目录 |
| `LOGS_DIR` | `./logs` | 日志输出目录 |
| `PYTHON_CMD` | `python3` | Python 命令路径 |

### .env.example 模板

```bash
# ===== 必需配置 =====
DATA_PATH=./data
KLINE_DATA_DIR=./data/strategies/1m
STRATEGIES_DIR=./strategies
DISCOVERY_OUTPUTS_DIR=./discovery_outputs
LOGS_DIR=./logs
PYTHON_CMD=python3
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
      "Bash(mkdir:*)",
      "Bash(xargs:*)",
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
  /trading-discover run --symbols S1,S2 --strategies ST1,ST2 --start DATE --end DATE
  /trading-discover run --all-strategies --symbols S1 --start DATE
       ↓
Phase 0: 环境预检
  ├── 检查回测引擎
  ├── 检查 K 线数据
  └── 检查策略目录
       ↓
Phase 0.5: 策略代码获取（git pull）  ← NEW
  ├── 确认 git 仓库地址
  ├── git clone / git pull
  └── 列出可用策略
       ↓
Phase 0.6: 代币配置确认  ← NEW
  ├── 输出策略代币配置摘要
  ├── 支持 +SYMBOL / -SYMBOL / SYMBOL1=SYMBOL2
  └── 用户确认后继续
       ↓
Phase 0.7: K线数据需求计算（calc_data_requirements.py）  ← NEW
  ├── 提取技术指标周期参数
  ├── 计算最少需要天数
  ├── 检查本地数据是否充足
  └── 输出 gap 分析
       ↓
Phase 1: 参数解析
  ├── 解析代币列表、策略列表、时间范围
  ├── 时间格式自动识别（YYYYMMDD / 时间戳）
  ├── 验证策略存在性
  └── 列出回测组合
       ↓
Phase 1.5: 策略分析（analyze_strategies.py）
  ├── 分析策略配置（symbols, timeframes, params）
  ├── 检查代码完整性（strategy.py, *_core.py）
  ├── 检查K线数据可用性（CSV 存在 + 日期范围覆盖）
  ├── 判定策略状态（ready/partial/skip）
  ├── --symbols 未指定时从配置读取默认 symbols
  ├── 过滤 skip 策略，只对 ready/partial 执行回测
  └── 输出分析报告 + JSON
       ↓
Phase 2: 执行回测
  ├── 对每个 (策略, 代币) 组合执行回测
  ├── 输出到 discovery_outputs/{strategy}/{symbol}/{date_range}/
  └── 支持并行 (--parallel N)
       ↓
Phase 3: 结果汇总
  ├── 汇总所有回测结果
  ├── 按策略对比 + 按代币对比
  └── 输出对比报告
```

---

## Related Skills

- `trading-dev`: CTA 策略开发全生命周期
- `trading-replay`: 每日策略代码备份 + 回放回测
