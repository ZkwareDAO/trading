# Kafka 集成 User Journeys

## Journey 1: 策略通过 Kafka 订阅 K 线数据

```
As a 策略开发者,
I want 通过 Kafka 订阅特定 symbol 的 K 线数据,
So that 我可以从中心化的数据源获取实时数据，而不是每个策略单独连接 WebSocket
```

**验收标准:**
- 可以连接到 Kafka broker
- 可以订阅指定的 Kafka topic
- 可以按 symbol 过滤消息
- 可以动态添加/移除订阅的 symbol

## Journey 2: 策略启动时自动选择数据源

```
As a 策略运维人员,
I want 策略启动时自动选择 Kafka 或 WebSocket 作为数据源,
So that 当 Kafka 不可用时可以自动回退到 WebSocket
```

**验收标准:**
- Kafka 优先，WebSocket 回退
- 连接失败时有清晰的日志
- 可以通过配置禁用 Kafka

## Journey 3: 每个策略独立消费消息

```
As a 系统架构师,
I want 每个策略使用独立的 Consumer Group,
So that 多个策略可以同时运行，各自收到完整的消息
```

**验收标准:**
- 每个策略使用唯一的 group_id
- 多个策略互不影响
- Consumer Group 状态可监控

## Journey 4: 异步消费不阻塞事件循环

```
As a 异步应用开发者,
I want Kafka 消费在 asyncio 事件循环中正常工作,
So that 策略的其他异步任务不会被阻塞
```

**验收标准:**
- 使用 poll + asyncio.sleep 实现非阻塞
- 消息处理支持异步回调
- 正确处理取消和关闭

## Journey 5: K 线数据正确转换和缓存

```
As a 策略引擎,
I want 从 Kafka 收到的 K 线数据正确转换为 Kline 对象并更新缓存,
So that 策略可以获取最新的市场数据
```

**验收标准:**
- JSON 消息正确解析为 Kline 对象
- 缓存正确更新
- 支持策略回调通知
