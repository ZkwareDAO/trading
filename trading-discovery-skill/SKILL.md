---
name: trading-discovery
description: 指定代币/策略/时间范围的回测探索 skill。支持 git pull 拉取策略 → 代币确认 → K线需求计算 → 多代币×多策略×自定义时间范围组合回测 → 后台执行，输出对比报告。
origin: trading
---

# Trading Discovery — 指定代币/策略/时间范围的回测探索

输入代币列表 + 策略列表 + 时间范围 → 组合回测 → 输出对比报告，一条链路闭环。

**核心行为**：灵活指定回测维度，探索策略在不同代币和时间范围下的表现。

**首要原则：无参数或参数不全时，必须一步一步引导用户，不要报错让用户自己补命令。**

## When to Activate

- 用户执行 `/trading-discover`（无参数）→ **进入交互式引导**
- 用户执行 `/trading-discover run --symbols BTCUSDT,ETHUSDT --strategies ema_rsi,ict_v4 --start 20260601 --end 20260701`（参数齐全）→ 跳过引导，直接 Phase 0
- 用户执行 `/trading-discover run --symbols BTCUSDT --start 20260601`（缺 strategies）→ **进入引导，只补缺失项**
- 用户说"探索回测"、"对比策略"、"多代币回测"
- 用户想看某个策略在不同代币或时间范围下的表现对比

## Commands

| 命令 | 说明 |
|------|------|
| `/trading-discover` | 无参数 → 进入交互式引导，一步一步收集参数 |
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

## Phase -1: 交互式引导（无参数/参数不全时） ← NEW

### 触发条件

进入引导的判定（满足任一即进入）：

| 条件 | 说明 |
|------|------|
| 无任何参数 | 用户只敲了 `/trading-discover` 或 `/trading-discover run` |
| 缺 `--strategies` 且无 `--all-strategies` | 必需参数缺失 |
| 缺 `--start` | 必需参数缺失 |
| 缺 `--symbols` 且 `--skip-analysis` | 此时 symbols 必需（无分析阶段无法从配置读取） |

**不进入引导**（参数齐全直接走原流程）：

- 有 `--all-strategies` + `--symbols` + `--start`
- 或 `--strategies` + `--start`（symbols 可从配置读）

### 引导核心原则

1. **缺啥补啥**：用户已经给的参数跳过不问，只问缺失项
2. **一步一问**：每次只问一个问题，给默认值 + 示例，用户答完再问下一个
3. **每步可改**：用户随时能修改前面给过的值
4. **不报错**：宁可多问一轮，也不要扔"参数不全，请补全命令"给用户
5. **引导完汇总**：所有参数收齐后，输出完整回测计划让用户确认，确认后才进 Phase 0

### 引导顺序

引导按下面顺序逐步收集，已提供的参数跳过对应步骤：

```
Step 0: 先跑环境快速探测（策略目录是否有可用策略）
        → 若无策略，先走 Phase 0.5 git pull 拉策略（这样后面能列出可用策略给用户选）
        → 若有策略，直接进 Step 1
       ↓
Step 1: 问策略（--strategies 或 --all-strategies）
        → 列出 STRATEGIES_DIR 下可用策略供选择
        → 给默认：all
       ↓
Step 2: 问代币（--symbols）
        → 若用户选了具体策略，从该策略配置读出默认 symbols 作为建议
        → 给默认：留空（从策略配置读取）
       ↓
Step 3: 问开始时间（--start）  ← 必填，无默认
        → 提示格式：YYYYMMDD 或 Unix 时间戳
        → 给示例：20260601
       ↓
Step 4: 问结束时间（--end）
        → 给默认：今天（当前日期）
       ↓
Step 5: 问可选参数（并行数/后台执行/跳过分析）
        → 给默认：全用默认值，直接回车跳过
       ↓
Step 6: 汇总确认 → 输出完整回测计划，用户确认后进 Phase 0
```

### Step 0: 引导前的环境快速探测

引导开始前先快速探测策略目录，目的是决定要不要先 git pull：

```bash
# 快速检查（不阻塞引导，只决定引导路径）
STRATEGIES_DIR="${STRATEGIES_DIR:-./strategies}"
if [ -d "$STRATEGIES_DIR" ] && [ "$(ls -1d "$STRATEGIES_DIR"/*/ 2>/dev/null | grep -v '\.git' | wc -l)" -gt 0 ]; then
    GUIDE_MODE="strategies_ready"   # 策略已就绪，直接引导选策略
else
    GUIDE_MODE="need_git_pull"      # 需要先 git pull，走 Phase 0.5
fi
```

- `need_git_pull`：先引导用户确认 git 地址 → 执行 Phase 0.5 拉策略 → 拉完列可用策略 → 进 Step 1
- `strategies_ready`：直接列可用策略 → 进 Step 1

### Step 1 话术模板：问策略

```
🧭 交互式引导 — 第 1 步（共 5 步）：选择策略

可用策略（来自 ./strategies）：
  1. ema_rsi      (3 configs)
  2. ict_v4       (2 configs)
  3. macd_cross   (1 config)

请选择（输入编号、策略名、或逗号分隔多个；输入 all 选全部）：
  > 1,2          ← 选 ema_rsi 和 ict_v4
  > all           ← 等同 --all-strategies
  > ema_rsi       ← 直接输策略名

默认：all
```

**收集逻辑**：
- 输入 `all` → `--all-strategies`
- 输入编号 → 映射到策略名
- 输入策略名 → 直接用
- 多个用逗号分隔

### Step 2 话术模板：问代币

```
🧭 交互式引导 — 第 2 步（共 5 步）：选择代币

（若已选策略，从策略配置读出默认代币作为建议）
ema_rsi 配置中的代币：BTCUSDT, ETHUSDT, SOLUSDT
ict_v4 配置中的代币：BTCUSDT, ETHUSDT

请输入要回测的代币（逗号分隔），或：
  > BTCUSDT,ETHUSDT,SOLUSDT   ← 直接指定
  > 留空回车                    ← 回测时从每个策略配置读取各自的代币
  > +DOGEUSDT                  ← 在建议基础上追加 DOGEUSDT

默认：留空（从策略配置读取）
```

### Step 3 话术模板：问开始时间（必填）

```
🧭 交互式引导 — 第 3 步（共 5 步）：开始时间（必填）

格式：YYYYMMDD 或 Unix 时间戳（秒）

示例：
  > 20260601       ← 2026年6月1日
  > 1748736000     ← Unix 时间戳

请输入开始时间：
```

**校验**：输入后立即校验格式，不合法则重新问，不要报错退出。

### Step 4 话术模板：问结束时间

```
🧭 交互式引导 — 第 4 步（共 5 步）：结束时间

默认：今天（20260811）
格式同开始时间（YYYYMMDD 或 Unix 时间戳）

请输入结束时间（留空回车用今天）：
```

### Step 5 话术模板：问可选参数

```
🧭 交互式引导 — 第 5 步（共 5 步）：可选参数

  并行回测数（--parallel，默认 1）：留空回车跳过
  后台执行（--background，默认否）：留空回车跳过，输入 y 后台跑
  跳过策略分析（--skip-analysis，默认否）：留空回车跳过

全部用默认值？直接回车即可。
```

### Step 6 话术模板：汇总确认

```
📋 引导完成 — 回测计划确认

  代币:    BTCUSDT, ETHUSDT, SOLUSDT
  策略:    ema_rsi, ict_v4
  时间:    20260601 - 20260811
  并行:    1
  后台:    否
  分析:    启用

回测组合 (6):
  1. ema_rsi × BTCUSDT
  2. ema_rsi × ETHUSDT
  3. ema_rsi × SOLUSDT
  4. ict_v4 × BTCUSDT
  5. ict_v4 × ETHUSDT
  6. ict_v4 × SOLUSDT

确认执行？
  > y / 回车   ← 进 Phase 0 正式预检 + 回测
  > n          ← 取消
  > 改 XX      ← 修改某项，如 "改 时间" 回到 Step 4 重问
```

### 引导收尾

用户确认后：
1. 把引导收集到的参数组装成等效命令行（内部使用，不必展示给用户）
2. **进入 Phase 0 正式预检**（引导前的 Step 0 只是快速探测，Phase 0 才是完整阻塞判定）

### 引导 vs 原流程对照

| 场景 | 旧行为 | 新行为（方案 B） |
|------|--------|----------------|
| `/trading-discover` 无参数 | 报错让用户补 run 命令 | 进引导，逐步问 5 步 |
| 只给 `--symbols` | 报错缺 strategies | 进引导，只问 strategies/start/end |
| 只给 `--start` | 报错缺 strategies/symbols | 进引导，只问 strategies/symbols |
| 参数齐全 | 直接 Phase 0 | 跳过引导，直接 Phase 0（不变） |

---

## Phase 0: 环境预检

### Step 0: 检查运行环境

```bash
# 1. 探测 Python（模板依赖在 .venv，很多环境没有 python3 这个名字）
PROJECT_DIR="${PROJECT_DIR:-.}"
if [ -z "${PYTHON_CMD:-}" ]; then
    if [ -x "${PROJECT_DIR}/.venv/bin/python" ]; then
        PYTHON_CMD="${PROJECT_DIR}/.venv/bin/python"
    elif command -v python3 &>/dev/null; then
        PYTHON_CMD="python3"
    else
        PYTHON_CMD="python"
    fi
fi

# 2. 检查回测引擎（v3.7 批量入口）
if (cd "$PROJECT_DIR" && $PYTHON_CMD -m backtest.batch_runner --help) &>/dev/null; then
    echo "✅ 回测引擎可用"
else
    echo "❌ 回测引擎不可用（阻塞项）"
fi

# 3. 检查 K 线数据
#    必须与项目 config/settings.yaml 的 data_manager.csv_dir 一致，
#    否则 run-profile 的 data_dir 校验不通过、回测启动即退出。
KLINE_DIR="${KLINE_DATA_DIR:-./data/klines}"
if [ -d "$KLINE_DIR" ] && [ -n "$(find "$KLINE_DIR" -name '*.csv' -print -quit 2>/dev/null)" ]; then
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

ema_rsi (overrides/: 3 个代币):
  Symbols:   BTCUSDT, ETHUSDT, SOLUSDT
  Timeframes: 4h, 1h
  Direction: neutral

ict_v4 (overrides/: 2 个代币):
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
    $PYTHON_CMD calc_data_requirements.py \
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
  配置:       ./strategies/ema_rsi/overrides/BTCUSDT.yaml
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
| `--python` | 自动探测 | Python 命令（默认 `$PROJECT_DIR/.venv/bin/python` → `python3` → `python`） |
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
$PYTHON_CMD analyze_strategies.py \
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
| overrides/<SYMBOL>.yaml | 策略参数文件（v3.7 单一事实来源） | 标记 skip |
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
  Data:   ./data/klines

[READY]   ema_rsi
  Config: /path/to/strategies/ema_rsi/overrides/BTCUSDT.yaml
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

### Step 1: 单次 batch_runner 调用执行全部组合

v3.7 的批量入口自带并发（`ProcessPoolExecutor`），不需要在 shell 里手工
控制后台任务。策略参数由 `strategies/<name>/overrides/<SYMBOL>.yaml`
自动解析，回测运行参数（输出目录/并发/资金/费率）由 run-profile 提供。

```bash
# 1. 构建运行清单：name:symbol,name:symbol（与实盘 --run 格式一致）
#    只纳入 overrides/<SYMBOL>.yaml 真实存在的组合 ——
#    显式清单里的文件缺失会让 batch_runner 整批报错。
RUN_LIST=""
for strategy in $STRATEGIES; do
    for symbol in $SYMBOLS; do
        [ -f "${STRATEGIES_DIR}/${strategy}/overrides/${symbol}.yaml" ] || continue
        RUN_LIST="${RUN_LIST:+$RUN_LIST,}${strategy}:${symbol}"
    done
done

# 2. 生成 run-profile（承载 output_dir / max_workers / cash / commission）
#    data_dir 由 make_profile.py 照抄 settings.yaml 的 data_manager.csv_dir，
#    不一致时模板启动即退出（verify_data_dir_consistency）。
$PYTHON_CMD make_profile.py \
    --project-dir "$PROJECT_DIR" \
    --name discovery \
    --output-dir "$DISCOVERY_OUTPUTS_DIR" \
    --max-workers "${PARALLEL:-1}"

# 3. 一次调用跑完所有组合
(cd "$PROJECT_DIR" && $PYTHON_CMD -m backtest.batch_runner \
    --run "$RUN_LIST" \
    --start "$START_DATE" \
    --end "$END_DATE" \
    --profile discovery \
    --log-level INFO) 2>&1 | tee -a "${LOGS_DIR}/discovery-${START_DATE}.log"
```

**并发控制**：由 profile 的 `max_workers` 决定（`--parallel N` 写入该字段），
不再用 shell 后台任务 + `wait -n`。

**⚠ 不要用 `batch_runner --daemon`**：该模式重建子命令时只传
`--profile` 和 `--batch-id`，会丢掉 `--run/--start/--end/--config`，
等于跑成空清单。需要后台执行请在外层 `nohup` 本脚本。

**输出目录结构**（由 `backtest/backtest_reporter.py` 决定）：

```
discovery_outputs/                        # = run-profile 的 output_dir
└── {strategy}/
    └── {date}/                           # 运行日期 YYYYMMDD
        └── {time}/                       # 运行时刻 HHMMSS
            └── {symbol}/
                ├── backtest_result.json  # 指标在 "metrics" 段，不在顶层
                ├── backtest_report.txt
                ├── backtest_trades.csv
                ├── backtest_equity.csv
                ├── backtest_signals.csv
                └── config.yaml           # 实际生效的参数副本，供复现
```

注意路径层级是 `{strategy}/{date}/{time}/{symbol}/` ——
每次运行独立成目录，同一组合多跑几次不会互相覆盖。

---

## Phase 3: 结果汇总

### Step 1: 汇总所有回测结果

用 `generate_report.py` 完成，它按 `rglob` 递归找结果文件，并从
`metrics` 段读指标：

```bash
$PYTHON_CMD generate_report.py \
    --output-dir "$DISCOVERY_OUTPUTS_DIR" \
    --start "$START_DATE" \
    --end "$END_DATE"
```

核心逻辑（两个容易踩的点都在这里）：

```python
from pathlib import Path
import json

base = Path("discovery_outputs")
summary = []
# 路径层级是 {strategy}/{date}/{time}/{symbol}/ —— 用 rglob 而不是固定层级
# glob，层级微调也不会静默漏结果
for result_file in sorted(base.rglob("backtest_result.json")):
    r = json.load(open(result_file))
    parts = result_file.relative_to(base).parts   # (strategy, date, time, symbol, file)
    # 指标在 "metrics" 段，不在顶层 —— 直接 r.get("total_return") 恒为 0
    m = r.get("metrics") if isinstance(r.get("metrics"), dict) else r
    summary.append({
        "strategy": parts[0],
        "symbol": parts[-2],
        "run_at": f"{parts[1]}/{parts[2]}",
        "total_return": m.get("total_return", 0),
        "roe": m.get("roe", 0),
        "max_drawdown": m.get("max_drawdown", 0),
        "win_rate": m.get("win_rate", 0),
        "total_trades": m.get("total_trades", 0),
        "sharpe_ratio": m.get("sharpe_ratio", 0),
        "profit_factor": m.get("profit_factor", 0),
    })
```

同一 (strategy, symbol) 跑过多次时按 `run_at` 取最新一次。

**零交易要单独点出来**：`total_return` 为 0 多数不是"策略没赚钱"，
而是回测期内一笔都没成交（数据不足 / 信号未触发 / 周期过长）。
报告里把 `total_trades == 0` 的组合单列，避免被读成有效结果。

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
| `PYTHON_CMD` | 自动探测 | Python 命令路径（留空则探测 `.venv/bin/python`） |

### .env.example 模板

```bash
# ===== 必需配置 =====
DATA_PATH=./data
KLINE_DATA_DIR=./data/klines
STRATEGIES_DIR=./strategies
DISCOVERY_OUTPUTS_DIR=./discovery_outputs
LOGS_DIR=./logs
PYTHON_CMD=
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
  /trading-discover                                  ← 无参数
  /trading-discover run --symbols S1 --start DATE    ← 参数不全
  /trading-discover run --symbols S1,S2 --strategies ST1,ST2 --start DATE --end DATE  ← 参数齐全
       ↓
Phase -1: 交互式引导（仅无参数/参数不全时）  ← NEW
  ├── Step 0: 环境快速探测（决定是否先 git pull）
  ├── Step 1: 问策略（缺 --strategies 时）
  ├── Step 2: 问代币（缺 --symbols 时）
  ├── Step 3: 问开始时间（缺 --start 时，必填）
  ├── Step 4: 问结束时间（缺 --end 时，默认今天）
  ├── Step 5: 问可选参数（并行/后台/跳过分析）
  └── Step 6: 汇总确认 → 用户确认后进 Phase 0
       ↓
Phase 0: 环境预检
  ├── 检查回测引擎
  ├── 检查 K 线数据
  └── 检查策略目录
       ↓
Phase 0.5: 策略代码获取（git pull）
  ├── 确认 git 仓库地址
  ├── git clone / git pull
  └── 列出可用策略
       ↓
Phase 0.6: 代币配置确认
  ├── 输出策略代币配置摘要
  ├── 支持 +SYMBOL / -SYMBOL / SYMBOL1=SYMBOL2
  └── 用户确认后继续
       ↓
Phase 0.7: K线数据需求计算（calc_data_requirements.py）
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
