# NOTE: IP addresses in this test are mock values, not real endpoints
#!/usr/bin/env python3
"""
测试 FactoryClient — 与 cta_factory_service 的通信封装
"""

import json
import random
import threading
import time
import urllib.error
import urllib.request
from unittest.mock import MagicMock, patch
from xmlrpc.server import SimpleXMLRPCServer

import pytest

from strategy_core.factory_client import FactoryClient


class MockFactoryService:
    """模拟 cta_factory_service 的 XML-RPC 服务器"""

    def __init__(self, host: str = "127.0.0.1", port: int = 18888):
        self.host = host
        self.port = port
        self.server = None
        self._strategies: dict = {}
        self._thread = None

    def rpc_register(self, config: dict) -> dict:
        """新格式：只接收一个 JSON 参数"""
        strategy_id = config.get("strategy_id")
        if not strategy_id:
            return {"status": "error", "message": "缺少 strategy_id"}
        self._strategies[strategy_id] = {
            "config": config,
            "status": "registered",
        }
        return {"status": "success", "strategy_id": strategy_id}

    def rpc_start(self, strategy_id: str, params: dict = None) -> dict:
        if strategy_id not in self._strategies:
            return {"status": "error", "message": f"策略 {strategy_id} 未注册"}
        self._strategies[strategy_id]["status"] = "running"
        return {"status": "success", "message": f"策略 {strategy_id} 已启动"}

    def rpc_stop(self, strategy_id: str) -> dict:
        if strategy_id in self._strategies:
            self._strategies[strategy_id]["status"] = "stopped"
        return {"status": "success", "message": f"策略 {strategy_id} 已停止"}

    def rpc_status(self, strategy_id: str = None) -> dict:
        if strategy_id:
            if strategy_id not in self._strategies:
                return {"status": "info", "message": f"策略 {strategy_id} 未注册"}
            info = self._strategies[strategy_id]
            return {
                "status": "success",
                "strategy_id": strategy_id,
                "running": info.get("status") == "running",
                "info": info,
            }
        return {
            "status": "success",
            "strategies": {
                name: {"status": info.get("status"), "info": info}
                for name, info in self._strategies.items()
            },
        }

    def start(self):
        self.server = SimpleXMLRPCServer(
            (self.host, self.port),
            allow_none=True,
            logRequests=False,
        )
        self.server.timeout = 0.5
        self.server.register_function(self.rpc_register, "register")
        self.server.register_function(self.rpc_start, "start")
        self.server.register_function(self.rpc_stop, "stop")
        self.server.register_function(self.rpc_status, "status")
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while self.server:
            try:
                self.server.handle_request()
            except Exception:
                break

    def stop(self):
        self.server = None


@pytest.fixture(scope="function")
def mock_factory_with_port():
    """创建模拟 factory service，返回 factory 和端口号"""
    # 使用时间戳确保端口唯一性
    import socket
    base_port = random.randint(19000, 19999)
    for attempt in range(10):
        port = base_port + attempt
        try:
            # 检查端口是否可用
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
            # 端口可用，创建服务
            factory = MockFactoryService(port=port)
            factory.start()
            time.sleep(0.2)
            yield factory, port
            factory.stop()
            return
        except OSError:
            continue
    pytest.fail("无法找到可用端口")


class TestFactoryClientInit:
    """测试 FactoryClient 初始化"""

    def test_init_with_endpoint(self, mock_factory_with_port):
        factory, port = mock_factory_with_port
        client = FactoryClient(
            factory_endpoint=f"http://127.0.0.1:{port}",
            callback_url="http://127.0.0.1:8892",
        )
        assert client.factory_endpoint == f"http://127.0.0.1:{port}"

    def test_init_without_factory(self):
        client = FactoryClient(
            factory_endpoint="http://127.0.0.1:9999",
            callback_url="http://127.0.0.1:8892",
        )
        assert client.factory_endpoint == "http://127.0.0.1:9999"


class TestFactoryClientRegister:
    """测试注册策略"""

    def test_register_success(self, mock_factory_with_port):
        factory, port = mock_factory_with_port
        client = FactoryClient(
            factory_endpoint=f"http://127.0.0.1:{port}",
            callback_url="http://127.0.0.1:8892",
        )
        result = client.register({"strategy_id": "cta_rbreaker_001", "symbol": "BTCUSDT"})
        assert result["status"] == "success"

    def test_register_already_exists(self, mock_factory_with_port):
        factory, port = mock_factory_with_port
        client = FactoryClient(
            factory_endpoint=f"http://127.0.0.1:{port}",
            callback_url="http://127.0.0.1:8892",
        )
        client.register({"strategy_id": "cta_rbreaker_001"})
        result = client.register({"strategy_id": "cta_rbreaker_001"})
        assert result["status"] in ("success", "info")

    def test_register_factory_unreachable(self):
        client = FactoryClient(
            factory_endpoint="http://127.0.0.1:9999",
            callback_url="http://127.0.0.1:8892",
        )
        result = client.register({"strategy_id": "cta_rbreaker_001"})
        assert result["status"] == "error"


class TestFactoryClientQueryStatus:
    """测试查询策略状态"""

    def test_query_registered_strategy(self, mock_factory_with_port):
        factory, port = mock_factory_with_port
        client = FactoryClient(
            factory_endpoint=f"http://127.0.0.1:{port}",
            callback_url="http://127.0.0.1:8892",
        )
        client.register({"strategy_id": "cta_rbreaker_001"})
        status = client.query_status("cta_rbreaker_001")
        assert status["status"] == "success"
        assert status["running"] == False

    def test_query_running_strategy(self, mock_factory_with_port):
        factory, port = mock_factory_with_port
        client = FactoryClient(
            factory_endpoint=f"http://127.0.0.1:{port}",
            callback_url="http://127.0.0.1:8892",
        )
        client.register({"strategy_id": "cta_rbreaker_001"})
        factory.rpc_start("cta_rbreaker_001")
        status = client.query_status("cta_rbreaker_001")
        assert status["running"] == True

    def test_query_unregistered_strategy(self, mock_factory_with_port):
        factory, port = mock_factory_with_port
        client = FactoryClient(
            factory_endpoint=f"http://127.0.0.1:{port}",
            callback_url="http://127.0.0.1:8892",
        )
        status = client.query_status("unknown_strategy")
        assert status["status"] == "info"

    def test_query_factory_unreachable(self):
        client = FactoryClient(
            factory_endpoint="http://127.0.0.1:9999",
            callback_url="http://127.0.0.1:8892",
        )
        status = client.query_status("cta_rbreaker_001")
        assert status["status"] == "error"


class TestFactoryClientReportStatus:
    """测试心跳上报"""

    def test_report_running_status(self, mock_factory_with_port):
        factory, port = mock_factory_with_port
        client = FactoryClient(
            factory_endpoint=f"http://127.0.0.1:{port}",
            callback_url="http://127.0.0.1:8892",
        )
        client.register({"strategy_id": "cta_rbreaker_001"})
        ok = client.report_status("cta_rbreaker_001", "running")
        assert ok == True

    def test_report_stopped_status(self, mock_factory_with_port):
        factory, port = mock_factory_with_port
        client = FactoryClient(
            factory_endpoint=f"http://127.0.0.1:{port}",
            callback_url="http://127.0.0.1:8892",
        )
        client.register({"strategy_id": "cta_rbreaker_001"})
        ok = client.report_status("cta_rbreaker_001", "stopped")
        assert ok == True

    def test_report_factory_unreachable(self):
        client = FactoryClient(
            factory_endpoint="http://127.0.0.1:9999",
            callback_url="http://127.0.0.1:8892",
        )
        ok = client.report_status("cta_rbreaker_001", "running")
        assert ok == False


class TestFactoryClientCallbackServer:
    """测试回调服务器"""

    def test_start_callback_server(self):
        port = random.randint(29000, 29999)
        client = FactoryClient(
            factory_endpoint="http://127.0.0.1:8888",
            callback_url=f"http://127.0.0.1:{port}",
        )
        client.start_callback_server(port=port)
        time.sleep(0.3)
        assert client._callback_server is not None
        client.stop_callback_server()

    def test_callback_handler_receives_start(self, mock_factory_with_port):
        factory, factory_port = mock_factory_with_port
        callback_port = random.randint(29000, 29999)

        mock_engine = MagicMock()
        mock_engine.start_strategy = MagicMock(return_value=True)

        client = FactoryClient(
            factory_endpoint=f"http://127.0.0.1:{factory_port}",
            callback_url=f"http://127.0.0.1:{callback_port}",
            engine=mock_engine,
        )
        client.start_callback_server(port=callback_port)
        time.sleep(0.3)

        import xmlrpc.client
        proxy = xmlrpc.client.ServerProxy(f"http://127.0.0.1:{callback_port}", allow_none=True)
        result = proxy.on_strategy_start("cta_rbreaker_001")

        assert result["status"] == "success"
        mock_engine.start_strategy.assert_called_once_with("cta_rbreaker_001")
        client.stop_callback_server()

    def test_callback_handler_receives_stop(self, mock_factory_with_port):
        factory, factory_port = mock_factory_with_port
        callback_port = random.randint(29000, 29999)

        mock_engine = MagicMock()
        mock_engine.stop_strategy = MagicMock(return_value=True)

        client = FactoryClient(
            factory_endpoint=f"http://127.0.0.1:{factory_port}",
            callback_url=f"http://127.0.0.1:{callback_port}",
            engine=mock_engine,
        )
        client.start_callback_server(port=callback_port)
        time.sleep(0.3)

        import xmlrpc.client
        proxy = xmlrpc.client.ServerProxy(f"http://127.0.0.1:{callback_port}", allow_none=True)
        result = proxy.on_strategy_stop("cta_rbreaker_001")

        assert result["status"] == "success"
        mock_engine.stop_strategy.assert_called_once_with("cta_rbreaker_001")
        client.stop_callback_server()


class TestFactoryClientQueryPositions:
    """测试仓位查询 - API 响应格式转换"""

    @pytest.fixture
    def position_client(self):
        """创建用于仓位查询测试的 client"""
        return FactoryClient(
            factory_endpoint="http://127.0.0.1:8888",
            callback_url="http://127.0.0.1:8892",
            position_proxy_url="http://127.0.0.1:8889",
        )

    def _mock_api_response(self, response_data):
        """Mock urlopen 返回指定响应"""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)

        return patch.object(urllib.request, "urlopen", return_value=mock_resp)

    def test_query_positions_converts_code_to_status(self, position_client):
        """API 返回 code: 0 应转换为 status: success"""
        mock_response = {
            "code": 0,
            "message": "success",
            "data": {"list": [{"ID": 18263, "Deleted": 1, "Asset": "BTCUSDT"}]},
        }

        with self._mock_api_response(mock_response):
            result = position_client.query_order_positions("strategy_001", "6", "BTCUSDT")

        assert result["status"] == "success"
        assert "list" in result["data"]

    def test_is_position_open_returns_false_for_closed_positions(self, position_client):
        """所有仓位 Deleted: 1 应返回 (False, latest_position)"""
        mock_response = {
            "code": 0,
            "message": "success",
            "data": {
                "list": [
                    {"ID": 18263, "Deleted": 1, "Asset": "BTCUSDT", "UpdatedAt": "2026-06-16T22:31:49+08:00"},
                    {"ID": 18276, "Deleted": 1, "Asset": "BTCUSDT", "UpdatedAt": "2026-06-23T13:24:09+08:00"},
                ]
            },
        }

        with self._mock_api_response(mock_response):
            result = position_client.is_position_open("strategy_001", "6", "BTCUSDT")

        assert result == (False, {'Asset': 'BTCUSDT', 'Deleted': 1, 'ID': 18276, 'UpdatedAt': '2026-06-23T13:24:09+08:00'})

    def test_is_position_open_returns_true_for_open_position(self, position_client):
        """存在 Deleted: 0 的仓位应返回 (True, position_detail)"""
        mock_response = {
            "code": 0,
            "message": "success",
            "data": {
                "list": [
                    {"ID": 18277, "Deleted": 0, "Asset": "BTCUSDT", "UpdatedAt": "2026-06-24T10:00:00+08:00"},
                ]
            },
        }

        with self._mock_api_response(mock_response):
            result = position_client.is_position_open("strategy_001", "6", "BTCUSDT")

        assert result == (True, {'Asset': 'BTCUSDT', 'Deleted': 0, 'ID': 18277, 'UpdatedAt': '2026-06-24T10:00:00+08:00'})

    def test_is_position_open_returns_none_on_api_error(self, position_client):
        """API 返回非 0 code 应返回 None"""
        mock_response = {"code": 500, "message": "internal error", "data": None}

        with self._mock_api_response(mock_response):
            result = position_client.is_position_open("strategy_001", "6", "BTCUSDT")

        assert result == (None, None)

    def test_is_position_open_returns_false_for_empty_list(self, position_client):
        """API 返回空列表应返回 (None, None) - 无法判断仓位状态"""
        mock_response = {"code": 0, "message": "success", "data": {"list": []}}

        with self._mock_api_response(mock_response):
            result = position_client.is_position_open("strategy_001", "6", "BTCUSDT")

        assert result == (None, None)

    def test_is_position_open_returns_none_on_network_timeout(self, position_client):
        """网络超时应返回 None"""
        with patch.object(urllib.request, "urlopen", side_effect=urllib.error.URLError("timeout")):
            result = position_client.is_position_open("strategy_001", "6", "BTCUSDT")

        assert result == (None, None)

    def test_is_position_open_returns_none_on_http_error(self, position_client):
        """HTTP 错误（如 404/500）应返回 None"""
        mock_error = urllib.error.HTTPError("http://example.com", 404, "Not Found", {}, MagicMock())
        mock_error.fp = None

        with patch.object(urllib.request, "urlopen", side_effect=mock_error):
            result = position_client.is_position_open("strategy_001", "6", "BTCUSDT")

        assert result == (None, None)

    def test_query_positions_handles_missing_data_field(self, position_client):
        """API 返回缺少 data 字段时应返回空 data"""
        mock_response = {"code": 0, "message": "success"}

        with self._mock_api_response(mock_response):
            result = position_client.query_order_positions("strategy_001", "6", "BTCUSDT")

        assert result["status"] == "success"
        assert result["data"] == {}

    def test_is_position_open_with_mixed_positions(self, position_client):
        """混合开仓和已平仓仓位应返回 (True, open_position)"""
        mock_response = {
            "code": 0,
            "message": "success",
            "data": {
                "list": [
                    {"ID": 18263, "Deleted": 1, "UpdatedAt": "2026-06-16T22:31:49+08:00"},
                    {"ID": 18277, "Deleted": 0, "UpdatedAt": "2026-06-24T10:00:00+08:00"},
                    {"ID": 18276, "Deleted": 1, "UpdatedAt": "2026-06-23T13:24:09+08:00"},
                ]
            },
        }

        with self._mock_api_response(mock_response):
            result = position_client.is_position_open("strategy_001", "6", "BTCUSDT")

        assert result == (True, {'Deleted': 0, 'ID': 18277, 'UpdatedAt': '2026-06-24T10:00:00+08:00'})