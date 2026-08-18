#!/usr/bin/env python3
"""scripts/lib/expand_pairs.sh 与两个批量脚本的测试。

展开逻辑是这两个脚本存在的唯一理由（并发/汇总/退出码都在 Python 侧），
一旦展开错了，后果是静默跑错标的或漏跑标的，故重点覆盖：
1. 笛卡尔积正确性与顺序
2. symbol 大写归一——与 parse_explicit_strategies:136 的 .upper() 对齐，
   不一致会让同一标的产生两份任务与两份输出目录
3. overrides 预检——下游对显式清单缺配置是直接报错，不拦截会导致整批失败
4. 参数缺值/缺失的拒绝——避免把空串传进 Python 才崩

用 subprocess 调 bash 而非引入 bats：新增测试框架需写进 requirements，
而 test_requirements_complete.py 会核对声明与实际 import 的一致性。
"""

import subprocess
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
LIB = REPO_ROOT / "scripts" / "lib" / "expand_pairs.sh"
BACKTEST_SH = REPO_ROOT / "scripts" / "run_backtest_batch.sh"
LIVE_SH = REPO_ROOT / "scripts" / "run_live_batch.sh"


def run_bash(snippet: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    """在 bash 中 source 库文件后执行片段。"""
    script = f'set -uo pipefail\nsource "{LIB}"\n{textwrap.dedent(snippet)}'
    return subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO_ROOT),
    )


# ── 语法（脚本必须可解析，否则一切免谈） ──────────────────────────

class TestSyntax:
    @pytest.mark.parametrize("path", [LIB, BACKTEST_SH, LIVE_SH])
    def test_bash_syntax_valid(self, path):
        r = subprocess.run(["bash", "-n", str(path)], capture_output=True, text=True)
        assert r.returncode == 0, f"{path.name} 语法错误: {r.stderr}"

    @pytest.mark.parametrize("path", [BACKTEST_SH, LIVE_SH])
    def test_is_executable(self, path):
        assert path.stat().st_mode & 0o111, f"{path.name} 缺可执行权限"


# ── 笛卡尔积展开 ──────────────────────────────────────────────

class TestExpandPairs:
    def test_single_strategy_single_symbol(self):
        r = run_bash('expand_pairs "sar_snt3_v3" "BTCUSDT"')
        assert r.returncode == 0
        assert r.stdout.strip() == "sar_snt3_v3:BTCUSDT"

    def test_two_strategies_three_symbols_yields_six(self):
        r = run_bash('expand_pairs "a,b" "BTCUSDT,ETHUSDT,SOLUSDT"')
        pairs = r.stdout.strip().split(",")

        assert len(pairs) == 6, f"2×3 应为 6 个组合，实际 {pairs}"
        assert pairs == [
            "a:BTCUSDT", "a:ETHUSDT", "a:SOLUSDT",
            "b:BTCUSDT", "b:ETHUSDT", "b:SOLUSDT",
        ]

    def test_symbol_uppercased(self):
        """小写输入必须归一为大写，与 Python 侧 symbol.upper() 对齐。"""
        r = run_bash('expand_pairs "s1" "btcusdt,EthUsdt"')
        assert r.stdout.strip() == "s1:BTCUSDT,s1:ETHUSDT"

    def test_whitespace_tolerated(self):
        r = run_bash('expand_pairs "a, b" " BTCUSDT , ETHUSDT "')
        assert r.stdout.strip() == "a:BTCUSDT,a:ETHUSDT,b:BTCUSDT,b:ETHUSDT"

    def test_trailing_comma_ignored(self):
        r = run_bash('expand_pairs "a," "BTCUSDT,"')
        assert r.stdout.strip() == "a:BTCUSDT"

    def test_duplicate_pairs_deduped(self):
        """重复组合会让同一回测跑两遍并互相覆盖输出，必须去重。"""
        r = run_bash('expand_pairs "a,a" "BTCUSDT,btcusdt"')
        assert r.stdout.strip() == "a:BTCUSDT"

    def test_empty_strategies_rejected(self):
        r = run_bash('expand_pairs "" "BTCUSDT"')
        assert r.returncode != 0
        assert "策略列表为空" in r.stderr

    def test_empty_symbols_rejected(self):
        r = run_bash('expand_pairs "a" ""')
        assert r.returncode != 0
        assert "代币列表为空" in r.stderr

    def test_comma_only_rejected(self):
        r = run_bash('expand_pairs ",,," "BTCUSDT"')
        assert r.returncode != 0


class TestCountPairs:
    def test_counts_pairs(self):
        r = run_bash('count_pairs "a:BTCUSDT,a:ETHUSDT,b:BTCUSDT"')
        assert r.stdout.strip() == "3"

    def test_single_pair(self):
        r = run_bash('count_pairs "a:BTCUSDT"')
        assert r.stdout.strip() == "1"


# ── overrides 预检 ────────────────────────────────────────────

class TestPrecheckOverrides:
    @pytest.fixture
    def fake_repo(self, tmp_path):
        """构造 strategies/<name>/overrides/<SYMBOL>.yaml 结构。"""
        d = tmp_path / "strategies" / "s1" / "overrides"
        d.mkdir(parents=True)
        (d / "BTCUSDT.yaml").write_text("s1: {}\n")
        (d / "ETHUSDT.yaml").write_text("s1: {}\n")
        return tmp_path

    def test_all_present_passes(self, fake_repo):
        r = run_bash(f'precheck_overrides "s1:BTCUSDT,s1:ETHUSDT" "{fake_repo}"')
        assert r.returncode == 0, r.stderr

    def test_missing_override_rejected(self, fake_repo):
        r = run_bash(f'precheck_overrides "s1:BTCUSDT,s1:DOGEUSDT" "{fake_repo}"')

        assert r.returncode != 0
        assert "DOGEUSDT" in r.stderr

    def test_error_lists_all_missing_not_just_first(self, fake_repo):
        """一次列全部缺失项，避免用户反复试错。"""
        r = run_bash(
            f'precheck_overrides "s1:DOGEUSDT,s1:XRPUSDT,s1:ZECUSDT" "{fake_repo}"'
        )

        assert r.returncode != 0
        for sym in ("DOGEUSDT", "XRPUSDT", "ZECUSDT"):
            assert sym in r.stderr
        assert "3/3" in r.stderr

    def test_unknown_strategy_rejected(self, fake_repo):
        r = run_bash(f'precheck_overrides "nope:BTCUSDT" "{fake_repo}"')
        assert r.returncode != 0


# ── CLI 参数处理（不真正启动 Python） ──────────────────────────

def run_script(script: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(script), *args],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
        stdin=subprocess.DEVNULL,
        timeout=60,
    )


class TestCliContract:
    @pytest.mark.parametrize("script", [BACKTEST_SH, LIVE_SH])
    def test_help_exits_zero_and_documents_semantics(self, script):
        r = run_script(script, "--help")

        assert r.returncode == 0
        assert "--strategies" in r.stdout
        assert "--symbols" in r.stdout
        # --strategies 在本脚本是策略名、在 Python 侧是 name:symbol，
        # 同名不同义必须在 help 里说明，否则误用会跑错标的
        assert "name:symbol" in r.stdout

    @pytest.mark.parametrize("script", [BACKTEST_SH, LIVE_SH])
    def test_unknown_arg_rejected(self, script):
        r = run_script(script, "--bogus")
        assert r.returncode != 0
        assert "未知参数" in r.stderr or "未知参数" in r.stdout

    @pytest.mark.parametrize("script", [BACKTEST_SH, LIVE_SH])
    def test_missing_required_args_rejected(self, script):
        r = run_script(script)
        assert r.returncode != 0

    @pytest.mark.parametrize("script", [BACKTEST_SH, LIVE_SH])
    def test_flag_without_value_rejected(self, script):
        """--strategies 后无值时应报错，而非把下一个 flag 当成值吞掉。"""
        r = run_script(script, "--strategies")
        assert r.returncode != 0
        assert "缺少值" in r.stderr

    def test_backtest_requires_start(self):
        r = run_script(BACKTEST_SH, "--strategies", "sar_snt3_v3",
                       "--symbols", "BTCUSDT")
        assert r.returncode != 0
        assert "--start" in r.stderr

    def test_missing_override_blocks_before_python(self):
        """预检必须在调 Python 前拦下，错误里不应出现回测已开始的痕迹。"""
        r = run_script(BACKTEST_SH, "--strategies", "definitely_not_a_strategy",
                       "--symbols", "BTCUSDT", "--start", "20260610", "--yes")

        assert r.returncode != 0
        assert "overrides" in r.stderr


class TestResolveTradingMode:
    """trading_mode 解析——缺省即 live，批量展开时必须让用户看见。

    风险实例：sar_snt3_v3 的 14 个 overrides 中只有 BTCUSDT 声明了
    trading_mode，其余 13 个缺省为 live。批量脚本一条命令即可把十几个标的
    拉进实盘下真单，屏幕上却看不出来。
    """

    @pytest.fixture
    def modes_repo(self, tmp_path):
        d = tmp_path / "strategies" / "s1" / "overrides"
        d.mkdir(parents=True)
        (d / "PAPER.yaml").write_text('s1:\n  trading_mode: "paper_trading"\n')
        (d / "EXPLICIT.yaml").write_text('s1:\n  trading_mode: "live"\n')
        (d / "SILENT.yaml").write_text("s1:\n  interval: 8h\n")
        (d / "FLAT.yaml").write_text('trading_mode: "paper_trading"\n')
        return tmp_path

    def test_paper_trading_detected(self, modes_repo):
        r = run_bash(f'resolve_trading_mode "s1" "PAPER" "{modes_repo}"')
        assert r.stdout.strip() == "paper_trading"

    def test_explicit_live_detected(self, modes_repo):
        r = run_bash(f'resolve_trading_mode "s1" "EXPLICIT" "{modes_repo}"')
        assert r.stdout.strip() == "live"

    def test_unspecified_defaults_to_live(self, modes_repo):
        """未声明 trading_mode 时必须报 live——与 Python 侧默认值一致。

        若这里回 paper_trading 或空，用户会以为在跑模拟盘而实际下真单。
        """
        r = run_bash(f'resolve_trading_mode "s1" "SILENT" "{modes_repo}"')
        assert r.stdout.strip() == "live"

    def test_flat_config_without_strategy_key(self, modes_repo):
        """配置未按策略名分节时也要能读出来。"""
        r = run_bash(f'resolve_trading_mode "s1" "FLAT" "{modes_repo}"')
        assert r.stdout.strip() == "paper_trading"

    def test_real_repo_unspecified_is_live(self):
        """回归锚点：真实仓库中未声明 trading_mode 的 overrides 解析为 live。"""
        target = REPO_ROOT / "strategies" / "sar_snt3_v3" / "overrides" / "ETHUSDT.yaml"
        if not target.exists():
            pytest.skip("sar_snt3_v3/ETHUSDT overrides 不存在")

        r = run_bash(f'resolve_trading_mode "sar_snt3_v3" "ETHUSDT" "{REPO_ROOT}"')
        assert r.stdout.strip() == "live"


class TestLiveModeWarning:
    """live 模式必须警示——脚本内容级校验，不实际启动进程。"""

    def test_live_script_resolves_and_warns(self):
        content = LIVE_SH.read_text(encoding="utf-8")

        assert "resolve_trading_mode" in content, "实盘脚本必须解析 trading_mode"
        assert "真实下单" in content or "真实资金" in content, "live 模式必须给出资金警示"

    def test_live_confirmation_requires_typing_live(self):
        """live 确认不能只是 y/N ——一个回车就下真单的门槛太低。"""
        content = LIVE_SH.read_text(encoding="utf-8")
        assert '"$reply" == "live"' in content

    def test_help_documents_trading_mode_default(self):
        r = run_script(LIVE_SH, "--help")
        assert r.returncode == 0
        assert "trading_mode" in r.stdout


class TestRegistryMode:
    """登记表模式——多策略各配不同代币。

    笛卡尔积表达不了"策略 A 跑 2 个币、策略 B 跑 5 个币"，故支持登记表。
    展开复用 StrategiesLoader，不在 shell 里重解析 YAML：symbols 两种格式、
    symbol 级 trading_mode 覆盖策略级、缺省回退 live 这套优先级只有一处实现。
    """

    @pytest.fixture
    def registry(self, tmp_path):
        p = tmp_path / "reg.yaml"
        p.write_text(
            "strategies:\n"
            "  sar_snt3_v3:\n"
            '    trading_mode: "paper_trading"\n'
            "    symbols:\n"
            "      - BTCUSDT\n"
            "      - name: ETHUSDT\n"
            '        trading_mode: "live"\n',
            encoding="utf-8",
        )
        return p

    def test_registry_pairs_expanded(self, registry):
        r = run_bash(f'registry_pairs "{registry}" "{REPO_ROOT}" '
                     f'"{REPO_ROOT}/.venv/bin/python3"')
        assert r.returncode == 0, r.stderr
        assert r.stdout.strip() == "sar_snt3_v3:BTCUSDT,sar_snt3_v3:ETHUSDT"

    def test_symbol_level_mode_overrides_strategy_level(self, registry):
        """symbol 级 trading_mode 必须覆盖策略级——否则会把 live 显示成 paper。"""
        r = run_bash(f'describe_registry "{registry}" "{REPO_ROOT}" '
                     f'"{REPO_ROOT}/.venv/bin/python3"')

        lines = dict(l.split("\t") for l in r.stdout.strip().splitlines())
        assert lines["sar_snt3_v3:BTCUSDT"] == "paper_trading"
        assert lines["sar_snt3_v3:ETHUSDT"] == "live"

    @pytest.mark.parametrize("script,flag", [(BACKTEST_SH, "--config"),
                                             (LIVE_SH, "--registry")])
    def test_modes_are_mutually_exclusive(self, script, flag, registry):
        """登记表与笛卡尔积同时给会产生歧义，必须报错而非静默择一。"""
        # --start 只有回测脚本认；实盘脚本传了会先撞"未知参数"，测不到互斥
        extra = ["--start", "20260610"] if script == BACKTEST_SH else []
        r = run_script(script, flag, str(registry),
                       "--strategies", "sar_snt3_v3", "--symbols", "BTCUSDT",
                       *extra)
        assert r.returncode != 0
        assert "互斥" in r.stderr

    @pytest.mark.parametrize("script,flag", [(BACKTEST_SH, "--config"),
                                             (LIVE_SH, "--registry")])
    def test_missing_registry_file_rejected(self, script, flag):
        extra = ["--start", "20260610"] if script == BACKTEST_SH else []
        r = run_script(script, flag, "/nonexistent/reg.yaml", *extra)
        assert r.returncode != 0
        assert "不存在" in r.stderr

    @pytest.mark.parametrize("script,flag", [(BACKTEST_SH, "--config"),
                                             (LIVE_SH, "--registry")])
    def test_empty_registry_rejected(self, script, flag, tmp_path):
        empty = tmp_path / "empty.yaml"
        empty.write_text("strategies: {}\n", encoding="utf-8")

        extra = ["--start", "20260610"] if script == BACKTEST_SH else []
        r = run_script(script, flag, str(empty), *extra)
        assert r.returncode != 0

    def test_live_registry_passes_registry_to_manager(self):
        """登记表模式必须把登记表交给 manager 的 --strategies，不能传 --run。

        manager 走 --run 时改从 overrides 读 trading_mode，与按登记表展示的
        模式不一致 —— 会出现屏幕显示 paper、实际跑 live。
        """
        content = LIVE_SH.read_text(encoding="utf-8")
        code = "\n".join(
            ln for ln in content.splitlines() if not ln.strip().startswith("#")
        )
        assert '--strategies "$REGISTRY"' in code

    @pytest.mark.parametrize("script,flag", [(BACKTEST_SH, "--config"),
                                             (LIVE_SH, "--registry")])
    def test_help_documents_registry_mode(self, script, flag):
        r = run_script(script, "--help")
        assert r.returncode == 0
        assert flag in r.stdout
        assert "登记表" in r.stdout


class TestStopShCompatibility:
    """实盘脚本必须与 stop.sh 共用 PID 文件，否则停不干净留下下单的孤儿进程。"""

    def test_pid_file_matches_stop_sh(self):
        pid_names = set()
        for path in (LIVE_SH, REPO_ROOT / "stop.sh", REPO_ROOT / "start.sh"):
            for line in path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s.startswith("PID_FILE="):
                    pid_names.add(s.split("=", 1)[1].strip().strip('"').strip("'"))

        assert len(pid_names) == 1, (
            f"start.sh / stop.sh / run_live_batch.sh 的 PID 文件名不一致: {pid_names}。"
            f"不一致会导致 stop.sh 读不到 PID，只能靠 pkill 兜底，"
            f"可能留下继续下单的孤儿策略进程。"
        )

    def test_foreground_pid_is_the_manager_not_a_wrapper(self):
        """前台模式 PID 文件必须指向 manager 进程本身。

        stop.sh 对该 PID 发 SIGTERM 并期待 manager 优雅停止策略子进程；
        若指向一个 wrapper shell，杀壳不会连带停 Python，会留下继续下单的
        孤儿进程。

        实现用 exec 让 Python 顶替 shell 进程，故 $$ 即 manager PID。
        曾用 `python & wait` + trap 转发，实测 Ctrl-C 不生效（bash 执行
        wait 期间不响应 trap），进程停不下来，故改为 exec。
        """
        content = LIVE_SH.read_text(encoding="utf-8")
        fg = content.split("else", 1)[-1]
        # 只看可执行代码：注释里记录了 wait 为何被弃用，不能当成实现来匹配
        code = "\n".join(
            ln for ln in fg.splitlines() if not ln.strip().startswith("#")
        )

        # exec 顶替进程：$$ 成为 manager PID，且 Ctrl-C 直达 Python
        assert "exec" in code, "前台模式必须用 exec 顶替进程"
        # 不得回到 `& wait` 写法——SIGINT 在 wait 期间不触发 trap
        assert "wait " not in code, "前台模式不得用 & wait（SIGINT 不生效）"
