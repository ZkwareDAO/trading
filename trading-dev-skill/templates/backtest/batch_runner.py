#!/usr/bin/env python3
"""
批量回测执行器 - 通过 subprocess 调用 run_backtest.py

功能：
- 从 config/strategies.yaml 读取策略登记表（与实盘共用同一份）
- 从 config/<profile>.yaml 读取回测专有参数（时间范围/数据目录/输出目录/并发数）
- 自动组合每个 (strategy, symbol) 的 overrides 路径
- 并发执行多个回测任务
- 支持后台运行模式

配置文件：
- config/strategies.yaml: 策略编排（实盘回测共用，单一事实来源）
- config/backtest.yaml: 回测 run-profile（回测专有参数）
"""

import argparse
import json
import logging
import platform
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from strategy_core.utils.strategies_loader import StrategiesLoader
from strategy_core.utils.log_handlers import DailyDirectoryFileHandler

# 复用实盘 run_strategies_manager 的 name:symbol 解析逻辑，保证三个入口
# （manager --run / run_backtest --strategies / batch_runner --run）CLI 风格一致
from run_strategies_manager import parse_explicit_strategies

from backtest.config_loader import load_profile

logger = logging.getLogger(__name__)


class BatchBacktestRunner:
    """并发回测执行器 - 通过 subprocess 调用 run_backtest.py

    配置来源：
    1. config/strategies.yaml — 策略登记表（与实盘共用）
    2. config/<profile>.yaml — 回测专有参数
    """

    def __init__(
        self,
        strategies_config_path: str = "config/strategies.yaml",
        profile: str = "backtest",
        start_override: str | None = None,
        end_override: str | None = None,
        log_level_override: str | None = None,
        explicit_strategies: str | None = None,
    ):
        """
        初始化执行器

        Args:
            strategies_config_path: 策略登记表（默认 config/strategies.yaml，与实盘共用）
            profile: run-profile 名（默认 backtest），从 config/<name>.yaml 读回测参数
            start_override: CLI 覆盖的 start 时间（优先级最高）
            end_override: CLI 覆盖的 end 时间（优先级最高）
            log_level_override: CLI 覆盖的日志级别，透传给每个 run_backtest 子进程
            explicit_strategies: CLI --run 运行清单（name:symbol,...），非空时覆盖登记表
        """
        self.strategies_config_path = strategies_config_path
        self.profile = profile
        self.start_override = start_override
        self.end_override = end_override
        self.log_level_override = log_level_override

        self.profile_cfg = load_profile(profile)
        self._loader = StrategiesLoader(strategies_config_path).load()

        # CLI --run 优先于登记表，与实盘 manager 同一套机制（set_explicit_pairs）。
        # 注意两条路径对"overrides 文件缺失"的处理刻意不同：登记表 warn+skip
        # （长期清单，个别标的没配好不该阻断整批），显式清单直接报错
        # （既然点名指定，静默跳过等于骗人）。
        explicit_pairs = parse_explicit_strategies(explicit_strategies)
        if explicit_pairs:
            logger.info(f"使用 CLI --run 指定运行清单: {explicit_pairs}")
            self._loader.set_explicit_pairs(explicit_pairs)
            # 立即展开：set_explicit_pairs 只登记不校验，展开才会检查 overrides 文件。
            # 若留给 run_all() 惰性触发，异常会逃出 main() 的 try 变成裸 traceback；
            # 在此展开可让 FileNotFoundError 落进 except 打印单行错误。结果有缓存，不重复计算。
            self._loader.expand_strategies()

    def _build_tasks(self) -> List[Dict]:
        """从 StrategiesLoader 构建任务列表。"""
        tasks = []
        for instance in self._loader.filter(enabled_only=True):
            config_path = instance.config_path
            if not Path(config_path).exists():
                logger.warning(f"配置文件不存在: {config_path}，跳过")
                continue

            start = self.start_override or self.profile_cfg.get("start", "")
            end = self.end_override or self.profile_cfg.get("end", "")

            tasks.append({
                "strategy": instance.name,
                "symbol": instance.symbol,
                "start": start,
                "end": end,
                "profile": self.profile,
                "config_path": config_path,
                "overrides": instance.overrides,
            })
        return tasks

    def _run_single(self, task: Dict) -> subprocess.CompletedProcess:
        """执行单个回测任务（subprocess 调 run_backtest.py）。

        只传 --strategies/--start/--end/--profile/--config-path，其余参数由 profile 提供。
        """
        cmd = [
            sys.executable, "-m", "backtest.run_backtest",
            "--strategies", f"{task['strategy']}:{task['symbol']}",
            "--start", task["start"],
            "--profile", task["profile"],
            "--config-path", task["config_path"],
        ]

        # end 可选
        if task.get("end"):
            cmd.extend(["--end", task["end"]])

        # overrides 可选（JSON 字符串）
        if task.get("overrides"):
            cmd.extend(["--overrides", json.dumps(task["overrides"])])

        # log_level 可选（CLI 覆盖优先，否则由子进程从 profile 读）
        if self.log_level_override:
            cmd.extend(["--log-level", self.log_level_override])

        logger.info(f"执行: {' '.join(cmd)}")
        return subprocess.run(cmd, capture_output=True, text=True)

    def run_all(self, daemon: bool = False) -> Dict[str, Any]:
        """并发执行所有任务。"""
        tasks = self._build_tasks()
        results = []

        if daemon:
            return self._run_daemon(tasks)

        max_workers = self.profile_cfg.get("max_workers", 4)
        with ProcessPoolExecutor(max_workers=max_workers) as executor:
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
        """后台运行模式。"""
        batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = self.profile_cfg.get("output_dir", "./backtest_output")
        batch_dir = Path(output_dir) / f"batch_{batch_id}"
        batch_dir.mkdir(parents=True, exist_ok=True)

        tasks_file = batch_dir / "tasks.json"
        with open(tasks_file, "w", encoding="utf-8") as f:
            json.dump(tasks, f, ensure_ascii=False, indent=2)

        pid_file = batch_dir / "batch.pid"
        log_file = batch_dir / "batch.log"

        cmd = [
            sys.executable, "-m", "backtest.batch_runner",
            "--profile", self.profile,
            "--batch-id", batch_id,
        ]

        if platform.system() == "Windows":
            cmd, kwargs = cmd, {"creationflags": 0x00000008, "close_fds": True}
        else:
            cmd, kwargs = ["nohup"] + cmd, {"start_new_session": True}

        with open(log_file, "w", encoding="utf-8") as log_f:
            process = subprocess.Popen(cmd, stdout=log_f, stderr=log_f, **kwargs)

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
        default="config/strategies.yaml",
        help="策略登记表路径（默认 config/strategies.yaml，与实盘共用）",
    )
    parser.add_argument(
        "--run",
        default=None,
        help=(
            "直接指定运行清单，格式 name:symbol,name:symbol，优先于 --config 登记表。"
            "与实盘 run_strategies_manager.py --run 格式一致。"
            "指定的 overrides 文件不存在则报错。"
            "示例: --run sar_snt3_v3:BTCUSDT,sar_snt3_v3:ETHUSDT"
        ),
    )
    parser.add_argument(
        "--profile",
        default="backtest",
        help="run-profile（默认 backtest），从 config/<name>.yaml 读回测参数",
    )
    parser.add_argument(
        "--start",
        help="回测开始时间（YYYYMMDD），覆盖 profile.start",
    )
    parser.add_argument(
        "--end",
        help="回测结束时间（YYYYMMDD），覆盖 profile.end",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="后台运行模式",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别，覆盖 profile 并透传给每个回测子进程",
    )
    parser.add_argument(
        "--batch-id",
        help="批次 ID（内部使用）",
    )

    args = parser.parse_args()

    file_handler = DailyDirectoryFileHandler(
        base_dir="logs/backtest",
        filename="batch_runner",
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    ))

    logging.basicConfig(
        level=getattr(logging, args.log_level, logging.INFO) if args.log_level else logging.INFO,
        handlers=[file_handler, logging.StreamHandler()],
    )

    try:
        runner = BatchBacktestRunner(
            strategies_config_path=args.config,
            profile=args.profile,
            start_override=args.start,
            end_override=args.end,
            log_level_override=args.log_level,
            explicit_strategies=args.run,
        )
    except (FileNotFoundError, ValueError) as e:
        logger.error(str(e))
        sys.exit(1)

    summary = runner.run_all(daemon=args.daemon)
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    # 失败必须反映到退出码：daily_backtest.py 跑在 crontab 里，
    # 若批量任务全崩仍返回 0，失败会被静默吞掉。
    # daemon 模式只负责拉起后台进程，此时无最终结果可判，不参与判定。
    if args.daemon:
        return

    failed = [r for r in summary["results"] if r.get("status") != "success"]
    if failed:
        logger.error(f"{len(failed)}/{summary['total']} 个回测任务失败")
        for r in failed:
            task = r.get("task", {})
            logger.error(
                f"  失败: {task.get('strategy')}:{task.get('symbol')} "
                f"status={r.get('status')} rc={r.get('return_code')} "
                f"{r.get('error') or (r.get('stderr') or '').strip().splitlines()[-1:] or ''}"
            )
        sys.exit(1)


if __name__ == "__main__":
    main()
