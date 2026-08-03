#!/usr/bin/env python3
"""
strategy_engine/registry.py 线程安全测试

测试 StrategyRegistry 的线程安全性：
1. 多线程同时注册策略
2. 多线程同时更新状态
3. 多线程同时读取和写入
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import threading
import time
from typing import List
from strategy_core.strategy_engine.registry import StrategyRegistry, StrategyStatus


class TestRegistryThreadSafety:
    """测试注册表线程安全"""

    def test_concurrent_register(self):
        """测试多线程并发注册策略"""
        registry = StrategyRegistry()
        results: List[bool] = []
        errors: List[Exception] = []

        def register_strategy(strategy_id: str):
            try:
                entry = registry.register(
                    strategy_id=strategy_id,
                    strategy_name=f"Strategy_{strategy_id}",
                    module_path=f"/path/to/{strategy_id}",
                    config={"test": True}
                )
                results.append(entry is not None)
            except Exception as e:
                errors.append(e)
                results.append(False)

        # 创建 10 个线程同时注册
        threads = []
        for i in range(10):
            t = threading.Thread(target=register_strategy, args=(f"strategy_{i}",))
            threads.append(t)

        # 同时启动所有线程
        for t in threads:
            t.start()

        # 等待所有线程完成
        for t in threads:
            t.join()

        # 验证所有注册都成功
        assert len(results) == 10, "所有 10 个线程都应完成"
        assert all(results), "所有注册都应成功"
        assert len(errors) == 0, f"不应有错误：{errors}"
        assert registry.count() == 10, "注册表应有 10 个策略"

        print("✓ 多线程并发注册测试通过")

    def test_concurrent_status_update(self):
        """测试多线程并发更新策略状态"""
        registry = StrategyRegistry()

        # 先注册一个策略
        registry.register(
            strategy_id="test_strategy",
            strategy_name="Test Strategy",
            module_path="/path/to/test",
            config={}
        )

        def update_status(status: StrategyStatus):
            registry.update_status("test_strategy", status)

        # 创建 20 个线程同时更新状态
        threads = []
        statuses = [StrategyStatus.RUNNING, StrategyStatus.STOPPED, StrategyStatus.PAUSED] * 6 + [StrategyStatus.ERROR]

        for status in statuses:
            t = threading.Thread(target=update_status, args=(status,))
            threads.append(t)

        # 同时启动
        for t in threads:
            t.start()

        # 等待完成
        for t in threads:
            t.join()

        # 验证最终状态是有效的（不验证更新次数，因为并发更新会覆盖）
        entry = registry.get("test_strategy")
        assert entry is not None, "策略应存在"
        assert entry.status in StrategyStatus, "状态应是有效的 StrategyStatus"

        print("✓ 多线程并发状态更新测试通过")

    def test_concurrent_read_write(self):
        """测试多线程并发读取和写入"""
        registry = StrategyRegistry()
        read_success = 0
        write_success = 0
        read_lock = threading.Lock()
        write_lock = threading.Lock()

        def writer(strategy_id: str):
            nonlocal write_success
            try:
                registry.register(
                    strategy_id=strategy_id,
                    strategy_name=f"Strategy_{strategy_id}",
                    module_path=f"/path/to/{strategy_id}",
                    config={}
                )
                with write_lock:
                    write_success += 1
            except Exception:
                pass

        def reader():
            nonlocal read_success
            try:
                strategies = registry.list_strategies()
                running = registry.get_running_strategies()
                count = registry.count()
                # 读取操作不应抛出异常
                with read_lock:
                    read_success += 1
            except Exception:
                pass

        # 创建 5 个写线程和 10 个读线程
        threads = []
        for i in range(5):
            t = threading.Thread(target=writer, args=(f"writer_{i}",))
            threads.append(t)

        for _ in range(10):
            t = threading.Thread(target=reader)
            threads.append(t)

        # 同时启动
        for t in threads:
            t.start()

        # 等待完成
        for t in threads:
            t.join()

        # 验证
        assert write_success > 0, "应有写入成功"
        assert read_success > 0, "应有读取成功"
        assert registry.count() <= 5, "最多 5 个策略被注册"

        print("✓ 多线程并发读写测试通过")

    def test_get_and_set_instance_thread_safe(self):
        """测试 get_instance 和 set_instance 的线程安全"""
        registry = StrategyRegistry()

        # 注册策略
        registry.register(
            strategy_id="test_instance",
            strategy_name="Test Instance",
            module_path="/path/to/test",
            config={}
        )

        instance_values = []
        lock = threading.Lock()

        def set_instance(value: str):
            registry.set_instance("test_instance", value)
            time.sleep(0.001)  # 小的延迟增加竞争可能性
            with lock:
                instance_values.append(value)

        def get_instance():
            value = registry.get_instance("test_instance")
            with lock:
                instance_values.append(("read", value))

        # 创建设置和获取线程
        threads = []
        for i in range(5):
            t = threading.Thread(target=set_instance, args=(f"value_{i}",))
            threads.append(t)
            t2 = threading.Thread(target=get_instance)
            threads.append(t2)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # 不应有异常
        assert len(instance_values) == 10, "所有操作都应完成"

        print("✓ get/set_instance 线程安全测试通过")

    def test_unregister_thread_safe(self):
        """测试 unregister 的线程安全"""
        registry = StrategyRegistry()

        # 注册 10 个策略
        for i in range(10):
            registry.register(
                strategy_id=f"unreg_{i}",
                strategy_name=f"Strategy_{i}",
                module_path="/path/to/test",
                config={}
            )

        results = []
        lock = threading.Lock()

        def unregister(strategy_id: str):
            result = registry.unregister(strategy_id)
            with lock:
                results.append(result)

        # 尝试并发注销
        threads = []
        for i in range(10):
            t = threading.Thread(target=unregister, args=(f"unreg_{i}",))
            threads.append(t)

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # 所有注销都应成功
        assert all(results), "所有注销都应成功"
        assert registry.count() == 0, "注册表应为空"

        print("✓ unregister 线程安全测试通过")


def run_tests():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("StrategyRegistry 线程安全测试")
    print("=" * 60)

    test = TestRegistryThreadSafety()
    results = []

    tests = [
        ("并发注册", test.test_concurrent_register),
        ("并发状态更新", test.test_concurrent_status_update),
        ("并发读写", test.test_concurrent_read_write),
        ("get/set_instance", test.test_get_and_set_instance_thread_safe),
        ("unregister", test.test_unregister_thread_safe),
    ]

    for name, test_func in tests:
        try:
            test_func()
            results.append((name, True))
        except Exception as e:
            print(f"❌ {name} 测试失败：{e}")
            results.append((name, False))

    # 汇总结果
    print("\n" + "=" * 60)
    print("测试结果汇总")
    print("=" * 60)

    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"{status}: {name}")

    total = len(results)
    passed = sum(1 for _, p in results if p)
    print(f"\n总计：{passed}/{total} 测试通过")

    return all(passed for _, passed in results)


if __name__ == "__main__":
    import sys
    success = run_tests()
    sys.exit(0 if success else 1)
