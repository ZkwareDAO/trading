"""
Kafka Signal Producer - Kafka 信号推送模块

将策略生成的信号推送到 Kafka Topic，供下游系统实时消费。
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Set

from .storage import Signal
from .csv_adapter import CtaSignalCSV

logger = logging.getLogger(__name__)

try:
    from kafka import KafkaProducer
except ImportError:
    KafkaProducer = None
    logger.warning(
        "kafka-python 未安装，Kafka 推送功能不可用。"
        "运行 pip install kafka-python-ng 安装。"
    )

DEFAULT_DEDUP_FILE = "./data/signals/.kafka_sent_ids"
# 去重文件 TTL：保留最近 N 小时的记录
DEFAULT_DEDUP_TTL_HOURS = 24


class _SignalJSONEncoder(json.JSONEncoder):
    """处理 bytes、dataclass 等非标准类型的 JSON 编码器"""
    def default(self, obj):
        if isinstance(obj, bytes):
            return obj.decode("utf-8", errors="replace")
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        if isinstance(obj, datetime):
            return obj.strftime("%Y-%m-%d %H:%M:%S")
        return super().default(obj)


class KafkaSignalProducer:
    """
    Kafka 信号推送器

    将 Signal 转换为 Kafka 格式 JSON 并推送到指定 Topic。
    支持 SASL/SSL 认证、压缩、重试、去重等配置。
    """

    def __init__(self, config: Dict[str, Any]):
        """
        初始化 Kafka Producer

        Args:
            config: Kafka 配置字典，包含：
                - enabled: 是否启用 (bool)
                - bootstrap_servers: Kafka 地址 (str)
                - topic: Topic 名称 (str)
                - sasl_mechanism: SASL 机制 (可选)
                - sasl_username: SASL 用户名 (可选)
                - sasl_password: SASL 密码 (可选)
                - compression: 压缩方式 (可选)
                - acks: 确认级别 (可选)
                - max_retries: 最大重试次数 (可选)
                - retry_backoff_ms: 重试间隔 (可选)
                - dedup_file: 去重持久化文件路径 (可选)
                - dedup_max_size: 去重缓存上限 (可选，默认 10000)
        """
        self.enabled = config.get("enabled", False)
        self.topic = config.get("topic", "cta_signals")
        self._kafka_producer = None
        self._sent_ids: Set[str] = set()
        self._dedup_file = config.get("dedup_file", DEFAULT_DEDUP_FILE)
        self._sent_ids_max = config.get("dedup_max_size", 10000)
        self._init_config = config  # 保存配置用于重连

        # 重试配置
        self._max_retries = config.get("max_retries", 3)
        self._retry_backoff_ms = config.get("retry_backoff_ms", 1000)

        # 熔断器配置
        self.circuit_breaker_threshold = config.get("circuit_breaker_threshold", 5)
        self.circuit_reset_timeout = config.get("circuit_reset_timeout", 30.0)
        self._circuit_state = "CLOSED"  # CLOSED / OPEN / HALF_OPEN
        self._consecutive_failures = 0
        self._circuit_open_time: float | None = None

        if not self.enabled or KafkaProducer is None:
            logger.info("Kafka 推送未启用或 kafka-python 未安装")
            return

        # 加载已有去重记录
        self._load_dedup_file()

        try:
            kwargs = self._build_producer_kwargs(config)
            self._kafka_producer = KafkaProducer(**kwargs)
            logger.info(
                f"Kafka Producer 初始化完成，topic={self.topic}, "
                f"servers={config.get('bootstrap_servers')}, "
                f"去重记录={len(self._sent_ids)} 条"
            )
        except Exception as e:
            logger.warning(f"Kafka Producer 初始化失败: {e}")
            self._kafka_producer = None

    def _is_retryable_error(self, error: Exception) -> bool:
        """判断错误是否可以通过重试恢复"""
        error_msg = str(error).lower()
        return any(kw in error_msg for kw in [
            "connection", "timeout", "timed out", "reset",
            "broker", "disconnected", "not ready",
            "leader not available", "not leader for partition",
            "seconds have passed",
        ])

    def _do_send(self, signal: Signal, **strategy_params) -> bool:
        """执行单次发送（不含去重和重试逻辑）"""
        if not self.is_available():
            return False

        cta_signal = CtaSignalCSV.from_signal(signal, **strategy_params)
        message = cta_signal.to_json()
        value = json.dumps(message, ensure_ascii=False, cls=_SignalJSONEncoder).encode("utf-8")

        self._kafka_producer.send(self.topic, value=value)
        self._kafka_producer.flush()

        self._record_sent(signal.signal_id)
        logger.debug(f"Kafka 信号已发送: {signal.signal_id}")
        return True

    def send_signal(self, signal: Signal, **strategy_params) -> bool:
        """
        发送单个信号到 Kafka

        带熔断器 + 指数退避重试：
        1. 熔断器 OPEN 且在超时内 → 立即返回 False（不阻塞）
        2. 熔断器 OPEN 且已超时 → HALF_OPEN，尝试一次
        3. 网络类错误重试 max_retries 次，每次退避时间翻倍
        4. 非网络类错误立即返回

        Args:
            signal: Signal 对象
            **strategy_params: 策略配置参数（传给 CtaSignalCSV.from_signal）

        Returns:
            是否发送成功（重复信号返回 False）
        """
        if not self.is_available():
            return False

        if self.has_sent(signal.signal_id):
            logger.debug(f"Kafka 信号已推送过，跳过: {signal.signal_id}")
            return False

        # === 熔断器检查 ===
        if self._circuit_state == "OPEN":
            if self._circuit_open_time is not None:
                elapsed = time.time() - self._circuit_open_time
                if elapsed < self.circuit_reset_timeout:
                    # 仍在熔断期内，跳过发送
                    logger.debug(
                        f"Kafka 熔断中（{elapsed:.0f}s/{self.circuit_reset_timeout}s），"
                        f"跳过: {signal.signal_id}"
                    )
                    return False
                # 超时，进入 HALF_OPEN 尝试恢复
                self._circuit_state = "HALF_OPEN"
                logger.info("Kafka 熔断超时，进入 HALF_OPEN 尝试恢复")
            else:
                return False

        # HALF_OPEN 状态下只尝试一次
        max_attempts = 1 if self._circuit_state == "HALF_OPEN" else (1 + self._max_retries)
        backoff_ms = self._retry_backoff_ms

        for attempt in range(max_attempts):
            try:
                result = self._do_send(signal, **strategy_params)
                if result:
                    # 发送成功：重置熔断器
                    self._circuit_state = "CLOSED"
                    self._consecutive_failures = 0
                return result

            except Exception as e:
                self._consecutive_failures += 1

                if not self._is_retryable_error(e):
                    logger.warning(f"Kafka 推送失败（不可重试）: {signal.signal_id}, 错误: {e}")
                    self._trip_circuit()
                    return False

                if attempt < max_attempts - 1:
                    logger.warning(
                        f"Kafka 推送失败，{self._retry_backoff_ms}ms 后重试 "
                        f"({attempt + 1}/{max_attempts - 1}): {signal.signal_id}, 错误: {e}"
                    )
                    time.sleep(backoff_ms / 1000.0)
                    backoff_ms *= 2

                    # 连接类错误尝试重连
                    self._kafka_producer = None
                    if not self._reconnect():
                        logger.warning("重连失败，继续重试")
                    continue

                # 耗尽重试次数
                logger.warning(
                    f"Kafka 推送失败（已重试 {max_attempts - 1} 次）: "
                    f"{signal.signal_id}, 错误: {e}"
                )
                self._trip_circuit()
                return False

    def has_sent(self, signal_id: str) -> bool:
        """检查某个 signal_id 是否已经推送过"""
        return signal_id in self._sent_ids

    def is_available(self) -> bool:
        """检查 Kafka 连接是否可用"""
        return self.enabled and self._kafka_producer is not None

    def send_cta_signal(self, cta_signal) -> bool:
        """
        直接发送 CtaSignalCSV 对象

        Args:
            cta_signal: 已生成的 CtaSignalCSV 对象

        Returns:
            是否发送成功
        """
        if not self.is_available():
            return False

        if self.has_sent(cta_signal.signal_id):
            logger.debug(f"Kafka 信号已推送过，跳过: {cta_signal.signal_id}")
            return False

        try:
            message = cta_signal.to_json()
            value = json.dumps(message, ensure_ascii=False, cls=_SignalJSONEncoder).encode("utf-8")

            self._kafka_producer.send(self.topic, value=value)
            self._kafka_producer.flush()

            self._record_sent(cta_signal.signal_id)
            logger.debug(f"Kafka 信号已发送: {cta_signal.signal_id}")
            return True

        except Exception as e:
            logger.warning(f"Kafka 推送失败: {cta_signal.signal_id}, 错误: {e}")
            return False

    def send_batch(self, signals: List[Signal], **strategy_params) -> int:
        """
        批量发送信号到 Kafka

        Args:
            signals: Signal 对象列表
            **strategy_params: 策略配置参数

        Returns:
            成功发送的信号数量
        """
        count = 0
        for signal in signals:
            if self.send_signal(signal, **strategy_params):
                count += 1
        return count

    def close(self):
        """关闭 Kafka Producer 连接"""
        if self._kafka_producer is not None:
            try:
                self._kafka_producer.flush()
                self._kafka_producer.close()
                logger.info("Kafka Producer 已关闭")
            except Exception as e:
                logger.warning(f"关闭 Kafka Producer 时出错: {e}")

    def _reconnect(self) -> bool:
        """
        重建 Kafka 连接

        Returns:
            是否重连成功
        """
        if not self.enabled or KafkaProducer is None:
            return False

        try:
            kwargs = self._build_producer_kwargs(self._init_config)
            self._kafka_producer = KafkaProducer(**kwargs)
            logger.info("Kafka Producer 重连成功")
            return True
        except Exception as e:
            logger.warning(f"Kafka Producer 重连失败: {e}")
            self._kafka_producer = None
            return False

    def _trip_circuit(self):
        """触发熔断：当连续失败达到阈值时进入 OPEN 状态"""
        self._kafka_producer = None
        if self._circuit_state == "HALF_OPEN":
            # HALF_OPEN 失败：立即回到 OPEN
            self._circuit_state = "OPEN"
            self._circuit_open_time = time.time()
            logger.warning("Kafka HALF_OPEN 恢复失败，重新进入熔断")
        elif self._consecutive_failures >= self.circuit_breaker_threshold:
            self._circuit_state = "OPEN"
            self._circuit_open_time = time.time()
            logger.warning(
                f"Kafka 熔断触发（连续 {self._consecutive_failures} 次失败），"
                f"{self.circuit_reset_timeout}s 后尝试恢复"
            )

    def _build_producer_kwargs(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        构建 Kafka Producer 配置参数

        Args:
            config: 原始配置字典

        Returns:
            kafka.KafkaProducer 构造函数参数
        """
        kwargs = {
            "bootstrap_servers": config.get("bootstrap_servers", "127.0.0.1:9092"),
            "acks": config.get("acks", "all"),
            "retries": config.get("max_retries", 3),
            "retry_backoff_ms": config.get("retry_backoff_ms", 1000),
            # 固定 API 版本，跳过 metadata 刷新（避免 broker advertised.listeners
            # 返回 localhost 等不可达地址导致连接超时）
            "api_version": (2, 5, 0),
        }

        # SASL 认证
        if config.get("sasl_mechanism"):
            kwargs["security_protocol"] = "SASL_PLAINTEXT"
            kwargs["sasl_mechanism"] = config["sasl_mechanism"]
            kwargs["sasl_plain_username"] = config.get("sasl_username", "")
            kwargs["sasl_plain_password"] = config.get("sasl_password", "")

        # SSL
        if config.get("ssl_cafile"):
            kwargs["security_protocol"] = "SSL"
            kwargs["ssl_cafile"] = config["ssl_cafile"]

        # 压缩
        compression = config.get("compression")
        if compression:
            kwargs["compression_type"] = compression

        return kwargs

    def _record_sent(self, signal_id: str):
        """记录已发送的 signal_id 到内存和持久化文件（带时间戳）"""
        # 内存去重
        self._sent_ids.add(signal_id)

        # 上限控制：超过则丢弃最旧的一半
        if len(self._sent_ids) > self._sent_ids_max:
            keep = list(self._sent_ids)[self._sent_ids_max // 2:]
            self._sent_ids = set(keep)
            self._rebuild_dedup_file()

        # 追加到持久化文件（格式：YYYYMMDDHHMMSS|signal_id）
        try:
            os.makedirs(os.path.dirname(self._dedup_file) or ".", exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            with open(self._dedup_file, "a") as f:
                f.write(f"{ts}|{signal_id}\n")
        except Exception as e:
            logger.warning(f"写入去重文件失败: {e}")

    def _load_dedup_file(self):
        """从去重文件加载已发送的 signal_id（自动清理过期条目）"""
        if not os.path.exists(self._dedup_file):
            return

        cutoff = datetime.now() - timedelta(hours=DEFAULT_DEDUP_TTL_HOURS)
        loaded_count = 0
        expired_count = 0

        try:
            with open(self._dedup_file, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    # 新格式：YYYYMMDDHHMMSS|signal_id
                    if "|" in line:
                        ts_str, sid = line.split("|", 1)
                        try:
                            entry_time = datetime.strptime(ts_str, "%Y%m%d%H%M%S")
                            if entry_time < cutoff:
                                expired_count += 1
                                continue
                            self._sent_ids.add(sid)
                            loaded_count += 1
                        except ValueError:
                            # 时间戳格式错误，跳过
                            expired_count += 1
                            continue
                    else:
                        # 旧格式（无时间戳）：视为过期
                        expired_count += 1
                        continue

            if expired_count:
                logger.info(
                    f"从去重文件加载 {loaded_count} 条记录（清理 {expired_count} 条过期）: "
                    f"{self._dedup_file}"
                )
            elif loaded_count:
                logger.info(f"从去重文件加载 {loaded_count} 条记录: {self._dedup_file}")
        except Exception as e:
            logger.warning(f"读取去重文件失败: {e}")

    def _rebuild_dedup_file(self):
        """重建去重文件，只保留当前内存中的记录"""
        try:
            os.makedirs(os.path.dirname(self._dedup_file) or ".", exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d%H%M%S")
            with open(self._dedup_file, "w") as f:
                for sid in self._sent_ids:
                    f.write(f"{ts}|{sid}\n")
        except Exception as e:
            logger.warning(f"重建去重文件失败: {e}")
