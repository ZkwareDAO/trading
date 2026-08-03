"""
Signal CSV Adapter - 信号 CSV 格式转换器

将策略信号转换为 CSV 格式，支持后续转换为 JSON 格式发送到 Kafka。

JSON 结构 (对齐设计文档):
{
    SignalID: "uuid",
    SignalTimestamp: "",
    symbol: "BTC",
    pos_type: 2,
    strategy_type: "CTAFuture",
    risk_strategy_type: "cta_intraday",
    strategy: { name, version, internal, params, valid_before, cash, parts },
    user_id: 1,
    signal: { side, action, exchange, valid_before, quantity/cash, trigger_price, slippage, order_type }
}
"""

import csv
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
from pathlib import Path
from dataclasses import dataclass, field
import uuid

from .storage import Signal
from ..constants import (
    DEFAULT_STOP_LOSS_PCT,
    DEFAULT_TRAILING_PROFIT_ACTIVATION,
    DEFAULT_TRAILING_PROFIT_DRAWDOWN,
)

logger = logging.getLogger(__name__)


# direction -> side 映射 (1=buy, 2=sell)
SIDE_MAP = {
    "long": 1,      # buy
    "short": 2,     # sell
    None: 1,
}


@dataclass
class CtaSignalCSV:
    """
    CTA 策略信号

    字段对应 JSON 结构的 strategy 和 signal 两部分
    """

    # ========== SignalID (不传到 Kafka，用于内部追踪) ==========
    signal_id: str = field(default_factory=lambda: f"sig_{uuid.uuid4().hex[:12]}")

    # ========== 基础字段 ==========
    signal_timestamp: int = 0       # 毫秒时间戳
    symbol: str = ""                # 交易对 (如 IF2406, BTCUSDT)
    pos_type: int = 2               # 1=现货，2=合约

    # ========== strategy 配置字段 (从 config.yaml 读取) ==========
    strategy_type: str = "CTAFutureFactory"   # 策略类型
    strategy_type_name: str = ""          # 策略类型名称（Kafka strategy.name）
    risk_strategy_type: str = "cta_intraday"  # 风控策略类型
    user_id: int = 1                     # 用户 ID
    strategy_name: str = ""         # 策略名称 (如 RBreakerv1_1m_IF2406)
    strategy_version: str = "v1"    # 策略版本 (v1, v2, v3)
    strategy_internal: str = ""     # K 线周期 (1h, 4h 等)
    strategy_params: str = "{}"     # 策略参数 (JSON 字符串)
    strategy_valid_before: str = "" # 策略有效时间
    strategy_cash: float = 0        # 策略最大拥有金额
    strategy_parts: int = 0         # 策略订单最大数量

    # ========== signal 信号字段 (生成的信号信息) ==========
    signal_side: int = 1            # 1=buy, 2=sell
    signal_action: str = ""         # buy, sell, buy_close, sell_close, reverse_long, reverse_short
    signal_exchange: str = "binance"
    signal_valid_before: str = ""   # 订单有效时间
    signal_trigger_price: float = 0 # 触发价格
    signal_slippage: float = 0      # 滑点
    signal_order_type: int = 1      # 1=限价单，2=市价单
    signal_quantity: float = 0      # 数量 (与 cash 二选一)
    signal_cash: float = 0          # 金额 (与 quantity 二选一)

    # ========== 杠杆配置字段 ==========
    leverage: int = 5  # 杠杆倍数，默认 5 倍

    # ========== 风控配置字段 ==========
    risk_stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT             # 止损阈值
    risk_trailing_profit_activation: float = DEFAULT_TRAILING_PROFIT_ACTIVATION    # 止盈回撤激活阈值
    risk_trailing_profit_drawdown: float = DEFAULT_TRAILING_PROFIT_DRAWDOWN     # 止盈回撤百分比

    # ========== 辅助字段 ==========
    strength: float = 0.0           # 信号强度
    metadata: str = "{}"            # 附加元数据
    trading_mode: str = "live"      # 运行模式 (live / paper_trading / smoking)

    def _build_params_with_risk(self) -> dict:
        """解析 strategy_params 并注入风控字段（百分比→小数，如 20→0.2）"""
        params = {}
        try:
            params = json.loads(self.strategy_params)
        except (json.JSONDecodeError, TypeError, ValueError):
            pass
        params["StopLossThreshold"] = -abs(self.risk_stop_loss_pct / 100)
        params["TakeProfitBackThreshold"] = self.risk_trailing_profit_activation / 100
        params["TakeProfitBackDynamicFallPercent"] = self.risk_trailing_profit_drawdown / 100
        return params

    def to_csv_row(self) -> dict:
        """转换为 CSV 行字典"""
        params = self._build_params_with_risk()

        return {
            # 基础字段
            "signal_id": self.signal_id,
            "signal_timestamp": self.signal_timestamp,
            "symbol": self.symbol,
            "pos_type": self.pos_type,

            # strategy 配置
            "strategy_type": self.strategy_type,
            "risk_strategy_type": self.risk_strategy_type,
            "user_id": self.user_id,
            "strategy_name": self.strategy_name,
            "strategy_version": self.strategy_version,
            "strategy_internal": self.strategy_internal,
            "strategy_params": json.dumps(params),  # 注入风控字段
            "strategy_valid_before": self.strategy_valid_before,
            "strategy_cash": self.strategy_cash,
            "strategy_parts": self.strategy_parts,
            "leverage": self.leverage,

            # signal 信号
            "signal_side": self.signal_side,
            "signal_action": self.signal_action,
            "signal_exchange": self.signal_exchange,
            "signal_valid_before": self.signal_valid_before,
            "signal_trigger_price": self.signal_trigger_price,
            "signal_slippage": self.signal_slippage,
            "signal_order_type": self.signal_order_type,
            "signal_quantity": self.signal_quantity,
            "signal_cash": self.signal_cash,

            # 辅助字段
            "strength": self.strength,
            "metadata": self.metadata,
            "trading_mode": self.trading_mode,
        }

    def to_json(self, user_id: Optional[int] = None) -> dict:
        """
        转换为 JSON 格式 (发送到 Kafka)

        Args:
            user_id: 用户 ID (默认使用 self.user_id)

        Returns:
            JSON 字典
        """
        # 默认使用存储的 user_id
        if user_id is None:
            user_id = self.user_id

        # 注入风控字段
        params = self._build_params_with_risk()

        # 构建 JSON 结构
        return {
            "SignalID": self.signal_id,
            "SignalTimestamp": self._ms_to_datetime(self.signal_timestamp),
            "symbol": self.symbol,
            "pos_type": self.pos_type,
            "strategy_type": self.strategy_type,
            "risk_strategy_type": self.risk_strategy_type,
            "strategy": {
                "name": self.strategy_type_name if self.strategy_type_name else self.strategy_name.split("_")[0],
                "version": self.strategy_version,
                "internal": self.strategy_internal,
                "description": f"{self.strategy_name} strategy",
                "params": params,
                "valid_before": self.strategy_valid_before,
                "cash": self.strategy_cash,
                "parts": self.strategy_parts,
                "leverage": self.leverage,
                "trading_mode": self.trading_mode,
            },
            "user_id": user_id,
            "signal": {
                "side": self.signal_side,
                "action": self.signal_action,
                "exchange": self.signal_exchange,
                "valid_before": self.signal_valid_before,
                "quantity": self.signal_quantity if self.signal_quantity > 0 else None,
                "cash": self.signal_cash if self.signal_cash > 0 else None,
                "trigger_price": self.signal_trigger_price,
                "slippage": self.signal_slippage,
                "order_type": self.signal_order_type,
            }
        }

    def _ms_to_datetime(self, ms: int) -> str:
        """毫秒时间戳转 datetime 字符串"""
        if ms <= 0:
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")

    @classmethod
    def from_signal(
        cls,
        signal: Signal,
        strategy_name: str = "",
        strategy_version: str = "v1",
        interval: str = "",  # 别名, 内部存储为 strategy_internal
        strategy_params: Optional[Dict[str, Any]] = None,
        strategy_valid_before: str = "2030-12-31 08:00:00",
        strategy_cash: float = 100,
        strategy_parts: int = 1,
        strategy_type: str = "CTAFutureFactory",
        strategy_type_name: str = "",  # 策略类型名称（Kafka strategy.name）
        risk_strategy_type: str = "cta_intraday",
        user_id: int = 1,
        signal_exchange: str = "binance",
        signal_order_type: int = 1,
        signal_slippage: float = 0,
        signal_valid_before: str = "",
        signal_valid_before_hours: int = 24,
        signal_cash: float = 0,
        signal_quantity: float = 0,
        pos_type: int = 2,
        # 杠杆参数
        leverage: int = 5,
        # 风控参数
        risk_stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
        risk_trailing_profit_activation: float = DEFAULT_TRAILING_PROFIT_ACTIVATION,
        risk_trailing_profit_drawdown: float = DEFAULT_TRAILING_PROFIT_DRAWDOWN,
        # 运行模式
        trading_mode: str = "live",
        **_ignored,
    ) -> 'CtaSignalCSV':
        """从 Signal 对象转换。多余 kwargs 会被忽略。"""
        # 转换时间戳为毫秒
        if isinstance(signal.timestamp, datetime):
            timestamp_ms = int(signal.timestamp.timestamp() * 1000)
        else:
            timestamp_ms = int(datetime.now().timestamp() * 1000)

        # 计算信号 valid_before (默认使用 signal_valid_before_hours)
        if not signal_valid_before:
            signal_valid_before = (
                datetime.now() + timedelta(hours=signal_valid_before_hours)
            ).strftime("%Y-%m-%d %H:%M:%S")

        # 计算每单金额（如果未显式指定）
        if signal_cash <= 0 and strategy_cash > 0 and strategy_parts > 0:
            signal_cash = strategy_cash / strategy_parts

        # 映射 side (1=buy, 2=sell)
        signal_side = SIDE_MAP.get(signal.direction, 1)

        # 信号 action (直接从 signal_type 获取)
        signal_action = signal.signal_type.value

        # 策略参数转为 JSON
        strategy_params_str = json.dumps(strategy_params or {})

        # 元数据（清理不可 JSON 序列化的值，如 dataclass、bytes 等）
        metadata_dict = {}
        metadata_dict["type"] = signal.signal_type.value
        for k, v in signal.metadata.items():
            if isinstance(v, bytes):
                metadata_dict[k] = v.decode("utf-8", errors="replace")
            elif hasattr(v, "to_dict"):
                # dataclass 对象（如 PriceLines）
                metadata_dict[k] = v.to_dict()
            elif isinstance(v, datetime):
                metadata_dict[k] = v.strftime("%Y-%m-%d %H:%M:%S")
            else:
                metadata_dict[k] = v

        return cls(
            signal_id=signal.signal_id,
            signal_timestamp=timestamp_ms,
            symbol=signal.symbol,
            pos_type=pos_type,
            strategy_type=strategy_type,
            strategy_type_name=strategy_type_name,
            risk_strategy_type=risk_strategy_type,
            user_id=user_id,
            strategy_name=strategy_name or signal.strategy_id,
            strategy_version=strategy_version,
            strategy_internal=interval,
            strategy_params=strategy_params_str,
            strategy_valid_before=strategy_valid_before,
            strategy_cash=strategy_cash,
            strategy_parts=strategy_parts,
            leverage=leverage,
            signal_side=signal_side,
            signal_action=signal_action,
            signal_exchange=signal_exchange,
            signal_order_type=signal_order_type,
            signal_slippage=signal_slippage,
            signal_valid_before=signal_valid_before,
            signal_trigger_price=signal.price,
            signal_cash=signal_cash,
            signal_quantity=signal_quantity,
            strength=signal.strength,
            metadata=json.dumps(metadata_dict, ensure_ascii=False),
            risk_stop_loss_pct=risk_stop_loss_pct,
            risk_trailing_profit_activation=risk_trailing_profit_activation,
            risk_trailing_profit_drawdown=risk_trailing_profit_drawdown,
            trading_mode=trading_mode,
        )


class SignalCsvWriter:
    """
    信号 CSV 写入器

    将策略信号写入 CSV 文件
    文件组织：./data/signals/{strategy_name}/{date}.csv
    """

    # CSV 文件列名 - 对应 JSON 结构
    FIELDNAMES = [
        # 基础字段
        "signal_id", "signal_timestamp", "symbol", "pos_type",

        # strategy 配置
        "strategy_type", "risk_strategy_type", "user_id",
        "strategy_name", "strategy_version", "strategy_internal",
        "strategy_params", "strategy_valid_before", "strategy_cash", "strategy_parts",
        "leverage",

        # signal 信号
        "signal_side", "signal_action", "signal_exchange", "signal_valid_before",
        "signal_trigger_price", "signal_slippage", "signal_order_type",
        "signal_quantity", "signal_cash",

        # 辅助字段
        "strength", "metadata", "trading_mode",
    ]

    def __init__(self, base_dir: str = "./data/signals"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"信号 CSV 存储目录初始化完成：{self.base_dir}")

    def _get_file_path(self, strategy_name: str, date: datetime) -> Path:
        # 使用 UTC 日期作为文件名，确保与 K 线时间一致
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        date_str = date.astimezone(timezone.utc).strftime("%Y%m%d")
        strategy_dir = self.base_dir / strategy_name
        strategy_dir.mkdir(parents=True, exist_ok=True)
        return strategy_dir / f"{date_str}.csv"

    def _init_csv_file(self, file_path: Path):
        if not file_path.exists():
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writeheader()
            logger.debug(f"创建信号 CSV 文件：{file_path}")

    def write_signal(
        self,
        signal: Signal,
        strategy_name: str,
        strategy_version: str,
        interval: str,
        strategy_params: Optional[Dict[str, Any]] = None,
        strategy_cash: float = 100,
        strategy_parts: int = 1,
        leverage: int = 5,
        strategy_valid_before: str = "2030-12-31 08:00:00",
        strategy_type: str = "CTAFutureFactory",
        strategy_type_name: str = "",
        risk_strategy_type: str = "cta_intraday",
        user_id: int = 1,
        signal_exchange: str = "binance",
        signal_order_type: int = 1,
        signal_slippage: float = 0,
        pos_type: int = 2,
        risk_stop_loss_pct: float = DEFAULT_STOP_LOSS_PCT,
        risk_trailing_profit_activation: float = DEFAULT_TRAILING_PROFIT_ACTIVATION,
        risk_trailing_profit_drawdown: float = DEFAULT_TRAILING_PROFIT_DRAWDOWN,
        trading_mode: str = "live",
    ) -> bool:
        """
        写入 CTA 策略信号到 CSV

        Args:
            signal: Signal 对象
            strategy_name: 策略名称
            strategy_version: 策略版本 (v1, v2, v3)
            interval: K 线周期
            strategy_params: 策略参数字典
            strategy_cash: 策略最大金额
            strategy_parts: 策略最大订单数
            leverage: 杠杆倍数
            strategy_valid_before: 策略有效时间
            strategy_type: 策略类型
            risk_strategy_type: 风控策略类型
            user_id: 用户 ID
            signal_exchange: 交易所
            signal_order_type: 订单类型 (1=限价，2=市价)
            signal_slippage: 滑点
            pos_type: 仓位类型 (1=现货，2=合约)
            risk_stop_loss_pct: 止损阈值
            risk_trailing_profit_activation: 止盈回撤激活阈值
            risk_trailing_profit_drawdown: 止盈回撤百分比
            trading_mode: 运行模式 (live / paper_trading / smoking)
        """
        try:
            cta_signal = CtaSignalCSV.from_signal(
                signal=signal,
                strategy_name=strategy_name,
                strategy_version=strategy_version,
                interval=interval,
                strategy_params=strategy_params,
                strategy_valid_before=strategy_valid_before,
                strategy_cash=strategy_cash,
                strategy_parts=strategy_parts,
                leverage=leverage,
                strategy_type=strategy_type,
                strategy_type_name=strategy_type_name,
                risk_strategy_type=risk_strategy_type,
                user_id=user_id,
                signal_exchange=signal_exchange,
                signal_order_type=signal_order_type,
                signal_slippage=signal_slippage,
                pos_type=pos_type,
                risk_stop_loss_pct=risk_stop_loss_pct,
                risk_trailing_profit_activation=risk_trailing_profit_activation,
                risk_trailing_profit_drawdown=risk_trailing_profit_drawdown,
                trading_mode=trading_mode,
            )

            file_path = self._get_file_path(strategy_name, signal.timestamp)
            self._init_csv_file(file_path)

            with open(file_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writerow(cta_signal.to_csv_row())

            logger.debug(f"信号已保存：{cta_signal.signal_id} -> {file_path}")
            return True

        except Exception as e:
            logger.error(f"保存信号失败：{e}")
            return False

    def write_cta_signal(self, cta_signal: CtaSignalCSV) -> bool:
        """
        直接写入 CtaSignalCSV 对象

        Args:
            cta_signal: 已生成的 CtaSignalCSV 对象

        Returns:
            是否写入成功
        """
        try:
            # 从 signal_timestamp 毫秒转换为 datetime（使用 UTC）
            if cta_signal.signal_timestamp > 0:
                signal_dt = datetime.fromtimestamp(cta_signal.signal_timestamp / 1000, tz=timezone.utc)
            else:
                signal_dt = datetime.now(timezone.utc)

            file_path = self._get_file_path(cta_signal.strategy_name, signal_dt)
            self._init_csv_file(file_path)

            with open(file_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=self.FIELDNAMES)
                writer.writerow(cta_signal.to_csv_row())

            logger.debug(f"信号已保存：{cta_signal.signal_id} -> {file_path}")
            return True

        except Exception as e:
            logger.error(f"保存信号失败：{e}")
            return False

    def write_batch(
        self,
        signals: List[Signal],
        strategy_name: str,
        strategy_version: str,
        interval: str,
        strategy_params: Optional[Dict[str, Any]] = None,
    ) -> int:
        """批量写入信号"""
        count = 0
        for signal in signals:
            if self.write_signal(
                signal, strategy_name, strategy_version, interval, strategy_params
            ):
                count += 1
        return count
