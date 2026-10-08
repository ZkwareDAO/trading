#!/usr/bin/env python3
"""Binance 直连下单执行器测试

全部 mock requests，不联网、不读真实凭证、不下真实订单。

重点守的是"下错单"而不是"没下单"：精度向上取整会超保证金、平仓走限价会让
本地仓位与交易所分叉、方向推导用错字段会把平多做成开多 —— 这几类缺陷在
mock 层就能钉死，到实盘才发现代价是真钱。
"""

import hashlib
import hmac
import logging
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from strategy_core.signal_logging.binance_trader import (
    MAINNET_BASE_URL,
    TESTNET_BASE_URL,
    BinanceApiError,
    BinanceCredentialsError,
    BinanceTrader,
    BinanceTraderConfig,
)
from strategy_core.signal_logging.csv_adapter import CtaSignalCSV

TEST_KEY = "test-api-key"
TEST_SECRET = "test-api-secret"

# BTCUSDT 的典型交易规则
EXCHANGE_INFO = {
    "symbols": [
        {
            "symbol": "BTCUSDT",
            "filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001"},
                {"filterType": "PRICE_FILTER", "tickSize": "0.10"},
                {"filterType": "MIN_NOTIONAL", "notional": "5"},
            ],
        }
    ]
}


def make_trader(**config_kwargs) -> BinanceTrader:
    """构造 trader，并预置交易规则缓存 + 免掉时间/持仓模式的网络往返"""
    trader = BinanceTrader(
        BinanceTraderConfig(**config_kwargs),
        api_key=TEST_KEY,
        api_secret=TEST_SECRET,
    )
    trader._time_offset_ms = 0
    trader._position_mode = "one_way"  # 免掉持仓模式探测的网络往返
    trader._symbol_filters["BTCUSDT"] = {
        "step_size": Decimal("0.001"),
        "min_qty": Decimal("0.001"),
        "tick_size": Decimal("0.10"),
        "min_notional": Decimal("5"),
    }
    return trader


def make_signal(**kwargs) -> CtaSignalCSV:
    """构造一个信号，默认是市价开多 200U × 5 倍杠杆 @ 50000"""
    defaults: dict = dict(
        signal_id="sig_abc123def456",
        symbol="BTCUSDT",
        signal_action="buy",
        signal_exchange="binance",
        signal_order_type=2,
        signal_trigger_price=50000.0,
        signal_cash=200.0,
        leverage=5,
        trading_mode="live",
    )
    defaults.update(kwargs)
    return CtaSignalCSV(**defaults)


def ok_response(payload=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = payload if payload is not None else {"orderId": 1, "status": "NEW"}
    resp.text = "{}"
    return resp


def error_response(status: int, code: int, msg: str) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {"code": code, "msg": msg}
    resp.text = f'{{"code": {code}, "msg": "{msg}"}}'
    return resp


def sent_params(mock_request) -> dict:
    """从 mock 的 requests.request 调用中解析出最后一次的 query 参数"""
    url = mock_request.call_args[0][1]
    query = url.split("?", 1)[1]
    parsed = {}
    for pair in query.split("&"):
        k, _, v = pair.partition("=")
        parsed[k] = v
    return parsed


def all_sent_params(mock_request) -> list:
    """解析全部调用的 query 参数（按调用顺序）"""
    result: list = []
    for call in mock_request.call_args_list:
        url = call[0][1]
        if "?" not in url:
            result.append({})
            continue
        parsed = {}
        for pair in url.split("?", 1)[1].split("&"):
            k, _, v = pair.partition("=")
            parsed[k] = v
        result.append(parsed)
    return result


class TestCredentials:
    """凭证缺失必须 fail fast，不能静默降级成假成功"""

    def test_missing_both_raises(self, monkeypatch):
        monkeypatch.delenv("BINANCE_API_KEY", raising=False)
        monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
        with pytest.raises(BinanceCredentialsError):
            BinanceTrader(BinanceTraderConfig())

    def test_missing_secret_raises(self, monkeypatch):
        monkeypatch.setenv("BINANCE_API_KEY", "k")
        monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
        with pytest.raises(BinanceCredentialsError):
            BinanceTrader(BinanceTraderConfig())

    def test_empty_string_secret_raises(self, monkeypatch):
        """空串与未设置同样危险，不能被 `is not None` 放过"""
        monkeypatch.setenv("BINANCE_API_KEY", "k")
        monkeypatch.setenv("BINANCE_API_SECRET", "")
        with pytest.raises(BinanceCredentialsError):
            BinanceTrader(BinanceTraderConfig())

    def test_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("BINANCE_API_KEY", "env-key")
        monkeypatch.setenv("BINANCE_API_SECRET", "env-secret")
        trader = BinanceTrader(BinanceTraderConfig())
        assert trader._api_key == "env-key"
        assert trader._api_secret == "env-secret"

    def test_testnet_switches_base_url(self):
        assert make_trader(testnet=True).base_url == TESTNET_BASE_URL
        assert make_trader(testnet=False).base_url == MAINNET_BASE_URL


class TestSigning:
    """HMAC 签名与 API key 传递"""

    def test_signature_matches_independent_hmac(self):
        """用独立算出的期望值对账，而不是拿实现自己的输出当预期"""
        trader = make_trader()
        query = "symbol=BTCUSDT&side=BUY&quantity=0.02"
        expected = hmac.new(
            TEST_SECRET.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        assert trader._sign(query) == expected

    def test_signed_request_appends_signature_and_header(self):
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            trader._signed_request("POST", "/fapi/v1/order", {"symbol": "BTCUSDT"})

        url = mock_request.call_args[0][1]
        assert "signature=" in url
        assert "timestamp=" in url
        assert "recvWindow=5000" in url
        assert mock_request.call_args[1]["headers"]["X-MBX-APIKEY"] == TEST_KEY

    def test_signature_covers_all_params(self):
        """签名必须覆盖 timestamp/recvWindow，否则交易所会以 -1022 拒绝"""
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            trader._signed_request("POST", "/fapi/v1/order", {"symbol": "BTCUSDT"})

        query = mock_request.call_args[0][1].split("?", 1)[1]
        body, _, signature = query.rpartition("&signature=")
        assert (
            hmac.new(TEST_SECRET.encode(), body.encode(), hashlib.sha256).hexdigest()
            == signature
        )

    def test_public_request_has_no_signature(self):
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response(EXCHANGE_INFO)
            trader._public_request("/fapi/v1/exchangeInfo", {"symbol": "ETHUSDT"})

        assert "signature=" not in mock_request.call_args[0][1]
        assert "X-MBX-APIKEY" not in mock_request.call_args[1]["headers"]


class TestQuantize:
    """精度处理：必须向下取整"""

    @pytest.mark.parametrize(
        "value,step,expected",
        [
            ("0.0179", "0.001", "0.017"),   # 关键：不是 0.018
            ("0.0199", "0.001", "0.019"),
            ("0.02", "0.001", "0.02"),
            ("1.999", "1", "1"),
            ("50000.19", "0.10", "50000.1"),
        ],
    )
    def test_rounds_down(self, value, step, expected):
        result = BinanceTrader._quantize(Decimal(value), Decimal(step))
        assert result == Decimal(expected), (
            f"{value} 按 {step} 取整应为 {expected}（向下），实际 {result}。"
            f"向上取整会超出可用保证金或触发 -1111 精度错误。"
        )

    def test_zero_step_is_passthrough(self):
        assert BinanceTrader._quantize(Decimal("0.123"), Decimal("0")) == Decimal("0.123")

    def test_fmt_avoids_scientific_notation(self):
        """Binance 不接受 1E-3 这类写法"""
        assert "E" not in BinanceTrader._fmt(Decimal("0.001"))
        assert "e" not in BinanceTrader._fmt(Decimal("0.00001"))


class TestOpenQuantity:
    """下单量折算与交易所下限校验"""

    def test_cash_times_leverage_over_price(self):
        trader = make_trader()
        # 200 × 5 / 50000 = 0.02
        qty = trader._calc_open_quantity(make_signal())
        assert qty == Decimal("0.02")

    def test_explicit_quantity_wins(self):
        trader = make_trader()
        qty = trader._calc_open_quantity(make_signal(signal_quantity=0.05))
        assert qty == Decimal("0.05")

    def test_below_min_qty_refuses(self, caplog):
        trader = make_trader()
        # 5 × 1 / 50000 = 0.0001 < minQty 0.001
        with caplog.at_level(logging.ERROR):
            qty = trader._calc_open_quantity(
                make_signal(signal_cash=5.0, leverage=1)
            )
        assert qty is None
        assert "最小值" in caplog.text

    def test_below_min_notional_refuses(self, caplog):
        """数量过了 minQty 但名义价值不足时也要拒绝

        用 cash=50 让 qty 正好等于 minQty(0.001)，名义价值 50U 低于设定的 100U 下限，
        以此穿过 minQty 分支、单独命中 notional 分支。
        """
        trader = make_trader()
        trader._symbol_filters["BTCUSDT"]["min_notional"] = Decimal("100")
        with caplog.at_level(logging.ERROR):
            qty = trader._calc_open_quantity(
                make_signal(signal_cash=50.0, leverage=1)
            )
        assert qty is None
        assert "名义价值" in caplog.text

    def test_zero_price_refuses(self, caplog):
        trader = make_trader()
        with caplog.at_level(logging.ERROR):
            qty = trader._calc_open_quantity(make_signal(signal_trigger_price=0))
        assert qty is None
        assert "价格非法" in caplog.text

    def test_no_cash_no_quantity_refuses(self, caplog):
        trader = make_trader()
        with caplog.at_level(logging.ERROR):
            qty = trader._calc_open_quantity(
                make_signal(signal_cash=0, signal_quantity=0)
            )
        assert qty is None

    def test_fetches_and_caches_exchange_info(self):
        """精度只拉一次，之后走进程内缓存"""
        trader = BinanceTrader(
            BinanceTraderConfig(), api_key=TEST_KEY, api_secret=TEST_SECRET
        )
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response(EXCHANGE_INFO)
            first = trader._get_symbol_filters("BTCUSDT")
            second = trader._get_symbol_filters("BTCUSDT")

        assert mock_request.call_count == 1
        assert first["step_size"] == Decimal("0.001")
        assert second is first

    def test_unknown_symbol_raises(self):
        trader = BinanceTrader(
            BinanceTraderConfig(), api_key=TEST_KEY, api_secret=TEST_SECRET
        )
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response({"symbols": []})
            with pytest.raises(BinanceApiError):
                trader._get_symbol_filters("NOPEUSDT")


class TestOpenOrder:
    """开仓：尊重 order_type"""

    def test_market_order(self):
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            assert trader.execute(make_signal(signal_order_type=2)) is True

        params = sent_params(mock_request)
        assert params["type"] == "MARKET"
        assert params["side"] == "BUY"
        assert params["quantity"] == "0.02"
        assert "price" not in params

    def test_limit_order_carries_price_and_tif(self):
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            assert trader.execute(make_signal(signal_order_type=1)) is True

        params = sent_params(mock_request)
        assert params["type"] == "LIMIT"
        assert params["timeInForce"] == "GTC"
        assert params["price"] == "50000"

    def test_limit_slippage_favours_fill(self):
        """买单向上让价、卖单向下让价，否则挂单永远不成交"""
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            trader.execute(make_signal(signal_order_type=1, signal_slippage=0.001))
        buy_price = Decimal(sent_params(mock_request)["price"])
        assert buy_price > Decimal("50000")

        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            trader.execute(
                make_signal(
                    signal_action="sell", signal_order_type=1, signal_slippage=0.001
                )
            )
        sell_price = Decimal(sent_params(mock_request)["price"])
        assert sell_price < Decimal("50000")

    def test_sell_opens_short(self):
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            trader.execute(make_signal(signal_action="sell"))

        assert sent_params(mock_request)["side"] == "SELL"

    def test_client_order_id_is_signal_id(self):
        """幂等键：同一根 K 线重复推送会被交易所以重复 clientOrderId 拒绝"""
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            trader.execute(make_signal(signal_id="sig_deadbeef1234"))

        assert sent_params(mock_request)["newClientOrderId"] == "sig_deadbeef1234"

    def test_sets_leverage_before_order(self):
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            trader.execute(make_signal(leverage=3))

        paths = [c[0][1] for c in mock_request.call_args_list]
        assert any("/fapi/v1/leverage" in p for p in paths)
        assert "/fapi/v1/leverage" in paths[0], "杠杆必须在下单前设置"

    def test_hedge_mode_open_carries_position_side(self):
        """双向持仓：开仓必须带 positionSide，且按 side 映射 LONG/SHORT"""
        trader = make_trader()
        trader._position_mode = "hedge"
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            trader.execute(make_signal())

        params = sent_params(mock_request)
        assert params.get("positionSide") == "LONG"
        assert "reduceOnly" not in params

    def test_hedge_mode_short_open_carries_position_side_short(self):
        trader = make_trader()
        trader._position_mode = "hedge"
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            trader.execute(make_signal(signal_action="sell"))

        params = sent_params(mock_request)
        assert params.get("positionSide") == "SHORT"

    def test_hedge_mode_close_sells_against_long_side(self):
        """双向持仓平多：SELL + positionSide=LONG，不允许 reduceOnly"""
        trader = make_trader()
        trader._position_mode = "hedge"
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.side_effect = [
                ok_response(
                    [{"symbol": "BTCUSDT", "positionAmt": "0.002"}]  # 持仓查询
                ),
                ok_response(),  # 平仓单
            ]
            trader.execute(make_signal(signal_action="sell_close"))

        params = sent_params(mock_request)
        assert params["side"] == "SELL"
        assert params.get("positionSide") == "LONG"
        assert "reduceOnly" not in params

    def test_hedge_mode_close_short_buys_against_short_side(self):
        trader = make_trader()
        trader._position_mode = "hedge"
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.side_effect = [
                ok_response([{"symbol": "BTCUSDT", "positionAmt": "-0.002"}]),
                ok_response(),
            ]
            trader.execute(make_signal(signal_action="buy_close"))

        params = sent_params(mock_request)
        assert params["side"] == "BUY"
        assert params.get("positionSide") == "SHORT"
        assert "reduceOnly" not in params

    def test_one_way_mode_keeps_reduce_only(self):
        """单向持仓行为不变：开仓无 positionSide"""
        trader = make_trader()
        trader._position_mode = "one_way"
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            trader.execute(make_signal())

        params = sent_params(mock_request)
        assert "positionSide" not in params

    def test_leverage_failure_does_not_block_order(self, caplog):
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.side_effect = [
                error_response(400, -4046, "No need to change leverage."),
                ok_response(),
            ]
            with caplog.at_level(logging.WARNING):
                assert trader.execute(make_signal()) is True
        assert "设置杠杆失败" in caplog.text


class TestClosePosition:
    """平仓：按实际持仓 reduceOnly 市价全平"""

    def _run_close(self, trader, signal, position_amt="0.02"):
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.side_effect = [
                ok_response([{"symbol": "BTCUSDT", "positionAmt": position_amt}]),
                ok_response(),
            ]
            result = trader.execute(signal)
        return result, mock_request

    def test_close_long_uses_reduce_only_market(self):
        trader = make_trader()
        # order_type=1（限价）也必须被平仓路径忽略
        signal = make_signal(signal_action="sell_close", signal_order_type=1)
        result, mock_request = self._run_close(trader, signal)

        assert result is True
        params = sent_params(mock_request)
        assert params["reduceOnly"] == "true"
        assert params["type"] == "MARKET", (
            "平仓必须市价：限价平仓挂单不成交会让本地仓位账本与交易所永久分叉"
        )
        assert params["side"] == "SELL"
        assert params["quantity"] == "0.02"

    def test_close_short_sends_buy(self):
        trader = make_trader()
        signal = make_signal(signal_action="buy_close")
        result, mock_request = self._run_close(trader, signal, position_amt="-0.02")

        assert result is True
        assert sent_params(mock_request)["side"] == "BUY"

    def test_close_uses_exchange_position_not_signal_quantity(self):
        """平仓量取交易所实际持仓，不看信号里的数量"""
        trader = make_trader()
        signal = make_signal(signal_action="sell_close", signal_quantity=999.0)
        _, mock_request = self._run_close(trader, signal, position_amt="0.015")

        assert sent_params(mock_request)["quantity"] == "0.015"

    def test_flat_closes_whatever_is_held(self):
        """flat 没有方向预期，多空都能平"""
        for amt, expected_side in (("0.02", "SELL"), ("-0.02", "BUY")):
            trader = make_trader()
            _, mock_request = self._run_close(
                trader, make_signal(signal_action="flat"), position_amt=amt
            )
            assert sent_params(mock_request)["side"] == expected_side

    def test_no_position_is_idempotent_success(self, caplog):
        """已经没仓位说明平仓意图已达成，不该发单也不该报失败"""
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response(
                [{"symbol": "BTCUSDT", "positionAmt": "0"}]
            )
            with caplog.at_level(logging.WARNING):
                result = trader.execute(make_signal(signal_action="sell_close"))

        assert result is True
        paths = [c[0][1] for c in mock_request.call_args_list]
        assert not any("/fapi/v1/order" in p for p in paths), "无持仓时不应发下单请求"
        assert "无持仓" in caplog.text

    def test_direction_mismatch_refuses(self, caplog):
        """要平多但账户是空头 → 拒绝。误平会毁掉同账户其他策略的反向持仓"""
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response(
                [{"symbol": "BTCUSDT", "positionAmt": "-0.02"}]
            )
            with caplog.at_level(logging.ERROR):
                result = trader.execute(make_signal(signal_action="sell_close"))

        assert result is False
        paths = [c[0][1] for c in mock_request.call_args_list]
        assert not any("/fapi/v1/order" in p for p in paths)
        assert "不一致" in caplog.text

    def test_position_amt_filters_by_symbol(self):
        """positionRisk 返回多个 symbol 时只累加目标 symbol"""
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response(
                [
                    {"symbol": "ETHUSDT", "positionAmt": "5.0"},
                    {"symbol": "BTCUSDT", "positionAmt": "0.03"},
                ]
            )
            assert trader._get_position_amt("BTCUSDT") == Decimal("0.03")


class TestReverse:
    """反手：先平后开，平仓失败不许开新仓"""

    def test_reverse_long_closes_then_opens(self):
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.side_effect = [
                ok_response([{"symbol": "BTCUSDT", "positionAmt": "-0.02"}]),  # 持空
                ok_response(),  # 平空
                ok_response(),  # 设杠杆
                ok_response(),  # 开多
            ]
            assert trader.execute(make_signal(signal_action="reverse_long")) is True

        orders = [
            p for p in all_sent_params(mock_request)
            if "type" in p and "side" in p
        ]
        assert len(orders) == 2
        assert orders[0]["reduceOnly"] == "true", "第一笔必须是平仓"
        assert orders[0]["side"] == "BUY"
        assert "reduceOnly" not in orders[1], "第二笔必须是开仓"
        assert orders[1]["side"] == "BUY"

    def test_reverse_close_failure_aborts_open(self, caplog):
        """平仓失败还去开仓会变成双倍单边持仓"""
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            # 持仓方向与 reverse_long 的预期（空头）不符 → 平仓被拒
            mock_request.return_value = ok_response(
                [{"symbol": "BTCUSDT", "positionAmt": "0.02"}]
            )
            with caplog.at_level(logging.ERROR):
                result = trader.execute(make_signal(signal_action="reverse_long"))

        assert result is False
        paths = [c[0][1] for c in mock_request.call_args_list]
        assert not any("/fapi/v1/order" in p for p in paths)

    def test_reverse_uses_distinct_client_order_ids(self):
        """两笔单共用 signal_id 会让第二笔被交易所当重复单拒绝"""
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.side_effect = [
                ok_response([{"symbol": "BTCUSDT", "positionAmt": "-0.02"}]),
                ok_response(),
                ok_response(),
                ok_response(),
            ]
            trader.execute(make_signal(signal_action="reverse_long"))

        ids = [
            p["newClientOrderId"]
            for p in all_sent_params(mock_request)
            if "newClientOrderId" in p
        ]
        assert len(ids) == 2
        assert len(set(ids)) == 2, f"两笔单的 clientOrderId 必须不同，实际: {ids}"

    def test_reverse_receipts_distinguish_close_from_open(self, caplog):
        """反手一个信号下两笔单，回执日志必须能区分哪笔是平、哪笔是开

        两笔回执共用同一 signal_id，若标签相同则事后无法从日志判断
        平仓是否真的执行了，排查重复持仓时会失去唯一线索。
        """
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.side_effect = [
                ok_response([{"symbol": "BTCUSDT", "positionAmt": "-0.02"}]),
                ok_response(),
                ok_response(),
                ok_response(),
            ]
            with caplog.at_level(logging.INFO):
                assert trader.execute(make_signal(signal_action="reverse_long")) is True

        receipts = [r.getMessage() for r in caplog.records if "成交回执" in r.getMessage()]
        assert len(receipts) == 2, f"反手应有两条回执，实际: {receipts}"
        assert any("平仓成交回执" in m for m in receipts), f"缺平仓回执: {receipts}"
        assert any("开仓成交回执" in m for m in receipts), f"缺开仓回执: {receipts}"


class TestGuards:
    """拒绝下单的各类前置校验"""

    def test_paper_trading_never_orders(self, caplog):
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            with caplog.at_level(logging.ERROR):
                result = trader.execute(make_signal(trading_mode="paper_trading"))

        assert result is False
        assert mock_request.call_count == 0
        assert "paper_trading" in caplog.text

    def test_exchange_mismatch_refuses(self, caplog):
        """hyperliquid 的信号在币安开仓会按完全不同的合约规格成交"""
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            with caplog.at_level(logging.ERROR):
                result = trader.execute(make_signal(signal_exchange="hyperliquid"))

        assert result is False
        assert mock_request.call_count == 0
        assert "不匹配" in caplog.text

    def test_unknown_action_refuses(self, caplog):
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            with caplog.at_level(logging.ERROR):
                result = trader.execute(make_signal(signal_action="teleport"))

        assert result is False
        paths = [c[0][1] for c in mock_request.call_args_list]
        assert not any("/fapi/v1/order" in p for p in paths)

    def test_hedge_mode_detected_and_adapted(self, caplog):
        """双向持仓不再拒绝：探测后按 hedge 模式带 positionSide 下单"""
        trader = make_trader()
        trader._position_mode = None
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response({"dualSidePosition": True})
            with caplog.at_level(logging.INFO):
                result = trader.execute(make_signal())

        assert result is True
        assert trader._position_mode == "hedge"
        params = sent_params(mock_request)
        assert params.get("positionSide") == "LONG"
        assert "持仓模式" in caplog.text

    def test_one_way_mode_detected_once(self):
        trader = make_trader()
        trader._position_mode = None
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response({"dualSidePosition": False})
            trader._detect_position_mode()
            trader._detect_position_mode()
        assert mock_request.call_count == 1
        assert trader._position_mode == "one_way"

    def test_api_error_returns_false_not_raise(self, caplog):
        """下单被拒必须返回 False 而非抛异常，否则会打断策略主循环"""
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.side_effect = [
                ok_response(),  # 杠杆
                error_response(400, -2019, "Margin is insufficient."),
            ]
            with caplog.at_level(logging.ERROR):
                result = trader.execute(make_signal())

        assert result is False
        assert "-2019" in caplog.text


class TestRetry:
    """重试策略：网络异常/5xx 重试，4xx 不重试"""

    def test_no_retry_on_4xx(self):
        """4xx 是交易所明确拒绝，重试只会放大问题（如重复下单尝试）"""
        trader = make_trader(max_retries=3)
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = error_response(400, -1111, "Precision error")
            with pytest.raises(BinanceApiError) as exc:
                trader._signed_request("POST", "/fapi/v1/order", {"symbol": "BTCUSDT"})

        assert mock_request.call_count == 1, "4xx 不该重试"
        assert exc.value.code == -1111

    def test_retries_on_network_error(self):
        trader = make_trader(max_retries=2)
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request, patch(
            "strategy_core.signal_logging.binance_trader.time.sleep"
        ):
            mock_request.side_effect = [
                Exception("connection reset"),
                ok_response(),
            ]
            result = trader._signed_request("GET", "/fapi/v2/positionRisk", {})

        assert mock_request.call_count == 2
        assert result is not None

    def test_retries_on_5xx_then_gives_up(self):
        trader = make_trader(max_retries=2)
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request, patch(
            "strategy_core.signal_logging.binance_trader.time.sleep"
        ):
            mock_request.return_value = error_response(503, 0, "Service unavailable")
            with pytest.raises(Exception):
                trader._signed_request("GET", "/fapi/v2/positionRisk", {})

        assert mock_request.call_count == 3  # 1 + 2 retries


class TestRetryRefreshesTimestamp:
    """重试必须重新打时间戳并重签，但幂等键必须保持不变

    缺陷背景：timestamp 曾在 _signed_request 里打一次、query+signature 在 _send
    循环外构建，重试逐字节重放。读超时 10s 后重试时 timestamp 已陈旧 ~11s，
    远超 recvWindow=5000ms，交易所以 -1021 拒绝——重试形同虚设。

    更糟的是它掩盖诊断信息：首单超时但实际已成交时，幂等键本该让重试返回
    -4015（"clientOrderId 重复"，明确告知已成交），现在时间戳先在网关被拦掉，
    返回 -1021，策略以为下单失败而交易所持仓，形成账本分叉。
    平仓同走此路径，止损遇抖动会让仓位裸奔。
    """

    ORDER_PARAMS = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "MARKET",
        "quantity": "0.02",
        "newClientOrderId": "sig_idem_key",
    }

    def _retry_once(self, trader, mock_request, clock_step_ms: int):
        """让第一次请求抛网络异常，并在每次读时钟时推进 clock_step_ms"""
        now = [1_700_000_000_000]

        def advancing_clock():
            now[0] += clock_step_ms
            return now[0]

        mock_request.side_effect = [Exception("read timeout"), ok_response()]
        with patch(
            "strategy_core.signal_logging.binance_trader._now_ms",
            side_effect=advancing_clock,
        ), patch("strategy_core.signal_logging.binance_trader.time.sleep"):
            return trader._signed_request("POST", "/fapi/v1/order", dict(self.ORDER_PARAMS))

    def test_retry_uses_fresh_timestamp(self):
        """重试的 timestamp 必须比首次新，否则必然超出 recvWindow 被拒"""
        trader = make_trader(max_retries=2, recv_window=5000)
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            self._retry_once(trader, mock_request, clock_step_ms=11_000)

        stamps = [int(p["timestamp"]) for p in all_sent_params(mock_request)]
        assert len(stamps) == 2
        assert stamps[1] > stamps[0], (
            f"重试复用了陈旧 timestamp {stamps}，交易所会以 -1021 拒绝"
        )

    def test_retry_timestamp_within_recv_window(self):
        """重试的 timestamp 与发出时刻的偏差必须落在 recvWindow 内"""
        recv_window = 5000
        trader = make_trader(max_retries=2, recv_window=recv_window)
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            self._retry_once(trader, mock_request, clock_step_ms=11_000)

        params = all_sent_params(mock_request)
        # 末次读时钟即"发出时刻"，两者之差就是签名的陈旧程度
        stamps = [int(p["timestamp"]) for p in params]
        assert stamps[1] - stamps[0] >= 11_000, "时钟未推进，用例失去意义"
        # 重签后陈旧度归零：timestamp 就是本次发出时读的时钟
        assert int(params[1]["recvWindow"]) == recv_window

    def test_retry_resigns_request(self):
        """timestamp 变了签名必须跟着变，否则交易所以 -1022 签名错误拒绝"""
        trader = make_trader(max_retries=2)
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            self._retry_once(trader, mock_request, clock_step_ms=11_000)

        sigs = [p["signature"] for p in all_sent_params(mock_request)]
        assert sigs[0] != sigs[1], "重放了旧签名"

    def test_retry_signature_is_valid_for_its_own_query(self):
        """每次重试的签名必须能验证它自己那次的 query（不是上一次的）"""
        trader = make_trader(max_retries=2)
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            self._retry_once(trader, mock_request, clock_step_ms=11_000)

        for i, call in enumerate(mock_request.call_args_list):
            query = call[0][1].split("?", 1)[1]
            body, _, signature = query.rpartition("&signature=")
            expected = hmac.new(
                TEST_SECRET.encode(), body.encode(), hashlib.sha256
            ).hexdigest()
            assert signature == expected, f"第 {i + 1} 次请求签名与其 query 不匹配"

    def test_retry_keeps_same_client_order_id(self):
        """幂等键必须跨重试保持不变

        这是"重试时重建参数"最危险的副作用：若 newClientOrderId 也跟着变，
        首单已成交而响应丢失时，重试会被当成全新订单接受 —— 直接双倍持仓。
        交易所靠这个键返回 -4015 拒掉重复单，它必须逐字节稳定。
        """
        trader = make_trader(max_retries=2)
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            self._retry_once(trader, mock_request, clock_step_ms=11_000)

        ids = [p["newClientOrderId"] for p in all_sent_params(mock_request)]
        assert ids == ["sig_idem_key", "sig_idem_key"], (
            f"幂等键跨重试发生变化 {ids}，首单已成交时会造成双倍持仓"
        )

    def test_retry_preserves_business_params(self):
        """除时间戳/签名外，业务参数不得在重试中漂移"""
        trader = make_trader(max_retries=2)
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            self._retry_once(trader, mock_request, clock_step_ms=11_000)

        volatile = {"timestamp", "signature"}
        first, second = [
            {k: v for k, v in p.items() if k not in volatile}
            for p in all_sent_params(mock_request)
        ]
        assert first == second, f"业务参数漂移: {first} vs {second}"

    def test_close_order_retry_also_refreshes(self):
        """平仓走同一条 _signed_request，止损路径同样不能被陈旧签名拖死"""
        trader = make_trader(max_retries=2)
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            now = [1_700_000_000_000]

            def advancing_clock():
                now[0] += 11_000
                return now[0]

            mock_request.side_effect = [
                ok_response([{"symbol": "BTCUSDT", "positionAmt": "0.02"}]),
                Exception("read timeout"),
                ok_response(),
            ]
            with patch(
                "strategy_core.signal_logging.binance_trader._now_ms",
                side_effect=advancing_clock,
            ), patch("strategy_core.signal_logging.binance_trader.time.sleep"):
                result = trader.execute(make_signal(signal_action="sell_close"))

        assert result is True
        orders = [
            p for call, p in zip(mock_request.call_args_list, all_sent_params(mock_request))
            if "/fapi/v1/order" in call[0][1]
        ]
        assert len(orders) == 2, "平仓下单未发生重试，用例失去意义"
        assert int(orders[1]["timestamp"]) > int(orders[0]["timestamp"])
        assert orders[0]["newClientOrderId"] == orders[1]["newClientOrderId"]

    def test_unsigned_request_needs_no_timestamp(self):
        """公共接口不签名也不带 timestamp，重试不应给它塞进去"""
        trader = make_trader(max_retries=2)
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request, patch(
            "strategy_core.signal_logging.binance_trader.time.sleep"
        ):
            mock_request.side_effect = [Exception("boom"), ok_response(EXCHANGE_INFO)]
            trader._public_request("/fapi/v1/exchangeInfo", {"symbol": "ETHUSDT"})

        for params in all_sent_params(mock_request):
            assert "timestamp" not in params
            assert "signature" not in params


class TestSecretsNotLeaked:
    """凭证绝不进日志"""

    def test_secret_absent_from_logs_on_success(self, caplog):
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = ok_response()
            with caplog.at_level(logging.DEBUG):
                trader.execute(make_signal())

        assert TEST_SECRET not in caplog.text
        assert TEST_KEY not in caplog.text

    def test_secret_absent_from_logs_on_failure(self, caplog):
        trader = make_trader()
        with patch(
            "strategy_core.signal_logging.binance_trader.requests.request"
        ) as mock_request:
            mock_request.return_value = error_response(400, -2019, "Margin insufficient")
            with caplog.at_level(logging.DEBUG):
                trader.execute(make_signal())

        assert TEST_SECRET not in caplog.text
        assert TEST_KEY not in caplog.text

    def test_signature_absent_from_logs(self):
        """签名进日志等于泄漏一次可重放的请求凭据"""
        trader = make_trader()
        records = []
        handler = logging.Handler()
        handler.emit = lambda record: records.append(record.getMessage())
        trader_logger = logging.getLogger(
            "strategy_core.signal_logging.binance_trader"
        )
        trader_logger.addHandler(handler)
        trader_logger.setLevel(logging.DEBUG)
        try:
            with patch(
                "strategy_core.signal_logging.binance_trader.requests.request"
            ) as mock_request:
                mock_request.return_value = ok_response()
                trader.execute(make_signal())
            joined = "\n".join(records)
            assert "signature=" not in joined
        finally:
            trader_logger.removeHandler(handler)


class TestEdgeFallback418:
    """测试网 418 共享封禁池的边缘回退

    背景：testnet 套在 CloudFront 后，币安按"回源 IP"限流，该 IP 由同一边缘
    节点的所有用户共享 —— 低频用户也会被别人的高频请求连坐封禁。换边缘 IP
    （Host/SNI 不变）即换封禁池。主网不走 CloudFront，回退只在 testnet 启用。
    """

    def _banned_response(self):
        resp = MagicMock()
        resp.status_code = 418
        resp.json.return_value = {"code": -1003, "msg": "Way too many requests"}
        resp.text = '{"code": -1003, "msg": "Way too many requests"}'
        return resp

    def test_418_falls_back_to_edge_and_succeeds(self):
        """默认路径 418 → 换边缘成功 → 返回边缘响应，且默认路径不再重试"""
        trader = make_trader(testnet=True)
        trader._edge_ips = ["203.0.113.10", "203.0.113.11"]

        calls = []

        def fake_edge(ip, method, path, query, headers):
            calls.append(ip)
            if ip.endswith(".10"):
                return 418, '{"code": -1003}'
            return 200, '{"dualSidePosition": false}'

        with patch.object(trader, "_edge_request", side_effect=fake_edge), \
             patch(
                 "strategy_core.signal_logging.binance_trader.requests.request",
                 return_value=self._banned_response(),
             ) as mock_req:
            result = trader._signed_request("GET", "/fapi/v1/positionSide/dual")

        assert result == {"dualSidePosition": False}
        assert "203.0.113.11" in calls, "应试到成功的边缘"
        assert mock_req.call_count == 1, "边缘成功后不应再走默认路径重试"

    def test_all_edges_banned_raises_without_retry_loop(self):
        """全部边缘仍 418 → 抛 BinanceApiError，且不打满默认路径重试循环

        418 有封禁时长，立刻重试只会延长封禁 —— 必须一次失败即抛。
        """
        trader = make_trader(testnet=True, max_retries=2)
        trader._edge_ips = ["203.0.113.20"]

        with patch.object(
            trader, "_edge_request", return_value=(418, '{"code": -1003}')
        ), patch(
            "strategy_core.signal_logging.binance_trader.requests.request",
            return_value=self._banned_response(),
        ) as mock_req:
            with pytest.raises(BinanceApiError):
                trader._signed_request("GET", "/fapi/v1/positionSide/dual")
        assert mock_req.call_count == 1, "418 最终失败不应触发默认路径重试"

    def test_418_on_mainnet_does_not_fall_back(self):
        """主网 418 不做边缘回退（主网无 CloudFront 共享池，正确动作是降频）"""
        trader = make_trader(testnet=False)

        with patch.object(trader, "_refresh_edge_ips", return_value=["203.0.113.30"]) as mock_refresh, \
             patch(
                 "strategy_core.signal_logging.binance_trader.requests.request",
                 return_value=self._banned_response(),
             ):
            with pytest.raises(BinanceApiError):
                trader._signed_request("GET", "/fapi/v1/positionSide/dual")
        mock_refresh.assert_not_called()

    def test_edge_rotation_remembers_successful_edge(self):
        """成功的边缘被记住（_edge_index 停在其上），下次 418 从它开始轮转"""
        trader = make_trader(testnet=True)
        trader._edge_ips = ["203.0.113.10", "203.0.113.11"]

        def fake_edge(ip, method, path, query, headers):
            if ip.endswith(".11"):
                return 200, '{"ok": true}'
            return 418, '{"code": -1003}'

        with patch.object(trader, "_edge_request", side_effect=fake_edge), \
             patch(
                 "strategy_core.signal_logging.binance_trader.requests.request",
                 return_value=self._banned_response(),
             ):
            trader._signed_request("GET", "/fapi/v1/time")
        assert trader._edge_index == 1, "应停在成功的边缘上"
