#!/usr/bin/env python3
"""
迁移信号 CSV 文件到新目录结构

旧结构: data/signals/{strategy_base_name}/{YYYYMMDD}.csv
        例如: data/signals/ICT/20260624.csv

新结构: data/signals/{strategy_full_name}/{YYYYMMDD}.csv
        例如: data/signals/ICT_1D_3_BNBUSDT_LIVE/20260624.csv

完整策略名构成: {strategy_name}_{interval}_{version}_{symbol}_{trading_mode}
- 从 CSV 行中提取字段组合

使用方法:
    python scripts/migrate_signals_dir.py --dry-run  # 预览迁移
    python scripts/migrate_signals_dir.py            # 执行迁移
"""

import argparse
import csv
import logging
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from strategy_core.utils.strategy_naming import build_strategy_id

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def build_full_strategy_name(row: Dict[str, str]) -> Optional[str]:
    """
    从 CSV 行构建完整策略实例名

    格式: {strategy_name}_{interval}_{version}_{symbol}_{trading_mode}
    例如: ICT_1D_3_BNBUSDT_LIVE
    """
    strategy_name = row.get("strategy_name", "").strip()
    interval = row.get("strategy_internal", "").strip()
    version = row.get("strategy_version", "").strip()
    symbol = row.get("symbol", "").strip()
    trading_mode = row.get("trading_mode", "live").strip()

    if not strategy_name or not symbol:
        logger.warning(f"缺少必要字段: strategy_name={strategy_name}, symbol={symbol}")
        return None

    return build_strategy_id(
        name=strategy_name,
        interval=interval,
        version=version,
        symbol=symbol,
        trading_mode=trading_mode,
    )


def migrate_csv_file(
    src_file: Path,
    dest_dir: Path,
    dry_run: bool = True,
) -> Tuple[int, Dict[str, Path]]:
    """
    迁移单个 CSV 文件

    将旧目录下的 CSV 按行拆分到新目录结构
    """
    if not src_file.exists():
        logger.error(f"文件不存在: {src_file}")
        return 0, {}

    strategy_rows: Dict[str, List[Dict[str, str]]] = defaultdict(list)

    with open(src_file, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            full_name = build_full_strategy_name(row)
            if full_name:
                strategy_rows[full_name].append(row)

    if not strategy_rows:
        logger.warning(f"无有效数据: {src_file}")
        return 0, {}

    date_str = src_file.stem
    migrated_count = 0
    target_files: Dict[str, Path] = {}

    for full_name, rows in strategy_rows.items():
        target_file = dest_dir / full_name / f"{date_str}.csv"
        target_files[full_name] = target_file
        logger.info(f"  {full_name}: {len(rows)} 行 -> {target_file}")

        if dry_run:
            migrated_count += len(rows)
            continue

        target_file.parent.mkdir(parents=True, exist_ok=True)

        # 检查目标文件已存在的 signal_id，避免重复写入
        existing_ids: set = set()
        if target_file.exists():
            with open(target_file, newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    existing_ids.add(r.get("signal_id", ""))

        # 过滤掉已存在的行
        new_rows = [r for r in rows if r.get("signal_id") not in existing_ids]
        skipped = len(rows) - len(new_rows)
        if skipped > 0:
            logger.info(f"    跳过 {skipped} 条已存在信号")

        if not new_rows:
            continue

        write_header = not target_file.exists()
        with open(target_file, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if write_header:
                writer.writeheader()
            writer.writerows(new_rows)

        migrated_count += len(new_rows)

    return migrated_count, target_files


def migrate_signals_dir(
    src_root: Path,
    dest_root: Path,
    dry_run: bool = True,
    remove_empty: bool = False,
) -> Tuple[int, int]:
    """迁移整个 signals 目录"""
    if not src_root.exists():
        logger.error(f"源目录不存在: {src_root}")
        return 0, 0

    total_files = 0
    total_rows = 0
    empty_dirs: List[Path] = []

    for base_name_dir in src_root.iterdir():
        if not base_name_dir.is_dir():
            continue

        logger.info(f"\n处理目录: {base_name_dir.name}/")
        csv_files = list(base_name_dir.glob("*.csv"))

        for csv_file in csv_files:
            logger.info(f"  文件: {csv_file.name}")
            rows, _ = migrate_csv_file(csv_file, dest_root, dry_run)
            total_rows += rows
            total_files += 1

        if remove_empty and not csv_files:
            empty_dirs.append(base_name_dir)

    if dry_run:
        logger.info(f"\n[预览] 共 {total_files} 文件, {total_rows} 行待迁移")
    else:
        logger.info(f"\n迁移完成: {total_files} 文件, {total_rows} 行")
        for dir_path in empty_dirs:
            logger.info(f"删除空目录: {dir_path}")
            dir_path.rmdir()

    return total_files, total_rows


def main():
    parser = argparse.ArgumentParser(
        description="迁移信号 CSV 到新目录结构",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
    # 预览迁移
    python scripts/migrate_signals_dir.py --dry-run

    # 执行迁移（原地）
    python scripts/migrate_signals_dir.py

    # 执行迁移并清理空目录
    python scripts/migrate_signals_dir.py --remove-empty
        """,
    )
    parser.add_argument(
        "--src",
        type=Path,
        default=Path("data/signals"),
        help="源目录 (默认: data/signals)",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="目标目录 (默认与源相同)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览，不实际迁移",
    )
    parser.add_argument(
        "--remove-empty",
        action="store_true",
        help="迁移后删除空目录",
    )

    args = parser.parse_args()

    dest = args.dest or args.src

    logger.info(f"信号目录迁移")
    logger.info(f"  源目录: {args.src}")
    logger.info(f"  目标目录: {dest}")
    logger.info(f"  预览模式: {args.dry_run}")
    logger.info("=" * 50)

    files, rows = migrate_signals_dir(
        args.src,
        dest,
        dry_run=args.dry_run,
        remove_empty=args.remove_empty,
    )

    if args.dry_run and rows > 0:
        logger.info("\n执行迁移请运行: python scripts/migrate_signals_dir.py")


if __name__ == "__main__":
    main()