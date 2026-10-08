# CTA Strategy Core 变更日志

所有重要变更将记录在此文件中。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

---

## [Unreleased]

### 已添加
- signal_logging: 新增 `direct_trading` 配置与 `BinanceTrader` —— 直连 Binance U 本位合约下单
  - 启用后信号不再经 HTTP 推送，由策略进程直接下单；与 `signal_hub` 互斥
    （同时开启时自动禁用 HTTP，避免重复开仓）
  - 凭证只从 `.env` 读（`BINANCE_API_KEY` / `BINANCE_API_SECRET`），缺失时进程启动即失败
  - 数量按 `signal_cash × leverage / price` 折算，精度取 `exchangeInfo` 的 stepSize 并**向下**取整
  - 平仓一律 MARKET + reduceOnly 且数量取交易所实际持仓；反手先平后开，平仓失败则放弃开仓
  - `newClientOrderId = signal_id` 作幂等键；仅 `paper_trading` 不下单
    （`live` 与 `smoking` 都会真实成交）
- backtest: 回测时自动保存大周期 CSV（15m/4h/1d），解决大周期数据不同步问题
  - 新增 `_save_big_interval_csvs()` 函数
  - 回测完成后自动更新 `{data_dir}/{interval}/{symbol}_{interval}.csv`
  - 合并去重，保留历史数据
- ICT: 新增 `SwingPoint` 数据类，包含 `bar_index` 和可选 `timestamp`
  - 支持通过 `swing_recent_bars` 参数限制波段点分析范围
  - 止盈目标计算现在基于 `SwingPoint.price` 属性
- ICT: 新增 7 个测试覆盖止盈目标计算逻辑（`test_tp_target.py`）

### 已移除
- signal_logging: **移除 Kafka 直推通道**（`kafka_producer.py`、`retry_queue.py`）
  - 删除 `KafkaSignalProducer`（含熔断器、去重 TTL、指数退避）与 `_SignalJSONEncoder`
  - 删除 `retry_queue.py`（失败信号持久化队列）—— 生产代码零调用，属死代码
  - `SignalLogger` 移除 `kafka_producer` / `kafka_topic` 参数；`kafka_topic` 更名为 `topic`
  - 配置删除 `signal_logging.kafka` 整段、`.env.example` 删 `KAFKA_BOOTSTRAP_SERVERS`、
    `requirements.txt` 删 `kafka-python-ng`
  - **保留** HTTP v1 payload 的 `topic` 字段（Signal Hub 的路由参数，与 Kafka 客户端无关），
    值改为 `logger.DEFAULT_SIGNAL_TOPIC = "strategy_signals"`，不再暴露为配置项
  - 删除 63 个测试用例，全部是已删除代码的测试（29+9+12 个整文件 + 13 个类级）。
    其中测 `CtaSignalCSV` 的用例已改写保留 —— `from_signal` 的 metadata 清理现在是
    HTTP 通道的**唯一**防线（不再有 encoder 兜第二层），
    见 `test_signal_metadata_serialization.py`（原 `test_kafka_metadata_serialization.py`）
  - ⚠️ 副作用：HTTP 推送失败后不再有降级兜底。当前 `log_signal` 在无通道/推送失败时
    仍返回 `True`（信号被丢弃却报告成功），该缺陷影响面因此变大，待后续修复

### 已修复
- backtest: 回测缺数据时的「自动下载」根本不联网 — 改走 `scripts/download_data.py`
  - 原走 `data_manager.load_klines_data`，它只扫本地按日 ZIP 解包目录
    （`$DATA_PATH/binance/futures/um/daily/...`），干净环境永远返回空 DataFrame
  - 新增 `download_data.download_range()`（区间由调用方给定，复用归档分块 + merge 链路），
    `preload_klines_to_cache` 只走这一条下载路径，删除 `load_klines_data`/`save_to_csv` 引用
  - 只补「需要且缺失」的子区间（头部 warm-up 缺口 / 尾部缺口），
    报障 case 从「CSV 末根到今天 47 天」收窄为实际需要的 12 天
- backtest: 数据不覆盖回测区间时改为 **exit 1**，不再静默产出零成交报告
  - 原实现下载失败只打 WARNING 继续跑，CSV 只到 07-08 而回测窗口自 08-20 起时，
    产出「处理 K 线数：0」的报告且退出码 0 —— 看起来像"策略没触发信号"
  - 错误信息含需要/实有区间、缺口天数与手动补数命令
  - warm-up 不足同样硬失败（指标数据不足只 warn 不阻断，属静默失真）
  - 中部空洞不阻断（交易所停机属常态），端点覆盖才是可执行信号
- backtest: `sync_end` 夹到当前时刻，不再向交易所索要未来 K 线
  - `--end` 取当天时会算出今天 23:59:59（比"现在"晚十几小时），
    使尾部缺口判据恒真，每次回测都白跑一次注定拿不到数据的下载
- data_manager: KlineRepository CSV 写入性能优化 — 每次 WS K 线到达时不再全量读写 CSV
  - 新增 `_try_fast_append()` / `_read_csv_tail()` / `_append_to_csv()` 智能保存方法
  - 无时间戳重叠时直接追加（~1ms），仅重叠时回退全量合并（~2s）
  - 1m CSV (190 万行) 写入从 ~2s 降至 ~1ms，WS K 线不再阻塞
- K线冷却: 修复使用错误时间框架导致的实盘与回测不一致
  - 新增 `cooldown_timeframe` 配置项，默认使用最后一个时间框架（入场时间框架）
  - 回测和实盘行为现在一致（之前回测跳过冷却）
  - 多时间框架策略（如 ICT: 1d/4h/15m）现在正确使用入场时间框架（15m）进行冷却
- strategies: 策略状态清理 bug 修复
  - `ICTStateV3.clear_position()` 现在清理所有 ICT 特有字段（entry_fvg, entry_prices, tp_target 等）
  - `RBreakerStateV3.clear_position()` 现在清理所有 R-Breaker 特有字段（price_lines, prev_high/low, reverse_count_today 等）
  - `DolphinStateV2.clear_position()` 现在清理所有 Dolphin 特有字段（channel, bars_since_entry）
  - 防止平仓后特有字段残留导致错误的入场判断

---

## [3.4.1] - 2026-04-02

### 已修改
- 项目重命名：`strategy-code` → `cta-strategy-code`
- 更新所有文档中的路径引用
- 更新测试文件中的绝对路径
- 更新 .claude/settings.local.json 中的路径配置
- 重新创建虚拟环境并安装依赖

### 已添加
- docs/TEST_CASES.md: 项目重命名测试用例文档
- test_rename_project.py: 自动化测试脚本

### 受影响文件
- README.md
- docs/SYSTEM_OVERVIEW.md
- strategies/ARCHITECTURE.md
- strategies/AUTONOMOUS_CONFIG.md
- test_register_factory.py
- .claude/settings.local.json
- strategy_core/strategy_engine/engine.py (注释)

### 测试结果
- 路径引用一致性测试：✓ 通过
- 虚拟环境验证测试：✓ 通过
- 策略模块导入测试：✓ 通过
- 配置文件加载测试：✓ 通过
- 策略注册测试：✓ 通过
- 文档完整性测试：✓ 通过
- 核心引擎测试：✓ 通过
- 数据管理器测试：✓ 通过

**总计**: 23/23 测试通过

---

## [3.4.0] - 2026-04-02

### 已修复
- 策略信号生成问题：三个策略（cta_rbreaker、cta_trend、cta_ict）在 K 线新增后未能正常生成信号

### 已添加
- 策略初始化重试机制：在 `on_kline()` 中检测策略核心状态，未初始化则自动重试
- 数据充足性检查（ICT 策略）：检查多时间框架数据是否满足最低要求
- 诊断日志：记录策略分析结果和信号强度详情
- 信号强度警告：当信号强度接近阈值时记录警告日志

### 已修改
- cta_rbreaker/strategy.py: 添加重试初始化逻辑
- cta_trend/strategy.py: 添加重试初始化逻辑
- cta_ict/strategy.py: 增强数据检查、添加诊断日志、信号强度警告
- cta_ict/ict_core.py: 优化信号强度计算逻辑
- cta_ict/config.yaml: 将 min_strength 从 0.5 降低到 0.4

### 技术细节
- R-Breaker: 初始化需要至少 2 根 K 线获取前一日数据
- Trend: 初始化需要至少 20 根 K 线计算均线
- ICT: 每个时间框架需要至少 5 根 K 线进行分析
- ICT 信号强度：score=1 时 0.4，score=2 时 0.7，score=3+ 时 1.0

### 文档
- docs/STRATEGY_SIGNAL_FIX.md: 新增策略信号修复详细文档
- strategies/CHECKLIST.md: 添加初始化重试和诊断日志检查项
- strategies/QUICK_REFERENCE.md: 添加信号调试和配置建议
- docs/KLINE_POLL_OPTIMIZATION.md: 添加策略信号修复记录

---

## [3.3.4] - 2026-04-02

### 已添加
- 策略多标的支持：cta_rbreaker 和 cta_trend 支持 `symbols` 和 `timeframes` 数组配置
- 向后兼容：仍支持 `symbol` 和 `timeframe` 单数格式配置
- 自动数据加载：为所有订阅的 symbol/timeframe 组合自动加载数据
- 独立冷却机制：多标的模式下各标的冷却时间独立计算

### 已修改
- cta_rbreaker/strategy.py: 支持数组格式，subscribed_symbols 返回所有标的
- cta_trend/strategy.py: 支持数组格式，subscribed_symbols 返回所有标的
- strategies/ARCHITECTURE.md: 更新配置说明和多标的模式文档
- strategies/SIGNAL_CSV_GUIDE.md: 更新策略命名示例
- strategies/README.md: 更新版本号

### 技术细节
- 策略名称使用第一个 symbol 和 timeframe 生成
- 多标的模式下，data_manager.register_timeframes() 注册所有时间周期
- get_status() 返回 symbols 和 timeframes 数组信息

---

## [3.3.3] - 2026-03-27

### 已添加
- 策略状态同步机制：main.py 定期从 factory-service 同步策略状态
- 每 5 次轮询同步一次状态（约 150 秒）
- 确保本地状态与 factory-service 保持一致

### 已修复
- 修复外部停止命令后策略仍执行的问题
- 修复策略状态不同步的问题

---

## [3.3.2] - 2026-03-27

### 已修复
- 修复 DATA_PATH 配置问题
- 从配置文件读取 source_data_path，不再依赖环境变量

---

## [3.3.1] - 2026-03-27

### 已修复
- 修复自动数据同步问题
- 在 main.py 中设置 DATA_PATH 环境变量
- 确保启动时自动同步新数据

---

## [3.3.0] - 2026-03-27

### 已添加
- 多时间框架数据同步功能
- 支持从 1m 源数据聚合生成 4h、1h 等周期数据
- KlineRepository 轻量级设计，只维护状态不存储数据

### 优化
- 数据聚合逻辑：OHLCV 标准聚合规则
- 迭代更新支持，自动合并去重

---

## [3.2.0] - 2026-03-26

### 已添加
- K 线 symbol 验证机制
- 添加防御性检查，验证 K 线 symbol 与策略订阅一致

### 已修复
- 修复错误策略接收 K 线的问题
- 修复信号价格错误的问题

---

## [3.1.0] - 2026-03-26

### 已修复
- 数据同步优化
- 同一天数据同步判断
- K 线分发修复：K 线只分发给对应策略
- CSV 列修复：避免列重复
- get_new_klines 优化

---

## [3.0.0] - 2026-03-25

### 已变更
- 重构：与 cta_factory_service 职责分离
- 策略核心专注于策略执行
- 工厂服务专注于策略管理

---

## [2.1.0] - 2026-03-23

### 已添加
- K 线轮询优化
- get_new_klines() 方法：自动判断新增 K 线
- timeframe 自适应：从策略实例获取正确周期
- 缓存自动刷新：检测文件修改时间

### 优化
- 策略调用频率减少 99%
- 支持任意时间周期
- 实时感知新数据

---

## [2.0.0] - 2026-03-20

### 已添加
- 自主配置模式
- CSV/JSON 格式统一
- Kafka 支持
- 策略名称自动生成

### 已变更
- 策略配置文件移至策略目录内
- 策略不依赖外部 ID

---

## [1.3.0] - 2026-03-20

### 已添加
- CTA R-Breaker 策略
- CTA Trend 策略
- 信号 CSV 适配器

---

## [1.2.0] - 2026-03-19

### 已修复
- 修复 data_manager
- 支持分层数据目录

---

## [1.1.0] - 2026-03-18

### 已变更
- 重构 data_manager 为纯本地 CSV 读取

---

## [1.0.0] - 2026-03-18

### 已添加
- 初始版本
- 基础策略引擎
- 数据管理器
- 信号日志系统

---

## 版本说明

### 语义化版本

- **主版本号**：不兼容的 API 修改
- **次版本号**：向下兼容的功能性新增
- **修订号**：向下兼容的问题修正

### 版本号更新规则

1. 主架构变更 → 主版本号 +1
2. 新功能添加 → 次版本号 +1
3. Bug 修复 → 修订号 +1

---

## 未来计划

- [ ] 添加更多技术指标
- [ ] 支持更多数据源
- [ ] 策略回测功能
- [ ] 实时性能监控
