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


def collect_symbols_rust(proj_dir, klines_dir=None):
    """扫描 Rust 快照配置，返回 (strategies, symbols)

    Rust 配置结构：config/{strategy}/example.yaml 或 config/{strategy}/{SYMBOL}.yaml
    代币在配置的 symbols 列表中。
    """
    config_dir = proj_dir / "config"
    if not config_dir.is_dir():
        return [], []

    # 每个策略目录 → (策略名, 该目录代币, 是否存在 {SYMBOL}.yaml)
    candidates = []
    for sub in sorted(config_dir.iterdir()):
        if not sub.is_dir() or sub.name.startswith("_"):
            continue
        strat_name = None
        syms = []
        has_symbol_files = False
        for yaml_file in sorted(sub.glob("*.yaml")):
            if yaml_file.name.startswith("_"):
                continue
            # {SYMBOL}.yaml 文件名模式：stem 即代币（如 AG.yaml/AU.yaml）
            stem = yaml_file.stem.upper()
            if stem != "EXAMPLE" and not stem.startswith("."):
                has_symbol_files = True
                if stem not in syms:
                    syms.append(stem)
            try:
                config = yaml.safe_load(yaml_file.read_text(encoding="utf-8")) or {}
            except Exception:
                continue
            # 单文件模式（含 strategy 字段 = 策略配置）
            if "strategy" in config:
                strat_name = config["strategy"]
            # symbols 列表
            for sym in config.get("symbols", []):
                if isinstance(sym, dict) and "symbol" in sym:
                    s = sym["symbol"].upper()
                elif isinstance(sym, str):
                    s = sym.upper()
                else:
                    continue
                if s not in syms:
                    syms.append(s)
        # 即使没有 symbols 字段，只要目录存在就算有策略（单文件模式）
        if strat_name is None and sub.joinpath("example.yaml").is_file():
            strat_name = sub.name
        if strat_name:
            candidates.append((strat_name, syms, has_symbol_files))

    # 优先只回测有 per-symbol 配置的策略目录；example-only 目录视为模板跳过。
    # （一个 Rust 仓库可能同时带多个 example_* 模板，全跑会误跑模板策略）
    selected = [c for c in candidates if c[2]] or candidates

    strat_names = []
    sym_set = set()
    sym_list = []
    for strat_name, syms, _has_symbol_files in selected:
        if strat_name not in strat_names:
            strat_names.append(strat_name)
        for s in syms:
            if s not in sym_set:
                sym_set.add(s)
                sym_list.append(s)

    # 单文件模式兜底：仍无代币时，从工作区 K线目录推断可用代币
    # （模板单文件配置无 symbols 字段，代币隐含在 data/klines/1m/{SYMBOL}_1m.csv 文件名中；
    #   快照不含 data/，读 replay 工作区根的 K线目录）
    if not sym_list:
        fallback_dirs = [proj_dir / "data" / "klines" / "1m",
                         Path.cwd() / "data" / "klines" / "1m"]
        if klines_dir:
            fallback_dirs.insert(0, Path(klines_dir).expanduser().resolve() / "1m")
        for kd in fallback_dirs:
            if not kd.is_dir():
                continue
            for f in sorted(kd.glob("*_1m.csv")):
                s = f.name.replace("_1m.csv", "").upper()
                if s and s not in sym_set:
                    sym_set.add(s)
                    sym_list.append(s)
            if sym_list:
                break

    return strat_names, sym_list


def ensure_klines_link(proj_dir, klines_dir):
    """把工作区 K 线目录软链到快照 data/klines

    快照由 sync-exee.py 生成时排除了 /data，Python 回测却在快照目录内以
    ./data/klines 读取 K 线，且 profile.data_dir 必须与 settings.csv_dir
    字符串一致（不能直接改成绝对路径），故用软链注入。
    """
    src = Path(klines_dir).expanduser().resolve()
    link = Path(proj_dir) / "data" / "klines"
    if link.is_symlink():
        if link.resolve() == src:
            return
        link.unlink()
    elif link.exists():
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(src, target_is_directory=True)


def ensure_backtest_profile(proj_dir, start, end, out_dir, template_path=None):
    """在快照 config/ 下生成 backtest.yaml（run-profile），返回生成路径

    动态写入 start/end/data_dir/output_dir，其余键取模板默认值。
    """
    config_dir = proj_dir / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    profile_path = config_dir / "backtest.yaml"

    defaults = {}
    if template_path:
        tpl = Path(template_path)
    else:
        # 兼容两种布局：scripts/ 内（旧）与 templates/ 内（当前）
        tpl = Path(__file__).parent / "backtest.example.yaml"
        if not tpl.is_file():
            tpl = Path(__file__).parent.parent / "templates" / "backtest.example.yaml"
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


def read_warmup_days_rust(proj_dir, strat_name):
    """读取 Rust 策略配置的 warmup_days（缺省 0）

    供回测 start 前推：单日回放窗口会因指标预热不足而无信号，
    start 需前推 warmup 天数（end 保持回放日不变）。
    """
    for name in ("example.yaml", f"{strat_name}.yaml"):
        p = Path(proj_dir) / "config" / strat_name / name
        if not p.is_file():
            continue
        try:
            config = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        try:
            return max(0, int(config.get("warmup_days", 0) or 0))
        except (TypeError, ValueError):
            return 0
    return 0


def run_replay_rust(proj_dir, out_dir, start, end, strat_name, symbols, data_dir=None):
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
        # 定位配置：优先该代币的 {symbol}.yaml（启用 per-symbol 覆盖），
        # 其次 example.yaml，最后目录模式（部分仓库 example.yaml 含多 symbol，
        # 目录模式会因“每文件只能有一个 symbol”失败，故不作为首选）
        config_dir = proj_dir / "config" / strat_name
        if (config_dir / f"{symbol}.yaml").is_file():
            config_target = config_dir / f"{symbol}.yaml"
        elif (config_dir / "example.yaml").is_file():
            config_target = config_dir / "example.yaml"
        elif config_dir.is_dir():
            config_target = config_dir
        else:
            config_target = config_dir / f"{symbol}.yaml"
        if not Path(config_target).exists():
            print(f"  ❌ 找不到策略配置文件: config/{strat_name}/")
            return False

        # 交易窗口只含回放日：start=回放日，end=回放日+1（Rust 为开区间）。
        # warmup 只加载不交易：通过 --warmup-start 指到回放日 - warmup_days。
        warmup_days = read_warmup_days_rust(proj_dir, strat_name)
        warmup_start = (datetime.strptime(start, "%Y%m%d")
                        - timedelta(days=warmup_days)).strftime("%Y%m%d")
        trade_end = (datetime.strptime(end, "%Y%m%d")
                     + timedelta(days=1)).strftime("%Y%m%d")
        print(f"  🗓 交易区间 {start} ~ {end}（含当日），"
              f"预热起点 {warmup_start}（{warmup_days} 天，只加载不交易）")

        cmd = [
            "cargo", "run", "--release", "--", "backtest",
            "--config", str(config_target),
            "--symbol", symbol,
            "--start", start, "--end", trade_end,
            "--warmup-start", warmup_start,
            "--output-dir", str(out_dir),
        ]
        # 快照不含 data/（sync 排除），显式指向 replay 工作区 K线目录
        if data_dir:
            cmd += ["--data-dir", str(Path(data_dir).resolve())]
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
    ap.add_argument("--snapshot-dir", default=None,
                    help="快照根目录（默认 <workspace>/snapshot，未配置 workspace 则 ./snapshot）")
    ap.add_argument("--output-dir", default=None,
                    help="回测结果根目录（默认 <workspace>/replay_outputs，未配置则 ./replay_outputs）")
    ap.add_argument("--start", default=None, help="回测开始日期，默认=date")
    ap.add_argument("--end", default=None, help="回测结束日期，默认=date")
    ap.add_argument("--data-dir", default=None,
                    help="K线根目录（默认取 config.yaml 顶层 data_dir，再回落 ./data/klines）")
    ap.add_argument("--frontend-out", default=None,
                    help="frontend-data 根目录（覆盖 config.yaml 的 frontend_data_dir；"
                         "为空则跳过看板生成）")
    args = ap.parse_args()

    day = parse_day(args.date)
    start = args.start or day
    end = args.end or day
    config = load_config(args.config)

    # 路径基准：config.yaml 的 workspace（可选）。
    # 绝对路径直接使用；相对路径（含默认子目录）以 workspace 为基准，未配置则相对当前目录。
    workspace_cfg = str(config.get("workspace") or "").strip()
    workspace = Path(workspace_cfg).expanduser().resolve() if workspace_cfg else None

    def resolve_path(value, default_rel):
        if value:
            p = Path(value).expanduser()
            if p.is_absolute() or workspace is None:
                return p.resolve()
            return (workspace / p).resolve()
        return (workspace / default_rel).resolve() if workspace else Path(default_rel).resolve()

    if workspace:
        print(f"  工作区(workspace): {workspace}")

    data_dir = resolve_path(args.data_dir or config.get("data_dir"), "data/klines")
    if not data_dir.is_dir():
        sys.exit(f"❌ K线目录不存在: {data_dir}"
                 "（用 --data-dir、config.yaml 的 data_dir 或 workspace 指定）")
    print(f"  K线目录(data_dir): {data_dir}")

    snapshot_base = resolve_path(args.snapshot_dir, "snapshot") / day
    if not snapshot_base.is_dir():
        sys.exit(f"❌ 快照目录不存在: {snapshot_base}，请先运行 sync-exee.py")

    output_base = (resolve_path(args.output_dir, "replay_outputs") / day).resolve()
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
            strat_names, symbols = collect_symbols_rust(proj_dir, klines_dir=data_dir)
            if not strat_names or not symbols:
                print(f"  ⚠ {name}: Rust 快照无可回测策略/代币，跳过")
                fail += 1
                continue
            print(f"  策略: {','.join(strat_names)}")
            print(f"  代币: {','.join(symbols)}")

            if run_replay_rust(proj_dir, out_dir, start, end, strat_names[0], symbols,
                               data_dir=data_dir):
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

        ensure_klines_link(proj_dir, data_dir)
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

    # Phase 7: 看板数据生成（条件：config.frontend_data_dir 或 --frontend-out 非空）
    frontend_out = str(args.frontend_out or config.get("frontend_data_dir") or "").strip()
    if frontend_out and success > 0:
        generator = Path(__file__).with_name("generate-kanban-data.py")
        if not generator.is_file():
            print(f"  ⚠ 未找到生成器: {generator}，跳过 frontend-data")
        else:
            frontend_abs = resolve_path(frontend_out, "frontend-data")
            cmd = [sys.executable, str(generator), "--date", day,
                   "--out", str(frontend_abs),
                   "--replay-data", str(resolve_path(None, "replay_data")),
                   "--replay-outputs", str(resolve_path(args.output_dir, "replay_outputs")),
                   "--snapshot", str(resolve_path(args.snapshot_dir, "snapshot")),
                   "--klines", str(data_dir)]
            print("\n=== Phase 7: 生成 frontend-data ===")
            print(f"  $ {' '.join(cmd)}")
            rc = subprocess.run(cmd).returncode
            if rc == 0:
                print(f"  ✅ frontend-data → {frontend_abs}/{day}/")
            else:
                print(f"  ❌ frontend-data 生成失败 (exit {rc})")
                fail += 1
    elif not frontend_out:
        print("  ⚠ 未配置 frontend_data_dir（或 --frontend-out），跳过看板数据生成")

    print(f"\n=== 完成: {success} 成功, {fail} 失败 ===")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
