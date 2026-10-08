#!/usr/bin/env python3
"""env_placeholders 的 ${VAR} 解析契约

本模块由 run_strategies_manager.py 与 run_strategy.py 共用（原先两处
逐字节重复，抽取为共享实现）。其核心语义有一处**不对称**，下游依赖它
做回退判断，必须锁定：

- 整串就是 `${VAR}`  → 返回 os.environ.get()，未设置时为 **None**
- 字符串内嵌 `${VAR}` → 做替换，未设置时替换为 **空串**

若把整串情形也变成空串，下游 `if value is None: 走回退` 的逻辑会失效
（空串是 falsy 但不是 None，某些判断走 `is None` 会漏掉）。
"""

import os

import pytest

from strategy_core.utils.env_placeholders import resolve_env_placeholders


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("PRESENT_VAR", "hello")
    monkeypatch.delenv("MISSING_VAR", raising=False)
    return monkeypatch


class TestWholeStringPlaceholder:
    """整串 ${VAR}：返回环境变量原值（可能是 None）"""

    def test_returns_value_when_set(self, env):
        assert resolve_env_placeholders("${PRESENT_VAR}") == "hello"

    def test_returns_none_when_unset(self, env):
        """未设置时必须是 None，不能是空串 —— 下游靠 None 走回退"""
        result = resolve_env_placeholders("${MISSING_VAR}")
        assert result is None, (
            f"整串 ${{MISSING_VAR}} 应返回 None，实得 {result!r}。"
            f"返回空串会让下游 `is None` 的回退判断失效。"
        )

    def test_surrounding_whitespace_is_tolerated(self, env):
        """两侧空白仍算整串匹配（实现用 obj.strip() 判定）"""
        assert resolve_env_placeholders("  ${PRESENT_VAR}  ") == "hello"


class TestEmbeddedPlaceholder:
    """内嵌 ${VAR}：替换，未设置的用空串"""

    def test_substitutes_when_set(self, env):
        assert resolve_env_placeholders("pre-${PRESENT_VAR}-post") == "pre-hello-post"

    def test_substitutes_empty_string_when_unset(self, env):
        """内嵌未设置变量替换为空串（而非 None，否则拼接会 TypeError）"""
        assert resolve_env_placeholders("a-${MISSING_VAR}-b") == "a--b"

    def test_multiple_placeholders_in_one_string(self, env):
        result = resolve_env_placeholders("${PRESENT_VAR}/${MISSING_VAR}/tail")
        assert result == "hello//tail"


class TestRecursion:
    """递归处理 dict / list，非字符串原样返回"""

    def test_recurses_into_dict(self, env):
        out = resolve_env_placeholders({"a": "${PRESENT_VAR}", "b": "${MISSING_VAR}"})
        assert out == {"a": "hello", "b": None}

    def test_recurses_into_list(self, env):
        """list 分支：逐项递归"""
        out = resolve_env_placeholders(["${PRESENT_VAR}", "${MISSING_VAR}", 42])
        assert out == ["hello", None, 42]

    def test_recurses_into_nested_structures(self, env):
        out = resolve_env_placeholders(
            {"outer": {"inner": ["${PRESENT_VAR}", {"deep": "${MISSING_VAR}"}]}}
        )
        assert out == {"outer": {"inner": ["hello", {"deep": None}]}}

    def test_non_string_scalars_pass_through(self, env):
        assert resolve_env_placeholders(42) == 42
        assert resolve_env_placeholders(None) is None
        assert resolve_env_placeholders(True) is True

    def test_plain_string_without_placeholder_is_unchanged(self, env):
        assert resolve_env_placeholders("no placeholder here") == "no placeholder here"


class TestPatternStrictness:
    """占位符格式：只认大写/数字/下划线"""

    def test_lowercase_name_is_not_treated_as_placeholder(self, env, monkeypatch):
        """小写变量名不匹配（正则限定 [A-Z0-9_]），原样保留"""
        monkeypatch.setenv("lower_var", "x")
        assert resolve_env_placeholders("${lower_var}") == "${lower_var}"

    def test_both_entrypoints_share_this_implementation(self):
        """两个入口必须复用同一实现，避免占位符语义分叉"""
        import run_strategy
        import run_strategies_manager

        assert (
            run_strategy._resolve_env_placeholders
            is run_strategies_manager._resolve_env_placeholders
            is resolve_env_placeholders
        ), "入口未复用共享实现，占位符语义可能分叉"
