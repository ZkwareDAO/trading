#!/usr/bin/env python3
"""
测试信号格式对齐设计文档

注：原文件末尾的 TestKafkaFormatAlignment（4 个用例）随 KafkaSignalProducer
一并删除 —— 它测的是已不存在的类。这 4 个用例断言的字段（strategy_type /
signal.action / strategy.internal / user_id）都出自 CtaSignalCSV.to_json()，
覆盖仍由本文件 TestDesignDocSignalFormat 承担，且 HTTP 通道发的正是同一个
to_json() 结果，故无覆盖缺口。

根据信号格式规范：docs/SIGNAL_CSV_FORMAT.md

需要验证的格式差异:
1. 顶层 strategy_type 字段 (如 "CTAFuture")
2. 顶层 risk_strategy_type 字段 (如 "cta_intraday")
3. strategy.internal (非 interval)
4. signal.action 字段 (如 "buy", "sell_close" 等)
5. user_id 从配置传入 (非硬编码)
"""

import json
import os
import tempfile
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from strategy_core.signal_logging.storage import Signal, SignalType
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV


def _make_signal() -> Signal:
    return Signal(
        signal_id="sig-format-test",
        strategy_id="cta_rbreaker_v2_1m_btcusdt",
        signal_type=SignalType.BUY,
        symbol="BTCUSDT",
        price=75000.0,
        strength=0.8,
        direction="long",
        timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
        metadata={"reason": "breakout"},
    )


class TestDesignDocSignalFormat:
    """验证信号 JSON 格式与设计文档一致"""

    def test_top_level_strategy_type(self):
        """JSON 顶层应包含 strategy_type 字段"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.005},
            strategy_type="CTAFuture",
            risk_strategy_type="cta_intraday",
            user_id=1,
        )
        msg = cta.to_json(user_id=1)
        assert "strategy_type" in msg, "顶层应包含 strategy_type 字段"
        assert msg["strategy_type"] == "CTAFuture"

    def test_top_level_risk_strategy_type(self):
        """JSON 顶层应包含 risk_strategy_type 字段"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.005},
            strategy_type="CTAFuture",
            risk_strategy_type="cta_intraday",
            user_id=1,
        )
        msg = cta.to_json(user_id=1)
        assert "risk_strategy_type" in msg, "顶层应包含 risk_strategy_type 字段"
        assert msg["risk_strategy_type"] == "cta_intraday"

    def test_strategy_internal_not_interval(self):
        """strategy 对象应使用 internal 而非 interval"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="15m",
            strategy_params={"threshold": 0.005},
        )
        msg = cta.to_json()
        assert "internal" in msg["strategy"], "strategy 应包含 internal 字段"
        assert msg["strategy"]["internal"] == "15m"
        assert "interval" not in msg["strategy"], "strategy 不应包含 interval 字段"

    def test_signal_action_field(self):
        """signal 对象应包含 action 字段"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.005},
        )
        msg = cta.to_json()
        assert "action" in msg["signal"], "signal 应包含 action 字段"
        assert msg["signal"]["action"] == "buy"

    def test_signal_action_sell_close(self):
        """SELL_CLOSE 信号 action 应为 sell_close"""
        signal = Signal(
            signal_id="sig-sell-close",
            strategy_id="test_strategy",
            signal_type=SignalType.SELL_CLOSE,
            symbol="BTCUSDT",
            price=74000.0,
            direction="long",
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
        )
        cta = CtaSignalCSV.from_signal(signal, strategy_name="test_v1")
        msg = cta.to_json()
        assert msg["signal"]["action"] == "sell_close"

    def test_signal_action_reverse_long(self):
        """REVERSE_LONG 信号 action 应为 reverse_long"""
        signal = Signal(
            signal_id="sig-reverse-long",
            strategy_id="test_strategy",
            signal_type=SignalType.REVERSE_LONG,
            symbol="BTCUSDT",
            price=73000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
        )
        cta = CtaSignalCSV.from_signal(signal, strategy_name="test_v1")
        msg = cta.to_json()
        assert msg["signal"]["action"] == "reverse_long"

    def test_signal_action_reverse_short(self):
        """REVERSE_SHORT 信号 action 应为 reverse_short"""
        signal = Signal(
            signal_id="sig-reverse-short",
            strategy_id="test_strategy",
            signal_type=SignalType.REVERSE_SHORT,
            symbol="BTCUSDT",
            price=73000.0,
            timestamp=datetime(2026, 4, 14, 10, 0, 0, tzinfo=timezone.utc),
        )
        cta = CtaSignalCSV.from_signal(signal, strategy_name="test_v1")
        msg = cta.to_json()
        assert msg["signal"]["action"] == "reverse_short"

    def test_user_id_from_config(self):
        """user_id 应从配置传入，默认值为 1"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            user_id=42,
        )
        msg = cta.to_json(user_id=42)
        assert msg["user_id"] == 42

    def test_full_json_structure_matches_design_doc(self):
        """完整 JSON 结构应匹配设计文档"""
        signal = _make_signal()
        cta = CtaSignalCSV.from_signal(
            signal,
            strategy_name="cta_rbreaker",
            strategy_version="v2",
            interval="1m",
            strategy_params={"threshold": 0.005},
            strategy_valid_before="2030-12-31 08:00:00",
            strategy_cash=100,
            strategy_parts=1,
            strategy_type="CTAFuture",
            risk_strategy_type="cta_intraday",
            user_id=1,
        )
        msg = cta.to_json(user_id=1)

        # 顶层字段
        assert "SignalID" in msg
        assert "SignalTimestamp" in msg
        assert "symbol" in msg
        assert "user_id" in msg
        assert "pos_type" in msg
        assert "strategy_type" in msg
        assert "risk_strategy_type" in msg

        # strategy 子字段
        s = msg["strategy"]
        assert "name" in s
        assert "version" in s
        assert "internal" in s
        assert "description" in s
        assert "params" in s
        assert "valid_before" in s
        assert "cash" in s
        assert "parts" in s
        assert "interval" not in s  # 确保旧的字段名不存在

        # signal 子字段
        sig = msg["signal"]
        assert "side" in sig
        assert "action" in sig
        assert "exchange" in sig
        assert "valid_before" in sig
        assert "trigger_price" in sig
        assert "slippage" in sig
        assert "order_type" in sig
