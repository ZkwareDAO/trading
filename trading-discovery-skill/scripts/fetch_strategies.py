#!/usr/bin/env python3
"""fetch_strategies.py — 策略代码获取（git clone / pull）

对应 SKILL.md Phase 0.5：回测前先拉取/更新所有策略代码。

config.yaml 结构（= templates/config.example.yaml）:
    strategy_name1:
      git_url: git@github.com:user/sar_snt.git
    strategy_name2:
      git_url: https://github.com/user/obv_atr.git
    strategy_name3:
      git_url:            # 空 → 该策略跳过并告警

顶层 key = 策略目录名（git clone 的目标文件夹名）。

用法:
    # 拉取/更新 config.yaml 里所有策略
    python3 fetch_strategies.py

    # 指定配置和父目录
    python3 fetch_strategies.py --config config.yaml --strategies-dir .

    # 只更新某几个策略
    python3 fetch_strategies.py --strategies sar_snt,obv_atr

流程:
  1. 读 config.yaml，拿到所有 (策略目录名, git_url)
  2. 遍历配置文件的策略目录
  3. 分析本地目录：
       - 目录已存在且含 .git → git pull（更新到最新）
       - 目录不存在 → git clone <git_url> → <目录>
       - 目录存在但无 .git → 告警跳过（不像 git 仓库，不擅自覆盖）
       - git_url 为空 → 告警跳过

退出码：任一策略失败返回 1，全部成功返回 0。
"""

import argparse
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: 需要 PyYAML（pip install pyyaml）", file=sys.stderr)
    sys.exit(2)


def load_config(path: str) -> dict:
    """加载 config.yaml，文件不存在则退出。

    结构：顶层 key = 策略目录名，值为含 git_url 的 dict（可空）。
    """
    p = Path(path)
    if not p.is_file():
        sys.exit(f"❌ 配置文件不存在: {path}")
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def iter_strategies(config: dict):
    """遍历配置文件的策略目录，yield (策略目录名, git_url)

    顶层每个 key 是一个策略目录名。值为 dict 时取 git_url，为 None
    （登记了但没填 url）时 git_url 视为空串。
    """
    for name, cfg in config.items():
        if isinstance(cfg, dict):
            yield name, cfg.get("git_url") or ""
        elif cfg is None:
            yield name, ""


def git_op(args, cwd=None):
    """执行 git 命令，stdout/stderr 直接继承到终端（让用户看到进度）。

    返回 returncode。
    """
    return subprocess.run(["git"] + args, cwd=cwd).returncode


def fetch_strategy(name: str, git_url: str, parent: Path) -> bool:
    """分析本地目录，对单个策略执行 clone 或 pull。返回是否成功。

    - 目录已存在且含 .git → git pull
    - 目录不存在 → git clone <git_url>
    - 目录存在但无 .git → 告警跳过（不覆盖）
    - git_url 为空 → 告警跳过
    """
    target = parent / name

    if not git_url:
        print(f"  ⚠ {name}: config.yaml 未填 git_url，跳过")
        return False

    # 目录已存在但不是 git 仓库 —— 不擅自覆盖用户已有内容
    if target.is_dir() and not (target / ".git").exists():
        print(f"  ⚠ {name}: {target} 已存在但非 git 仓库，跳过（不覆盖）")
        return False

    if (target / ".git").is_dir():
        # 已是 git 仓库 → pull 更新
        print(f"  📥 {name}: git pull（{target}）")
        rc = git_op(["pull", "--ff-only"], cwd=str(target))
        if rc != 0:
            # --ff-only 失败多半是有本地改动或分叉，回退到普通 pull
            print(f"  ↻ {name}: --ff-only 失败，尝试普通 git pull")
            rc = git_op(["pull"], cwd=str(target))
        if rc == 0:
            print(f"  ✅ {name}: 已更新")
            return True
        print(f"  ❌ {name}: git pull 失败 (exit {rc})")
        return False

    # 目录不存在 → clone
    print(f"  📥 {name}: git clone {git_url} → {target}")
    parent.mkdir(parents=True, exist_ok=True)
    rc = git_op(["clone", git_url, str(target)])
    if rc == 0:
        print(f"  ✅ {name}: 已克隆")
        return True
    print(f"  ❌ {name}: git clone 失败 (exit {rc})，请检查地址和权限")
    return False


def list_strategies(parent: Path):
    """clone/pull 后列出可用策略（SKILL.md Phase 0.5 Step 3）"""
    print("\n📋 可用策略:")
    found = 0
    if not parent.is_dir():
        print(f"  （{parent} 不存在）")
        return
    for d in sorted(parent.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        # 统计配置文件数（config*.yaml 与 config/*.yaml，去重）
        cfgs = set()
        for p in list(d.rglob("config*.yaml")) + list(d.glob("config/*.yaml")):
            cfgs.add(p.relative_to(d))
        cfg_count = len(cfgs)
        has_wrapper = "✓" if (d / "scripts" / "run_backtest_batch.sh").is_file() else " "
        print(f"  {has_wrapper} {d.name} ({cfg_count} configs)")
        found += 1
    if not found:
        print("  （无策略目录）")


def main():
    ap = argparse.ArgumentParser(description="策略代码获取（git clone / pull）")
    ap.add_argument("--config", default="config.yaml",
                    help="策略登记表路径（顶层 key=策略目录名，含 git_url）")
    ap.add_argument("--strategies-dir", default=".",
                    help="策略目录的父目录（clone 目标在其下）")
    ap.add_argument("--strategies", default=None,
                    help="只处理指定策略（逗号分隔目录名），默认全部")
    ap.add_argument("--no-list", action="store_true",
                    help="跳过末尾的可用策略列表展示")
    args = ap.parse_args()

    config = load_config(args.config)
    parent = Path(args.strategies_dir).resolve()

    only = None
    if args.strategies:
        only = {s.strip() for s in args.strategies.split(",") if s.strip()}

    print(f"=== fetch_strategies 开始，父目录 {parent} ===")
    print(f"  配置: {args.config}")
    print()

    entries = list(iter_strategies(config))
    if only is not None:
        entries = [(n, u) for n, u in entries if n in only]
    if not entries:
        sys.exit("❌ 登记表中无策略（或 --strategies 过滤后为空）")

    success, fail = 0, 0
    seen = set()
    for name, git_url in entries:
        if name in seen:
            continue
        seen.add(name)
        if fetch_strategy(name, git_url, parent):
            success += 1
        else:
            fail += 1

    if not args.no_list:
        list_strategies(parent)

    print(f"\n=== 完成: {success} 成功, {fail} 失败 ===")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
