#!/usr/bin/env python3
"""sync-exee.py — 每日策略项目备份

从实盘机器同步策略项目快照到本地，按 snapshot/{day}/{策略文件夹}/ 存放。

用法:
    python3 sync-exee.py                       # 备份昨天（默认）
    python3 sync-exee.py --date 20260807       # 备份指定日期
    python3 sync-exee.py --config config.yaml  # 指定配置文件

流程:
  1. 读 config.yaml，遍历所有 model(product/paper/smoking) 下配置的策略
  2. rsync 拉取策略项目，排除 logs / .venv / backtest_output（.gitignore 产物）
     —— data 目录体积大，一并排除，仅按第 3 步拉取必要子集
  3. 额外同步 data 指定文件（day 默认昨天，格式 YYYYMMDD）:
       data/signals/{策略名}/{day}.csv
       data/positions/                       （整个目录）
       data/history_positions/{策略名}/{day}.csv
     data 子集独立存放至 replay_data/{day}/{策略文件夹}/data/
  4. 代码存放至 snapshot/{day}/{策略文件夹}/，目录结构与远程一致
     （与 replay_outputs 对仗：replay_data=实盘输入基准，replay_outputs=回测结果）
  5. 同步完成后扫描所有快照的 strategies/*/overrides/*.yaml，
     收集代币去重，生成 symbols.yaml（供 download_data.py 读取）

约定:
  - 策略文件夹 = config 中 path 的 basename
  - 策略名     = config 中的 key，同时作为 data 子目录的 strategy_id
  - host 字段可填 user@ip 或 ssh 别名；端口/密钥走 ~/.ssh/config
"""

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

# 本地 host 标识：这些写法表示源就在本机，走本地拷贝而非 ssh
LOCAL_HOSTS = {"", "127.0.0.1", "localhost", "::1"}

# 同步时排除的目录：运行产物、虚拟环境、大数据目录
# data 整体排除：体积大，仅按需求第 3 步拉取必要子集
EXCLUDE_DIRS = ["logs", ".venv", "backtest_output", "data"]

# config 顶层 model 分组
MODEL_KEYS = ["product", "paper", "smoking"]


def parse_day(value):
    """解析日期，默认昨天，校验 YYYYMMDD 格式"""
    if not value:
        value = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    if len(value) != 8 or not value.isdigit():
        sys.exit(f"❌ 日期格式错误: {value}，应为 YYYYMMDD（如 20260807）")
    return value


def load_config(path):
    """加载 YAML 配置"""
    if not Path(path).is_file():
        sys.exit(f"❌ 配置文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def iter_strategies(config):
    """遍历所有 model 下的策略，yield (策略名, host, remote_path)

    config 结构:
        product:
          strategy_name1: {host: ..., path: ...}
        paper: ...
        smoking: ...
    """
    for model in MODEL_KEYS:
        strategies = config.get(model) or {}
        if not isinstance(strategies, dict):
            continue
        for name, cfg in strategies.items():
            if isinstance(cfg, dict) and cfg.get("path"):
                yield name, cfg.get("host", ""), cfg["path"]


def collect_symbols(snapshot_base):
    """扫描所有快照的 strategies/*/overrides/*.yaml，收集代币去重

    多个策略可能代币重复，统一去重后排序。
    跳过 .tmp-* 临时目录。
    """
    symbols = set()
    if not snapshot_base.is_dir():
        return []
    for folder_dir in snapshot_base.iterdir():
        if not folder_dir.is_dir() or folder_dir.name.startswith(".tmp-"):
            continue
        strategies_dir = folder_dir / "strategies"
        if not strategies_dir.is_dir():
            continue
        # 每个 strategy 子目录下的 overrides/*.yaml 文件名即代币
        for strat_dir in strategies_dir.iterdir():
            if not strat_dir.is_dir():
                continue
            overrides_dir = strat_dir / "overrides"
            if not overrides_dir.is_dir():
                continue
            for f in overrides_dir.glob("*.yaml"):
                if f.is_file() and not f.name.startswith("."):
                    symbols.add(f.stem.upper())
    return sorted(symbols)


def write_symbols_yaml(symbols, path):
    """写 symbols.yaml（供 download_data.py 读取）

    格式:
        symbols:
          - BTCUSDT
          - ETHUSDT
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# 自动生成 — 由 sync-exee.py 从快照 overrides 收集去重，勿手改\n")
        f.write("# 供 download_data.py 读取\n")
        f.write("symbols:\n")
        for sym in symbols:
            f.write(f"  - {sym}\n")


def run(cmd):
    """执行命令，实时输出，返回是否成功"""
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(cmd).returncode == 0


def is_local(host):
    """源是否在本机：空 / 127.0.0.1 / localhost / ::1 视为本地"""
    return (host or "").strip() in LOCAL_HOSTS


def rsync_pull(host, remote, local, excludes=None):
    """rsync 拉取 remote → local，排除指定目录

    本地 host（127.0.0.1 等）走纯本地 rsync（无 -e ssh）；
    远程 host 走 rsync over ssh。
    """
    if is_local(host):
        src = f"{remote}/"
    else:
        src = f"{host}:{remote}/"
    cmd = ["rsync", "-az", "--delete"]
    if not is_local(host):
        cmd += ["-e", "ssh -o StrictHostKeyChecking=accept-new"]
    for d in excludes or []:
        cmd += ["--exclude", f"{d}/"]
    cmd += [src, f"{local}/"]
    return run(cmd)


def sync_data_files(host, remote_path, local_dir, day, name):
    """同步 data 指定子集

    - data/signals/{name}/{day}.csv
    - data/positions/                   （整个目录）
    - data/history_positions/{name}/{day}.csv

    单个 csv 缺失不算错（部分策略当天无信号/历史持仓）；
    --ignore-missing-args 让缺失文件不污染退出码。

    本地 host 走纯本地 rsync（无 ssh）。
    """
    prefix = "" if is_local(host) else f"{host}:"
    pulls = [
        f"data/signals/{name}/{day}.csv",
        "data/positions",
        f"data/history_positions/{name}/{day}.csv",
    ]
    ok = True
    for rel in pulls:
        local_target = local_dir / Path(rel).parent
        local_target.mkdir(parents=True, exist_ok=True)
        cmd = ["rsync", "-az", "--ignore-missing-args"]
        if not is_local(host):
            cmd += ["-e", "ssh -o StrictHostKeyChecking=accept-new"]
        cmd += [f"{prefix}{remote_path}/{rel}", f"{local_target}/"]
        print(f"  $ {' '.join(cmd)}")
        r = subprocess.run(cmd)
        # positions 是目录，缺失才告警；csv 缺失可接受
        if r.returncode != 0 and not rel.endswith(day + ".csv"):
            ok = False
    return ok


def main():
    ap = argparse.ArgumentParser(description="每日策略项目备份")
    ap.add_argument("--date", default=None, help="备份日期 YYYYMMDD，默认昨天")
    ap.add_argument("--config", default="config.yaml", help="配置文件路径")
    ap.add_argument("--snapshot-dir", default="./snapshot", help="快照根目录")
    ap.add_argument("--data-dir", default="./replay_data", help="data 子集根目录")
    args = ap.parse_args()

    day = parse_day(args.date)
    config = load_config(args.config)

    snapshot_base = Path(args.snapshot_dir) / day
    snapshot_base.mkdir(parents=True, exist_ok=True)
    data_base = Path(args.data_dir) / day
    data_base.mkdir(parents=True, exist_ok=True)

    print(f"=== sync-exee 开始，日期 {day} ===")

    seen = set()
    success, fail = 0, 0
    for name, host, remote_path in iter_strategies(config):
        folder = Path(remote_path).name or name
        local_dir = snapshot_base / folder

        # 同一日期下策略文件夹名需唯一（不同 model 同名时靠 path basename 区分）
        if folder in seen:
            print(f"⚠ 策略 {name}: 快照目录 {folder} 已被占用，跳过"
                  f"（请保证各策略 path 的 basename 唯一）")
            continue
        seen.add(folder)

        print(f"\n--- {name} → snapshot/{day}/{folder}/ ---")
        print(f"  源: {host or '(本地)'}:{remote_path}")
        if not host:
            print(f"  ⚠ {name}: 缺少 host，跳过")
            fail += 1
            continue

        # 临时目录，成功后原子移动到最终位置
        tmp_dir = snapshot_base / f".tmp-{folder}"
        if tmp_dir.exists():
            shutil.rmtree(tmp_dir)
        tmp_dir.mkdir(parents=True, exist_ok=True)

        # 步骤 2: 拉取代码（排除产物/venv/data）
        if not rsync_pull(host, remote_path, tmp_dir, excludes=EXCLUDE_DIRS):
            print(f"  ❌ {name}: 代码同步失败")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            fail += 1
            continue

        # 步骤 3: 拉取 data 指定子集 → replay_data/{day}/{folder}/data/
        data_dir = data_base / folder
        sync_data_files(host, remote_path, data_dir, day, name)

        # 步骤 4: 原子移动到最终位置
        if local_dir.exists():
            shutil.rmtree(local_dir)
        tmp_dir.rename(local_dir)
        print(f"  ✅ {name}: 已备份到 snapshot/{day}/{folder}/")
        success += 1

    # 步骤 5: 扫描快照 overrides 收集代币去重 → 生成 symbols.yaml
    symbols = collect_symbols(snapshot_base)
    symbols_path = snapshot_base / "symbols.yaml"
    write_symbols_yaml(symbols, symbols_path)
    print(f"\n✅ 生成 {symbols_path}（{len(symbols)} 个代币，已去重）")

    print(f"\n=== 完成: {success} 成功, {fail} 失败 ===")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
