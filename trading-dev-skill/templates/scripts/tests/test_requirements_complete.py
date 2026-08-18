#!/usr/bin/env python3
"""依赖声明完整性测试

起因：`backtrader` 被 6 个文件 import 但从未写进 requirements.txt。开发机上它
碰巧装在 ~/.local，所以本地回测一直能跑；干净环境执行文档里的回测命令直接
`ModuleNotFoundError`。同理 `pytest` 只靠未使用的 py-clob-client-v2 传递依赖存在。

这类缺陷的特征是"在有污染的环境里不可见"，因此靠 AST 扫描而非运行时 import 来测：
用真实的 import 语句集合对账声明集合，两边都不能有多余。
"""

import ast
import pathlib
import sys

import pytest

# scripts/tests/ → scripts/ → 仓库根，故取 parents[2]
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

# 扫描时跳过：字节码缓存、vendored 依赖、归档脚本
SKIP_PARTS = ("__pycache__", ".venv", "site-packages", "node_modules", "docs/archive")

# import 名 → 发行包名（两者不一致的情况）
IMPORT_TO_PACKAGE = {
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "talib": "ta-lib",
    "kafka": "kafka-python-ng",
    "pandas_ta": "pandas-ta",
    "bt": "backtrader",
}

# 无需声明的 import：
#   pytest 在 requirements-dev.txt（本文件单独校验）
#   backtrader 的惯用别名由 IMPORT_TO_PACKAGE 处理
ALLOW_UNDECLARED = {"pytest"}


def _iter_source_files():
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT).as_posix()
        if any(part in rel for part in SKIP_PARTS):
            continue
        yield path


def _collect_third_party_imports():
    """AST 提取全库第三方顶层 import 名 → {module: {file, ...}}"""
    stdlib = set(sys.stdlib_module_names)
    local = {
        p.name for p in REPO_ROOT.iterdir() if p.is_dir() and not p.name.startswith(".")
    } | {p.stem for p in REPO_ROOT.glob("*.py")}

    found: dict[str, set[str]] = {}
    for path in _iter_source_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                top = name.split(".")[0]
                if top in stdlib or top in local:
                    continue
                found.setdefault(top, set()).add(rel)
    return found


def _parse_requirements(filename):
    """解析 requirements 文件为规范化的发行包名集合"""
    path = REPO_ROOT / filename
    if not path.exists():
        return set()
    packages = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].strip()
        if not line or line.startswith("-"):
            continue
        # 去掉版本约束与 extras: "pkg[x]>=1.0" → "pkg"
        for sep in (">=", "==", "<=", "~=", ">", "<", "[", ";"):
            line = line.split(sep)[0]
        packages.add(line.strip().lower().replace("_", "-"))
    return packages


@pytest.fixture(scope="module")
def imports():
    return _collect_third_party_imports()


@pytest.fixture(scope="module")
def declared():
    return _parse_requirements("requirements.txt") | _parse_requirements(
        "requirements-dev.txt"
    )


class TestNoUndeclaredImports:
    """代码 import 的包必须被声明 —— 否则干净环境直接崩"""

    def test_every_import_is_declared(self, imports, declared):
        missing = {}
        for module, files in imports.items():
            if module in ALLOW_UNDECLARED:
                continue
            pkg = IMPORT_TO_PACKAGE.get(module, module).lower().replace("_", "-")
            if pkg not in declared:
                missing[module] = (pkg, sorted(files)[:3])

        assert not missing, (
            "以下模块被 import 但未在 requirements 中声明，干净环境会 "
            "ModuleNotFoundError：\n"
            + "\n".join(
                f"  import {m} (需声明 {pkg}) — 例如 {files}"
                for m, (pkg, files) in sorted(missing.items())
            )
        )

    def test_backtrader_declared(self, declared):
        """回归锚点：backtrader 曾缺失，导致干净环境无法回测"""
        assert "backtrader" in declared

    def test_pytest_declared_explicitly(self):
        """pytest 必须显式声明，不能依赖其他包的传递依赖

        它曾只通过 py-clob-client-v2 → poly_eip712_structs 间接存在，
        删掉那个未使用的包后测试就跑不起来了。
        """
        assert "pytest" in _parse_requirements("requirements-dev.txt")


class TestNoUnusedDeclarations:
    """声明了但无人 import 的包应删除

    多余声明不只是体积问题：py-clob-client-v2 曾把 pytest 拽进环境，
    掩盖了"pytest 未被声明"这个真实缺陷。
    """

    # 类型 stub 与 pytest 插件不会被 import，属正常：
    #   types-*        供 mypy 读取，运行时无 import
    #   pytest-asyncio 通过 @pytest.mark.asyncio 标记生效，靠 entry point 注册
    NOT_IMPORTED_BY_DESIGN = {
        "types-requests",
        "types-pyyaml",
        "pytest-asyncio",
    }

    def test_no_unused_packages(self, imports, declared):
        used = {
            IMPORT_TO_PACKAGE.get(m, m).lower().replace("_", "-") for m in imports
        }
        unused = declared - used - self.NOT_IMPORTED_BY_DESIGN

        assert not unused, (
            "以下包已声明但全库无 import，应删除（多余依赖会掩盖真实的缺失依赖）：\n"
            + "\n".join(f"  {p}" for p in sorted(unused))
        )
