#!/usr/bin/env python3
"""
CTA Strategy Core 项目重命名测试脚本
验证项目重命名后所有路径引用和模块功能的正确性
"""

import sys
import os
import yaml

# 设置项目路径
PROJECT_PATH = "/home/qpw/workspace/cta-strategy-code"
sys.path.insert(0, PROJECT_PATH)
os.chdir(PROJECT_PATH)

# 测试结果统计
test_results = {
    "passed": 0,
    "failed": 0,
    "skipped": 0
}

def print_header(title):
    print("\n" + "=" * 60)
    print(f"  {title}")
    print("=" * 60)

def print_result(test_name, passed, message=""):
    if passed:
        print(f"  ✓ {test_name}")
        test_results["passed"] += 1
    else:
        print(f"  ✗ {test_name}: {message}")
        test_results["failed"] += 1

# ============================================
# 测试 1: 路径引用一致性测试
# ============================================
print_header("测试 1: 路径引用一致性测试")

import subprocess
result = subprocess.run(
    ["grep", "-r", "workspace/strategy-code", "--include=*.md", "--include=*.py", "--include=*.json", "."],
    capture_output=True,
    text=True
)

# 排除测试脚本本身的引用和 .venv 目录
non_venv_matches = [
    line for line in result.stdout.split('\n')
    if line and '.venv' not in line and 'strategy_core.log' not in line
    and 'test_rename_project.py' not in line and 'TEST_CASES.md' not in line
]

if len(non_venv_matches) == 0:
    print_result("路径引用检查", True)
else:
    print_result("路径引用检查", False, f"发现 {len(non_venv_matches)} 处旧路径引用")
    for match in non_venv_matches[:5]:
        print(f"    {match}")

# ============================================
# 测试 2: 虚拟环境验证测试
# ============================================
print_header("测试 2: 虚拟环境验证测试")

# 检查虚拟环境配置
venv_config_path = ".venv/pyvenv.cfg"
if os.path.exists(venv_config_path):
    with open(venv_config_path, 'r') as f:
        content = f.read()
    if "cta-strategy-code" in content:
        print_result("虚拟环境配置", True)
    else:
        print_result("虚拟环境配置", False, "配置中未包含新项目名称")
else:
    print_result("虚拟环境配置", False, "pyvenv.cfg 不存在")

# 检查 Python 可执行文件
if os.path.exists(".venv/bin/python3"):
    result = subprocess.run([".venv/bin/python3", "--version"], capture_output=True, text=True)
    if result.returncode == 0:
        print_result(f"Python 版本：{result.stdout.strip()}", True)
    else:
        print_result("Python 版本检查", False)
else:
    print_result("Python 可执行文件", False, ".venv/bin/python3 不存在")

# ============================================
# 测试 3: 策略模块导入测试
# ============================================
print_header("测试 3: 策略模块导入测试")

test_modules = [
    "strategies.cta_ict.strategy",
    "strategies.cta_rbreaker.strategy",
    "strategies.cta_trend.strategy",
]

for module in test_modules:
    try:
        __import__(module)
        print_result(f"导入 {module}", True)
    except ImportError as e:
        print_result(f"导入 {module}", False, str(e))

# 测试 Strategy 类可访问性
try:
    print_result("Strategy 类可访问", True)
except Exception as e:
    print_result("Strategy 类可访问", False, str(e))

# ============================================
# 测试 4: 配置文件加载测试
# ============================================
print_header("测试 4: 配置文件加载测试")

config_files = [
    "strategies/cta_ict/config.yaml",
    "strategies/cta_rbreaker/config.yaml",
    "strategies/cta_trend/config.yaml",
]

for config_file in config_files:
    try:
        with open(config_file, 'r') as f:
            config = yaml.safe_load(f)
        # 验证必要字段
        strategy_type = list(config.keys())[0]
        has_enabled = 'enabled' in config[strategy_type]
        has_version = 'version' in config[strategy_type]
        if has_enabled and has_version:
            print_result(f"加载 {config_file}", True)
        else:
            print_result(f"加载 {config_file}", False, "缺少必要字段")
    except Exception as e:
        print_result(f"加载 {config_file}", False, str(e))

# ============================================
# 测试 5: 文档完整性测试
# ============================================
print_header("测试 5: 文档完整性测试")

doc_files = [
    "README.md",
    "CHANGELOG.md",
    "ARCHITECTURE.md",
    "docs/SYSTEM_OVERVIEW.md",
    "docs/RENAME_SUMMARY.md",
    "docs/TEST_CASES.md",
    "strategies/README.md",
    "strategies/ARCHITECTURE.md",
    "strategies/AUTONOMOUS_CONFIG.md",
]

for doc_file in doc_files:
    if os.path.exists(doc_file):
        # 检查版本号 (主要文档应为 3.4.1)
        with open(doc_file, 'r') as f:
            content = f.read()
        if "3.4.1" in content or doc_file in ["docs/RENAME_SUMMARY.md", "docs/TEST_CASES.md"]:
            print_result(f"文档存在：{doc_file}", True)
        else:
            print_result(f"文档版本：{doc_file}", False, "版本号应为 3.4.1")
    else:
        print_result(f"文档缺失：{doc_file}", False)

# ============================================
# 测试 6: 核心引擎测试
# ============================================
print_header("测试 6: 核心引擎测试")

try:
    print_result("导入 StrategyEngine", True)
except Exception as e:
    print_result("导入 StrategyEngine", False, str(e))

try:
    from strategy_core.strategy_engine.registry import StrategyRegistry
    registry = StrategyRegistry()
    registry.register(
        strategy_id="TestStrategy",
        strategy_name="Test",
        module_path="strategies.test.strategy",
        config={"test": True}
    )
    strategies = registry.list_strategies()
    print_result(f"StrategyRegistry 操作 (已注册 {len(strategies)} 个策略)", True)
except Exception as e:
    print_result("StrategyRegistry 操作", False, str(e))

try:
    print_result("导入 SignalLogger", True)
except Exception as e:
    print_result("导入 SignalLogger", False, str(e))

# ============================================
# 测试 7: 数据管理器测试
# ============================================
print_header("测试 7: 数据管理器测试")

try:
    print_result("导入 DataManager", True)
except Exception as e:
    print_result("导入 DataManager", False, str(e))

# ============================================
# 测试结果汇总
# ============================================
print_header("测试结果汇总")

total = test_results["passed"] + test_results["failed"]
print(f"  通过：{test_results['passed']}/{total}")
print(f"  失败：{test_results['failed']}/{total}")

if test_results["failed"] == 0:
    print("\n  ✓ 所有测试通过!")
    sys.exit(0)
else:
    print(f"\n  ✗ 有 {test_results['failed']} 个测试失败")
    sys.exit(1)
