"""HTTP 信号发送器 — 通过 HTTP 接口推送信号到 Kafka"""

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

import requests

from strategy_core.signal_logging.storage import Signal
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV

logger = logging.getLogger(__name__)


@dataclass
class RetryConfig:
    """重试配置"""
    max_retries: int = 3  # 最大重试次数
    base_delay: float = 1.0  # 基础延迟（秒）
    max_delay: float = 10.0  # 最大延迟（秒）


class HttpSignalSender:
    """通过 POST /api/{version}/kafka/message 发送信号"""

    def __init__(
        self,
        base_url: str,
        api_path: str = "/api/v1/kafka/message",
        timeout: float = 5.0,
        retry_config: Optional[RetryConfig] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_path = api_path
        self.timeout = timeout
        self.retry_config = retry_config or RetryConfig()

    def _extract_api_version(self) -> int:
        """
        从 api_path 提取版本号

        Returns:
            版本号（如 1, 2, 3），无版本号时默认返回 1
        """
        match = re.search(r'/v(\d+)/', self.api_path)
        return int(match.group(1)) if match else 1

    def _build_v1_payload(self, topic: str, message: str) -> str:
        """
        构建 V1 格式 payload（包装结构）

        Args:
            topic: Kafka topic
            message: JSON 消息体

        Returns:
            JSON 字符串 {"topic": ..., "message": ...}
        """
        return json.dumps({"topic": topic, "message": message}, ensure_ascii=False)

    def _build_v2_payload(self, cta_signal: CtaSignalCSV) -> str:
        """
        构建 V2+ 格式 payload（直接序列化）

        Args:
            cta_signal: CtaSignalCSV 对象

        Returns:
            JSON 字符串（直接 cta_signal.to_json()）
        """
        return json.dumps(cta_signal.to_json(), ensure_ascii=False)

    def _build_payload(self, cta_signal: CtaSignalCSV, topic: str) -> str:
        """
        根据 API 版本构建 payload

        Args:
            cta_signal: CtaSignalCSV 对象
            topic: Kafka topic

        Returns:
            JSON 字符串 payload
        """
        if self._extract_api_version() <= 1:
            message = json.dumps(cta_signal.to_json(), ensure_ascii=False)
            return self._build_v1_payload(topic, message)
        return self._build_v2_payload(cta_signal)

    def _calculate_delay(self, attempt: int) -> float:
        """计算指数退避延迟"""
        delay = self.retry_config.base_delay * (2 ** attempt)
        return min(delay, self.retry_config.max_delay)

    def _send_with_retry(
        self,
        signal_id: str,
        symbol: str,
        payload: str,
    ) -> bool:
        """
        带重试的 HTTP 发送核心逻辑

        Args:
            signal_id: 信号 ID（用于日志）
            symbol: 交易对（用于日志）
            payload: 已构建的 JSON payload

        Returns:
            是否发送成功
        """
        url = f"{self.base_url}{self.api_path}"
        max_attempts = self.retry_config.max_retries + 1

        for attempt in range(max_attempts):
            try:
                if attempt > 0:
                    delay = self._calculate_delay(attempt - 1)
                    logger.info(
                        f"HTTP 信号重试: signal_id={signal_id}, "
                        f"第 {attempt} 次重试, 延迟 {delay:.1f}s"
                    )
                    time.sleep(delay)

                logger.info(
                    f"HTTP 信号发送请求: signal_id={signal_id}, "
                    f"url={url}, symbol={symbol}"
                )

                resp = requests.post(
                    url=url,
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=self.timeout,
                )

                if 200 <= resp.status_code < 300:
                    logger.info(f"HTTP 信号发送响应: signal_id={signal_id}, status={resp.status_code}")
                    return True

                # 非 2xx 响应
                if attempt < max_attempts - 1:
                    logger.warning(
                        f"HTTP 信号发送失败，将重试: signal_id={signal_id}, "
                        f"status={resp.status_code}, body={resp.text[:200]}"
                    )
                else:
                    logger.warning(
                        f"HTTP 信号发送失败（重试耗尽）: signal_id={signal_id}, "
                        f"status={resp.status_code}, body={resp.text[:200]}"
                    )

            except Exception as e:
                if attempt < max_attempts - 1:
                    logger.warning(f"HTTP 信号发送异常，将重试: signal_id={signal_id}, 错误: {e}")
                else:
                    logger.warning(f"HTTP 信号发送异常（重试耗尽）: {signal_id}, 错误: {e}")

        return False

    def send_signal(self, signal: Signal, topic: str = "strategy_signals", **params) -> bool:
        """
        发送信号到 HTTP 端点（带重试）

        Args:
            signal: Signal 对象
            topic: Kafka topic
            **params: 附加参数（strategy_params 等）

        Returns:
            是否发送成功
        """
        cta = CtaSignalCSV.from_signal(signal, **params)
        payload = self._build_payload(cta, topic)
        return self._send_with_retry(signal.signal_id, signal.symbol, payload)

    def send_cta_signal(self, cta_signal, topic: str = "strategy_signals") -> bool:
        """
        直接发送 CtaSignalCSV 对象（带重试）

        Args:
            cta_signal: 已生成的 CtaSignalCSV 对象
            topic: Kafka topic

        Returns:
            是否发送成功
        """
        payload = self._build_payload(cta_signal, topic)
        return self._send_with_retry(cta_signal.signal_id, cta_signal.symbol, payload)
