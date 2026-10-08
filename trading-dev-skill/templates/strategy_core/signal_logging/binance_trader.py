"""Binance U 本位合约直连下单执行器

启用 `direct_trading` 后，信号不再经 Signal Hub / Kafka 转发，由策略进程直接
调用 Binance U 本位合约 API 下单。

为什么下单与"消息推送"是两套取舍：消息推送失败重发无副作用；
本模块发的是"订单"，重发可能重复开仓。因此这里的重试策略、幂等键、
以及"精度必须向下取整"都是与消息推送相反的取舍，见各函数注释。
（历史上的 http_sender 消息推送模块已随单体化删除，此对比仅说明设计动机。）

凭证只从环境变量读（BINANCE_API_KEY / BINANCE_API_SECRET），不进配置文件、不进日志。
"""

import hashlib
import hmac
import http.client
import json
import logging
import os
import socket
import ssl
import time
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlencode

import requests

from strategy_core.signal_logging.csv_adapter import CtaSignalCSV

logger = logging.getLogger(__name__)

# 生产 / 测试网基址
MAINNET_BASE_URL = "https://fapi.binance.com"
TESTNET_HOST = "testnet.binancefuture.com"
TESTNET_BASE_URL = f"https://{TESTNET_HOST}"

# 开仓动作 → 交易所方向
_OPEN_SIDE = {
    "buy": "BUY",           # 开多
    "sell": "SELL",         # 开空
    "reverse_long": "BUY",  # 反手做多（平掉空头后开多）
    "reverse_short": "SELL",
}

# 平仓动作 → 被平仓位的方向（用于与交易所实际持仓交叉校验）
#
# 注意：不能用 CtaSignalCSV.signal_side 推交易所方向。signal_side 由
# Signal.direction 映射而来，而 sell_close（平多）的 direction 是 "long" →
# signal_side=1(buy)，与"平多要下 SELL 单"正好相反。故一律从 signal_action 推。
_CLOSE_EXPECTED_POSITION = {
    "buy_close": "short",    # 买入平仓 → 原持仓是空头
    "sell_close": "long",    # 卖出平仓 → 原持仓是多头
    "reverse_long": "short",  # 反手做多 → 先平空头
    "reverse_short": "long",
}

# 需要先平后开的反手动作
_REVERSE_ACTIONS = frozenset({"reverse_long", "reverse_short"})

# 纯平仓动作（flat 的方向由实际持仓决定）
_CLOSE_ACTIONS = frozenset({"buy_close", "sell_close", "flat"})


class BinanceCredentialsError(Exception):
    """缺少 API 凭证

    故意在构造时抛出而非在下单时静默降级：direct_trading 开着却发不出单，
    等于策略在"以为已成交"的状态下继续跑，比进程起不来危险得多。
    """


class BinanceApiError(Exception):
    """交易所返回业务错误（4xx + code/msg）"""

    def __init__(self, code: int, msg: str, http_status: int = 0):
        super().__init__(f"code={code}, msg={msg}, http_status={http_status}")
        self.code = code
        self.msg = msg
        self.http_status = http_status


@dataclass
class BinanceTraderConfig:
    """直连下单配置（不含凭证）"""
    testnet: bool = False
    recv_window: int = 5000
    timeout: float = 10.0
    max_retries: int = 2  # 仅对网络异常与 5xx 生效，4xx 一律不重试
    # timestamp 预留量（毫秒）：吸收偏移估计误差。币安硬规则：timestamp 超前
    # 服务器 **不得超过 1000ms**（否则 -1021 "ahead of server's time"），
    # 故预留必须 < 1000。滞后方向由 recvWindow 兜底。
    clock_drift_margin_ms: int = 500


def _now_ms() -> int:
    """当前毫秒时间戳（独立函数便于测试注入）"""
    return int(time.time() * 1000)


class BinanceTrader:
    """把 CtaSignalCSV 翻译成 Binance fapi 订单

    启动时自动探测持仓模式（GET /fapi/v1/positionSide/dual）并适配：
    - 单向（One-way）：不开 positionSide，平仓用 reduceOnly
    - 双向（Hedge）：开仓带 positionSide=LONG/SHORT，平仓按对应方向持仓量
      下对侧单（Hedge 模式不允许 reduceOnly，会报 -1106）
    """

    def __init__(
        self,
        config: Optional[BinanceTraderConfig] = None,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
    ):
        self.config = config or BinanceTraderConfig()
        self._api_key = api_key if api_key is not None else os.environ.get("BINANCE_API_KEY", "")
        self._api_secret = (
            api_secret if api_secret is not None else os.environ.get("BINANCE_API_SECRET", "")
        )

        if not self._api_key or not self._api_secret:
            raise BinanceCredentialsError(
                "直连下单已启用但缺少凭证：请在 .env 配置 BINANCE_API_KEY 与 BINANCE_API_SECRET"
            )

        self.base_url = TESTNET_BASE_URL if self.config.testnet else MAINNET_BASE_URL

        # 进程内缓存，不落盘
        self._symbol_filters: Dict[str, Dict[str, Decimal]] = {}
        self._leverage_applied: Dict[str, int] = {}
        self._time_offset_ms: Optional[int] = None
        self._position_mode: Optional[str] = None  # "one_way" | "hedge"，探测后缓存

        # 测试网 418 共享封禁池的边缘回退：
        # testnet.binancefuture.com 套在 AWS CloudFront 后，币安后端按"CloudFront
        # 回源 IP"限流，该 IP 由同一边缘节点的所有用户共享 —— 任何人的高频请求
        # 都会把整个节点打进 418（实测本会话仅 ~20 个请求被封两次、每次 1-1.5h）。
        # 换一个边缘 IP 直连（Host/SNI 不变）即落入不同封禁池。主网不走 CloudFront，
        # 无此问题，回退只在 testnet=True 时启用。
        self._edge_ips: List[str] = []
        self._edge_index = 0

        logger.info(
            "Binance 直连下单已启用: base_url=%s, testnet=%s",
            self.base_url, self.config.testnet,
        )

    # ------------------------------------------------------------------
    # HTTP 层
    # ------------------------------------------------------------------

    def _sign(self, query: str) -> str:
        """HMAC-SHA256 签名（对已编码的 query string 原文签名）"""
        return hmac.new(
            self._api_secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _public_request(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        """无签名 GET（exchangeInfo / time）"""
        return self._send("GET", path, params or {}, signed=False)

    def _signed_request(
        self,
        method: str,
        path: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """带签名请求，timestamp 与签名由 _send 在每次尝试时生成"""
        payload = dict(params or {})
        payload["recvWindow"] = self.config.recv_window
        return self._send(method, path, payload, signed=True)

    def _build_query(self, params: Dict[str, Any], signed: bool) -> str:
        """构建（并在需要时签名）单次尝试的 query string

        每次尝试都重新打 timestamp 再重签：签名覆盖 timestamp，两者必须一起重建。
        业务参数原样透传 —— 尤其 newClientOrderId 幂等键一旦跟着变，首单已成交
        而响应丢失时，重试会被交易所当成全新订单接受，直接双倍持仓。
        """
        if not signed:
            return urlencode(params)
        payload = dict(params)
        payload["timestamp"] = _now_ms() + self._server_time_offset() + self.config.clock_drift_margin_ms
        query = urlencode(payload)
        return f"{query}&signature={self._sign(query)}"

    def _send(self, method: str, path: str, params: Dict[str, Any], signed: bool) -> Any:
        """统一发送 + 重试

        重试只覆盖网络异常和 5xx（请求未必到达 / 交易所侧故障）。4xx 是交易所
        明确拒绝（参数错、余额不足、重复 clientOrderId），重试只会放大问题。

        timestamp 与签名在循环内逐次重建。曾经它们在循环外算一次被逐字节重放：
        读超时耗掉 10s 后重试，签名已陈旧远超 recvWindow(5s)，交易所必以 -1021
        拒绝，重试形同虚设；更糟的是它掩盖了 -4015（幂等键重复 = 首单其实已成交）
        —— 那是唯一能说明"交易所已持仓"的诊断信号。

        例外：418（IP 被限流封禁）在 testnet 上做一次边缘回退后重试——
        测试网的封禁打在 CloudFront 共享回源 IP 上，换边缘即换封禁池
        （见 _refresh_edge_ips）。418 不是业务拒绝，重试有明确收益；
        主网共享池问题不存在，418 照常不重试（请求频率本身需要降）。
        """
        url = f"{self.base_url}{path}"
        headers = {"X-MBX-APIKEY": self._api_key} if signed else {}

        last_error: Optional[Exception] = None
        for attempt in range(self.config.max_retries + 1):
            try:
                query = self._build_query(params, signed)
                resp = requests.request(
                    method,
                    f"{url}?{query}" if query else url,
                    headers=headers,
                    timeout=self.config.timeout,
                )
                if 200 <= resp.status_code < 300:
                    return resp.json()

                if resp.status_code == 418 and self.config.testnet:
                    # 测试网共享封禁池：换边缘 IP 后重试（同一次 attempt 内）。
                    # 全部边缘仍 418 → 视为最终失败，直接抛出（不能落进下面的
                    # 5xx 重试分支把 418 当可重试错误打满循环——418 有封禁时长，
                    # 立刻重试只会把封禁时间越养越长）。
                    if self._try_edge_fallback(method, path, query, headers):
                        return self._edge_response  # type: ignore[has-type]
                    code, msg = self._parse_error(resp)
                    raise BinanceApiError(code, msg, resp.status_code)

                if resp.status_code < 500:
                    # 交易所明确拒绝，不重试
                    code, msg = self._parse_error(resp)
                    raise BinanceApiError(code, msg, resp.status_code)

                last_error = BinanceApiError(*self._parse_error(resp), resp.status_code)
                logger.warning(
                    "Binance 请求 5xx，将重试: path=%s, status=%s", path, resp.status_code
                )
            except BinanceApiError:
                raise
            except Exception as e:  # 网络异常
                last_error = e
                logger.warning("Binance 请求异常，将重试: path=%s, 错误: %s", path, e)

            if attempt < self.config.max_retries:
                time.sleep(min(2 ** attempt, 5))

        raise last_error if last_error else RuntimeError(f"Binance 请求失败: {path}")

    # ------------------------------------------------------------------
    # 测试网 418 边缘回退（CloudFront 共享封禁池绕行）
    # ------------------------------------------------------------------

    def _refresh_edge_ips(self) -> List[str]:
        """解析测试网域名拿到当前 CloudFront 边缘 IP 列表"""
        try:
            infos = socket.getaddrinfo(TESTNET_HOST, 443, socket.AF_INET)
            return sorted({info[4][0] for info in infos})
        except Exception as e:
            logger.warning("解析测试网边缘 IP 失败: %s", e)
            return []

    def _edge_request(self, edge_ip: str, method: str, path: str, query: str,
                      headers: Dict[str, str]) -> Tuple[int, str]:
        """直连指定边缘 IP 发请求（Host/SNI 保持域名，TLS 证书校验正常）"""
        ctx = ssl.create_default_context()
        with socket.create_connection((edge_ip, 443), timeout=self.config.timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=TESTNET_HOST) as s:
                header_lines = "\r\n".join(f"{k}: {v}" for k, v in headers.items())
                req = (
                    f"{method} {path}?{query} HTTP/1.1\r\n"
                    f"Host: {TESTNET_HOST}\r\n"
                    f"{header_lines}\r\n"
                    f"Connection: close\r\n\r\n"
                )
                s.sendall(req.encode())
                resp = b""
                while True:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    resp += chunk
        head, _, body = resp.decode(errors="replace").partition("\r\n\r\n")
        status_line = head.split("\r\n")[0]
        try:
            status = int(status_line.split()[1])
        except (IndexError, ValueError):
            status = 0
        return status, body

    def _try_edge_fallback(self, method: str, path: str, query: str,
                           headers: Dict[str, str]) -> bool:
        """418 后逐个尝试其他边缘 IP，成功则缓存响应并返回 True

        注意：query 是 418 那次请求的签名串。timestamp 在 recvWindow 内
        （失败得非常快），换边缘重发同一签名串是安全的——不存在"重放陈旧
        签名"的问题，真正要防的是下单重试改变幂等键，这里原样复用。
        """
        if not self._edge_ips:
            self._edge_ips = self._refresh_edge_ips()
        if not self._edge_ips:
            return False

        for _ in range(len(self._edge_ips)):
            self._edge_index = (self._edge_index + 1) % len(self._edge_ips)
            ip = self._edge_ips[self._edge_index]
            try:
                status, body = self._edge_request(ip, method, path, query, headers)
                if status == 200:
                    logger.info(
                        "测试网 418：已切换边缘 IP %s 重试成功", ip
                    )
                    self._edge_response = json.loads(body)
                    return True
                logger.warning(
                    "测试网边缘 %s 返回 %s，尝试下一个", ip, status
                )
            except Exception as e:
                logger.warning("测试网边缘 %s 请求异常: %s", ip, e)
        return False

    @staticmethod
    def _parse_error(resp: Any) -> Tuple[int, str]:
        """从响应体解析 code/msg，解析不出时退回 HTTP 文本"""
        try:
            body = resp.json()
            return int(body.get("code", 0)), str(body.get("msg", ""))
        except Exception:
            return 0, str(getattr(resp, "text", ""))[:200]

    def _server_time_offset(self) -> int:
        """服务器与本地时钟差（只拉一次；失败按 0 处理）

        真实偏移 = serverTime - local_before（请求**发出前**打点），且必须取
        多次采样中 RTT 最小的一次：响应方向抖动（实测代理/CDN 链路 RTT 在
        0.4s~5.5s 间波动）会把"响应耗时"混进偏移估计，单次采样最大可虚高 4s。
        取最小 RTT 样本后，估计值 ≈ 真实偏移 + 发送方向耗时（偏大 ~0.2-0.5s），
        再由 clock_drift_margin_ms 预留吸收——注意币安硬规则：timestamp 超前
        服务器不得超过 1000ms，否则 -1021；滞后方向由 recvWindow 兜底。
        """
        if self._time_offset_ms is None:
            best_rtt: Optional[int] = None
            best_offset = 0
            for _ in range(3):
                try:
                    local_before = _now_ms()
                    data = self._public_request("/fapi/v1/time")
                    local_after = _now_ms()
                    rtt = local_after - local_before
                    offset = int(data["serverTime"]) - local_before
                    if best_rtt is None or rtt < best_rtt:
                        best_rtt = rtt
                        best_offset = offset
                except Exception as e:
                    logger.warning("获取 Binance 服务器时间失败: %s", e)
            self._time_offset_ms = best_offset
            logger.info(
                "Binance 服务器时间偏移: %sms (best RTT %sms)",
                self._time_offset_ms, best_rtt,
            )
        return self._time_offset_ms

    # ------------------------------------------------------------------
    # 交易规则与精度
    # ------------------------------------------------------------------

    def _get_symbol_filters(self, symbol: str) -> Dict[str, Decimal]:
        """拉取并缓存 symbol 的数量/价格精度与下限"""
        cached = self._symbol_filters.get(symbol)
        if cached is not None:
            return cached

        data = self._public_request("/fapi/v1/exchangeInfo", {"symbol": symbol})
        for item in data.get("symbols", []):
            if item.get("symbol") != symbol:
                continue
            filters = {f.get("filterType"): f for f in item.get("filters", [])}
            lot = filters.get("LOT_SIZE", {})
            price_filter = filters.get("PRICE_FILTER", {})
            notional = filters.get("MIN_NOTIONAL", {})
            parsed = {
                "step_size": Decimal(str(lot.get("stepSize", "0.001"))),
                "min_qty": Decimal(str(lot.get("minQty", "0"))),
                "tick_size": Decimal(str(price_filter.get("tickSize", "0.01"))),
                "min_notional": Decimal(str(notional.get("notional", "0"))),
            }
            self._symbol_filters[symbol] = parsed
            return parsed

        raise BinanceApiError(0, f"exchangeInfo 中未找到 symbol: {symbol}")

    @staticmethod
    def _quantize(value: Decimal, step: Decimal) -> Decimal:
        """按 step 向下取整

        必须向下（ROUND_DOWN）：向上取整会让下单量超出可用保证金或触发
        -1111 Precision is over the maximum，而少下一个 step 只是略微少一点仓位。
        """
        if step <= 0:
            return value
        return (value / step).to_integral_value(rounding=ROUND_DOWN) * step

    @staticmethod
    def _fmt(value: Decimal) -> str:
        """去掉尾随零的定点字符串（Binance 不接受科学计数法）"""
        return format(value.normalize(), "f")

    def _detect_position_mode(self) -> str:
        """探测账户持仓模式并缓存：one_way | hedge

        每进程只探测一次；探测失败按单向处理（与旧行为一致，失败会在下单时暴露）。
        """
        if self._position_mode:
            return self._position_mode
        try:
            data = self._signed_request("GET", "/fapi/v1/positionSide/dual")
            if bool(data.get("dualSidePosition", False)):
                self._position_mode = "hedge"
            else:
                self._position_mode = "one_way"
        except Exception as e:
            logger.warning(
                "持仓模式探测失败，按单向模式继续: %s", e
            )
            self._position_mode = "one_way"
        logger.info("持仓模式: %s", self._position_mode)
        return self._position_mode

    def _apply_leverage(self, symbol: str, leverage: int) -> None:
        """设置杠杆（每 symbol 每进程一次；失败不阻断下单）"""
        if leverage <= 0 or self._leverage_applied.get(symbol) == leverage:
            return
        try:
            self._signed_request(
                "POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": leverage}
            )
            self._leverage_applied[symbol] = leverage
            logger.info("已设置杠杆: symbol=%s, leverage=%s", symbol, leverage)
        except Exception as e:
            logger.warning("设置杠杆失败（继续下单）: symbol=%s, 错误: %s", symbol, e)

    def _get_position_amt(self, symbol: str) -> Decimal:
        """查询带符号持仓量（>0 多头，<0 空头，0 无持仓）"""
        data = self._signed_request("GET", "/fapi/v2/positionRisk", {"symbol": symbol})
        rows = data if isinstance(data, list) else [data]
        total = Decimal("0")
        for row in rows:
            if row.get("symbol") != symbol:
                continue
            total += Decimal(str(row.get("positionAmt", "0")))
        return total

    # ------------------------------------------------------------------
    # 下单
    # ------------------------------------------------------------------

    def execute(self, cta_signal: CtaSignalCSV) -> bool:
        """执行一个信号，返回是否全部下单成功"""
        action = (cta_signal.signal_action or "").lower()
        symbol = cta_signal.symbol

        # 模拟盘防线（run_strategy 已拦一层，这里是纵深防御）
        if cta_signal.trading_mode == "paper_trading":
            logger.error(
                "paper_trading 模式不允许直连下单，已跳过: signal_id=%s", cta_signal.signal_id
            )
            return False

        # 信号声明的交易所与本执行器不一致时拒绝：拿着 hyperliquid 的信号
        # 在币安开仓会按完全不同的合约规格成交。
        exchange = (cta_signal.signal_exchange or "").lower()
        if exchange and exchange != "binance":
            logger.error(
                "信号交易所与直连执行器不匹配，拒绝下单: signal_id=%s, signal_exchange=%s, "
                "executor=binance",
                cta_signal.signal_id, cta_signal.signal_exchange,
            )
            return False

        try:
            if action in _REVERSE_ACTIONS:
                # 先平后开：平仓失败则不开新仓，否则会变成双倍单边持仓
                if not self._close_position(cta_signal, action, order_id_suffix="_c"):
                    logger.error(
                        "反手信号平仓失败，已放弃开仓: signal_id=%s, action=%s",
                        cta_signal.signal_id, action,
                    )
                    return False
                return self._open_position(cta_signal, action)

            if action in _CLOSE_ACTIONS:
                return self._close_position(cta_signal, action)

            if action in _OPEN_SIDE:
                return self._open_position(cta_signal, action)

            logger.error(
                "未知信号动作，无法下单: signal_id=%s, action=%s", cta_signal.signal_id, action
            )
            return False

        except BinanceApiError as e:
            logger.error(
                "直连下单被交易所拒绝: signal_id=%s, symbol=%s, action=%s, %s",
                cta_signal.signal_id, symbol, action, e,
            )
            return False
        except Exception as e:
            logger.error(
                "直连下单异常: signal_id=%s, symbol=%s, action=%s, 错误: %s",
                cta_signal.signal_id, symbol, action, e,
            )
            return False

    def _calc_open_quantity(self, cta_signal: CtaSignalCSV) -> Optional[Decimal]:
        """按 cash × leverage / price 折算下单量，并按交易规则校验

        返回 None 表示不满足下单条件（已记 error 日志）。
        """
        symbol = cta_signal.symbol
        filters = self._get_symbol_filters(symbol)
        price = Decimal(str(cta_signal.signal_trigger_price))

        if price <= 0:
            logger.error("信号价格非法，无法折算下单量: signal_id=%s, price=%s",
                         cta_signal.signal_id, price)
            return None

        if cta_signal.signal_quantity and cta_signal.signal_quantity > 0:
            # 策略显式给了数量则直接用
            raw_qty = Decimal(str(cta_signal.signal_quantity))
        else:
            cash = Decimal(str(cta_signal.signal_cash))
            if cash <= 0:
                logger.error(
                    "signal_cash 与 signal_quantity 均未设置，无法下单: signal_id=%s",
                    cta_signal.signal_id,
                )
                return None
            leverage = Decimal(str(max(cta_signal.leverage, 1)))
            raw_qty = cash * leverage / price

        qty = self._quantize(raw_qty, filters["step_size"])

        if qty <= 0 or qty < filters["min_qty"]:
            logger.error(
                "下单量低于交易所最小值，已跳过: signal_id=%s, symbol=%s, qty=%s, min_qty=%s",
                cta_signal.signal_id, symbol, self._fmt(qty), self._fmt(filters["min_qty"]),
            )
            return None

        min_notional = filters["min_notional"]
        if min_notional > 0 and qty * price < min_notional:
            logger.error(
                "下单名义价值低于交易所最小值，已跳过: signal_id=%s, symbol=%s, "
                "notional=%s, min_notional=%s",
                cta_signal.signal_id, symbol, self._fmt(qty * price), self._fmt(min_notional),
            )
            return None

        return qty

    def _submit_order(self, params: Dict[str, Any], signal_id: str, kind: str) -> bool:
        """下单并记录回执（kind 用于区分开仓/平仓，反手时一个信号会有两笔）

        始终返回 True：走到这里说明交易所已接受订单。失败路径一律走异常
        （BinanceApiError / 网络异常），由 execute() 统一捕获转成 False。
        """
        result = self._signed_request("POST", "/fapi/v1/order", params)
        logger.info(
            "直连%s成交回执: signal_id=%s, orderId=%s, status=%s",
            kind, signal_id, result.get("orderId"), result.get("status"),
        )
        return True

    def _open_position(self, cta_signal: CtaSignalCSV, action: str) -> bool:
        """开仓（尊重 signal_order_type：1=LIMIT，2=MARKET）"""
        side = _OPEN_SIDE[action]
        symbol = cta_signal.symbol

        qty = self._calc_open_quantity(cta_signal)
        if qty is None:
            return False

        self._apply_leverage(symbol, cta_signal.leverage)
        # positionSide 依赖持仓模式，探测必须发生在构建订单参数前；
        # 放在杠杆设置之后是为了保持"杠杆请求是下单前最后一个请求"的既有语义
        self._detect_position_mode()

        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "quantity": self._fmt(qty),
            # signal_id 是 (策略, 标的, K线时间, 动作) 的确定性哈希，用作幂等键：
            # 同一根 K 线重复推送时交易所会以"重复 clientOrderId"拒绝第二笔。
            "newClientOrderId": cta_signal.signal_id,
        }

        # 双向持仓必须声明 positionSide（缺省会报 -4061）；BUY 开多 → LONG，
        # SELL 开空 → SHORT
        if self._position_mode == "hedge":
            params["positionSide"] = "LONG" if side == "BUY" else "SHORT"

        if cta_signal.signal_order_type == 1:
            filters = self._get_symbol_filters(symbol)
            price = Decimal(str(cta_signal.signal_trigger_price))
            slippage = Decimal(str(cta_signal.signal_slippage or 0))
            # 滑点朝有利于成交的方向让价
            adjusted = price * (1 + slippage) if side == "BUY" else price * (1 - slippage)
            limit_price = self._quantize(adjusted, filters["tick_size"])
            params["type"] = "LIMIT"
            params["timeInForce"] = "GTC"
            params["price"] = self._fmt(limit_price)
        else:
            params["type"] = "MARKET"

        logger.info(
            "直连开仓请求: signal_id=%s, symbol=%s, side=%s, type=%s, qty=%s, price=%s",
            cta_signal.signal_id, symbol, side, params["type"],
            params["quantity"], params.get("price", "-"),
        )
        return self._submit_order(params, cta_signal.signal_id, "开仓")

    def _close_position(
        self,
        cta_signal: CtaSignalCSV,
        action: str,
        order_id_suffix: str = "",
    ) -> bool:
        """平仓：按交易所实际持仓量 reduceOnly 市价全平

        平仓一律 MARKET，不看 signal_order_type：限价平仓挂单不成交会让本地
        仓位账本认为已离场、交易所却仍持仓，止损信号尤其不能容忍这种分叉。
        """
        symbol = cta_signal.symbol
        position_amt = self._get_position_amt(symbol)

        if position_amt == 0:
            # 幂等：已经没有仓位，平仓意图已达成
            logger.warning(
                "平仓信号但交易所无持仓，视为已平: signal_id=%s, symbol=%s, action=%s",
                cta_signal.signal_id, symbol, action,
            )
            return True

        actual = "long" if position_amt > 0 else "short"
        expected = _CLOSE_EXPECTED_POSITION.get(action)
        if expected and expected != actual:
            # 不按实际持仓强平：同一账户可能有其他策略的反向仓位，
            # 误平会直接毁掉别人的持仓。
            logger.error(
                "平仓方向与交易所实际持仓不一致，拒绝下单: signal_id=%s, symbol=%s, "
                "action=%s, expected=%s, actual=%s, position_amt=%s",
                cta_signal.signal_id, symbol, action, expected, actual, position_amt,
            )
            return False

        filters = self._get_symbol_filters(symbol)
        qty = self._quantize(abs(position_amt), filters["step_size"])
        if qty <= 0:
            logger.error(
                "持仓量小于最小步进，无法平仓: signal_id=%s, symbol=%s, position_amt=%s",
                cta_signal.signal_id, symbol, position_amt,
            )
            return False

        side = "SELL" if position_amt > 0 else "BUY"
        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            "quantity": self._fmt(qty),
            # 反手时两笔单共用同一 signal_id，加后缀避免 clientOrderId 冲突
            "newClientOrderId": f"{cta_signal.signal_id}{order_id_suffix}",
        }
        if self._position_mode == "hedge":
            # 双向持仓不允许 reduceOnly（-1106），靠 positionSide 对冲方向约束：
            # 平多 = SELL + side=LONG，平空 = BUY + side=SHORT。
            # 注意 Hedge 模式下 positionAmt 只含本方向持仓，不会误伤另一侧。
            params["positionSide"] = "LONG" if position_amt > 0 else "SHORT"
        else:
            params["reduceOnly"] = "true"

        protection = (
            "positionSide" if "positionSide" in params else "reduceOnly"
        )
        logger.info(
            "直连平仓请求: signal_id=%s, symbol=%s, side=%s, qty=%s, %s=%s",
            cta_signal.signal_id, symbol, side, params["quantity"],
            protection, params.get(protection, ""),
        )
        return self._submit_order(params, cta_signal.signal_id, "平仓")
