#!/usr/bin/env python3
"""
Klines WebSocket 客户端模块

提供与 klines_service 的 WebSocket 连接，接收实时 K 线推送
"""

import asyncio
import json
import logging
from typing import Optional, Callable, List, Dict, Any

import websockets
from websockets.exceptions import ConnectionClosed

from data_manager.klines_data import Kline

logger = logging.getLogger(__name__)


class KlinesWebSocketClient:
    """
    klines_service WebSocket 客户端

    功能:
    - 连接 klines_service WebSocket
    - 订阅/取消订阅 symbol
    - 接收实时 K 线推送
    - 自动重连
    """

    def __init__(
        self,
        ws_url: str = "ws://127.0.0.1:17081/ws/klines",
        symbols: Optional[List[str]] = None,
        reconnect_delay: float = 5.0,
        max_reconnect: int = 5,
        max_backoff: float = 120.0,
    ):
        """
        初始化 WebSocket 客户端

        Args:
            ws_url: WebSocket 地址
            symbols: 初始订阅的 symbol 列表
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

    def set_on_kline_callback(self, callback: Callable):
        """设置 K 线数据回调"""
        self._on_kline_callback = callback

    def set_on_reconnect_callback(self, callback: Callable):
        """设置重连成功回调"""
        self._on_reconnect_callback = callback

    async def connect(self) -> bool:
        """连接到 WebSocket 服务"""
        try:
            self._ws = await websockets.connect(
                self.ws_url,
                ping_interval=30,
                ping_timeout=30,
                close_timeout=10,
                open_timeout=30
            )
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

    async def subscribe(self, symbols: List[str]) -> bool:
        """订阅 symbol（自动去重）"""
        if not self._connected or self._ws is None:
            logger.warning("WebSocket 未连接，无法订阅")
            raise RuntimeError("Not connected")

        try:
            message = {
                "action": "subscribe",
                "symbols": symbols
            }
            await self._ws.send(json.dumps(message))

            # 去重添加：只添加尚未订阅的 symbol
            for symbol in symbols:
                if symbol not in self.symbols:
                    self.symbols.append(symbol)

            logger.info(f"已订阅：{symbols}")
            return True

        except Exception as e:
            logger.error(f"订阅失败：{e}")
            return False

    async def unsubscribe(self, symbols: List[str]) -> bool:
        """取消订阅 symbol"""
        if not self._connected or self._ws is None:
            logger.warning("WebSocket 未连接，无法取消订阅")
            return False

        try:
            message = {
                "action": "unsubscribe",
                "symbols": symbols
            }
            await self._ws.send(json.dumps(message))

            for symbol in symbols:
                if symbol in self.symbols:
                    self.symbols.remove(symbol)

            logger.info(f"已取消订阅：{symbols}")
            return True

        except Exception as e:
            logger.error(f"取消订阅失败：{e}")
            return False

    async def _receive_loop(self):
        """接收消息循环"""
        assert self._ws is not None
        try:
            async for message in self._ws:
                try:
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
        """消息处理器"""
        msg_type = data.get('type', '')

        if msg_type == 'kline':
            kline = self._parse_kline_data(data)
            if self._on_kline_callback:
                await self._call_callback(self._on_kline_callback, kline)
        else:
            logger.debug(f"收到未知消息类型：{msg_type}")

    def _parse_kline_data(self, data: Dict[str, Any]) -> Kline:
        """解析 K 线数据"""
        kline_data = data.get('data', {})

        # 从外层或内层获取 symbol
        if 'symbol' not in kline_data:
            kline_data['symbol'] = data.get('symbol', '')

        return Kline.from_dict(kline_data)

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
        """重连逻辑：无限重连（max_reconnect=0）或有限次数，退避有上限"""
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
                    # 重连成功后重新订阅
                    if self.symbols:
                        await self.subscribe(self.symbols)
                    # 通知重连回调
                    if self._on_reconnect_callback:
                        await self._call_callback(self._on_reconnect_callback)
                    return  # 重连成功，退出循环
                # 重连失败，继续循环尝试下一次
        finally:
            self._reconnecting = False
