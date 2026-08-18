#!/usr/bin/env python3
"""
测试 FactoryClient 远程仓位查询接口

验证：
1. 查询仓位列表
2. 判断仓位是否开启
3. 处理网络错误

补覆盖说明：本文件原有 11 个用例在遗留测试清理中被删除——它们全部失败，
根因是构造 FactoryClient 时只传 `factory_endpoint=`，而查询 URL 实际由
`position_proxy_url` 拼出，导致 endpoint 为 None、请求必然失败（源码功能正常）。
遗留下来的用例只覆盖了"查不到 → (None, None)"这类降级路径，
真正的判定路径（开启 → True / 已平 → False / 取最新一条）无覆盖。

该功能在实盘由 BaseStrategy 远程仓位同步调用，错判会导致重复开仓或漏平仓，
故补回下方 TestRemotePositionVerdict。

契约（对齐 factory_client.py 实现）：
- 响应体 data.list 是仓位数组；旧格式 {"status":"success"} 与新格式 {"code":0} 均支持
- Deleted == 0 → 开启；Deleted == 1 → 已平仓
- 多条仓位取 UpdatedAt 最大的一条
- 无记录 / 查询失败 / Deleted 缺失 → (None, None) 表示"无法判断"，
  调用方据此保持本地状态，绝不可退化成 False
"""

import json
import logging
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from strategy_core.factory_client import FactoryClient

# RFC5737 文档地址，避免真实内网 IP 入库
PROXY_URL = "http://203.0.113.10:8889"
STRATEGY = "SARSNT3_8H_3_BTCUSDT_LIVE"
USER = "user_001"


def _mock_response(payload: dict) -> MagicMock:
    """构造 urlopen 的 context-manager 返回值。"""
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _position_client() -> FactoryClient:
    """构造用于仓位查询的 client。

    关键：URL 由 position_proxy_url 拼出，不是 factory_endpoint。
    传错参数名会拼出 'None/api/...'，请求必然失败——这正是原 11 个用例全灭的原因。
    """
    return FactoryClient(position_proxy_url=PROXY_URL)


def _positions(items: list) -> dict:
    return {"status": "success", "data": {"list": items}}


class TestRemotePositionVerdict:
    """仓位判定路径（补回被删除的覆盖）"""

    def test_url_built_from_position_proxy_url(self):
        """URL 必须由 position_proxy_url 拼出且不含 None。

        这条直接钉住原测试踩的坑：换成 factory_endpoint 就会拼出 'None/api/...'。
        """
        captured = {}

        def fake_urlopen(req, timeout=None):
            captured["url"] = req.full_url
            return _mock_response(_positions([]))

        with patch("strategy_core.factory_client.urllib.request.urlopen",
                   side_effect=fake_urlopen):
            _position_client().query_order_positions(STRATEGY, USER)

        assert captured["url"].startswith(PROXY_URL)
        assert "None" not in captured["url"]
        assert f"strategy_name={STRATEGY}" in captured["url"]
        assert f"user_id={USER}" in captured["url"]

    def test_query_returns_position_data(self):
        """查询成功时返回仓位数据（原覆盖缺失的成功路径）。"""
        payload = _positions([{"ID": 1, "Deleted": 0}])
        with patch("strategy_core.factory_client.urllib.request.urlopen",
                   return_value=_mock_response(payload)):
            result = _position_client().query_order_positions(STRATEGY, USER)

        assert result["status"] == "success"
        assert result["data"]["list"][0]["ID"] == 1

    def test_new_response_format_code_zero(self):
        """新格式 {"code": 0} 与旧格式 {"status": "success"} 均视为成功。"""
        payload = {"code": 0, "data": {"list": [{"ID": 7, "Deleted": 1}]}}
        with patch("strategy_core.factory_client.urllib.request.urlopen",
                   return_value=_mock_response(payload)):
            result = _position_client().query_order_positions(STRATEGY, USER)

        assert result["status"] == "success"

    def test_open_position_returns_true(self):
        """Deleted == 0 → 仓位开启。"""
        payload = _positions([
            {"ID": 1, "Deleted": 0, "UpdatedAt": "2026-08-01T00:00:00Z"}
        ])
        with patch("strategy_core.factory_client.urllib.request.urlopen",
                   return_value=_mock_response(payload)):
            is_open, latest = _position_client().is_position_open(STRATEGY, USER)

        assert is_open is True
        assert latest["ID"] == 1

    def test_closed_position_returns_false(self):
        """Deleted == 1 → 已平仓。"""
        payload = _positions([
            {"ID": 2, "Deleted": 1, "UpdatedAt": "2026-08-01T00:00:00Z"}
        ])
        with patch("strategy_core.factory_client.urllib.request.urlopen",
                   return_value=_mock_response(payload)):
            is_open, latest = _position_client().is_position_open(STRATEGY, USER)

        assert is_open is False
        assert latest["ID"] == 2

    def test_picks_latest_when_newest_is_closed(self):
        """多条仓位取 UpdatedAt 最新：旧的开启 + 新的已平 → False。"""
        payload = _positions([
            {"ID": 10, "Deleted": 0, "UpdatedAt": "2026-08-01T00:00:00Z"},
            {"ID": 11, "Deleted": 1, "UpdatedAt": "2026-08-05T00:00:00Z"},
        ])
        with patch("strategy_core.factory_client.urllib.request.urlopen",
                   return_value=_mock_response(payload)):
            is_open, latest = _position_client().is_position_open(STRATEGY, USER)

        assert is_open is False
        assert latest["ID"] == 11

    def test_picks_latest_when_newest_is_open(self):
        """反向用例：旧的已平 + 新的开启 → True（防排序方向写反）。"""
        payload = _positions([
            {"ID": 20, "Deleted": 1, "UpdatedAt": "2026-08-01T00:00:00Z"},
            {"ID": 21, "Deleted": 0, "UpdatedAt": "2026-08-05T00:00:00Z"},
        ])
        with patch("strategy_core.factory_client.urllib.request.urlopen",
                   return_value=_mock_response(payload)):
            is_open, latest = _position_client().is_position_open(STRATEGY, USER)

        assert is_open is True
        assert latest["ID"] == 21

    @pytest.mark.parametrize("deleted_key,updated_key", [
        ("deleted", "updated_at"),   # 蛇形小写（后端实际风格）
        ("DELETED", "UPDATEDAT"),    # 全大写
    ])
    def test_field_name_case_variants(self, deleted_key, updated_key):
        """后端字段命名风格不一致时仍能解析（_get_field 的兼容能力）。"""
        payload = _positions([
            {"ID": 4, deleted_key: 0, updated_key: "2026-08-01T00:00:00Z"}
        ])
        with patch("strategy_core.factory_client.urllib.request.urlopen",
                   return_value=_mock_response(payload)):
            is_open, _ = _position_client().is_position_open(STRATEGY, USER)

        assert is_open is True

    def test_unconfigured_proxy_url_degrades_gracefully(self):
        """position_proxy_url 未配置（开源默认 ${POSITION_PROXY_URL} 未设）→
        返回 error 而非抛异常，上层据此得到 (None, None)。"""
        client = FactoryClient()
        result = client.query_order_positions(STRATEGY, USER)

        assert result["status"] == "error"

    def test_configured_proxy_query_failure_returns_none_not_false(self):
        """已配置代理但查询失败 → (None, None)，绝不可返回 False。

        返回 False 会让上层误认为"远程已平仓"并清理本地仓位，
        导致实际持仓失去管理。这是本模块最关键的安全属性。
        """
        with patch("strategy_core.factory_client.urllib.request.urlopen",
                   side_effect=OSError("connection refused")):
            is_open, latest = _position_client().is_position_open(STRATEGY, USER)

        assert is_open is None
        assert latest is None


class TestFactoryClientPosition:
    """测试 FactoryClient 仓位查询（原有用例，覆盖降级路径）"""

    def test_is_position_open_empty_list(self):
        """无仓位时返回 (None, None) - 无法判断，保持本地状态"""
        client = FactoryClient(factory_endpoint="http://127.0.0.1:8888")

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "success",
            "data": {"list": []}
        }).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("strategy_core.factory_client.urllib.request.urlopen", return_value=mock_response):
            is_open, position_detail = client.is_position_open("ICT_4H_V2", "user_001")

        # 无仓位记录 → 无法判断（返回 None），不清理本地状态
        assert is_open is None
        assert position_detail is None

    def test_is_position_open_network_error(self, caplog):
        """网络错误时返回 (None, None)"""
        client = FactoryClient(factory_endpoint="http://127.0.0.1:8888")

        with patch("strategy_core.factory_client.urllib.request.urlopen") as mock_urlopen:
            import urllib.error
            mock_urlopen.side_effect = urllib.error.URLError("connection refused")

            with caplog.at_level(logging.WARNING, logger="strategy_core.factory_client"):
                is_open, position_detail = client.is_position_open("ICT_4H_V2", "user_001")

        assert is_open is None
        assert position_detail is None
        assert "查询子仓位失败" in caplog.text or "失败" in caplog.text


    def test_position_proxy_port(self):
        """使用代理端口 8889 查询仓位"""
        # FactoryClient 应支持通过代理端口查询
        client = FactoryClient(
            factory_endpoint="http://127.0.0.1:8888",
            position_proxy_url="http://127.0.0.1:8889",
        )

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "success",
            "data": {"list": []}
        }).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("strategy_core.factory_client.urllib.request.urlopen", return_value=mock_response) as mock_req:
            client.query_order_positions("ICT_4H_V2", "user_001")

            # 验证使用代理端口
            call_args = mock_req.call_args[0][0]
            assert "8889" in str(call_args.full_url)



    # ========== 新增测试：API 路径配置化 ==========

    def test_query_order_positions_with_custom_api_path(self):
        """使用自定义 API 路径查询仓位"""
        client = FactoryClient(
            factory_endpoint="http://127.0.0.1:8888",
            position_proxy_url="http://127.0.0.1:8889",
            position_api_path="/api/position/user-order-positions",  # 自定义路径
        )

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "success",
            "data": {"list": []}
        }).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("strategy_core.factory_client.urllib.request.urlopen", return_value=mock_response) as mock_req:
            client.query_order_positions("ICT_4H_V2", "user_001")

            # 验证 URL 使用自定义路径
            call_args = mock_req.call_args[0][0]
            assert "/api/position/user-order-positions" in str(call_args.full_url)

    def test_query_order_positions_default_api_path(self):
        """未指定 API 路径时使用默认路径"""
        client = FactoryClient(
            factory_endpoint="http://127.0.0.1:8888",
            position_proxy_url="http://127.0.0.1:8889",
        )

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "success",
            "data": {"list": []}
        }).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("strategy_core.factory_client.urllib.request.urlopen", return_value=mock_response) as mock_req:
            client.query_order_positions("ICT_4H_V2", "user_001")

            # 验证 URL 使用默认路径 /api/position/user-order-positions
            call_args = mock_req.call_args[0][0]
            assert "/api/position/user-order-positions" in str(call_args.full_url)

    # ========== 新增测试：字段缺失时返回 None ==========

    def test_is_position_open_deleted_field_missing(self):
        """Deleted 字段缺失时返回 (None, None)，无法判断"""
        client = FactoryClient(factory_endpoint="http://127.0.0.1:8888")

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "code": 0,
            "data": {
                "list": [
                    {
                        "id": 2413,
                        "asset": "SOLUSDT",
                        # 缺少 deleted 字段！
                        "updated_at": "2026-07-08T06:00:00+08:00",
                    },
                ]
            },
            "message": "success"
        }).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("strategy_core.factory_client.urllib.request.urlopen", return_value=mock_response):
            is_open, position_detail = client.is_position_open("OBVATR_4H_2", "6", "SOLUSDT")

        # Deleted 缺失时无法判断，返回 (None, None)
        assert is_open is None
        assert position_detail is None

    def test_is_position_open_empty_list_returns_none(self):
        """
        无仓位记录时返回 (None, None)，不清理本地状态

        场景：
        - API 返回空列表
        - 本地有持仓，但远程无记录（可能信号未执行）

        期望：返回 (None, None)，表示无法判断，保持本地状态
        """
        client = FactoryClient(factory_endpoint="http://127.0.0.1:8888")

        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "code": 0,
            "data": {"list": []},
            "message": "success"
        }).encode("utf-8")
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("strategy_core.factory_client.urllib.request.urlopen", return_value=mock_response):
            is_open, position_detail = client.is_position_open("RBREAKER_15M_3_SOLUSDT", "12", "SOLUSDT")

        # 无仓位记录 → 无法判断（返回 None）
        assert is_open is None
        assert position_detail is None
