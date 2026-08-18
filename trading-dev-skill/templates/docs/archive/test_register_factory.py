#!/usr/bin/env python3
"""
测试 cta-strategy-code 注册策略到 cta_factory_service
"""

import sys
import os
sys.path.insert(0, "/home/qpw/workspace/cta-strategy-code")
os.chdir("/home/qpw/workspace/cta-strategy-code")

import xmlrpc.client
from strategy_core.strategy_engine import StrategyEngine

FACTORY_URL = "http://127.0.0.1:8888"

print("=" * 60)
print("测试 cta-strategy-code 注册策略到 cta_factory_service")
print("=" * 60)

# 1. 创建 StrategyEngine 实例
print("\n1. 创建 StrategyEngine 实例...")
engine = StrategyEngine(
    factory_endpoint=FACTORY_URL,
    strategies_dir="./strategies"
)
print("   ✓ StrategyEngine 创建成功")

# 2. 连接到 cta_factory_service
print("\n2. 连接到 cta_factory_service...")
connected = engine.connect_to_factory()
if connected:
    print("   ✓ 连接成功")
else:
    print("   ✗ 连接失败")
    sys.exit(1)

# 3. 发现策略
print("\n3. 发现策略...")
discovered = engine.discover_strategies()
print(f"   ✓ 发现策略：{discovered}")

# 4. 加载策略配置
print("\n4. 加载策略...")
# 创建一个假的策略实例用于测试
from strategy_core.strategy_engine.registry import StrategyRegistry

registry = StrategyRegistry()
registry.register(
    strategy_id="TestStrategy_BTC",
    strategy_name="cta_ict",
    module_path="strategies.cta_ict.strategy",
    config={"symbol": "BTCUSDT", "timeframe": "4h", "test": True}
)
engine.registry = registry
print("   ✓ 策略加载成功")

# 5. 注册到 cta_factory_service
print("\n5. 注册策略到 cta_factory_service...")
result = engine.register_to_factory()
if result:
    print("   ✓ 注册成功")
else:
    print("   ✗ 注册失败")

# 6. 验证注册
print("\n6. 验证注册...")
client = xmlrpc.client.ServerProxy(FACTORY_URL, allow_none=True)
status = client.status("TestStrategy_BTC")
print(f"   状态：{status}")

# 7. 测试启动策略（内部模式）
print("\n7. 测试启动策略（内部模式）...")
start_result = client.start("TestStrategy_BTC", {})
print(f"   启动结果：{start_result}")

# 8. 测试停止策略
print("\n8. 测试停止策略...")
stop_result = client.stop("TestStrategy_BTC", {})
print(f"   停止结果：{stop_result}")

# 9. 列出所有策略
print("\n9. 列出所有策略...")
list_result = client.list()
print(f"   已注册：{list_result.get('registered', [])}")
print(f"   运行中：{list_result.get('running', [])}")

print("\n" + "=" * 60)
print("测试完成!")
print("=" * 60)
