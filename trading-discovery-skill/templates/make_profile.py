#!/usr/bin/env python3
"""make_profile.py — 生成回测 run-profile (config/<name>.yaml)

v3.7 模板把回测专有参数（timeframe/data_dir/output_dir/cash/commission/
max_workers）从 CLI 下放到 config/<profile>.yaml，由 --profile 选取。
本脚本按需生成一个临时 profile，让 discovery/replay 能指定自己的 output_dir
而不改动项目入库的 config/backtest.yaml。

硬约束（来自 backtest/config_loader.py）:
  1. profile.data_dir 必须与 config/settings.yaml 的 data_manager.csv_dir
     完全一致，否则 verify_data_dir_consistency() 抛错、回测启动即退出。
     => data_dir 只能照抄 settings.yaml，不可自定义。
  2. profile 文件名不能是 settings / strategies / settings.example /
     strategies.example（RESERVED_CONFIG_NAMES 守卫）。
  3. profile 名不能含路径分隔符或以 . 开头。

用法:
    python3 make_profile.py --project-dir /path/to/cta --name discovery \
        --output-dir /abs/path/discovery_outputs --max-workers 4
"""

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: 需要 PyYAML（pip install pyyaml）", file=sys.stderr)
    sys.exit(2)

# 与 backtest/config_loader.py 的 RESERVED_CONFIG_NAMES 保持一致
RESERVED_NAMES = frozenset({
    "settings", "settings.example", "strategies", "strategies.example",
})


def read_settings_csv_dir(project_dir: Path) -> str:
    """从 config/settings.yaml 读 data_manager.csv_dir。

    返回空串表示 settings.yaml 不存在或未配置该键 —— 此时
    verify_data_dir_consistency() 会放行，但数据仍需真实存在，
    调用方应把默认值 ./data/klines 与实际数据目录核对。
    """
    settings = project_dir / "config" / "settings.yaml"
    if not settings.is_file():
        return ""
    try:
        with open(settings, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
    except Exception as e:
        print(f"WARN: 读取 {settings} 失败: {e}", file=sys.stderr)
        return ""
    dm = cfg.get("data_manager") or {}
    if not isinstance(dm, dict):
        return ""
    return str(dm.get("csv_dir") or "")


def main() -> int:
    p = argparse.ArgumentParser(description="生成回测 run-profile")
    p.add_argument("--project-dir", required=True,
                   help="CTA 项目根目录（含 config/ backtest/ strategies/）")
    p.add_argument("--name", required=True,
                   help="profile 名，生成 config/<name>.yaml")
    p.add_argument("--output-dir", required=True,
                   help="回测产物输出目录（本 profile 的唯一自定义项）")
    p.add_argument("--start", default="", help="profile.start（通常由 CLI 覆盖）")
    p.add_argument("--end", default="", help="profile.end（通常由 CLI 覆盖）")
    p.add_argument("--cash", type=float, default=5000)
    p.add_argument("--commission", type=float, default=0.0004)
    p.add_argument("--max-workers", type=int, default=4,
                   help="batch_runner 并发数（对应旧 --parallel）")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p.add_argument("--use-today-as-output-date", default="true",
                   choices=["true", "false"])
    args = p.parse_args()

    name = args.name
    if "/" in name or "\\" in name or name.startswith("."):
        print(f"ERROR: profile 名不能含路径分隔符或以 . 开头: {name!r}",
              file=sys.stderr)
        return 1
    if name in RESERVED_NAMES:
        print(f"ERROR: profile 名 {name!r} 被模板保留（系统层/编排层配置）",
              file=sys.stderr)
        return 1

    project_dir = Path(args.project_dir)
    config_dir = project_dir / "config"
    if not config_dir.is_dir():
        print(f"ERROR: 不是有效的项目根目录（缺 config/）: {project_dir}",
              file=sys.stderr)
        return 1

    csv_dir = read_settings_csv_dir(project_dir)
    if csv_dir:
        data_dir = csv_dir
    else:
        data_dir = "./data/klines"
        print(
            "WARN: config/settings.yaml 未配置 data_manager.csv_dir，"
            f"profile.data_dir 取默认值 {data_dir}",
            file=sys.stderr,
        )

    profile = {
        "start": args.start,
        "end": args.end,
        "cash": args.cash,
        "commission": args.commission,
        # data_dir 必须照抄 settings.yaml 的 csv_dir，见文件头约束 1
        "data_dir": data_dir,
        "output_dir": args.output_dir,
        "use_today_as_output_date": args.use_today_as_output_date == "true",
        "log_level": args.log_level,
        "max_workers": args.max_workers,
    }

    target = config_dir / f"{name}.yaml"
    header = (
        f"# 自动生成的 run-profile（{name}）— 由 make_profile.py 写入，可安全删除\n"
        "# 只承载回测运行方式，绝不含策略参数\n"
        "# （策略参数唯一来源是 strategies/<name>/overrides/<SYMBOL>.yaml）\n"
        f"# data_dir 照抄 config/settings.yaml 的 data_manager.csv_dir，改动会导致启动校验失败\n"
    )
    with open(target, "w", encoding="utf-8") as f:
        f.write(header)
        yaml.safe_dump(profile, f, allow_unicode=True, sort_keys=False)

    # stdout 只输出 profile 名，供调用方 $(...) 捕获
    print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
