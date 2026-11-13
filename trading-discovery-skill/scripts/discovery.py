#!/usr/bin/env python3
"""discovery.py — 指定代币/策略/时间范围的回测探索

遍历已下载好的策略目录，对每个策略执行回测，结果输出到
discovery_outputs/{策略目录}/。

策略目录由 SKILL.md Phase 0.5 提前 git clone/pull 就绪，本脚本只做遍历，
不再执行 clone。遍历入口有两类：
  1. config.yaml 登记表：顶层 key = 策略目录名（推荐，可只回测子集）
  2. --strategies-dir 直接扫目录：列出其下所有策略文件夹

config.yaml 结构（= templates/config.example.yaml，git_url 字段已不再消费，
留作登记可空）:
    strategy_name1:
      git_url:
    strategy_name2:
      git_url:

用法:
    python3 discovery.py --start 20260601 --end 20260801
    python3 discovery.py --start 20260601 --strategies sar_snt,obv_atr
    python3 discovery.py --start 20260601 --config config.yaml \\
        --backtest-config backtest.yaml --strategies-dir .

流程:
  1. 遍历策略目录（config.yaml 登记表 或 直接扫 --strategies-dir）
  2. 读 backtest.yaml，固定 data_dir / output_dir 口径：
       data_dir   = download_data.py 写入的 K 线目录（固定，回测读取）
       output_dir = discovery_outputs/{策略目录}/（每个策略一份产物根）
  3. 遍历每个策略目录，从 {策略目录}/config/strategies.yaml 读取代币清单
     （推荐入口；缺省回退 overrides/*.yaml 的文件名）
  4. 在每个策略目录里执行其自带的 scripts/run_backtest_batch.sh
     —— 每个策略一次调用，传该策略实际可回测的代币子集

约定:
  - 策略目录名 = config.yaml 顶层 key（= clone 目标 basename）
  - 回测参数（时间范围/资金/费率/输出/并发）走 backtest.yaml（run-profile）
  - 策略参数唯一来源 = strategies/<name>/overrides/<SYM>.yaml（wrapper 预检）
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: 需要 PyYAML（pip install pyyaml）", file=sys.stderr)
    sys.exit(2)


def parse_time(value: str) -> str:
    """解析时间输入，统一输出为 YYYYMMDD 格式。

    支持两种格式（与 SKILL.md Phase 1 Step 2 一致）：
      - YYYYMMDD（8 位纯数字）
      - Unix 时间戳（10 位纯数字，秒级）
    """
    if not value:
        sys.exit("❌ 缺少 --start（必需，格式 YYYYMMDD 或 Unix 时间戳）")
    if value.isdigit() and len(value) == 10:
        from datetime import datetime
        dt = datetime.fromtimestamp(int(value))
        return dt.strftime("%Y%m%d")
    if value.isdigit() and len(value) == 8:
        return value
    sys.exit(f"❌ 无法识别的时间格式: {value}，支持 YYYYMMDD 或 Unix 时间戳")


def load_yaml(path) -> dict:
    """加载 YAML 配置，文件不存在则退出。"""
    p = Path(path)
    if not p.is_file():
        sys.exit(f"❌ 配置文件不存在: {path}")
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def read_strategy_config(proj_dir, strategy_name) -> dict:
    """读取策略目录下第一份含 strategy 字段的 YAML。"""
    cfg_dir = Path(proj_dir) / "config" / (strategy_name or "")
    if not cfg_dir.is_dir():
        return {}
    for path in sorted(cfg_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict) and data.get("strategy"):
            return data
    return {}


def write_project_meta(out_dir, strategy, engine, config) -> None:
    """落盘 engine/timeframe/leverage，供 frontend 转换器读取。"""
    meta = {"strategy": strategy, "engine": engine}
    if isinstance(config, dict):
        for key in ("timeframe", "leverage", "warmup_days"):
            if config.get(key) is not None:
                meta[key] = config[key]
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    (Path(out_dir) / ".meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def discover_strategy_dirs(strategies_parent: Path, config: dict, only=None):
    """遍历策略目录，yield (策略目录名, 绝对路径)。

    优先用 config.yaml 登记表（顶层 key = 策略目录名）；
    config.yaml 不存在或为空时，直接扫 strategies_parent 下所有含
    scripts/run_backtest_batch.sh 的子目录（兜底）。
    only 非空时只保留集合内的目录名。
    """
    entries = []
    if config:
        for name in config.keys():
            entries.append(name)
    if not entries:
        # 兜底：扫目录，挑出有 wrapper 的策略文件夹
        if strategies_parent.is_dir():
            for sub in sorted(strategies_parent.iterdir()):
                if sub.is_dir() and (sub / "scripts" / "run_backtest_batch.sh").is_file():
                    entries.append(sub.name)

    seen = set()
    for name in entries:
        if only is not None and name not in only:
            continue
        if name in seen:
            continue
        seen.add(name)
        yield name, strategies_parent / name


def read_symbols_from_registry(strategy_dir: Path):
    """从 {策略目录}/config/strategies.yaml 读取代币清单（推荐入口）。

    格式见 trading-dev templates/config/strategies.yaml：
        strategies:
          <strategy_name>:
            symbols:
              - BTCUSDT
              - name: ETHUSDT   # 也支持对象格式
    返回 (symbols 列表, 来源描述)。读不到返回 ([], None)。
    同时返回该登记表里的策略包名（strategies 段 key），用于 wrapper --strategies。
    """
    registry = strategy_dir / "config" / "strategies.yaml"
    if not registry.is_file():
        return [], None, None
    try:
        with open(registry, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"  ⚠ 读取 {registry} 失败: {e}", file=sys.stderr)
        return [], None, None

    strategies = data.get("strategies") or {}
    if not isinstance(strategies, dict):
        return [], str(registry), None

    symbols = []
    pkg_names = []
    for pkg_name, cfg in strategies.items():
        pkg_names.append(pkg_name)
        if not isinstance(cfg, dict):
            continue
        for sym in cfg.get("symbols") or []:
            if isinstance(sym, dict):
                sym = sym.get("name")
            if sym:
                symbols.append(str(sym).upper())
    # 去重保序
    seen = set()
    unique = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            unique.append(s)
    return unique, str(registry), ",".join(pkg_names) if pkg_names else None


def fallback_symbols_from_overrides(strategy_dir: Path):
    """无 strategies.yaml 时，从 overrides/*.yaml 文件名反推代币。

    overrides/<SYMBOL>.yaml 是 v3.7 策略参数唯一来源，文件名即代币名。
    这是兜底路径，不如 strategies.yaml 可靠（无法区分 live/paper）。
    覆盖 {策略目录}/strategies/<pkg>/overrides/ 一层。
    """
    strategies_root = strategy_dir / "strategies"
    symbols = []
    if strategies_root.is_dir():
        for sub in sorted(strategies_root.iterdir()):
            ov = sub / "overrides"
            if not ov.is_dir():
                continue
            for f in sorted(ov.glob("*.yaml")):
                sym = f.stem.upper()
                if sym not in ("__INIT__",) and sym not in symbols:
                    symbols.append(sym)
    return symbols


def ensure_overrides(proj_dir: Path, pkg_names: str, symbols: list) -> None:
    """Phase 3 配置兜底：对缺 overrides 的代币调 init_overrides.py 补建。

    wrapper 的 precheck_overrides 校验 strategies/<pkg>/overrides/<SYM>.yaml，
    任一缺失即拒绝整批。这里在回测前先把缺的补上：复制同策略已有 override
    （init_overrides.py 的 sibling 模板路径），新建一律 paper_trading。

    init_overrides 的 --strategy-dir 指向含 overrides/ 的那层 =
    {策略目录}/strategies/<pkg>/，不是 clone 顶层目录。

    失败不阻塞：记 warning 后继续，wrapper 的 precheck 仍会兜底拒绝并给明确提示。
    """
    init_script = Path(__file__).resolve().parent / "init_overrides.py"
    if not init_script.is_file():
        print(f"  ⚠ 未找到 init_overrides.py（{init_script}），跳过配置兜底")
        return

    for pkg in (s.strip() for s in pkg_names.split(",") if s.strip()):
        pkg_dir = proj_dir / "strategies" / pkg
        if not pkg_dir.is_dir():
            continue
        missing = [sym for sym in symbols
                   if not (pkg_dir / "overrides" / f"{sym}.yaml").is_file()]
        if not missing:
            continue
        print(f"  📝 {pkg}: 缺 {len(missing)} 个 overrides，调 init_overrides 兜底")
        cmd = [sys.executable, str(init_script),
               "--strategy-dir", str(pkg_dir),
               "--symbols", ",".join(missing)]
        print(f"  $ {' '.join(cmd)}")
        r = subprocess.run(cmd, cwd=str(proj_dir))
        if r.returncode != 0:
            print(f"  ⚠ {pkg}: init_overrides 返回 {r.returncode}"
                  "（wrapper 的 precheck 仍会兜底拒绝）")


def ensure_venv(proj_dir: Path):
    """在策略目录内创建/复用 .venv，返回 venv 的 python 路径。

    与 replay.py 一致：不真的 source，而是把 venv/bin 前置到 PATH，
    效果等同激活。有 requirements.txt 顺带装依赖。
    """
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
    return python


def with_venv_env(venv_python):
    """构造激活了 venv 的环境变量（PATH 前置 venv/bin）"""
    env = os.environ.copy()
    venv_bin = str(Path(venv_python).parent)
    env["PATH"] = venv_bin + os.pathsep + env.get("PATH", "")
    env["VIRTUAL_ENV"] = str(Path(venv_python).parent.parent)
    return env


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


def read_symbols_rust(strategy_dir):
    """从 Rust 策略配置读取代币清单

    Rust 配置结构：config/{strategy}/example.yaml 或 config/{strategy}/{SYMBOL}.yaml
    代币在配置的 symbols 列表中（字符串或对象格式）。
    返回 (symbols 列表, 来源描述, strategy_name)。
    """
    config_root = strategy_dir / "config"
    symbols = []
    strategy_name = None

    if not config_root.is_dir():
        return [], None, None

    # 扫描所有 yaml 文件（跳过 _global）
    for yaml_file in sorted(config_root.rglob("*.yaml")):
        if yaml_file.name.startswith("_"):
            continue
        try:
            with open(yaml_file, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
        except Exception:
            continue
        if not isinstance(cfg, dict):
            continue

        # 获取策略名
        if "strategy" in cfg and isinstance(cfg["strategy"], str):
            strategy_name = cfg["strategy"]

        # 目录模式：{SYMBOL}.yaml 文件名即代币
        # （config/{strategy}/BTCUSDT.yaml；文件名定义 symbol，见策略仓 config.rs load_dir）
        if yaml_file.parent != config_root:
            stem = yaml_file.stem.upper()
            if stem != "EXAMPLE" and not stem.startswith("."):
                symbols.append(stem)

        # 从 symbols 列表收集代币
        for sym in cfg.get("symbols") or []:
            if isinstance(sym, dict):
                s = sym.get("symbol") or sym.get("name")
            elif isinstance(sym, str):
                s = sym
            else:
                continue
            if s:
                symbols.append(str(s).upper())

        # 单文件模式：顶层 symbol 字段
        if "symbol" in cfg:
            symbols.append(str(cfg["symbol"]).upper())

    # 去重保序
    seen = set()
    unique = []
    for s in symbols:
        if s not in seen:
            seen.add(s)
            unique.append(s)

    src = str(config_root) if unique else None
    return unique, src, strategy_name


def ensure_klines_link(proj_dir, data_dir):
    """把工作区 K 线目录软链到策略目录 data/klines

    Rust 策略仓自带的 scripts/run_backtest_batch.sh 以 $PROJ_DIR/data/klines
    作为 --data-dir（路径写死在策略仓内），因此由本脚本根据 backtest.yaml
    的 data_dir 建立软链，使 K 线目录可配置且策略仓无需改动。
    已存在真实目录时不覆盖（尊重策略仓本地数据）。
    """
    if not data_dir:
        return
    src = Path(data_dir).expanduser().resolve()
    if not src.is_dir():
        print(f"  ⚠ K线目录不存在，跳过软链: {src}")
        return
    link = Path(proj_dir) / "data" / "klines"
    if link.is_symlink():
        if link.resolve() == src:
            return
        link.unlink()
    elif link.exists():
        print(f"  ⚠ {link} 已是真实目录，沿用策略仓自带 K 线（忽略 data_dir）")
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(src, target_is_directory=True)
    print(f"  K线软链: {link} → {src}")


def run_backtest_rust(proj_dir, start, end, symbols, out_dir, cash, commission,
                      data_dir=None, strategy_name=None):
    """执行 Rust 策略回测

    Rust 回测通过 cargo run --release -- backtest 调用。
    逐个代币串行执行，输出到 discovery_outputs/{strategy}/。
    data_dir 非空时先软链到策略目录 data/klines（wrapper 硬编码该路径）。
    strategy_name 非空且 config/<name>/ 存在时，用目录模式配置（含 per-symbol）。
    """
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    ensure_klines_link(proj_dir, data_dir)

    # 定位 Cargo.toml
    cargo_toml = proj_dir / "Cargo.toml"
    if not cargo_toml.is_file():
        print(f"  ❌ 未找到 Cargo.toml: {cargo_toml}")
        return False

    # 定位策略配置：优先 config/<strategy>/ 目录模式（含 per-symbol 覆盖），
    # 否则回退扫描第一个含 strategy 字段的 YAML（单文件模式）
    config_root = proj_dir / "config"
    def pick_config(symbol):
        """按代币选配置：{symbol}.yaml → example.yaml → 策略目录 → 首个含 strategy 的 YAML"""
        if strategy_name:
            strat_dir = config_root / strategy_name
            if strat_dir.is_dir():
                per = strat_dir / f"{symbol}.yaml"
                if per.is_file():
                    return per
                example = strat_dir / "example.yaml"
                if example.is_file():
                    return example
                return strat_dir
        for yaml_file in sorted(config_root.rglob("*.yaml")):
            if yaml_file.name.startswith("_"):
                continue
            try:
                with open(yaml_file, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
            except Exception:
                continue
            if isinstance(cfg, dict) and "strategy" in cfg:
                return yaml_file
        return None

    # 先编译
    print(f"  🔨 编译 Rust 项目...")
    r = subprocess.run(["cargo", "build", "--release"], cwd=str(proj_dir))
    if r.returncode != 0:
        print(f"  ❌ cargo build 失败")
        return False

    # 逐个代币执行回测
    all_ok = True
    for symbol in symbols:
        config_target = pick_config(symbol)
        if not config_target:
            print(f"  ❌ 未找到策略配置文件（config/*.yaml 中无 strategy 字段）")
            return False
        cmd = [
            "cargo", "run", "--release", "--", "backtest",
            "--config", str(config_target),
            "--symbol", symbol,
            "--start", start,
            "--output-dir", str(out_dir),
            "--cash", str(cash),
            "--leverage", "1",
        ]
        if data_dir:
            cmd += ["--data-dir", str(Path(data_dir).expanduser().resolve())]
        if end:
            cmd += ["--end", end]
        if commission:
            # Rust 版可能不支持 --commission 参数，忽略
            pass

        print(f"  $ {' '.join(cmd)}")
        r = subprocess.run(cmd, cwd=str(proj_dir))
        if r.returncode != 0:
            print(f"  ❌ {symbol}: 回测失败 (exit {r.returncode})")
            all_ok = False
        else:
            print(f"  ✅ {symbol}: 回测完成")

    return all_ok


def main():
    ap = argparse.ArgumentParser(description="指定代币/策略/时间范围的回测探索")
    ap.add_argument("--start", required=True,
                    help="回测开始时间 YYYYMMDD 或 Unix 时间戳（必需）")
    ap.add_argument("--end", default=None,
                    help="回测结束时间，默认当前时间")
    ap.add_argument("--config", default="config.yaml",
                    help="策略登记表路径（顶层 key=策略目录名）；不存在则扫 --strategies-dir")
    ap.add_argument("--backtest-config", default="backtest.yaml",
                    help="回测 run-profile 路径（data_dir / output_dir 固定）")
    ap.add_argument("--strategies-dir", default=".",
                    help="策略目录的父目录（策略文件夹在其下查找）")
    ap.add_argument("--output-root", default="./discovery_outputs",
                    help="discovery 产物根目录，每个策略一份子目录")
    ap.add_argument("--frontend-out", default=None,
                    help="frontend-data 根目录（覆盖 backtest.yaml 的 "
                         "frontend_data_dir；为空则跳过自动转换）")
    ap.add_argument("--strategies", default=None,
                    help="只回测指定策略（逗号分隔目录名），默认全部")
    ap.add_argument("--python", default=None,
                    help="Python 命令路径，默认探测 .venv/bin/python → python3")
    ap.add_argument("--log-level", default="INFO",
                    help="透传给 run_backtest_batch.sh 的日志级别")
    args = ap.parse_args()

    start = parse_time(args.start)
    end = args.end or ""

    # config.yaml 可不存在（兜底走扫目录），存在则用其登记表
    config = {}
    if Path(args.config).is_file():
        config = load_yaml(args.config)

    # 预检 1: backtest.yaml 是否存在（缺失时给出模板路径与必填字段）
    bt_path = Path(args.backtest_config)
    if not bt_path.is_file():
        skill_root = Path(__file__).resolve().parent.parent
        template = skill_root / "templates" / "backtest.example.yaml"
        print(f"❌ 配置文件不存在: {args.backtest_config}")
        print("   请先复制模板并填写：")
        print(f"     cp {template} {args.backtest_config}")
        print("     data_dir            K 线目录（需含 1m/{SYMBOL}_1m.csv）")
        print("     frontend_data_dir   看板输出目录（留空则不生成前端数据）")
        sys.exit(1)

    bt_config = load_yaml(args.backtest_config)

    # backtest.yaml 固定口径：data_dir = K 线目录，output_dir 每策略覆盖
    # Python 分支沿用原始写法（profile 需与 settings.csv_dir 字符串一致）；
    # Rust 分支用绝对路径建软链（相对 CWD 解析）。
    data_dir = bt_config.get("data_dir") or "./data/klines"
    data_dir_abs = str(Path(data_dir).expanduser().resolve())
    cash = bt_config.get("cash", 5000)
    commission = bt_config.get("commission", 0.0004)
    max_workers = bt_config.get("max_workers", 4)
    profile_start = bt_config.get("start", "")
    profile_end = bt_config.get("end", "")

    strategies_parent = Path(args.strategies_dir).resolve()
    output_root = Path(args.output_root).resolve()

    # --strategies 过滤
    only = None
    if args.strategies:
        only = {s.strip() for s in args.strategies.split(",") if s.strip()}

    print(f"=== discovery 开始，回测区间 {start} ~ {end or '<当前>'} ===")
    print(f"  策略父目录: {strategies_parent}")
    print(f"  回测 profile: {args.backtest_config}")
    print(f"  K线目录(data_dir): {data_dir}")
    print(f"  产物根(output_root): {output_root}")
    print(f"  并发(max_workers): {max_workers}")

    # 预检 2: K 线目录（Python 引擎可自动补数据，Rust 不会；仅告警不阻断）
    kline_dir = Path(data_dir).expanduser().resolve()
    kline_1m = kline_dir / "1m"
    has_klines = kline_1m.is_dir() and any(kline_1m.glob("*_1m.csv"))
    if not has_klines:
        downloader = Path(__file__).with_name("download_data.py")
        print(f"  ⚠ K线目录不存在或为空: {kline_1m}")
        print("     Rust 策略不会自动下载，请先执行：")
        print(f"       python3 {downloader} --symbols BTCUSDT --data-dir {kline_dir}")
        print("     Python 策略引擎可能自动补数据；若失败请同样先下载")

    # 预检 3: frontend_data_dir
    if not (args.frontend_out or bt_config.get("frontend_data_dir")):
        print("  ⚠ 未配置 frontend_data_dir（或 --frontend-out），"
              "本次不会生成 frontend-data")
    print()

    entries = list(discover_strategy_dirs(strategies_parent, config, only))
    if not entries:
        sys.exit("❌ 未找到任何策略目录"
                 f"（{strategies_parent} 下无含 scripts/run_backtest_batch.sh 的子目录，"
                 "且 config.yaml 无登记）")

    success, fail, skip = 0, 0, 0
    failures = []
    for name, proj_dir in entries:
        print(f"--- {name} → {proj_dir} ---")

        if not proj_dir.is_dir():
            print(f"  ⚠ {name}: 策略目录不存在，跳过")
            skip += 1
            continue

        # 自动检测语言类型
        lang = detect_lang(proj_dir)
        print(f"  语言: {lang}")

        if lang == "rust":
            # Rust 分支
            symbols, src, strategy_name = read_symbols_rust(proj_dir)
            if not symbols:
                print(f"  ⚠ {name}: 无法从 Rust 配置确定代币清单，跳过")
                skip += 1
                continue
            print(f"  代币({len(symbols)}): {', '.join(symbols)}  ← {src}")
            print(f"  策略名: {strategy_name}")

            out_dir = output_root / name
            out_dir.mkdir(parents=True, exist_ok=True)
            write_project_meta(out_dir, strategy_name, "rust",
                               read_strategy_config(proj_dir, strategy_name))

            if run_backtest_rust(proj_dir, start, end, symbols, out_dir, cash,
                                 commission, data_dir=data_dir_abs,
                                 strategy_name=strategy_name):
                print(f"  ✅ {name}: 回测完成 → {out_dir}/")
                success += 1
            else:
                print(f"  ❌ {name}: 回测失败")
                fail += 1
                failures.append(f"{name}: Rust 回测失败（检查 K 线目录/策略配置）")
            continue

        # Python 分支（现有逻辑不变）
        batch_script = proj_dir / "scripts" / "run_backtest_batch.sh"
        if not batch_script.is_file():
            print(f"  ⚠ {name}: 缺少 scripts/run_backtest_batch.sh（需模板 v3.7+），跳过")
            skip += 1
            continue

        # 步骤 3: 从 {策略目录}/config/strategies.yaml 读代币清单
        symbols, src, pkg_names = read_symbols_from_registry(proj_dir)
        if not symbols:
            symbols = fallback_symbols_from_overrides(proj_dir)
            src = "overrides/*.yaml（兜底）" if symbols else None
        if not symbols:
            print(f"  ⚠ {name}: 无法确定代币清单"
                  f"（{proj_dir}/config/strategies.yaml 不存在或无 symbols），跳过")
            skip += 1
            continue

        # wrapper 的 --strategies 要的是 strategies/ 下的策略包名，
        # 不一定等于 clone 目录名（前者如 sar_snt3_v3，后者如 sar_snt）。
        # 从 strategies.yaml 读真名，读不到则回退 clone 目录名。
        strategies_arg = pkg_names or name
        print(f"  代币({len(symbols)}): {', '.join(symbols)}  ← {src}")
        print(f"  策略包名: {strategies_arg}")

        # Phase 3 配置兜底：缺 overrides 的代币先补建，避免 wrapper 拒绝整批
        ensure_overrides(proj_dir, strategies_arg, symbols)

        # 步骤 2: 每策略一份 output_dir = discovery_outputs/{策略目录}/
        out_dir = output_root / name
        out_dir.mkdir(parents=True, exist_ok=True)
        write_project_meta(out_dir, strategies_arg, "python", {})

        # 写入该策略的 run-profile（output_dir/data_dir/cash/commission/并发）
        # wrapper 用 --profile <name> 读取 config/<name>.yaml；data_dir 必须与
        # settings.yaml 的 csv_dir 一致，否则 verify_data_dir_consistency 拒绝启动。
        profile_name = f"discovery_{name}"
        profile_path = proj_dir / "config" / f"{profile_name}.yaml"
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile = {
            "start": profile_start or start,
            "end": profile_end if profile_end else end,
            "cash": cash,
            "commission": commission,
            "data_dir": data_dir,
            "output_dir": str(out_dir),
            "use_today_as_output_date": True,
            "log_level": args.log_level,
            "max_workers": max_workers,
        }
        with open(profile_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(profile, f, allow_unicode=True, sort_keys=False)

        # 步骤 4: 在策略目录内执行其自带 wrapper
        # --yes 必须：非交互环境，任务数>6 时 wrapper 会 read 卡死
        cmd = ["bash", str(batch_script),
               "--strategies", strategies_arg,
               "--symbols", ",".join(symbols),
               "--start", start,
               "--profile", profile_name,
               "--log-level", args.log_level,
               "--yes"]
        if end:
            cmd += ["--end", end]

        # venv 激活（有 .venv 才建/复用）
        venv_python = ensure_venv(proj_dir)
        env = with_venv_env(venv_python) if venv_python else os.environ.copy()

        print(f"  $ {' '.join(cmd)}")
        r = subprocess.run(cmd, cwd=str(proj_dir), env=env)

        # 清理临时 profile
        try:
            profile_path.unlink()
        except OSError:
            pass

        if r.returncode == 0:
            print(f"  ✅ {name}: 回测完成 → {out_dir}/")
            success += 1
        else:
            print(f"  ❌ {name}: 回测失败 (exit {r.returncode})")
            fail += 1
            failures.append(f"{name}: Python 回测失败 exit {r.returncode}")

    # Phase 5: 自动转换为 frontend-data/discovery
    # 输出目录优先取 --frontend-out，其次 backtest.yaml 的 frontend_data_dir。
    frontend_out = args.frontend_out or bt_config.get("frontend_data_dir") or ""
    if frontend_out and success > 0:
        converter = Path(__file__).with_name("generate-discovery-data.py")
        if not converter.is_file():
            print(f"  ⚠ 未找到转换脚本: {converter}，跳过 frontend-data 生成")
        else:
            frontend_abs = Path(frontend_out).expanduser().resolve()
            cmd = [sys.executable, str(converter),
                   "--discovery-outputs", str(output_root),
                   "--out", str(frontend_abs)]
            print("\n=== Phase 5: 生成 frontend-data ===")
            print(f"  $ {' '.join(cmd)}")
            rc = subprocess.run(cmd).returncode
            if rc == 0:
                print(f"  ✅ frontend-data → {frontend_abs}/discovery/")
            else:
                print(f"  ❌ frontend-data 生成失败 (exit {rc})")
                fail += 1
                failures.append("frontend-data: 转换失败")

    print(f"\n=== 完成: {success} 成功, {fail} 失败, {skip} 跳过 ===")
    if failures:
        print("失败原因：")
        for item in failures:
            print(f"  - {item}")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
