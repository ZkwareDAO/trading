#!/usr/bin/env python3
"""
批量回测执行器 - 通过 subprocess 调用 run_backtest.py

功能：
- 从 strategies.yaml 或 main.yaml 读取全局配置
- 自动组合 config_path
- 并发执行多个回测任务
- 支持后台运行模式

配置文件支持：
- 新格式（推荐）: config/strategies.yaml - 统一配置
- 旧格式（兼容）: backtest/config/main.yaml - 回测专用
"""

import argparse
import json
import logging
import os
import platform
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from backtest.config_loader import (
    build_config_path,
    load_main_config,
    resolve_config_path,
    resolve_strategy_config_path,
)
from strategy_core.utils.strategies_loader import StrategiesLoader
from strategy_core.utils.log_handlers import DailyDirectoryFileHandler

logger = logging.getLogger(__name__)

# 回测配置文件路径（可通过环境变量覆盖）
DEFAULT_BACKTEST_CONFIG_PATH = os.environ.get(
    "BACKTEST_CONFIG_PATH", "backtest/config/main.yaml"
)


class BatchBacktestRunner:
    """并发回测执行器 - 通过 subprocess 调用 run_backtest.py

    支持两种配置格式：
    1. 新格式: config/strategies.yaml（推荐）
    2. 旧格式: backtest/config/main.yaml（兼容）
    """

    def __init__(
        self,
        config_path: str = "backtest/config/strategies.yaml",
        start_override: str | None = None,
        end_override: str | None = None,
        use_strategies_config: bool | None = None,
        backtest_config_path: str | None = None,
    ):
        """
        初始化执行器

        Args:
            config_path: 策略配置文件路径（strategies.yaml 或 main.yaml）
            start_override: CLI 覆盖的 start 时间（优先级最高）
            end_override: CLI 覆盖的 end 时间（优先级最高）
            use_strategies_config: 是否使用 strategies.yaml 格式（None=自动检测）
            backtest_config_path: 回测配置文件路径（仅新格式需要）
        """
        self.config_path = config_path
        self.start_override = start_override
        self.end_override = end_override

        # 自动检测格式：检查 strategies 是否为字典（新格式）或列表/不存在（旧格式）
        config_data = load_main_config(config_path)
        self.use_strategies_config = (
            use_strategies_config
            if use_strategies_config is not None
            else isinstance(config_data.get("strategies"), dict)
        )

        if self.use_strategies_config:
            # 新格式：策略从 strategies.yaml，回测配置从 backtest_config_path
            self._loader = StrategiesLoader(config_path).load()
            bt_path = backtest_config_path or DEFAULT_BACKTEST_CONFIG_PATH
            self.main_config = load_main_config(bt_path)
        else:
            # 旧格式：兼容 main.yaml（策略和回测配置在一起）
            self._loader = None
            self.main_config = config_data

        self.config_dir = str(Path(config_path).parent)

    def _build_tasks(self) -> List[Dict]:
        """
        构建任务列表

        新格式：使用 StrategiesLoader 展开策略实例
        旧格式：从 main.yaml 解析策略列表

        Returns:
            任务列表
        """
        if self.use_strategies_config:
            return self._build_tasks_from_loader()
        return self._build_tasks_from_main_yaml()

    def _build_task_dict(
        self,
        strategy: str,
        symbol: str,
        config_path: str,
        overrides: Dict,
    ) -> Dict:
        """构建任务字典（公共逻辑）"""
        return {
            "strategy": strategy,
            "symbol": symbol,
            "start": self.start_override or self.main_config["start"],
            "end": self.end_override or self.main_config.get("end"),
            "data_dir": self.main_config["data_dir"],
            "output_dir": self.main_config["output_dir"],
            "log_level": self.main_config.get("log_level", "INFO"),
            "config_path": config_path,
            "overrides": overrides,
            "use_today_as_output_date": self.main_config.get("use_today_as_output_date", True),
        }

    def _build_tasks_from_loader(self) -> List[Dict]:
        """从 StrategiesLoader 构建任务列表"""
        tasks = []
        for instance in self._loader.filter(enabled_only=True):
            config_path = resolve_config_path(instance.config_path)
            if not Path(config_path).exists():
                logger.warning(f"配置文件不存在: {config_path}，跳过")
                continue
            tasks.append(self._build_task_dict(
                instance.name, instance.symbol, config_path, instance.overrides
            ))
        return tasks

    def _build_tasks_from_main_yaml(self) -> List[Dict]:
        """从 main.yaml 构建任务列表（兼容旧格式）"""
        tasks = []
        global_config_path = self.main_config.get("config_path", "config/strategies")

        for item in self.main_config.get("strategies", []):
            if not item.get("enabled", True):
                continue

            strategy_name = item["name"]
            symbols = item.get("symbols", ["BTCUSDT"])
            strategy_config_path = item.get("config_path")
            overrides = item.get("overrides", {})

            for symbol in symbols:
                # 判断配置模式
                if strategy_config_path or "config_path" in self.main_config:
                    config_path = resolve_strategy_config_path(
                        strategy_name, symbol, global_config_path, strategy_config_path
                    )
                else:
                    config_path = build_config_path(self.config_dir, strategy_name, symbol)

                config_path = resolve_config_path(config_path)
                if not Path(config_path).exists():
                    logger.warning(f"配置文件不存在: {config_path}，跳过")
                    continue

                tasks.append(self._build_task_dict(
                    strategy_name, symbol, config_path, overrides
                ))

        return tasks

    def _run_single(self, task: Dict) -> subprocess.CompletedProcess:
        """
        执行单个回测任务

        只传递必要参数，其他参数使用 run_backtest.py 默认值：
        --timeframe: 默认 1m
        --cash: 默认 100000
        --commission: 默认 0.0

        Args:
            task: 任务字典

        Returns:
            subprocess 执行结果
        """
        cmd = [
            sys.executable, "-m", "backtest.run_backtest",
            "--strategy", task["strategy"],
            "--start", task["start"],
            "--symbol", task["symbol"],
            "--data-dir", task["data_dir"],
            "--output-dir", task["output_dir"],
            "--log-level", task["log_level"],
            "--config", task["config_path"],
        ]

        # end 可选，未配置时不传 --end 参数
        if task.get("end"):
            cmd.extend(["--end", task["end"]])

        # overrides 可选，传递 JSON 字符串
        if task.get("overrides"):
            cmd.extend(["--overrides", json.dumps(task["overrides"])])

        # 输出目录日期模式
        if task.get("use_today_as_output_date"):
            cmd.append("--use-today-as-output-date")

        logger.info(f"执行: {' '.join(cmd)}")
        return subprocess.run(cmd, capture_output=True, text=True)

    def run_all(self, daemon: bool = False) -> Dict[str, Any]:
        """
        并发执行所有任务

        Args:
            daemon: 是否后台运行

        Returns:
            执行摘要
        """
        tasks = self._build_tasks()
        results = []

        if daemon:
            return self._run_daemon(tasks)

        # 前台模式：并发执行
        with ProcessPoolExecutor(max_workers=self.main_config.get("max_workers", 4)) as executor:
            futures = {executor.submit(self._run_single, task): task for task in tasks}

            for future in as_completed(futures):
                task = futures[future]
                try:
                    result = future.result()
                    results.append({
                        "task": task,
                        "status": "success" if result.returncode == 0 else "failed",
                        "return_code": result.returncode,
                        "stdout": result.stdout[:500] if result.stdout else "",
                        "stderr": result.stderr[:500] if result.stderr else "",
                    })
                except Exception as e:
                    results.append({
                        "task": task,
                        "status": "error",
                        "error": str(e),
                    })

        return {"total": len(tasks), "results": results}

    def _run_daemon(self, tasks: List[Dict]) -> Dict[str, Any]:
        """
        后台运行模式

        Args:
            tasks: 任务列表

        Returns:
            执行摘要
        """

        # 创建批次输出目录
        batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        batch_dir = Path(self.main_config["output_dir"]) / f"batch_{batch_id}"
        batch_dir.mkdir(parents=True, exist_ok=True)

        # 写入任务列表
        tasks_file = batch_dir / "tasks.json"
        with open(tasks_file, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)

        # 后台运行（跨平台）
        pid_file = batch_dir / "batch.pid"
        log_file = batch_dir / "batch.log"

        cmd = [
            sys.executable, "-m", "backtest.batch_runner",
            "--config", str(Path(self.config_dir) / "main.yaml"),
            "--batch-id", batch_id,
        ]

        # 平台差异：Windows 用 DETACHED_PROCESS，Linux 用 nohup
        if platform.system() == "Windows":
            cmd, kwargs = cmd, {"creationflags": 0x00000008, "close_fds": True}
        else:
            cmd, kwargs = ["nohup"] + cmd, {"start_new_session": True}

        with open(log_file, "w", encoding="utf-8") as log_f:
            process = subprocess.Popen(cmd, stdout=log_f, stderr=log_f, **kwargs)

        # 写入 PID
        with open(pid_file, "w") as f:
            f.write(str(process.pid))

        logger.info(f"后台任务已启动: batch_id={batch_id}, pid={process.pid}")
        logger.info(f"日志文件: {log_file}")

        return {
            "total": len(tasks),
            "batch_id": batch_id,
            "pid": process.pid,
            "log_file": str(log_file),
            "status": "running",
        }


def main():
    """CLI 入口"""
    parser = argparse.ArgumentParser(description="批量回测执行器")
    parser.add_argument(
        "--config",
        default="backtest/config/strategies.yaml",
        help="策略配置文件路径（默认 backtest/config/strategies.yaml）",
    )
    parser.add_argument(
        "--backtest-config",
        default=None,
        help="回测配置文件路径（默认 backtest/config/main.yaml）",
    )
    parser.add_argument(
        "--start",
        help="回测开始时间（YYYYMMDD），覆盖配置文件中的 start",
    )
    parser.add_argument(
        "--end",
        help="回测结束时间（YYYYMMDD），覆盖配置文件中的 end",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="后台运行模式",
    )
    parser.add_argument(
        "--batch-id",
        help="批次 ID（内部使用）",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="查看运行状态",
    )

    args = parser.parse_args()

    # 配置日志 - 按日目录存储（UTC 时间）
    file_handler = DailyDirectoryFileHandler(
        base_dir="logs/backtest",
        filename="batch_runner",
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))

    logging.basicConfig(
        level=logging.INFO,
        handlers=[
            file_handler,
            logging.StreamHandler(),
        ],
    )

    # 确定配置文件
    strategies_config = args.config
    backtest_config = args.backtest_config or DEFAULT_BACKTEST_CONFIG_PATH

    runner = BatchBacktestRunner(
        config_path=strategies_config,
        start_override=args.start,
        end_override=args.end,
        backtest_config_path=backtest_config,
    )

    if args.status:
        # 查看状态
        print("状态查询功能待实现")
        return

    # 执行回测
    summary = runner.run_all(daemon=args.daemon)

    # 输出摘要
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
