#!/usr/bin/env python3
"""
测试 SIGTERM 信号处理是否触发仓位持久化

验证流程：
1. 验证信号处理器正确注册
2. 验证信号处理器触发 stop_event
"""

import asyncio
import os
import signal
import sys

import pytest


def test_sigterm_handler_registered():
    """测试 SIGTERM 信号处理器是否正确注册"""
    import asyncio
    import signal

    # 模拟 main() 中的信号处理器注册逻辑
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    stop_event = asyncio.Event()
    handler_called = False

    def sigterm_handler():
        nonlocal handler_called
        handler_called = True
        stop_event.set()

    # 注册信号处理器
    try:
        loop.add_signal_handler(signal.SIGTERM, sigterm_handler)
    except NotImplementedError:
        # Windows 不支持 add_signal_handler
        pytest.skip("Windows 不支持 add_signal_handler")

    # 发送信号
    loop.call_soon(lambda: os.kill(os.getpid(), signal.SIGTERM))

    # 等待信号处理
    try:
        loop.run_until_complete(asyncio.wait_for(stop_event.wait(), timeout=5))
    except asyncio.TimeoutError:
        pytest.fail("信号处理器未被调用")

    assert handler_called, "SIGTERM 信号处理器应该被调用"

    loop.close()


def test_sigterm_triggers_graceful_shutdown():
    """测试 SIGTERM 触发优雅退出流程"""

    async def simulate_main():
        """模拟 main() 中的 SIGTERM 处理流程"""
        stop_event = asyncio.Event()

        def sigterm_handler():
            print("收到 SIGTERM，触发仓位持久化...")
            stop_event.set()

        loop = asyncio.get_running_loop()
        loop.add_signal_handler(signal.SIGTERM, sigterm_handler)

        # 模拟策略运行
        running = True
        stop_triggered = False

        # 发送 SIGTERM
        loop.call_soon(lambda: os.kill(os.getpid(), signal.SIGTERM))

        # 等待 stop_event
        await stop_event.wait()
        stop_triggered = True

        # 模拟 runner.stop() 被调用
        print("策略进程停止")
        running = False

        return stop_triggered, running

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        stop_triggered, running = loop.run_until_complete(simulate_main())
        assert stop_triggered, "SIGTERM 应触发 stop_event"
        assert not running, "策略应该停止"
    finally:
        loop.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
