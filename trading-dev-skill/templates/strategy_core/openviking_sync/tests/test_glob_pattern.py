"""测试 glob pattern 递归搜索"""

from datetime import datetime
from pathlib import Path
import pytest

from strategy_core.openviking_sync.universal_syncer import UniversalSyncer
from strategy_core.openviking_sync.ov_client import OpenVikingConfig


class MockOvClient:
    """Mock OpenViking client"""
    def ensure_account(self):
        pass


class TestGlobPattern:
    """测试 glob pattern 递归和非递归搜索"""

    @pytest.fixture
    def setup_files(self, tmp_path: Path):
        """创建测试文件结构"""
        # 创建根目录文件（非递归 pattern 能找到）
        root_file = tmp_path / "test.md"
        root_file.write_text("root content")

        # 创建子目录文件（只有递归 pattern 能找到）
        subdir = tmp_path / "20260622"
        subdir.mkdir()
        sub_file = subdir / "test.md"
        sub_file.write_text("sub content")

        return tmp_path, root_file, sub_file

    def test_non_recursive_pattern_only_finds_root(self, setup_files):
        """非递归 pattern 只在根目录搜索"""
        base_dir, root_file, sub_file = setup_files

        config = {
            "paths": [str(base_dir)],
            "pattern": "test.md",  # 非递归
        }

        syncer = UniversalSyncer("test", config, MockOvClient())
        files = syncer._scan_files(datetime(2026, 6, 22))

        assert root_file in files
        assert sub_file not in files  # 子目录文件不会被找到

    def test_recursive_pattern_finds_all(self, setup_files):
        """递归 pattern 搜索所有子目录"""
        base_dir, root_file, sub_file = setup_files

        config = {
            "paths": [str(base_dir)],
            "pattern": "**/test.md",  # 递归
        }

        syncer = UniversalSyncer("test", config, MockOvClient())
        files = syncer._scan_files(datetime(2026, 6, 22))

        assert root_file in files
        assert sub_file in files  # 子目录文件会被找到

    def test_signal_comparison_pattern_must_be_recursive(self, setup_files):
        """signal_comparison 的 pattern 必须是递归的"""
        base_dir, root_file, sub_file = setup_files

        # 模拟 signal_comparison 配置
        config = {
            "paths": [str(base_dir)],
            "pattern": "**/comparison_report.md",  # 正确的递归 pattern
            "date_from": "{parent_dir}",
        }

        # 创建 comparison_report.md 在子目录
        subdir = base_dir / "20260622"
        report_file = subdir / "comparison_report.md"
        report_file.write_text("# Report")

        syncer = UniversalSyncer("signal_comparison", config, MockOvClient())
        files = syncer._scan_files(datetime(2026, 6, 22))

        assert report_file in files
