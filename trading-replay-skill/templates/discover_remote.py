#!/usr/bin/env python3
"""discover_remote.py — 远程实盘策略发现 (Phase 1.5)

SSH 到实盘机器，列出 SCP_PROJECT_DIR/strategies/ 下的策略目录，
获取每个策略的文件数、最后修改时间、目录大小，输出结构化结果。

用法:
    python3 discover_remote.py --config config.yaml
    python3 discover_remote.py --config config.yaml --json
    python3 discover_remote.py --config config.yaml --strategy ema_rsi
    python3 discover_remote.py --config config.yaml --output logs/remote-discovery.json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime


# ----- config loading (mirrors sync-exee.py pattern) -----

def _load_yaml(path: str) -> dict:
    """加载 YAML 配置文件"""
    if not os.path.exists(path):
        return {}
    try:
        import yaml
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        return {}


def _load_env(env_path: str = ".env") -> dict:
    """加载 .env 文件，返回 {KEY: value}"""
    env = {}
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _safe_int(value, default):
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _get_scp_config(config: dict, env: dict) -> dict:
    """合并远程连接配置 (.env 优先于 config.yaml)"""
    scp_cfg = config.get("scp", {})

    project_dir = env.get("SCP_PROJECT_DIR", scp_cfg.get("project_dir", ""))
    if not project_dir:
        strategy_dir = env.get("SCP_STRATEGY_DIR", scp_cfg.get("strategy_dir", ""))
        if strategy_dir.endswith("/strategies"):
            project_dir = strategy_dir.rstrip("/").rsplit("/strategies", 1)[0]

    return {
        "host": env.get("SCP_HOST", scp_cfg.get("host", "")),
        "port": env.get("SCP_PORT", scp_cfg.get("port", "22")),
        "user": env.get("SCP_USER", scp_cfg.get("user", "")),
        "project_dir": project_dir,
        "key": env.get("SCP_KEY", scp_cfg.get("key", "~/.ssh/id_rsa")),
        "timeout": _safe_int(env.get("SCP_TIMEOUT", scp_cfg.get("timeout", "30")), 30),
    }


def _build_ssh_cmd(scp_cfg: dict) -> list:
    """构建 SSH 基础命令"""
    key = os.path.expanduser(scp_cfg["key"])
    return [
        "ssh",
        "-p", str(scp_cfg["port"]),
        "-i", key,
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", "ConnectTimeout=" + str(scp_cfg["timeout"]),
        f"{scp_cfg['user']}@{scp_cfg['host']}",
    ]


# ----- remote discovery -----

def discover(scp_cfg: dict, strategy_filter: str = "") -> list[dict]:
    """SSH 到远程机器，发现策略目录及元信息

    Returns:
        [{"name": "ema_rsi", "file_count": 12, "last_modified": "2026-08-09 14:30", "size_kb": 256}, ...]
    """
    if not scp_cfg.get("host") or not scp_cfg.get("user") or not scp_cfg.get("project_dir"):
        return []

    remote_dir = f"{scp_cfg['project_dir'].rstrip('/')}/strategies"
    ssh_cmd = _build_ssh_cmd(scp_cfg)

    # 内联 shell 脚本：列出目录 + 文件数 + 修改时间 + 大小
    shell_script = f"""
STRATEGIES_DIR="{remote_dir}"
if [ ! -d "$STRATEGIES_DIR" ]; then
    echo '{{"error":"strategies directory not found"}}'
    exit 1
fi
echo "["
first=1
for d in "$STRATEGIES_DIR"/*/; do
    name=$(basename "$d")
    [ "$name" = "." ] && continue
    fc=$(find "$d" -type f 2>/dev/null | wc -l)
    ts=$(stat -c '%Y' "$d" 2>/dev/null || echo 0)
    sz=$(du -sk "$d" 2>/dev/null | cut -f1 || echo 0)
    [ $first -eq 1 ] && first=0 || echo ","
    printf '  {{"name":"%s","file_count":%d,"last_modified_ts":%d,"size_kb":%d}}\n' "$name" "$fc" "$ts" "$sz"
done
echo ""
echo "]"
"""
    try:
        result = subprocess.run(
            ssh_cmd + [shell_script],
            capture_output=True, text=True,
            timeout=scp_cfg["timeout"] * 3,
        )
    except subprocess.TimeoutExpired:
        print(f"❌ SSH 连接超时 ({scp_cfg['timeout'] * 3}s)", file=sys.stderr)
        return []
    except Exception as e:
        print(f"❌ SSH 执行异常: {e}", file=sys.stderr)
        return []

    if result.returncode != 0:
        stderr = result.stderr.strip()
        if "strategies directory not found" in (result.stdout + stderr):
            print(f"❌ 远程策略目录不存在: {remote_dir}", file=sys.stderr)
        else:
            print(f"❌ SSH 失败: {stderr or result.stdout.strip()}", file=sys.stderr)
        return []

    stdout = result.stdout.strip()
    if not stdout or stdout == "[]":
        print(f"⚠ 远程策略目录为空: {remote_dir}", file=sys.stderr)
        return []

    try:
        strategies = json.loads(stdout)
    except json.JSONDecodeError:
        print("❌ 远程输出解析失败", file=sys.stderr)
        return []

    # 时间戳→可读格式
    for s in strategies:
        ts = s.pop("last_modified_ts", 0)
        try:
            s["last_modified"] = datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M") if ts else "unknown"
        except (ValueError, OSError):
            s["last_modified"] = "unknown"

    if strategy_filter:
        strategies = [s for s in strategies if s["name"] == strategy_filter]

    return strategies


# ----- output formatting -----

def format_terminal(strategies: list[dict], scp_cfg: dict) -> str:
    """格式化终端人类可读输出"""
    remote_path = f"{scp_cfg['user']}@{scp_cfg['host']}:{scp_cfg['project_dir']}/strategies/"

    lines = [
        "",
        "=" * 62,
        "  远程实盘策略发现",
        "=" * 62,
        f"  来源:     {remote_path}",
        f"  策略数:   {len(strategies)}",
        "",
    ]

    if not strategies:
        lines.append("  ⚠ 未发现任何策略目录")
        lines.append("=" * 62)
        return '\n'.join(lines)

    for i, s in enumerate(strategies, 1):
        name = s["name"]
        fc = s.get("file_count", "?")
        lm = s.get("last_modified", "?")
        sz = s.get("size_kb", 0)
        sz_str = f"{sz}KB" if sz else "?"
        lines.append(
            f"  {i:2d}. {name:<28s} {fc:>4d} files  "
            f"{lm}  {sz_str:>8s}"
        )

    lines.extend([
        "",
        "-" * 62,
        "  model 类型: product(实盘) | smoking(模拟盘) | paper(纸上交易)",
        "  备份路径:   snapshot/{date}/{strategy}-{model}/",
        "=" * 62,
    ])
    return '\n'.join(lines)


def format_json(strategies: list[dict], scp_cfg: dict) -> dict:
    """格式化 JSON 输出"""
    return {
        "source": f"{scp_cfg['user']}@{scp_cfg['host']}:{scp_cfg['project_dir']}/strategies",
        "timestamp": datetime.now().isoformat(),
        "strategy_count": len(strategies),
        "strategies": strategies,
    }


# ----- main -----

def main():
    parser = argparse.ArgumentParser(description="远程实盘策略发现 (Phase 1.5)")
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    parser.add_argument("--strategy", default="", help="只查看指定策略")
    parser.add_argument("--output", default="", help="JSON 输出文件路径")
    args = parser.parse_args()

    config = _load_yaml(args.config)
    env = _load_env()
    scp_cfg = _get_scp_config(config, env)

    # 验证配置
    if not scp_cfg["host"]:
        msg = "SCP_HOST 未配置，请在 .env 中设置"
        print(json.dumps({"error": msg}, ensure_ascii=False) if args.json else f"❌ {msg}")
        sys.exit(1)
    if not scp_cfg["project_dir"]:
        msg = "SCP_PROJECT_DIR 未配置"
        print(json.dumps({"error": msg}, ensure_ascii=False) if args.json else f"❌ {msg}")
        sys.exit(1)

    strategies = discover(scp_cfg, strategy_filter=args.strategy)

    if args.json:
        print(json.dumps(format_json(strategies, scp_cfg), indent=2, ensure_ascii=False))
    else:
        print(format_terminal(strategies, scp_cfg))

    if args.output:
        os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(format_json(strategies, scp_cfg), f, indent=2, ensure_ascii=False)

    return 0 if strategies else 1


if __name__ == "__main__":
    sys.exit(main())
