"""
FactoryClient — 与 cta_factory_service 的通信封装

职责：
- 注册策略到 factory
- 查询策略上次状态
- 上报策略状态（心跳）
- 接收 factory 的控制回调（start/stop/pause/resume）
- 查询远程仓位状态
"""

import json
import logging
import re
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Optional, Set, Tuple
from xmlrpc.server import SimpleXMLRPCServer
import xmlrpc.client

logger = logging.getLogger(__name__)

# 策略进程启动命令
STRATEGY_PROCESS_CMD = [sys.executable, str(Path(__file__).parent.parent / "run_strategy.py")]


class FactoryClient:
    """
    与 cta_factory_service 的通信封装

    封装两类通信：
    1. 主动 RPC（strategy-code → factory）：register, query_status, report_status
    2. 被动回调（factory → strategy-code）：on_strategy_start/stop/pause/resume
    3. 仓位查询（HTTP → Position 代理）
    """

    @staticmethod
    def _get_field(item: dict, field_name: str):
        """
        获取字典字段值，兼容大小写和命名风格

        支持的命名风格：
        - 原样：UpdatedBy
        - 全小写：updatedby
        - 全大写：UPDATEDBY
        - 蛇形（驼峰转下划线）：updated_by

        Args:
            item: 字典对象
            field_name: 字段名（驼峰或帕斯卡命名）

        Returns:
            字段值，不存在则返回 None
        """
        if field_name in item:
            return item[field_name]

        # 全小写
        lower_key = field_name.lower()
        if lower_key in item:
            return item[lower_key]

        # 全大写
        upper_key = field_name.upper()
        if upper_key in item:
            return item[upper_key]

        # 驼峰转蛇形（UpdatedAt → updated_at）
        snake_key = re.sub(r'([A-Z])', r'_\1', field_name).lower().lstrip('_')
        if snake_key in item:
            return item[snake_key]

        return None

    def __init__(
        self,
        factory_endpoint: str = "http://127.0.0.1:8888",
        callback_url: str = "http://127.0.0.1:8892",
        engine: Optional[Any] = None,
        global_config_path: str = "config/settings.yaml",
        log_level: str = "INFO",
        position_proxy_url: str = "http://127.0.0.1:8889",
        position_api_path: str = "/api/position/user-order-positions",
    ):
        """
        初始化 FactoryClient

        Args:
            factory_endpoint: factory RPC 地址
            callback_url: 本地回调地址（用于接收 factory 控制）
            engine: StrategyEngine 实例（用于执行回调指令）
            global_config_path: 全局配置路径（用于启动子进程）
            log_level: 日志级别（用于启动子进程）
            position_proxy_url: Position 代理地址（端口 8889）
            position_api_path: 仓位查询 API 路径（默认 /api/position/user-order-positions）
        """
        self.factory_endpoint = factory_endpoint
        self.callback_url = callback_url
        self.engine = engine
        self.global_config_path = global_config_path
        self.log_level = log_level
        self.position_proxy_url = position_proxy_url
        self.position_api_path = position_api_path

        self._callback_server: Optional[SimpleXMLRPCServer] = None
        self._callback_thread: Optional[threading.Thread] = None
        self._factory_proxy: Optional[xmlrpc.client.ServerProxy] = None

        # 子进程管理
        self._subprocesses: Dict[str, subprocess.Popen] = {}
        self._strategy_configs: Dict[str, Dict[str, Any]] = {}

    def _get_factory_proxy(self) -> xmlrpc.client.ServerProxy:
        """获取 factory RPC 代理（延迟创建）"""
        if self._factory_proxy is None:
            self._factory_proxy = xmlrpc.client.ServerProxy(
                self.factory_endpoint,
                allow_none=True,
            )
        return self._factory_proxy

    # ========== 主动 RPC（strategy-code → factory）==========

    def register(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """
        注册策略到 factory

        Args:
            config: 策略配置字典，必须包含 strategy_id，其他字段可选：
                - strategy_id: 策略唯一 ID（必须）
                - name: 策略目录名
                - interval: 时间周期
                - version: 版本
                - symbol: 交易对
                - trading_mode: 运行模式
                - script: 策略脚本路径
                - user_id: 用户 ID
                - ... 其他任意字段

        Returns:
            factory 返回结果
        """
        strategy_id = config.get("strategy_id")
        if not strategy_id:
            return {"status": "error", "message": "缺少 strategy_id"}

        # 保存配置到本地
        self._strategy_configs[strategy_id] = config.copy()

        try:
            proxy = self._get_factory_proxy()
            # XML-RPC 只传一个 JSON 参数
            result = proxy.register(config)
            logger.info(f"策略 {strategy_id} 注册成功")
            return result
        except Exception as e:
            logger.warning(f"注册策略 {strategy_id} 失败: {e}")
            return {"status": "error", "message": str(e)}

    def query_status(self, strategy_id: str) -> Dict[str, Any]:
        """
        查询策略在 factory 中的状态

        Args:
            strategy_id: 策略 ID

        Returns:
            状态信息
        """
        try:
            proxy = self._get_factory_proxy()
            result = proxy.status(strategy_id)
            return result
        except Exception as e:
            logger.warning(f"查询策略 {strategy_id} 状态失败: {e}")
            return {"status": "error", "message": str(e)}

    def report_status(
        self,
        strategy_id: str,
        status: str,
    ) -> bool:
        """
        上报策略状态（心跳）

        Args:
            strategy_id: 策略 ID
            status: 状态 (running/stopped/paused)

        Returns:
            是否成功
        """
        try:
            proxy = self._get_factory_proxy()
            # factory 目前没有专门的 report 接口
            # 通过 status 方法查询确认状态一致
            current = proxy.status(strategy_id)
            if current.get("status") == "success":
                logger.debug(f"策略 {strategy_id} 状态上报: {status}")
                return True
            return False
        except Exception as e:
            logger.warning(f"上报策略 {strategy_id} 状态失败: {e}")
            return False

    def request_start(self, strategy_id: str) -> Dict[str, Any]:
        """
        请求 factory 启动策略（仅用于恢复上次状态）

        Args:
            strategy_id: 策略 ID

        Returns:
            factory 返回结果
        """
        try:
            proxy = self._get_factory_proxy()
            result = proxy.start(strategy_id)
            logger.info(f"请求启动策略 {strategy_id}: {result}")
            return result
        except Exception as e:
            logger.warning(f"请求启动策略 {strategy_id} 失败: {e}")
            return {"status": "error", "message": str(e)}

    def request_stop(self, strategy_id: str) -> Dict[str, Any]:
        """
        请求 factory 停止策略（更新状态为 stopped）

        Args:
            strategy_id: 策略 ID

        Returns:
            factory 返回结果
        """
        try:
            proxy = self._get_factory_proxy()
            result = proxy.stop(strategy_id)
            logger.info(f"请求停止策略 {strategy_id}: {result}")
            return result
        except Exception as e:
            logger.warning(f"请求停止策略 {strategy_id} 失败: {e}")
            return {"status": "error", "message": str(e)}

    def update_pid(self, strategy_id: str, pid: int) -> bool:
        """
        更新策略进程 PID

        Args:
            strategy_id: 策略 ID
            pid: 进程 ID

        Returns:
            是否成功
        """
        # 保存到本地配置
        if strategy_id in self._strategy_configs:
            self._strategy_configs[strategy_id]["pid"] = pid
        logger.debug(f"策略 {strategy_id} PID 更新: {pid}")
        return True

    # ========== 被动回调（factory → strategy-code）==========

    def start_callback_server(self, host: str = "0.0.0.0", port: int = 8892) -> None:
        """
        启动回调服务器

        接收 factory 发送的控制指令：
        - on_strategy_start(strategy_id)
        - on_strategy_stop(strategy_id)
        - on_strategy_pause(strategy_id)
        - on_strategy_resume(strategy_id)
        """
        if self._callback_server is not None:
            logger.warning("回调服务器已在运行")
            return

        self._callback_server = SimpleXMLRPCServer(
            (host, port),
            allow_none=True,
            logRequests=False,
        )
        self._callback_server.timeout = 1.0

        # 注册回调方法
        self._callback_server.register_function(
            self._on_strategy_start, "on_strategy_start"
        )
        self._callback_server.register_function(
            self._on_strategy_stop, "on_strategy_stop"
        )
        self._callback_server.register_function(
            self._on_strategy_pause, "on_strategy_pause"
        )
        self._callback_server.register_function(
            self._on_strategy_resume, "on_strategy_resume"
        )
        # 兼容 factory 的通用状态变更通知
        self._callback_server.register_function(
            self._on_factory_state_change, "on_factory_state_change"
        )

        # 在后台线程运行
        self._callback_thread = threading.Thread(
            target=self._serve_callback,
            daemon=True,
        )
        self._callback_thread.start()

        logger.info(f"回调服务器已启动，监听端口 {port}")

    def _serve_callback(self) -> None:
        """回调服务器主循环"""
        while self._callback_server:
            try:
                self._callback_server.handle_request()
            except Exception:
                break

    def stop_callback_server(self) -> None:
        """停止回调服务器"""
        if self._callback_server:
            self._callback_server = None
            logger.info("回调服务器已停止")

    def _on_strategy_start(self, strategy_id: str) -> Dict[str, Any]:
        """回调：启动策略"""
        logger.info(f"收到 factory 启动指令: {strategy_id}")

        # 优先使用 engine（单进程模式）
        if self.engine:
            try:
                success = self.engine.start_strategy(strategy_id)
                if success:
                    return {"status": "success", "message": f"策略 {strategy_id} 已启动"}
                else:
                    return {"status": "error", "message": f"策略 {strategy_id} 启动失败"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        # 多进程模式：启动子进程
        # 检查是否已在运行
        if strategy_id in self._subprocesses:
            proc = self._subprocesses[strategy_id]
            if proc.poll() is None:
                logger.warning(f"策略 {strategy_id} 已在运行 (PID: {proc.pid})")
                return {"status": "success", "message": f"策略 {strategy_id} 已在运行", "pid": proc.pid}

        # 从保存的配置中获取完整参数
        config = self._strategy_configs.get(strategy_id, {})

        # 构建启动命令（新格式）
        try:
            if config.get("symbol"):
                # 新格式：使用 --name --symbol --interval --version --trading-mode
                cmd = [
                    *STRATEGY_PROCESS_CMD,
                    "--name", config.get("name", strategy_id.split("_")[0].lower()),
                    "--symbol", config["symbol"],
                    "--interval", config.get("interval", "4h"),
                    "--version", config.get("version", "v2"),
                    "--trading-mode", config.get("trading_mode", "live"),
                    "--global-config", self.global_config_path,
                    "--log-level", self.log_level,
                ]
                # 添加配置文件路径（如果指定）
                if config.get("config_path"):
                    cmd.extend(["--config-path", config["config_path"]])
            else:
                # 旧格式兼容
                strategy_name = strategy_id.rsplit("_", 1)[0] if "_" in strategy_id else strategy_id
                cmd = [
                    *STRATEGY_PROCESS_CMD,
                    "--strategy", strategy_name,
                    "--global-config", self.global_config_path,
                    "--log-level", self.log_level,
                ]

            logger.info(f"启动策略子进程: {' '.join(cmd)}")

            # 启动子进程（不再重定向 stdout/stderr，由 Python 日志系统处理）
            proc = subprocess.Popen(cmd)
            self._subprocesses[strategy_id] = proc

            # 保存 PID 到配置
            config["pid"] = proc.pid
            self._strategy_configs[strategy_id] = config

            logger.info(f"策略 {strategy_id} 子进程已启动 (PID: {proc.pid})")
            return {"status": "success", "message": f"策略 {strategy_id} 已启动", "pid": proc.pid}
        except Exception as e:
            logger.error(f"启动策略 {strategy_id} 子进程失败: {e}")
            return {"status": "error", "message": str(e)}

    def _on_strategy_stop(self, strategy_id: str) -> Dict[str, Any]:
        """回调：停止策略"""
        logger.info(f"收到 factory 停止指令: {strategy_id}")

        # 优先使用 engine（单进程模式）
        if self.engine:
            try:
                success = self.engine.stop_strategy(strategy_id)
                if success:
                    return {"status": "success", "message": f"策略 {strategy_id} 已停止"}
                else:
                    return {"status": "error", "message": f"策略 {strategy_id} 停止失败"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        # 多进程模式：停止子进程
        if strategy_id not in self._subprocesses:
            return {"status": "warning", "message": f"策略 {strategy_id} 未在运行"}

        proc = self._subprocesses[strategy_id]
        old_pid = proc.pid

        if proc.poll() is not None:
            # 进程已退出
            del self._subprocesses[strategy_id]
            # 清理配置中的 PID
            if strategy_id in self._strategy_configs:
                self._strategy_configs[strategy_id].pop("pid", None)
            return {"status": "success", "message": f"策略 {strategy_id} 已停止"}

        try:
            # 发送 SIGTERM（优雅停止，触发 on_stop 回调）
            logger.info(f"发送 SIGTERM 到策略 {strategy_id} (PID: {old_pid})")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # 超时后强制终止
                logger.warning(f"策略 {strategy_id} 未响应 SIGTERM，发送 SIGKILL")
                proc.kill()
                proc.wait()

            del self._subprocesses[strategy_id]
            # 清理配置中的 PID
            if strategy_id in self._strategy_configs:
                self._strategy_configs[strategy_id].pop("pid", None)

            logger.info(f"策略 {strategy_id} 子进程已停止")
            return {"status": "success", "message": f"策略 {strategy_id} 已停止", "pid": old_pid}
        except Exception as e:
            logger.error(f"停止策略 {strategy_id} 子进程失败: {e}")
            return {"status": "error", "message": str(e)}

    def _on_strategy_pause(self, strategy_id: str) -> Dict[str, Any]:
        """回调：暂停策略"""
        logger.info(f"收到 factory 暂停指令: {strategy_id}")

        # 优先使用 engine（单进程模式）
        if self.engine:
            try:
                success = self.engine.pause_strategy(strategy_id)
                if success:
                    return {"status": "success", "message": f"策略 {strategy_id} 已暂停"}
                else:
                    return {"status": "error", "message": f"策略 {strategy_id} 暂停失败"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        # 多进程模式：暂停通过发送 SIGUSR1 信号（如果策略支持）
        if strategy_id not in self._subprocesses:
            return {"status": "warning", "message": f"策略 {strategy_id} 未在运行"}

        proc = self._subprocesses[strategy_id]
        if proc.poll() is not None:
            return {"status": "warning", "message": f"策略 {strategy_id} 已停止"}

        # 暂不支持子进程暂停，返回警告
        return {"status": "warning", "message": "子进程模式暂不支持暂停"}

    def _on_strategy_resume(self, strategy_id: str) -> Dict[str, Any]:
        """回调：恢复策略"""
        logger.info(f"收到 factory 恢复指令: {strategy_id}")

        # 优先使用 engine（单进程模式）
        if self.engine:
            try:
                success = self.engine.resume_strategy(strategy_id)
                if success:
                    return {"status": "success", "message": f"策略 {strategy_id} 已恢复"}
                else:
                    return {"status": "error", "message": f"策略 {strategy_id} 恢复失败"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

        # 多进程模式：恢复通过发送 SIGUSR2 信号（如果策略支持）
        if strategy_id not in self._subprocesses:
            return {"status": "warning", "message": f"策略 {strategy_id} 未在运行"}

        proc = self._subprocesses[strategy_id]
        if proc.poll() is not None:
            return {"status": "warning", "message": f"策略 {strategy_id} 已停止"}

        # 暂不支持子进程恢复，返回警告
        return {"status": "warning", "message": "子进程模式暂不支持恢复"}

    def _on_factory_state_change(self, strategy_id: str, state: str) -> Dict[str, Any]:
        """
        回调：factory 状态变更通知（通用接口）

        Factory 调用此方法通知状态变更，state 可能是：
        - 'running': 策略已启动
        - 'stopped': 策略已停止
        - 'paused': 策略已暂停
        - 'resumed': 策略已恢复

        Args:
            strategy_id: 策略 ID
            state: 新状态

        Returns:
            处理结果
        """
        logger.info(f"收到 factory 状态变更通知: {strategy_id} -> {state}")

        # 根据状态调用对应的处理方法
        if state == "running":
            return self._on_strategy_start(strategy_id)
        elif state == "stopped":
            return self._on_strategy_stop(strategy_id)
        elif state == "paused":
            return self._on_strategy_pause(strategy_id)
        elif state == "resumed":
            return self._on_strategy_resume(strategy_id)
        else:
            logger.warning(f"未知状态: {state}")
            return {"status": "warning", "message": f"未知状态: {state}"}

    def get_running_strategies(self) -> Set[str]:
        """获取当前运行的策略 ID 集合"""
        running = set()
        for strategy_id, proc in list(self._subprocesses.items()):
            if proc.poll() is None:
                running.add(strategy_id)
            else:
                # 清理已退出的进程
                del self._subprocesses[strategy_id]
        return running

    def stop_all_subprocesses(self) -> None:
        """停止所有子进程"""
        for strategy_id, proc in list(self._subprocesses.items()):
            if proc.poll() is None:
                logger.info(f"停止策略 {strategy_id} 子进程 (PID: {proc.pid})")
                try:
                    proc.terminate()
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                except Exception as e:
                    logger.warning(f"停止策略 {strategy_id} 失败: {e}")
        self._subprocesses.clear()

    # ========== 仓位查询接口（HTTP → Position 代理）==========

    def query_order_positions(
        self,
        strategy_name: str,
        user_id: str,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        查询子仓位列表

        Args:
            strategy_name: 策略名称
            user_id: 用户 ID
            symbol: 可选的交易对过滤

        Returns:
            仓位列表响应
        """
        query_params = {
            "strategy_name": strategy_name,
            "user_id": user_id,
        }
        if symbol:
            query_params["symbol"] = symbol

        encoded_params = urllib.parse.urlencode(query_params)
        url = f"{self.position_proxy_url}{self.position_api_path}?{encoded_params}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                data = json.loads(body)
                # 统一响应格式：
                # - 旧格式: {"status": "success", "data": {...}}
                # - 新格式: {"code": 0, "data": {...}}
                if data.get("status") == "success" or data.get("code") == 0:
                    return {"status": "success", "data": data.get("data", {})}
                return {"status": "error", "message": data.get("message", "Unknown error")}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8") if e.fp else ""
            logger.warning(f"查询子仓位失败 (HTTP {e.code}): {body}")
            return {"status": "error", "message": f"HTTP {e.code}: {body}"}
        except Exception as e:
            logger.warning(f"查询子仓位失败: {e}")
            return {"status": "error", "message": str(e)}

    def is_position_open(
        self,
        strategy_name: str,
        user_id: str,
        symbol: Optional[str] = None,
    ) -> Tuple[Optional[bool], Optional[Dict[str, Any]]]:
        """
        判断是否有开启的仓位

        Args:
            strategy_name: 策略名称
            user_id: 用户 ID
            symbol: 可选的交易对过滤

        Returns:
            Tuple[Optional[bool], Optional[Dict]]:
            - (True, dict): 有开启仓位，返回最新仓位详情
            - (False, dict): 所有仓位已关闭，返回最新仓位详情
            - (None, None): 无仓位记录或查询失败（无法判断）
        """
        result = self.query_order_positions(strategy_name, user_id, symbol)

        if result.get("status") != "success":
            logger.warning(
                f"[is_position_open] 查询失败: strategy_name={strategy_name}, "
                f"user_id={user_id}, symbol={symbol}, result={result}"
            )
            return None, None

        items = result.get("data", {}).get("list", [])
        if not items:
            # 无仓位记录 → 无法判断（可能信号未执行），不清理本地状态
            logger.info(
                f"[is_position_open] 无仓位记录: strategy_name={strategy_name}, "
                f"user_id={user_id}, symbol={symbol}"
            )
            return None, None

        # 按 UpdatedAt 排序，取最新一条仓位
        latest = max(items, key=lambda x: self._get_field(x, "UpdatedAt") or "")
        deleted = self._get_field(latest, "Deleted")

        # Deleted 字段缺失时无法判断
        if deleted is None:
            logger.warning(
                f"[is_position_open] Deleted 字段缺失，无法判断仓位状态: "
                f"strategy_name={strategy_name}, item={latest}"
            )
            return None, None

        # 根据最新仓位的 deleted 字段判断状态
        status = "开启" if deleted == 0 else "已关闭"
        close_time_val = self._get_field(latest, "CloseTime")
        close_time = f", CloseTime={close_time_val}" if deleted == 1 and close_time_val else ""

        logger.info(
            f"[is_position_open] 检测到{status}仓位: strategy_name={strategy_name}, "
            f"user_id={user_id}, symbol={symbol} | "
            f"最新仓位: ID={self._get_field(latest, 'ID')}, Side={self._get_field(latest, 'Side')}, "
            f"EntryPrice={self._get_field(latest, 'EntryPrice')}, Quantity={self._get_field(latest, 'Quantity')}, "
            f"OpenTime={self._get_field(latest, 'OpenTime')}{close_time}, Deleted={deleted}"
        )

        # deleted=0 → 有开启仓位
        # deleted=1 → 已平仓
        return deleted == 0, latest