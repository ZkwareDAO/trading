#!/usr/bin/env python3
"""direct_trading 配置接线测试

验证 run_strategy.py 与 SignalLogger 的通道选择（单体模式）：
1. direct_trading.enabled=true → SignalLogger 拿到 direct_trader，存储后本进程直连下单
2. paper_trading 模式下永不构造 trader（不下真单）
3. direct_trading.enabled=false / 缺段 → 不构造 trader，不需要凭证（回归保护）
4. 缺凭证 → 进程启动即失败，不静默降级

signal_hub HTTP 推送通道已随单体化移除：不再存在"双通道重复下单"的失效模式，
历史上对 http_endpoint is None 的断言一并删除。下单执行语义
（BinanceTrader 请求细节）由 test_binance_trader.py 覆盖。
"""

from unittest.mock import MagicMock, patch

import pytest
import yaml

from strategy_core.signal_logging.binance_trader import BinanceCredentialsError

FAKE_KEY = "unit-test-key"
FAKE_SECRET = "unit-test-secret"


def write_configs(tmp_path, direct_trading=None, extra=None):
    """写出一份最小可用的 settings.yaml + 策略配置，返回 (配置路径, 策略配置)"""
    global_config = {
        "signal_logging": {
            "storage": {"path": str(tmp_path / "signals")},
        },
    }
    if direct_trading is not None:
        global_config["direct_trading"] = direct_trading
    if extra:
        global_config.update(extra)

    config_file = tmp_path / "settings.yaml"
    with open(config_file, "w") as f:
        yaml.dump(global_config, f)

    strategy_dir = tmp_path / "strategies" / "test_strategy"
    strategy_dir.mkdir(parents=True, exist_ok=True)
    strategy_config = {"enabled": True, "symbols": ["BTCUSDT"]}
    return str(config_file), strategy_config


def build_runner(config_file, strategy_config, trading_mode="live"):
    """构造 runner，返回 SignalLogger 的 mock 类以便检查入参"""
    from run_strategy import StrategyProcessRunner

    with patch("run_strategy.SignalLogger") as mock_logger_class:
        mock_logger_class.return_value = MagicMock()
        StrategyProcessRunner(
            strategy_name="test_strategy",
            strategy_config=strategy_config,
            global_config_path=config_file,
            trading_mode=trading_mode,
        )
        return mock_logger_class


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("BINANCE_API_KEY", FAKE_KEY)
    monkeypatch.setenv("BINANCE_API_SECRET", FAKE_SECRET)


class TestDirectTradingEnabled:
    """启用直连时的执行器接线"""

    def test_passes_direct_trader_to_logger(self, tmp_path, creds):
        config_file, strategy_config = write_configs(
            tmp_path,
            direct_trading={"enabled": True, "exchange": "binance", "testnet": True},
        )
        kwargs = build_runner(config_file, strategy_config).call_args[1]

        assert kwargs["direct_trader"] is not None

    def test_testnet_flag_reaches_trader(self, tmp_path, creds):
        config_file, strategy_config = write_configs(
            tmp_path, direct_trading={"enabled": True, "testnet": True}
        )
        trader = build_runner(config_file, strategy_config).call_args[1]["direct_trader"]
        assert trader.config.testnet is True
        assert "testnet" in trader.base_url

    def test_custom_timeouts_reach_trader(self, tmp_path, creds):
        config_file, strategy_config = write_configs(
            tmp_path,
            direct_trading={
                "enabled": True,
                "recv_window": 3000,
                "timeout": 7.5,
                "max_retries": 4,
            },
        )
        trader = build_runner(config_file, strategy_config).call_args[1]["direct_trader"]
        assert trader.config.recv_window == 3000
        assert trader.config.timeout == 7.5
        assert trader.config.max_retries == 4

    def test_unsupported_exchange_raises(self, tmp_path, creds):
        config_file, strategy_config = write_configs(
            tmp_path, direct_trading={"enabled": True, "exchange": "hyperliquid"}
        )
        with pytest.raises(ValueError, match="仅支持 binance"):
            build_runner(config_file, strategy_config)

    def test_missing_credentials_aborts_startup(self, tmp_path, monkeypatch):
        """开着直连却下不了单，必须让进程起不来而不是静默跑空"""
        monkeypatch.delenv("BINANCE_API_KEY", raising=False)
        monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
        config_file, strategy_config = write_configs(
            tmp_path, direct_trading={"enabled": True}
        )
        with pytest.raises(BinanceCredentialsError):
            build_runner(config_file, strategy_config)


class TestPaperTradingBlocked:
    """模拟盘不下真单"""

    def test_paper_trading_gets_no_trader(self, tmp_path, creds):
        config_file, strategy_config = write_configs(
            tmp_path, direct_trading={"enabled": True}
        )
        kwargs = build_runner(
            config_file, strategy_config, trading_mode="paper_trading"
        ).call_args[1]
        assert kwargs["direct_trader"] is None

    def test_paper_trading_skips_credential_check(self, tmp_path, monkeypatch):
        """模拟盘既然不下单，就不该因为缺凭证而起不来"""
        monkeypatch.delenv("BINANCE_API_KEY", raising=False)
        monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
        config_file, strategy_config = write_configs(
            tmp_path, direct_trading={"enabled": True}
        )
        kwargs = build_runner(
            config_file, strategy_config, trading_mode="paper_trading"
        ).call_args[1]
        assert kwargs["direct_trader"] is None

    @pytest.mark.parametrize("mode", ["live", "smoking"])
    def test_live_and_smoking_do_place_real_orders(self, tmp_path, creds, mode):
        """live 与 smoking 都会下真单 —— 这是明确决策，不是漏拦

        smoking（冒烟）字面上像"只是测试"，实际会真实成交：其设计意图就是用真单
        验证全链路。唯一不下单的模式是 paper_trading。

        本用例的作用是把这个反直觉的约定钉住：若日后有人误以为 smoking 该被拦
        而加上防线，会先在这里失败并读到上面这段说明，从而知道要先确认意图。
        """
        config_file, strategy_config = write_configs(
            tmp_path, direct_trading={"enabled": True}
        )
        kwargs = build_runner(
            config_file, strategy_config, trading_mode=mode
        ).call_args[1]
        assert kwargs["direct_trader"] is not None, (
            f"trading_mode={mode} 应当构造执行器（会下真单）；"
            f"只有 paper_trading 被拦"
        )


class TestDirectTradingDisabled:
    """未启用时必须与改动前行为一致"""

    def test_disabled_gets_no_trader(self, tmp_path, creds):
        config_file, strategy_config = write_configs(
            tmp_path, direct_trading={"enabled": False}
        )
        kwargs = build_runner(config_file, strategy_config).call_args[1]
        assert kwargs["direct_trader"] is None

    def test_missing_section_gets_no_trader(self, tmp_path):
        """settings.yaml 里没有 direct_trading 段（旧配置文件）也要正常工作"""
        config_file, strategy_config = write_configs(tmp_path)
        kwargs = build_runner(config_file, strategy_config).call_args[1]
        assert kwargs["direct_trader"] is None

    def test_disabled_does_not_require_credentials(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BINANCE_API_KEY", raising=False)
        monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
        config_file, strategy_config = write_configs(
            tmp_path, direct_trading={"enabled": False}
        )
        kwargs = build_runner(config_file, strategy_config).call_args[1]
        assert kwargs["direct_trader"] is None


class TestSignalLoggerRouting:
    """SignalLogger 内部的直连路由（单体模式唯一下单通道）"""

    def _make_logger(self, tmp_path, direct_trader):
        from strategy_core.signal_logging import SignalLogger, SignalStorage

        return SignalLogger(
            SignalStorage(base_dir=str(tmp_path / "signals")),
            direct_trader=direct_trader,
        )

    def _make_cta(self):
        from strategy_core.signal_logging.csv_adapter import CtaSignalCSV

        return CtaSignalCSV(signal_id="sig_route_1", symbol="BTCUSDT", signal_action="buy")

    def test_direct_trader_executes_cta_signal(self, tmp_path):
        trader = MagicMock()
        trader.execute.return_value = True
        logger_obj = self._make_logger(tmp_path, trader)

        assert logger_obj.log_cta_signal(self._make_cta()) is True
        trader.execute.assert_called_once()

    def test_direct_trader_failure_is_reported(self, tmp_path):
        """下单失败必须如实上报，不许被吞成成功"""
        trader = MagicMock()
        trader.execute.return_value = False
        logger_obj = self._make_logger(tmp_path, trader)

        assert logger_obj.log_cta_signal(self._make_cta()) is False

    def test_direct_trader_exception_returns_false(self, tmp_path):
        trader = MagicMock()
        trader.execute.side_effect = RuntimeError("boom")
        logger_obj = self._make_logger(tmp_path, trader)

        assert logger_obj.log_cta_signal(self._make_cta()) is False

    def test_log_signal_also_routes_to_direct(self, tmp_path):
        from datetime import datetime, timezone

        from strategy_core.signal_logging.storage import Signal, SignalType

        trader = MagicMock()
        trader.execute.return_value = True
        logger_obj = self._make_logger(tmp_path, trader)

        signal = Signal(
            strategy_id="TEST_1h_BTCUSDT",
            signal_type=SignalType.BUY,
            symbol="BTCUSDT",
            price=50000.0,
            timestamp=datetime(2026, 8, 27, tzinfo=timezone.utc),
        )
        assert logger_obj.log_signal(signal) is True
        trader.execute.assert_called_once()

    def test_without_direct_trader_log_succeeds_without_order(self, tmp_path):
        """未配置直连时信号只落存储，log_cta_signal 恒为 True（不下单）"""
        logger_obj = self._make_logger(tmp_path, None)

        assert logger_obj.log_cta_signal(self._make_cta()) is True
