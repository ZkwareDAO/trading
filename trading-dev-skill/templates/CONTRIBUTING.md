# Contributing to CTA Strategy Core

感谢参与本开源项目！本文档说明开发流程与提交规范。

## 开发环境

```bash
# 1. 安装依赖
pip install -r requirements.txt -r requirements-dev.txt

# 2. TA-Lib C 库（技术指标依赖）
# Ubuntu/Debian
sudo apt-get install ta-lib && pip install TA-Lib
# macOS
brew install ta-lib && pip install TA-Lib

# 3. 跑一次回测验证环境（用仓库自带示例数据，无需任何配置）
python3 -m backtest.run_backtest --strategies sar_snt3_v3:BTCUSDT --start 20260610 --end 20260708
```

只做回测/策略开发的话，第 3 步跑通即可——回测不依赖任何外部服务。

需要跑模拟盘/实盘时再配置：

```bash
cp .env.example .env
# 编辑 .env，按需填服务地址（全部可留空，留空则对应功能优雅降级）
```

`config/settings.yaml` 已入库并用 `${VAR}` 占位，无需复制模板。

## 提交前检查

```bash
# 数据管理器测试
python3 -m pytest data_manager/tests/ -v

# 回测框架测试
python3 -m pytest backtest/tests/ -v

# 类型/语法检查（编辑后必跑）
python3 -c "import ast,glob; [ast.parse(open(f).read()) for f in glob.glob('**/*.py', recursive=True)]"
```

改动回测或配置加载路径时，额外做**数值等价验收**：改动前后跑同一条命令，
对比 `backtest_result.json` 的 `metrics` 应完全一致（时间戳字段除外）。
指标变化就说明改动影响了策略行为，不是纯重构。

## 编码红线（必须遵守）

详见 [docs/strategy/AI_CONSTRAINTS.md](docs/strategy/AI_CONSTRAINTS.md)。核心：

- 入场判断只用已闭合 K 线（禁止未来函数）
- 信号时间戳用 K 线时间，禁止 `datetime.now()`
- 指标在 `BaseStrategyCore.analyze()` 内计算，禁止在 Strategy 类计算
- 禁止跳过数据不足检查
- State 可变默认值用 `field(default_factory=list)`，禁止 `[]` / `{}`
- 缓存字段不写入 `to_persist_dict()`
- **禁止让回测与实盘读两份不同的策略参数**（配置分叉 = 回测失真）

## 新增策略流程

1. 阅读 [docs/strategy/QUICKSTART.md](docs/strategy/QUICKSTART.md)
2. 用 skill `/zk_cta-strategy-logic-refine` 输出策略规格
3. 用 skill `/zk_cta-strategy-implement` 生成代码
4. 在 `strategies/<name>/overrides/<SYMBOL>.yaml` 放 per-symbol 参数
5. 在 `config/strategies.yaml` 注册策略 + symbols
6. 跑回测验证：`python3 -m backtest.run_backtest --strategies <name>:<SYMBOL> --start <YYYYMMDD>`

## 提交规范

- **Commit message**：`<type>: <desc>`，type ∈ `feat | fix | refactor | docs | test | chore`
- **脱敏**：禁止提交真实 IP / 域名 / 密钥 / 开发机绝对路径。配置用 `${ENV_VAR}` 占位，
  实际值放 `.env`（不入库）；测试固定值用 RFC5737 文档地址（`203.0.113.x`）
- **测试**：新功能必须带测试
- **文档**：改了行为就改文档；改了 CLI 参数必须同步 `docs/SCRIPTS.md` 与 `backtest/README.md`

## 配置约定（三层模型）

| 文件 | 用途 | 入库 |
|------|------|------|
| `config/settings.yaml` | 系统层：数据源 / 信号 / 引擎（实盘回测共用） | ✅（用 `${VAR}` 占位） |
| `config/strategies.yaml` | 编排层：跑哪些策略 × symbols（实盘回测共用） | ✅ |
| `strategies/<name>/overrides/<SYMBOL>.yaml` | 策略层：per-symbol 参数**唯一事实来源** | ✅ |
| `config/backtest.yaml` | run-profile：回测运行方式（键与 `settings.yaml` 不相交） | ✅ |
| `.env` | 实际服务地址 / 密钥 | ❌（仅 `.env.example` 入库） |

新增 profile 键前先确认**有代码消费它**。无消费者的"说明性配置"会与 `settings.yaml`
形成"两处不同值、且都不生效"的假象（`mode` / `signal_hub` / `strategy_engine`
已因此删除），`test_profile_contains_no_unconsumed_keys` 会拦住回退。

**关键约束**：策略参数（周期 / 资金 / 风控 / 交易所）只从策略层读取。
新增 CLI 参数或 profile 字段时，不得让它能覆盖策略参数——否则回测与实盘会读到
两份不同参数。完整规范见 [docs/CONFIG_UNIFICATION_SPEC.md](docs/CONFIG_UNIFICATION_SPEC.md)。

## 行为准则

友好、专业、对事不对人。提问前先搜 issue 和文档。
