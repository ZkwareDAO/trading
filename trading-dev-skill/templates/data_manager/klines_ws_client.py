#!/usr/bin/env python3
"""
Binance 公共 WebSocket 客户端模块

连接 Binance fstream combined-stream，接收实时 1m K 线推送。
单体模式：数据层直连交易所，streams 固定在连接 URL 中，
运行中新增 symbol 需重建连接（由 DataManager.subscribe_klines_async 负责）。
"""

import asyncio
import json
import logging
import os
from typing import Optional, Callable, List, Dict, Any

import websockets
from websockets.exceptions import ConnectionClosed

from data_manager.klines_data import Kline

logger = logging.getLogger(__name__)


class KlinesWebSocketClient:
    """
    Binance 公共 WebSocket 客户端

    功能:
    - 连接 Binance fstream combined-stream
    - 接收实时 K 线推送
    - 自动重连（streams 在 URL 里，重连后无需重新订阅）
    """

    def __init__(
        self,
        ws_url: str = "wss://fstream.binance.com/stream",
        symbols: Optional[List[str]] = None,
        reconnect_delay: float = 5.0,
        max_reconnect: int = 5,
        max_backoff: float = 120.0,
    ):
        """
        初始化 WebSocket 客户端

        Args:
            ws_url: WebSocket 地址（combined-stream，含 streams 列表）
            symbols: 订阅的 symbol 列表（仅记录用途）
            reconnect_delay: 重连延迟（秒）
            max_reconnect: 最大重试次数（0 表示无限）
            max_backoff: 重连退避上限（秒），默认 120s
        """
        self.ws_url = ws_url
        self.symbols = symbols or []
        self.reconnect_delay = reconnect_delay
        self.max_reconnect = max_reconnect
        self.max_backoff = max_backoff

        # 连接状态
        self._connected = False
        self._ws: Any = None
        self._reconnect_count = 0
        self._running = False
        self._reconnecting = False  # 防重入标志

        # 回调
        self._on_kline_callback: Optional[Callable] = None
        self._on_disconnect_callback: Optional[Callable] = None
        self._on_reconnect_callback: Optional[Callable] = None

        # 任务
        self._receive_task: Optional[asyncio.Task] = None

        # 首帧探测：connect() 后外部 probe 等待首个数据帧，
        # 避免 probe 自己 recv() 与 _receive_loop 冲突。
        # 事件循环可能跨重连变化，懒创建以保证绑定到当前 loop。
        self._first_frame_event: Optional[asyncio.Event] = None

    def set_on_kline_callback(self, callback: Callable):
        """设置 K 线数据回调"""
        self._on_kline_callback = callback

    def set_on_reconnect_callback(self, callback: Callable):
        """设置重连成功回调"""
        self._on_reconnect_callback = callback

    def _ensure_first_frame_event(self) -> asyncio.Event:
        """懒创建首帧事件，绑定到当前运行的事件循环。"""
        if self._first_frame_event is None:
            self._first_frame_event = asyncio.Event()
        return self._first_frame_event

    def reset_first_frame_event(self) -> asyncio.Event:
        """重置（清空）首帧事件并返回，供每次 connect 后的 probe 复用。"""
        event = self._ensure_first_frame_event()
        event.clear()
        return event

    async def wait_first_frame(self, timeout: float) -> bool:
        """等待首个数据帧到达（由 _message_handler 置位）。

        替代外部直接 _ws.recv() 探测，避免与 _receive_loop 的 recv 冲突。
        """
        event = self._ensure_first_frame_event()
        try:
            await asyncio.wait_for(event.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def connect(self) -> bool:
        """连接到 Binance WebSocket"""
        try:
            connect_kwargs = dict(
                ping_interval=30,
                ping_timeout=30,
                close_timeout=10,
                open_timeout=30,
            )
            if self.ws_url.startswith("wss://"):
                # Binance 公共 WS（wss://）走 HTTP 代理（如 .env 配置了）
                proxy = (
                    os.environ.get("HTTPS_PROXY")
                    or os.environ.get("https_proxy")
                    or os.environ.get("HTTP_PROXY")
                    or os.environ.get("http_proxy")
                )
                if proxy:
                    connect_kwargs["proxy"] = proxy
                    logger.info(f"WebSocket 通过代理连接：{proxy}")
            else:
                # 非 wss（如 ws://127.0.0.1 测试地址）必须显式禁用代理。
                # websockets>=13 默认 proxy=True 会自动读环境变量 —— klines_loader
                # 的 load_dotenv() 把代理注入环境后，回环连接也会被劫持到代理，
                # 得到 InvalidMessage/超时而非预期的 ConnectionRefused。
                connect_kwargs["proxy"] = None
            self._ws = await websockets.connect(self.ws_url, **connect_kwargs)
            self._connected = True
            self._running = True
            self._reconnect_count = 0

            logger.info(f"WebSocket 连接成功：{self.ws_url}")

            # 启动接收任务
            self._receive_task = asyncio.create_task(self._receive_loop())

            return True

        except Exception as e:
            logger.error(f"WebSocket 连接失败：{e}")
            self._connected = False
            return False

    async def disconnect(self):
        """断开连接"""
        self._running = False

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass

        if self._ws:
            ws = self._ws
            self._ws = None
            await ws.close()

        self._connected = False

        logger.info("WebSocket 已断开")

    async def _receive_loop(self):
        """接收消息循环"""
        assert self._ws is not None
        logger.debug("[WS-RECV] receive_loop 启动，等待消息")
        try:
            async for message in self._ws:
                try:
                    logger.debug(f"[WS-RAW] {message[:200]}")
                    data = json.loads(message)
                    await self._message_handler(data)
                except json.JSONDecodeError as e:
                    logger.warning(f"消息解析失败：{e}")

        except ConnectionClosed:
            logger.warning("WebSocket 连接已关闭")
            await self._handle_disconnect()
        except Exception as e:
            logger.error(f"接收消息异常：{e}")
            await self._handle_disconnect()

    async def _message_handler(self, data: Dict[str, Any]):
        """消息处理器：Binance combined-stream {"stream":"...","data":{"e":"kline","k":{...}}}"""
        # 首帧到达，唤醒可能正在 probe 的协程
        if self._first_frame_event is not None and not self._first_frame_event.is_set():
            self._first_frame_event.set()

        kline = self._parse_binance_kline(data)
        if kline is not None and self._on_kline_callback:
            await self._call_callback(self._on_kline_callback, kline)

    def _parse_binance_kline(self, data: Dict[str, Any]) -> Optional[Kline]:
        """解析 Binance combined-stream kline 消息"""
        try:
            payload = data.get("data", data)
            if payload.get("e") != "kline":
                return None
            k = payload.get("k", {})
            symbol = k.get("s", "")
            interval = k.get("i", "1m")
            # Binance kline 字段：t=open_time, o/h/l/c, v, T=close_time, q, n, V, Q, x=is_closed
            raw = [
                k.get("t"),
                k.get("o"),
                k.get("h"),
                k.get("l"),
                k.get("c"),
                k.get("v"),
                k.get("T"),
                k.get("q"),
                k.get("n"),
                k.get("V"),
                k.get("Q"),
                "0",
            ]
            kline = Kline.from_binance_format(raw, symbol, interval)
            kline.is_final = bool(k.get("x", False))
            return kline
        except Exception as e:
            logger.warning(f"Binance kline 解析失败: {e}")
            return None

    async def _call_callback(self, callback: Callable, *args):
        """调用回调（支持同步和异步）"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(*args)
            else:
                callback(*args)
        except Exception as e:
            logger.error(f"回调执行失败：{e}")

    async def _handle_disconnect(self):
        """处理断线"""
        # 防重入：如果已经在重连中，直接返回
        if self._reconnecting:
            return

        self._connected = False

        if self._on_disconnect_callback:
            await self._call_callback(self._on_disconnect_callback)

        # 尝试重连
        await self._reconnect()

    async def _reconnect(self):
        """重连逻辑：无限重连（max_reconnect=0）或有限次数，退避有上限。

        Binance combined-stream 的 streams 固定在 URL 里，
        重连（复用同一 URL）后无需重新订阅。
        """
        if not self._running:
            return

        # 防重入：如果已经在重连中，直接返回
        if self._reconnecting:
            return

        self._reconnecting = True

        try:
            while self._running:
                # max_reconnect=0 表示无限重连
                is_infinite = self.max_reconnect == 0
                if not is_infinite and self._reconnect_count >= self.max_reconnect:
                    logger.error(f"达到最大重连次数 ({self.max_reconnect})，放弃重连")
                    return

                self._reconnect_count += 1
                wait_time = self.reconnect_delay * (2 ** (self._reconnect_count - 1))
                # 退避上限封顶
                wait_time = min(wait_time, self.max_backoff)

                logger.info(
                    f"准备重连 (尝试 {self._reconnect_count}/{'inf' if is_infinite else self.max_reconnect}, "
                    f"{wait_time:.1f}s 后)"
                )
                await asyncio.sleep(wait_time)

                if await self.connect():
                    # 通知重连回调
                    if self._on_reconnect_callback:
                        await self._call_callback(self._on_reconnect_callback)
                    return  # 重连成功，退出循环
                # 重连失败，继续循环尝试下一次
        finally:
            self._reconnecting = False
