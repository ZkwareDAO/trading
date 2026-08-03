"""
CLI 入口

命令行工具用于同步交易数据到 OpenViking。

Usage:
    python -m strategy_core.openviking_sync sync --today
    python -m strategy_core.openviking_sync sync --date 2026-05-29
    python -m strategy_core.openviking_sync sync --all
    python -m strategy_core.openviking_sync sync --today --source signals,positions
    python -m strategy_core.openviking_sync status
    python -m strategy_core.openviking_sync health
    python -m strategy_core.openviking_sync list-syncers
"""

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

from .sync_service import TradingDataSyncService
from .ov_client import OpenVikingClient, OpenVikingConfig

# 加载 .env 文件
load_dotenv()

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False):
    """配置日志"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def load_settings(settings_path: Optional[str] = None) -> dict:
    """加载配置文件"""
    if settings_path is None:
        # 优先使用独立配置文件
        settings_path = "./config/openviking_sync.yaml"

    path = Path(settings_path)
    if not path.exists():
        logger.warning(f"Settings file not found: {settings_path}")
        return {}

    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _parse_date(date_str: str) -> Optional[datetime]:
    """解析日期字符串"""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None


def _parse_strategies(strategy_str: Optional[str]) -> Optional[list]:
    """解析策略字符串"""
    if not strategy_str:
        return None
    return [s.strip() for s in strategy_str.split(",")]


def _parse_sources(source_str: Optional[str]) -> Optional[list]:
    """解析同步源字符串"""
    if not source_str:
        return None
    return [s.strip() for s in source_str.split(",")]


def _print_results(results: list, verbose: bool) -> int:
    """输出同步结果，返回退出码"""
    total_success = sum(r.total_success for r in results)
    total_failed = sum(r.total_failed for r in results)

    print(f"\nSync completed: {total_success} success, {total_failed} failed")

    if verbose and results:
        for r in results:
            print(f"\n  Date: {r.date}")

            # 按类型分组显示
            for result in r.results:
                status = "✓" if result.success else "✗"
                source_type = result.source_type
                source_name = result.source_name

                extra_info = ""
                if hasattr(result, 'strategy_name') and result.strategy_name:
                    extra_info += f" [{result.strategy_name}]"
                if hasattr(result, 'items_count'):
                    extra_info += f" ({result.items_count} items)"

                print(f"    {status} {source_type}/{source_name}{extra_info}")

    return 0 if total_failed == 0 else 1


def cmd_sync(args):
    """同步命令"""
    settings = load_settings(args.config)
    service = TradingDataSyncService.from_settings(settings, args.config)

    # 解析日期
    if args.today:
        date = datetime.now()
    elif args.date:
        date = _parse_date(args.date)
        if date is None:
            print(f"Error: Invalid date format: {args.date}. Use YYYY-MM-DD.")
            return 1
    else:
        date = None

    # 解析策略和同步源
    strategy_names = _parse_strategies(args.strategy)
    sources = _parse_sources(args.source)

    # 执行同步
    results = _execute_sync(args, service, date, strategy_names, sources)

    return _print_results(results, args.verbose)


def _execute_sync(
    args,
    service: TradingDataSyncService,
    date: Optional[datetime],
    strategy_names: Optional[list],
    sources: Optional[list],
) -> list:
    """执行同步操作，返回结果列表"""
    if args.all:
        print("Syncing all pending data...")
        return service.sync_all_pending()

    if args.start and args.end:
        print(f"Syncing range: {args.start} to {args.end}...")
        start = _parse_date(args.start)
        end = _parse_date(args.end)
        if start and end:
            return service.sync_range(start, end, strategy_names, sources)
        return []

    # 单日同步
    sync_date = date or datetime.now()
    print(f"Syncing: {sync_date.strftime('%Y-%m-%d')}")

    if sources:
        print(f"Sources: {', '.join(sources)}")

    result = service.sync_daily(
        sync_date,
        strategy_names,
        sources=sources,
    )
    return [result]


def cmd_status(args):
    """状态命令"""
    settings = load_settings(args.config)

    # 检查去重文件
    dedup_file = Path(settings.get("openviking_sync", {}).get("dedup", {}).get("file", "./data/.ov_synced_records"))

    print("Sync Status")
    print("=" * 40)

    if dedup_file.exists():
        with open(dedup_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            synced = data.get("synced", [])
            print(f"Synced records: {len(synced)}")
            if args.verbose and synced:
                for record in synced[:10]:
                    print(f"  - {record}")
                if len(synced) > 10:
                    print(f"  ... and {len(synced) - 10} more")
    else:
        print("No synced records found.")

    return 0


def cmd_health(args):
    """健康检查命令"""
    # 使用独立配置文件
    try:
        service = TradingDataSyncService.from_config_file(
            args.config or "./config/openviking_sync.yaml"
        )
        ov_config = service.ov_config
        client = service.ov_client
    except FileNotFoundError:
        # 回退到默认配置
        ov_config = OpenVikingConfig(
            server_url="http://localhost:1933",
            cli_path="ov",
        )
        client = OpenVikingClient(ov_config)

    print("OpenViking Health Check")
    print("=" * 40)

    # 检查 CLI
    import shutil
    cli_path = shutil.which(ov_config.cli_path)
    if cli_path:
        print(f"CLI: {cli_path} ✓")
    else:
        print(f"CLI: {ov_config.cli_path} not found ✗")

    # 检查服务
    if client.check_health():
        print(f"Server: {ov_config.server_url} ✓")
    else:
        print(f"Server: {ov_config.server_url} not responding ✗")

    return 0


def cmd_list_syncers(args):
    """列出同步器命令"""
    settings = load_settings(args.config)
    service = TradingDataSyncService.from_settings(settings, args.config)

    print("Registered Syncers")
    print("=" * 40)

    syncers = service.list_syncers()
    if syncers:
        for name in syncers:
            syncer = service.syncers.get(name)
            if syncer:
                print(f"  - {name}: {syncer.__class__.__name__}")
    else:
        print("  No syncers registered.")

    return 0


def cmd_list(args):
    """列出资源命令"""
    settings = load_settings(args.config)

    ov_config = OpenVikingConfig(
        server_url=settings.get("openviking", {}).get("server", {}).get("url", "http://localhost:1933"),
        cli_path=settings.get("openviking", {}).get("server", {}).get("cli_path", "ov"),
    )

    client = OpenVikingClient(ov_config)

    # 生成 URI
    if args.date:
        date = datetime.strptime(args.date, "%Y-%m-%d")
        uri = client.generate_daily_uri(date)
    else:
        uri = args.uri or "viking://resources/trading_data/"

    print(f"Listing: {uri}")
    print("=" * 40)

    resources = client.list_resources(uri)

    if resources:
        for r in resources:
            if isinstance(r, dict):
                print(f"  {r.get('uri', r)}")
            else:
                print(f"  {r}")
    else:
        print("  No resources found.")

    return 0


def main():
    """主入口"""
    parser = argparse.ArgumentParser(
        description="OpenViking Trading Data Sync Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-c", "--config",
        help="Path to settings.yaml",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # sync 命令
    sync_parser = subparsers.add_parser("sync", help="Sync trading data to OpenViking")
    sync_group = sync_parser.add_mutually_exclusive_group()
    sync_group.add_argument(
        "--today",
        action="store_true",
        help="Sync today's data",
    )
    sync_group.add_argument(
        "--date",
        help="Sync specific date (YYYY-MM-DD)",
    )
    sync_group.add_argument(
        "--all",
        action="store_true",
        help="Sync all pending data",
    )
    sync_parser.add_argument(
        "--start",
        help="Start date for range sync (YYYY-MM-DD)",
    )
    sync_parser.add_argument(
        "--end",
        help="End date for range sync (YYYY-MM-DD)",
    )
    sync_parser.add_argument(
        "--strategy",
        help="Comma-separated strategy names to sync",
    )
    sync_parser.add_argument(
        "--source",
        help="Comma-separated sync sources (e.g., signals,backtest,positions,history_positions)",
    )
    sync_parser.add_argument(
        "--only-signals",
        action="store_true",
        help="Sync only signals (deprecated, use --source)",
    )
    sync_parser.add_argument(
        "--only-backtest",
        action="store_true",
        help="Sync only backtest results (deprecated, use --source)",
    )
    sync_parser.set_defaults(func=cmd_sync)

    # status 命令
    status_parser = subparsers.add_parser("status", help="Show sync status")
    status_parser.set_defaults(func=cmd_status)

    # health 命令
    health_parser = subparsers.add_parser("health", help="Check OpenViking health")
    health_parser.set_defaults(func=cmd_health)

    # list-syncers 命令
    list_syncers_parser = subparsers.add_parser("list-syncers", help="List registered syncers")
    list_syncers_parser.set_defaults(func=cmd_list_syncers)

    # list 命令
    list_parser = subparsers.add_parser("list", help="List resources in OpenViking")
    list_parser.add_argument(
        "--date",
        help="List resources for specific date (YYYY-MM-DD)",
    )
    list_parser.add_argument(
        "--uri",
        help="List resources at specific URI",
    )
    list_parser.set_defaults(func=cmd_list)

    args = parser.parse_args()

    setup_logging(args.verbose)

    if args.command is None:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
