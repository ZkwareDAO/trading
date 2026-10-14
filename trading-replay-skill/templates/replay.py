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
  3. 遍历 config 策略名，cd 到 snapshot/{day}/{策略文件夹}/
  4. Python: 创建 venv + 执行 scripts/run_backtest_batch.sh
     Rust: cargo build --release + cargo run -- backtest
  5. 回测结果输出到 replay_outputs/{day}/{策略文件夹}/

约定:
  - 策略文件夹 = config 中 path 的 basename
  - lang 字段决定回测方式（python 默认，rust 可选）
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


def detect_lang(project_path):
    """自动检测策略语言类型

    检测规则：
    - 存在 Cargo.toml → rust
    - 存在 requirements.txt 或 strategy_core/ → python
    - 默认 python（向后兼容）
    """
    p = Path(project_path)
    if (p / "Cargo.toml").is_file():
        return "rust"
    if (p / "requirements.txt").is_file() or (p / "strategy_core").is_dir():
        return "python"
    return "python"


def iter_strategies(config):
    """遍历所有 model 下的策略，yield (策略名, 策略文件夹, lang)

    lang 自动检测：config 中显式指定 lang 优先，否则通过 detect_lang() 自动判断。
    """
    for model in MODEL_KEYS:
        strategies = config.get(model) or {}
        if not isinstance(strategies, dict):
            continue
        for name, cfg in strategies.items():
            if isinstance(cfg, dict) and cfg.get("path"):
                lang = cfg.get("lang") or detect_lang(cfg["path"])
                yield name, Path(cfg["path"]).name or name, lang


def ensure_venv(proj_dir):
    """在快照目录内创建 .venv（已存在则复用），返回 venv 的 python 路径"""
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
    """扫描 Python 快照内策略与代币，返回 (strategies, symbols)

    遍历 proj_dir/strategies/*/ 子目录，扫 overrides/*.yaml 文件名收集代币。
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


def collect_symbols_rust(proj_dir):
    """扫描 Rust 快照配置，返回 (strategies, symbols)

    Rust 配置结构：config/{strategy}/example.yaml 或 config/{strategy}/{SYMBOL}.yaml
    代币在配置的 symbols 列表中。
    """
    config_dir = proj_dir / "config"
    strat_names = []
    sym_set = set()
    sym_list = []
    if not config_dir.is_dir():
        return [], []

    for sub in config_dir.iterdir():
        if not sub.is_dir() or sub.name.startswith("_"):
            continue
        # 扫描该策略目录下所有 yaml
        has_sym = False
        for yaml_file in sub.glob("*.yaml"):
            if yaml_file.name.startswith("_"):
                continue
            try:
                config = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            # 单文件模式（含 strategy 字段 = 策略配置）
            if "strategy" in config:
                strat_names.append(config["strategy"])
            # symbols 列表
            for sym in config.get("symbols", []):
                if isinstance(sym, dict) and "symbol" in sym:
                    s = sym["symbol"].upper()
                elif isinstance(sym, str):
                    s = sym.upper()
                else:
                    continue
                if s not in sym_set:
                    sym_set.add(s)
                    sym_list.append(s)
                has_sym = True
        # 即使没有 symbols 字段，只要目录存在就算有策略（单文件模式）
        if not has_sym and sub.joinpath("example.yaml").is_file():
            strat_names.append(sub.name)

    return strat_names, sym_list


def ensure_backtest_profile(proj_dir, start, end, out_dir, template_path=None):
    """在快照 config/ 下生成 backtest.yaml（run-profile），返回生成路径

    动态写入 start/end/data_dir/output_dir，其余键取模板默认值。
    """
    config_dir = proj_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    profile_path = config_dir / "backtest.yaml"

    defaults = {}
    tpl = Path(template_path) if template_path else (
        Path(__file__).parent / "backtest.example.yaml")
    if tpl.is_file():
        defaults = yaml.safe_load(tpl.read_text(encoding="utf-8")) or {}

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


def run_replay_rust(proj_dir, out_dir, start, end, strat_name, symbols):
    """执行 Rust 策略回测

    Rust 回测通过 cargo run --release -- backtest 调用，无内置批量脚本。
    逐个代币串行执行。
    """
    proj_dir = Path(proj_dir).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. 先编译
    print(f"  🔨 编译 Rust 项目...")
    r = subprocess.run(["cargo", "build", "--release"], cwd=str(proj_dir))
    if r.returncode != 0:
        print(f"  ❌ cargo build 失败")
        return False

    # 2. 逐个代币执行回测
    all_ok = True
    for symbol in symbols:
        # 定位配置文件
        config_file = proj_dir / "config" / strat_name / "example.yaml"
        if not config_file.is_file():
            config_file = proj_dir / "config" / strat_name / f"{symbol}.yaml"
        if not config_file.is_file():
            print(f"  ❌ 找不到策略配置文件: config/{strat_name}/")
            return False

        cmd = [
            "cargo", "run", "--release", "--", "backtest",
            "--config", str(config_file),
            "--symbol", symbol,
            "--start", start, "--end", end,
            "--output_dir", str(out_dir),
        ]
        print(f"  $ {' '.join(cmd)}")
        r = subprocess.run(cmd, cwd=str(proj_dir))
        if r.returncode != 0:
            print(f"  ❌ {symbol}: 回测失败 (exit {r.returncode})")
            all_ok = False
        else:
            print(f"  ✅ {symbol}: 回测完成")

    return all_ok


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
    for name, folder, lang in iter_strategies(config):
        # 同名策略文件夹去重，避免重复回测
        if folder in seen:
            continue
        seen.add(folder)

        proj_dir = (snapshot_base / folder).resolve()
        print(f"\n--- {name} → {proj_dir} [lang={lang}] ---")

        if not proj_dir.is_dir():
            print(f"  ⚠ {name}: 快照不存在，跳过")
            fail += 1
            continue

        out_dir = output_base / folder

        if lang == "rust":
            # Rust 分支
            strat_names, symbols = collect_symbols_rust(proj_dir)
            if not strat_names or not symbols:
                print(f"  ⚠ {name}: Rust 快照无可回测策略/代币，跳过")
                fail += 1
                continue
            print(f"  策略: {','.join(strat_names)}")
            print(f"  代币: {','.join(symbols)}")

            if run_replay_rust(proj_dir, out_dir, start, end, strat_names[0], symbols):
                print(f"  ✅ {name}: 回测完成 → replay_outputs/{day}/{folder}/")
                success += 1
            else:
                print(f"  ❌ {name}: 回测失败")
                fail += 1
            continue

        # Python 分支（现有逻辑不变）
        batch_script = proj_dir / "scripts" / "run_backtest_batch.sh"
        if not batch_script.is_file():
            print(f"  ⚠ {name}: 缺少 scripts/run_backtest_batch.sh，跳过")
            fail += 1
            continue

        venv_python = ensure_venv(proj_dir)
        if venv_python is None:
            print(f"  ❌ {name}: venv 创建失败")
            fail += 1
            continue

        strat_names, symbols = collect_strategy_symbols(proj_dir)
        if not strat_names or not symbols:
            print(f"  ⚠ {name}: 快照无可回测策略/代币（缺 strategies/*/overrides/），跳过")
            fail += 1
            continue
        print(f"  策略: {','.join(strat_names)}")
        print(f"  代币: {','.join(symbols)}")

        ensure_backtest_profile(proj_dir, start, end, out_dir)

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
