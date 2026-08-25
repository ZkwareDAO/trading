#!/usr/bin/env python3
"""replay.py — 每日回放回测

遍历本地快照，对每个策略执行回测，结果输出到 replay_outputs/{day}/。

用法:
    python3 replay.py                        # 回放昨天（默认）
    python3 replay.py --date 20260807        # 回放指定日期快照
    python3 replay.py --start 20260801 --end 20260807  # 自定义回测区间

流程:
  1. 读 config.yaml
  2. replay 日期默认昨天，可 --date 指定
  3. 每个快照目录内创建并激活 venv (python3 -m venv .venv)
  4. 遍历 config 策略名，cd 到 snapshot/{day}/{策略文件夹}/
  5. 扫快照 strategies/*/overrides/*.yaml 收集策略名+代币
  6. 在快照 config/ 下生成 backtest.yaml（动态 start/end/data_dir/output_dir）
  7. 执行 scripts/run_backtest_batch.sh --strategies X --symbols Y --profile backtest --start --end --yes
  8. 回测结果由 backtest.yaml.output_dir 直指 replay_outputs/{day}/{策略文件夹}/

约定:
  - 策略文件夹 = config 中 path 的 basename
  - 默认回测区间 start = end = replay 日期（复盘那一天），
    可用 --start/--end 覆盖
  - --strategies 的策略名取快照 strategies/ 子目录名（与下游
    strategies/<name>/overrides/<sym>.yaml 路径自然匹配），非 config.yaml 的 key
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import yaml

# config 顶层 model 分组
MODEL_KEYS = ["product", "paper", "smoking"]

# 回测数据目录（= download_data.py 的 K线写入路径，与 settings.csv_dir 一致）
BACKTEST_DATA_DIR = "./data/klines"


def parse_day(value):
    """解析日期，默认昨天，校验 YYYYMMDD 格式"""
    if not value:
        value = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    if len(value) != 8 or not value.isdigit():
        sys.exit(f"❌ 日期格式错误: {value}，应为 YYYYMMDD")
    return value


def load_config(path):
    """加载 YAML 配置"""
    if not Path(path).is_file():
        sys.exit(f"❌ 配置文件不存在: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def iter_strategies(config):
    """遍历所有 model 下的策略，yield (策略名, 策略文件夹)

    策略文件夹 = path 的 basename，用于定位 snapshot/{day}/{文件夹}/
    """
    for model in MODEL_KEYS:
        strategies = config.get(model) or {}
        if not isinstance(strategies, dict):
            continue
        for name, cfg in strategies.items():
            if isinstance(cfg, dict) and cfg.get("path"):
                yield name, Path(cfg["path"]).name or name


def ensure_venv(proj_dir):
    """在快照目录内创建 .venv（已存在则复用），返回 venv 的 python 路径

    对应需求第 3、4 步：python3 -m venv .venv + source .venv/bin/activate
    —— 这里不真的 source，而是把 venv/bin 前置到 PATH，效果等同激活。
    若存在 requirements.txt，顺带装依赖（否则回测 import 会失败）。

    全部用绝对路径：subprocess 的 cwd 会切到 proj_dir，若用相对路径，
    切换后相对路径即失效（FileNotFoundError / requirements 打不开）。
    """
    proj_dir = Path(proj_dir).resolve()
    venv_dir = proj_dir / ".venv"
    python = venv_dir / "bin" / "python"
    if not python.is_file():
        r = subprocess.run(["python3", "-m", "venv", str(venv_dir)],
                           cwd=str(proj_dir))
        if r.returncode != 0:
            return None

    req = proj_dir / "requirements.txt"
    if req.is_file():
        subprocess.run([str(python), "-m", "pip", "install", "-q", "-r", str(req)],
                       cwd=str(proj_dir))
    return str(python)


def with_venv_env(venv_python):
    """构造激活了 venv 的环境变量（PATH 前置 venv/bin）"""
    env = os.environ.copy()
    venv_bin = str(Path(venv_python).parent)
    env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(Path(venv_python).parent.parent)
    return env


def collect_strategy_symbols(proj_dir):
    """扫描快照内策略与代币，返回 (strategies, symbols)

    遍历 proj_dir/strategies/*/ 子目录，扫 overrides/*.yaml 文件名收集代币。
    策略名 = strategies/ 子目录名（与下游 strategies/<name>/overrides/<sym>.yaml
    路径自然匹配，过 precheck_overrides 校验）。

    返回:
        (strategy_names: list[str], symbols: list[str])，均去重保序、symbols 大写。
        两者任一为空表示快照无可回测内容。
    """
    strategies_dir = proj_dir / "strategies"
    strat_names = []
    sym_set = set()
    sym_list = []
    if not strategies_dir.is_dir():
        return [], []
    for sub in strategies_dir.iterdir():
        if not sub.is_dir() or sub.name.startswith("__") or sub.name.startswith("."):
            continue
        overrides_dir = sub / "overrides"
        if not overrides_dir.is_dir():
            continue
        has_sym = False
        for f in overrides_dir.glob("*.yaml"):
            if f.is_file() and not f.name.startswith("."):
                sym = f.stem.upper()
                if sym not in sym_set:
                    sym_set.add(sym)
                    sym_list.append(sym)
                has_sym = True
        if has_sym:
            strat_names.append(sub.name)
    return strat_names, sym_list


def ensure_backtest_profile(proj_dir, start, end, out_dir, template_path=None):
    """在快照 config/ 下生成 backtest.yaml（run-profile），返回生成路径

    动态写入 start/end/data_dir/output_dir，其余键取模板默认值。
    - data_dir: 固定常量 ./data/klines（= download_data.py K线写入路径，
      与 settings.csv_dir 一致，过 verify_data_dir_consistency 校验）
    - output_dir: replay_outputs/{day}/{folder}/ 绝对路径（回测原生写入）
    - start/end: replay 日期（CLI --start/--end 仍可覆盖）

    生成前若快照已有 config/backtest.yaml，备份为 backtest.yaml.bak
    （replay 需动态日期/输出，覆盖是预期行为）。
    """
    config_dir = proj_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    profile_path = config_dir / "backtest.yaml"

    # 读模板默认值（cash/commission/use_today_as_output_date/log_level/max_workers）
    defaults = {}
    tpl = Path(template_path) if template_path else (
        Path(__file__).parent / "backtest.example.yaml")
    if tpl.is_file():
        defaults = yaml.safe_load(tpl.read_text(encoding="utf-8")) or {}

    # 备份快照自带的 backtest.yaml
    if profile_path.is_file():
        shutil.copy2(profile_path, config_dir / "backtest.yaml.bak")

    out_dir_abs = str(Path(out_dir).resolve())
    lines = [
        "# 由 replay.py 自动生成 — 勿手改",
        "# 回测 run-profile，承载运行方式（时间范围/资金/费率/输出/并发）。",
        "# start/end/data_dir/output_dir 由 replay 动态写入，覆盖模板默认值。",
        "",
        f"start: \"{start}\"",
        f"end: \"{end}\"",
        "",
        "# 资金与费用",
        f"cash: {defaults.get('cash', 5000)}",
        f"commission: {defaults.get('commission', 0.0004)}",
        "",
        "# 数据与输出（data_dir 与 settings.csv_dir 一致；output_dir 由 replay 指定）",
        f"data_dir: \"{BACKTEST_DATA_DIR}\"",
        f"output_dir: \"{out_dir_abs}\"",
        f"use_today_as_output_date: {str(defaults.get('use_today_as_output_date', True)).lower()}",
        f"log_level: \"{defaults.get('log_level', 'INFO')}\"",
        "",
        "# 并发",
        f"max_workers: {defaults.get('max_workers', 4)}",
        "",
    ]
    profile_path.write_text("\n".join(lines), encoding="utf-8")
    return profile_path


def main():
    ap = argparse.ArgumentParser(description="每日回放回测")
    ap.add_argument("--date", default=None, help="回放日期 YYYYMMDD，默认昨天")
    ap.add_argument("--config", default="config.yaml", help="配置文件路径")
    ap.add_argument("--snapshot-dir", default="./snapshot", help="快照根目录")
    ap.add_argument("--output-dir", default="./replay_outputs", help="回测结果根目录")
    ap.add_argument("--start", default=None, help="回测开始日期，默认=date")
    ap.add_argument("--end", default=None, help="回测结束日期，默认=date")
    args = ap.parse_args()

    day = parse_day(args.date)
    start = args.start or day
    end = args.end or day
    config = load_config(args.config)

    snapshot_base = Path(args.snapshot_dir) / day
    if not snapshot_base.is_dir():
        sys.exit(f"❌ 快照目录不存在: {snapshot_base}，请先运行 sync-exee.py")

    output_base = (Path(args.output_dir) / day).resolve()
    output_base.mkdir(parents=True, exist_ok=True)

    print(f"=== replay 开始，日期 {day}，回测区间 {start} ~ {end} ===")

    seen = set()
    success, fail = 0, 0
    for name, folder in iter_strategies(config):
        # 同名策略文件夹去重，避免重复回测
        if folder in seen:
            continue
        seen.add(folder)

        proj_dir = (snapshot_base / folder).resolve()
        print(f"\n--- {name} → {proj_dir} ---")

        if not proj_dir.is_dir():
            print(f"  ⚠ {name}: 快照不存在，跳过")
            fail += 1
            continue

        batch_script = proj_dir / "scripts" / "run_backtest_batch.sh"
        if not batch_script.is_file():
            print(f"  ⚠ {name}: 缺少 scripts/run_backtest_batch.sh，跳过")
            fail += 1
            continue

        # 步骤 3、4: 创建并激活 venv
        venv_python = ensure_venv(proj_dir)
        if venv_python is None:
            print(f"  ❌ {name}: venv 创建失败")
            fail += 1
            continue

        # 步骤 5: 扫快照 strategies/*/overrides/*.yaml 收集策略名+代币
        strat_names, symbols = collect_strategy_symbols(proj_dir)
        if not strat_names or not symbols:
            print(f"  ⚠ {name}: 快照无可回测策略/代币（缺 strategies/*/overrides/），跳过")
            fail += 1
            continue
        print(f"  策略: {','.join(strat_names)}")
        print(f"  代币: {','.join(symbols)}")

        # 步骤 6: 在快照 config/ 下生成 backtest.yaml（动态 start/end/data_dir/output_dir）
        out_dir = output_base / folder
        ensure_backtest_profile(proj_dir, start, end, out_dir)

        # 步骤 7: 执行回测（笛卡尔积模式，输出由 backtest.yaml.output_dir 直指 out_dir）
        cmd = ["bash", str(batch_script),
               "--strategies", ",".join(strat_names),
               "--symbols", ",".join(symbols),
               "--profile", "backtest",
               "--start", start, "--end", end,
               "--yes"]
        print(f"  $ {' '.join(cmd)}")
        r = subprocess.run(cmd, cwd=str(proj_dir), env=with_venv_env(venv_python))

        if r.returncode == 0:
            print(f"  ✅ {name}: 回测完成 → replay_outputs/{day}/{folder}/")
            success += 1
        else:
            print(f"  ❌ {name}: 回测失败 (exit {r.returncode})")
            fail += 1

    print(f"\n=== 完成: {success} 成功, {fail} 失败 ===")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
