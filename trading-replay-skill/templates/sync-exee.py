#!/usr/bin/env python3
"""sync-exee.py — 每日策略项目备份

从实盘机器 rsync 整个项目，排除日志/产物/venv/git，
按 snapshot/{day}/{project_name}-{model} 存放。
包含 data/ 目录（K线数据），Replay 机器拿到快照后可直接运行回测。

用法:
    python3 sync-exee.py                          # 当日备份
    python3 sync-exee.py --date 20260801          # 指定日期
    python3 sync-exee.py --config config.yaml     # 指定配置
    python3 sync-exee.py --model product          # 只备份指定模型
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

# rsync 排除列表：运行产物、缓存、虚拟环境
RSYNC_EXCLUDES = [
    ".venv/",             # Python 虚拟环境，本地重建
    "node_modules/",
    "__pycache__/",       # 编译缓存
    "*.pyc",
    "logs/",              # 运行日志
    "backtest_output*/",  # 回测产物
    "benchmark_output*/", # benchmark 产物
    "snapshot/",          # 避免递归拉取旧快照
    "replay_outputs/",    # replay 产物
    "discovery_outputs/", # discovery 产物
    ".git/",              # git 历史
    ".env",               # 含敏感信息，不拉；Replay 机器用本地 .env
    "*.log",              # 日志文件
    ".idea/",             # IDE 配置
    ".vscode/",
]


def setup_logging(logs_dir: str, date: str) -> logging.Logger:
    """配置日志输出到文件和终端"""
    logs_path = Path(logs_dir)
    logs_path.mkdir(parents=True, exist_ok=True)

    log_file = logs_path / f"sync-{date}.log"

    logger = logging.getLogger("sync-exee")
    logger.setLevel(logging.INFO)

    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    formatter = logging.Formatter("[%(asctime)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


def load_config(config_path: str) -> dict:
    """加载配置文件"""
    config = {}
    if os.path.exists(config_path):
        with open(config_path) as f:
            config = yaml.safe_load(f) or {}
    return config


def load_env(env_path: str = ".env") -> dict:
    """加载 .env 文件"""
    env = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
    return env


def _safe_int(value, default):
    """安全转换为 int，失败返回默认值"""
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def get_scp_config(config: dict, env: dict) -> dict:
    """合并远程同步配置（.env 优先于 config.yaml）"""
    scp_cfg = config.get("scp", {})

    # project_dir: 实盘项目根目录（如 /home/trader/your_project）
    # 可自动推断：若 strategy_dir 以 /strategies 结尾，取上一级
    project_dir = env.get("SCP_PROJECT_DIR", scp_cfg.get("project_dir", ""))
    if not project_dir:
        strategy_dir = env.get("SCP_STRATEGY_DIR", scp_cfg.get("strategy_dir", ""))
        if strategy_dir.endswith("/strategies") or strategy_dir.endswith("/strategies/"):
            project_dir = strategy_dir.rstrip("/").rsplit("/strategies", 1)[0]

    return {
        "host": env.get("SCP_HOST", scp_cfg.get("host", "")),
        "port": env.get("SCP_PORT", scp_cfg.get("port", "22")),
        "user": env.get("SCP_USER", scp_cfg.get("user", "")),
        "project_dir": project_dir,
        "key": env.get("SCP_KEY", scp_cfg.get("key", "~/.ssh/id_rsa")),
        "timeout": _safe_int(env.get("SCP_TIMEOUT", scp_cfg.get("timeout", "30")), 30),
        "retry": _safe_int(env.get("SCP_RETRY", scp_cfg.get("retry", "3")), 3),
    }


def get_paths_config(config: dict, env: dict) -> dict:
    """合并路径配置"""
    paths_cfg = config.get("paths", {})

    return {
        "snapshot_dir": env.get("SNAPSHOT_DIR", paths_cfg.get("snapshot_dir", "./snapshot")),
        "logs_dir": env.get("LOGS_DIR", paths_cfg.get("logs_dir", "./logs")),
        "replay_outputs_dir": env.get(
            "REPLAY_OUTPUTS_DIR", paths_cfg.get("replay_outputs_dir", "./replay_outputs")
        ),
    }


def sync_project(
    project_name: str,
    model: str,
    date: str,
    scp_config: dict,
    paths_config: dict,
    logger: logging.Logger,
    snapshot_base: Path | None = None,
) -> bool:
    """rsync 拉取完整项目，排除日志/产物/大文件

    产物: snapshot/{date}/{project_name}-{model}/
    """
    project_dir = scp_config.get("project_dir", "")
    if not project_dir:
        logger.error("❌ SCP_PROJECT_DIR 未配置，且无法从 SCP_STRATEGY_DIR 自动推断")
        return False

    if snapshot_base is None:
        snapshot_base = Path(paths_config["snapshot_dir"]) / date
    snapshot_base.mkdir(parents=True, exist_ok=True)

    target_dir = snapshot_base / f"{project_name}-{model}"
    temp_dir = snapshot_base / f".tmp-{project_name}-{model}"

    # 清理残留
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    host = scp_config["host"]
    port = scp_config["port"]
    user = scp_config["user"]
    key = os.path.expanduser(scp_config["key"])
    timeout = scp_config["timeout"]

    if not host or not user:
        logger.error("配置不完整: 缺少 SCP_HOST 或 SCP_USER")
        return False

    remote_path = f"{user}@{host}:{project_dir}/"

    # 构建 rsync 命令
    # 用列表传 SSH 参数，避免路径含空格时字符串拼接断裂
    ssh_cmd = [
        "ssh",
        "-p", str(port),
        "-i", key,
        "-o", "StrictHostKeyChecking=accept-new",
    ]
    rsync_cmd = [
        "rsync", "-az",
        "--timeout", str(timeout * 3),
        "--rsh", " ".join(ssh_cmd),
    ]

    # 添加排除规则
    for exclude in RSYNC_EXCLUDES:
        rsync_cmd.extend(["--exclude", exclude])

    rsync_cmd.extend([remote_path, str(temp_dir)])

    for attempt in range(1, scp_config["retry"] + 1):
        try:
            logger.info(f"rsync: {remote_path} → {temp_dir} (attempt {attempt}/{scp_config['retry']})")
            result = subprocess.run(
                rsync_cmd,
                capture_output=True,
                text=True,
                timeout=timeout * 10,
            )
            if result.returncode == 0:
                # 成功：临时目录 → 目标目录
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                temp_dir.rename(target_dir)

                file_count = sum(1 for _ in target_dir.rglob("*") if _.is_file())
                logger.info(f"✅ {project_name}-{model}: {file_count} files synced")
                return True
            else:
                logger.warning(f"rsync 失败 (attempt {attempt}): {result.stderr.strip()}")
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)
        except subprocess.TimeoutExpired:
            logger.warning(f"rsync 超时 (attempt {attempt})")
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
        except FileNotFoundError:
            logger.error("❌ rsync 未安装，请执行: sudo apt install rsync")
            return False
        except Exception as e:
            logger.warning(f"rsync 异常 (attempt {attempt}): {e}")
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

    logger.error(f"❌ {project_name}-{model}: sync failed after {scp_config['retry']} attempts")
    return False


def discover_project_name(scp_config: dict, logger: logging.Logger) -> str:
    """从远程项目路径提取项目名"""
    project_dir = scp_config.get("project_dir", "")
    if project_dir:
        return project_dir.rstrip("/").rsplit("/", 1)[-1]
    return "project"


def main():
    parser = argparse.ArgumentParser(description="每日策略项目备份")
    parser.add_argument("--date", default=None, help="备份日期 (YYYYMMDD，默认当天)")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--model", default=None, help="只备份指定模型 (product/smoking/paper)")
    args = parser.parse_args()

    date = args.date or datetime.now().strftime("%Y%m%d")

    config = load_config(args.config)
    env = load_env()
    scp_config = get_scp_config(config, env)
    paths_config = get_paths_config(config, env)

    logger = setup_logging(paths_config["logs_dir"], date)
    logger.info(f"START sync-exee.py --date {date}")

    if not scp_config["host"]:
        logger.error("❌ SCP_HOST 未配置，无法执行备份")
        sys.exit(1)

    if not scp_config["project_dir"]:
        logger.error("❌ SCP_PROJECT_DIR 未配置，且无法从 SCP_STRATEGY_DIR 自动推断")
        logger.error("  请在 .env 中设置 SCP_PROJECT_DIR=/path/to/your_project")
        sys.exit(1)

    # 项目名从远程路径提取（如 your_project）
    project_name = discover_project_name(scp_config, logger)
    logger.info(f"项目名: {project_name}, 远程路径: {scp_config['project_dir']}")

    # 模型列表
    models = config.get("replay", {}).get("models", ["product", "smoking", "paper"])
    if args.model:
        models = [args.model]

    success_count = 0
    fail_count = 0

    # 所有 model 共享同一份远程代码，只需 rsync 一次
    # 后续 model 通过本地复制 + 不同目录后缀来区分
    snapshot_base = Path(paths_config["snapshot_dir"]) / date

    first_model_file_count = 0

    for i, model in enumerate(models):
        if i == 0:
            # 第一个 model：rsync 从远程拉取
            if sync_project(project_name, model, date, scp_config, paths_config, logger, snapshot_base):
                first_model_file_count = sum(1 for _ in (snapshot_base / f"{project_name}-{model}").rglob("*") if _.is_file())
                success_count += 1
            else:
                fail_count += 1
        else:
            # 后续 model：复制第一个 model 的快照（同一项目，不同 model 后缀）
            first_model_dir = snapshot_base / f"{project_name}-{models[0]}"
            target_dir = snapshot_base / f"{project_name}-{model}"
            if first_model_dir.exists():
                if target_dir.exists():
                    shutil.rmtree(target_dir)
                shutil.copytree(str(first_model_dir), str(target_dir))
                logger.info(f"✅ {project_name}-{model}: copied from {models[0]} ({first_model_file_count} files)")
                success_count += 1
            else:
                logger.error(f"❌ {project_name}-{model}: source {models[0]} not found")
                fail_count += 1

    logger.info(
        f"END sync-exee.py: {len(models)} models, "
        f"{success_count} synced, {fail_count} failed"
    )

    if fail_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
