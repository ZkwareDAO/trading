#!/usr/bin/env python3
"""关停时必须回收 Binance REST 轮询任务（Prove-It 复现测试）

**缺陷**：`_binance_poll_task` 由 `_start_binance_rest_poll()` 用
`asyncio.create_task()` 创建，但它是独立字段，**从不加入 `_background_tasks`**。
而进程关停走 `run_strategy.py` 的 `await data_manager.close()`，
`close()` 只取消 `_background_tasks` —— 于是 Binance 回退模式下，
策略进程关停后 REST 轮询协程仍在后台运行。

唯一取消它的是 `stop_realtime()`，但该方法全仓零引用（曾被死代码扫描
报为「unused method」，实为接线未接上）。
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from data_manager.manager import DataManager, DataManagerConfig


def _make_dm() -> DataManager:
    tmp = Path(tempfile.mkdtemp())
    (tmp / "1m").mkdir(parents=True, exist_ok=True)
    return DataManager(DataManagerConfig(csv_dir=str(tmp)))


async def _never_ending():
    while True:
        await asyncio.sleep(0.01)


class TestBinancePollTaskCleanup:
    """轮询任务的生命周期回收"""

    @pytest.mark.asyncio
    async def test_close_cancels_binance_poll_task(self):
        """close() 必须取消 Binance 轮询任务，否则进程关停后协程泄漏"""
        dm = _make_dm()
        dm._binance_poll_task = asyncio.create_task(_never_ending())
        await asyncio.sleep(0)  # 让任务真正启动

        await dm.close()

        assert dm._binance_poll_task is None or dm._binance_poll_task.done(), (
            "close() 后 Binance 轮询任务仍在运行 —— 协程泄漏。"
            "_binance_poll_task 不在 _background_tasks 中，close() 收不到它，"
            "而唯一取消它的 stop_realtime() 零引用。"
        )

    @pytest.mark.asyncio
    async def test_close_is_idempotent_without_poll_task(self):
        """未启动轮询时 close() 不应报错（Binance 回退模式未激活的常态）"""
        dm = _make_dm()
        assert dm._binance_poll_task is None

        await dm.close()  # 不应抛异常

        assert dm._binance_poll_task is None

    @pytest.mark.asyncio
    async def test_close_tolerates_already_finished_poll_task(self):
        """轮询任务已自行结束时，close() 不应因重复取消而报错"""
        dm = _make_dm()

        async def _quick():
            return None

        dm._binance_poll_task = asyncio.create_task(_quick())
        await dm._binance_poll_task  # 先让它跑完

        await dm.close()  # 不应抛异常

    @pytest.mark.asyncio
    async def test_close_completes_when_poll_task_raises(self):
        """轮询任务抛非取消异常时，close() 仍须走完（关停不能被拖死）"""
        dm = _make_dm()

        async def _boom():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                raise RuntimeError("清理时炸了")

        dm._binance_poll_task = asyncio.create_task(_boom())
        await asyncio.sleep(0)

        await dm.close()  # 不应把 RuntimeError 抛给调用方

        assert dm._binance_poll_task is None
        assert dm._connected is False

    @pytest.mark.asyncio
    async def test_stop_realtime_also_cancels_poll_task(self):
        """stop_realtime() 的既有行为不能被破坏（它是另一条清理路径）"""
        dm = _make_dm()
        dm._binance_poll_task = asyncio.create_task(_never_ending())
        await asyncio.sleep(0)

        await dm.stop_realtime()

        assert dm._binance_poll_task is None
