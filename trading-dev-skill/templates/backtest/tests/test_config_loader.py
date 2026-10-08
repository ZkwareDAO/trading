#!/usr/bin/env python3
"""
测试配置加载器

覆盖当前保留的函数：
- load_main_config: 通用 YAML 加载
- load_profile: run-profile 加载（缺失/为空均视为错误）
- parse_date: 日期解析

注：以下测试类已随 legacy 配置族删除（一刀切收敛，不保留兼容层）：
- TestLoadBatchConfig（load_batch_config 已删）
- TestBuildConfigPath（build_config_path 已删）
- TestResolveConfigPath（resolve_config_path 已删）
原 TestLoadMainConfig 读取的 backtest/config/main.yaml 已删除，
回测参数现由 config/backtest.yaml 承载，故改为读取 profile 文件。
"""

import pathlib

import pytest
from backtest.config_loader import (
    load_main_config,
    load_profile,
    parse_date,
    verify_data_dir_consistency,
)

# 所有 run-profile 文件（含示例）。示例文件也必须守规矩：它是给用户抄的模板，
# 若含无人消费的键或与 settings.yaml 重复，用户会照抄错误。
PROFILE_FILES = ["config/backtest.yaml", "config/quick.example.yaml"]

# run_backtest / batch_runner 实际读取的 profile 键（grep profile_cfg 得出）
CONSUMED_PROFILE_KEYS = {
    "start", "end", "cash", "commission", "data_dir",
    "output_dir", "use_today_as_output_date", "log_level",
    "max_workers", "timeframe",
}


class TestVerifyDataDirConsistency:
    """测试 data_dir ↔ settings.csv_dir 一致性校验

    回测不读 settings.yaml，所以 data_dir 只能在 profile 里自己有一份。
    这是两个配置文件间唯一的语义重复，靠注释约定维持不住：一旦有人只改一处，
    实盘写入 A 目录、回测从 B 目录读，回测结果基于过时数据却毫无提示——
    属于回测失真，必须由代码拦住。
    """

    def test_consistent_paths_pass(self):
        assert verify_data_dir_consistency("./data/klines", "./data/klines") is True

    def test_equivalent_paths_pass(self):
        """路径写法不同但指向同一目录，不应误报"""
        assert verify_data_dir_consistency("./data/klines", "data/klines") is True
        assert verify_data_dir_consistency("data/klines/", "./data/klines") is True

    def test_divergent_paths_raise(self):
        """真正的分叉必须抛错，且信息要点明两个来源"""
        with pytest.raises(ValueError) as exc:
            verify_data_dir_consistency("./data/klines", "./data/other")

        msg = str(exc.value)
        assert "data_dir" in msg
        assert "csv_dir" in msg

    def test_missing_settings_is_tolerated(self):
        """settings.yaml 不存在（如纯回测使用者）不应阻断回测"""
        assert verify_data_dir_consistency("./data/klines", None) is True


class TestLoadProfile:
    """测试 run-profile 加载（run_backtest 与 batch_runner 共用同一实现）"""

    def test_load_backtest_profile_by_name(self):
        """按 profile 名加载，无需写全路径。

        断言值不写死：配置文件里的 start 会被正常调整（如推进回测区间），
        硬编码会让测试随配置漂移误报。加载机制的正确性 = 结果与文件内容一致。
        """
        import yaml

        config = load_profile("backtest")
        with open("config/backtest.yaml", encoding="utf-8") as f:
            expected = yaml.safe_load(f) or {}

        assert config["start"] == expected["start"]
        assert config["data_dir"] == expected["data_dir"]

    def test_missing_profile_raises_file_not_found(self):
        """profile 不存在必须报错，不可静默回退默认值——
        否则"这次跑的是哪套参数"不可知，与配置收敛目的相悖"""
        with pytest.raises(FileNotFoundError):
            load_profile("not_exist_profile")

    def test_empty_profile_raises_value_error(self, tmp_path, monkeypatch):
        """profile 存在但内容为空也必须报错，且错误信息要说"为空"而非"不存在" """
        import backtest.config_loader as cl

        monkeypatch.setattr(cl, "PROFILES_DIR", tmp_path)
        (tmp_path / "empty.yaml").write_text("", encoding="utf-8")

        with pytest.raises(ValueError, match="为空"):
            load_profile("empty")

    @pytest.mark.parametrize("bad_name", [
        "../secrets",            # 穿越到仓库外
        "../../etc/hostname",    # 穿越到系统文件
        "..\\windows",           # Windows 风格分隔符
        ".hidden",               # 隐藏文件前缀
    ])
    def test_path_traversal_rejected(self, bad_name):
        """profile 是文件名而非路径：含分隔符必须拒绝。

        未拦截时 `--profile ../config/settings` 会把系统配置当 profile 解析，
        报出令人困惑的错误（KeyError/字段缺失）而非"参数不合法"。
        """
        with pytest.raises(ValueError, match="不合法"):
            load_profile(bad_name)

    def test_legitimate_names_still_work(self):
        """守卫不得误伤正常 profile 名。断言与配置文件内容一致，不写死具体值。"""
        import yaml

        with open("config/backtest.yaml", encoding="utf-8") as f:
            expected = yaml.safe_load(f) or {}
        assert load_profile("backtest")["start"] == expected["start"]

    @pytest.mark.parametrize("reserved", [
        "settings", "settings.example", "strategies", "strategies.example",
    ])
    def test_reserved_config_names_rejected(self, reserved):
        """config/ 下的系统层/编排层配置不是 profile，必须显式拦截。

        profile 与 settings.yaml 同目录（回测本来就要读 settings.yaml 获取
        use_bar_high_low_for_exit，分开放反而割裂）。若不拦截，
        `--profile settings` 会把系统配置当 profile 解析，报出字段缺失的怪错误
        而非"参数不合法"。
        """
        with pytest.raises(ValueError, match="不是 run-profile"):
            load_profile(reserved)


class TestLoadMainConfig:
    """测试 YAML 配置加载（以 run-profile 为对象）"""

    def test_load_backtest_profile(self):
        """成功加载回测 profile"""
        config = load_main_config("config/backtest.yaml")

        # data_dir 必须与 config/settings.yaml 的 csv_dir 一致（消除数据目录分叉）
        assert config["data_dir"] == "./data/klines"
        assert "output_dir" in config
        assert "max_workers" in config
        assert "cash" in config
        assert "commission" in config

    @pytest.mark.parametrize("profile_file", PROFILE_FILES)
    def test_profile_contains_no_unconsumed_keys(self, profile_file):
        """profile 只允许出现代码真实消费的键。

        原先此处断言 signal_hub.enabled is False / factory_enabled is False，
        但经核查这两个键（以及 mode）没有任何消费者：回测根本不读 settings.yaml，
        也不初始化推送与 factory 客户端，"回测关闭外部服务"由链路本身保证。
        它们只是把同一开关在两个文件里写成不同的值（settings.yaml 是 true），
        制造"两处配置、都不生效"的假象，故已删除。此测试防止其被重新加回。
        """
        config = load_main_config(profile_file)

        extra = set(config) - CONSUMED_PROFILE_KEYS
        assert not extra, f"{profile_file} 含无人消费的键: {sorted(extra)}"

    @pytest.mark.parametrize("profile_file", PROFILE_FILES)
    def test_profile_keys_disjoint_from_settings(self, profile_file):
        """profile 与 settings.yaml 的键集合必须不相交——这是"两处配置不重复"的保证。

        回测读【两份】配置：settings.yaml（与实盘共用，提供
        use_bar_high_low_for_exit 等影响成交判定的字段）+ profile。二者键不相交，
        故无覆盖关系。唯一的语义重复是 data_dir ↔ settings.data_manager.csv_dir，
        键名不同，由 verify_data_dir_consistency 校验。
        """
        import yaml

        config = load_main_config(profile_file)
        with open("config/settings.yaml", "r", encoding="utf-8") as f:
            settings = yaml.safe_load(f)

        overlap = set(config) & set(settings)
        assert not overlap, f"{profile_file} 与 settings.yaml 键重复: {sorted(overlap)}"

    def test_example_profile_exists(self):
        """示例 profile 必须存在：它是 --profile 参数存在意义的唯一证明。

        若删除，--profile 就成了"永远只有一个可选值"的死参数，读者无从理解其用途。
        """
        assert pathlib.Path("config/quick.example.yaml").exists()

    def test_load_config_file_not_found(self):
        """配置文件不存在时抛出异常"""
        with pytest.raises(FileNotFoundError):
            load_main_config("config/not_exist.yaml")


class TestParseDate:
    """测试日期解析"""

    def test_parse_date_yyyymmdd(self):
        """YYYYMMDD 格式"""
        date_str, dt = parse_date("20250101")
        assert date_str == "20250101"
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 1

    def test_parse_date_yyyy_mm_dd(self):
        """YYYY-MM-DD 格式"""
        date_str, dt = parse_date("2025-01-01")
        assert date_str == "20250101"
        assert dt.year == 2025
        assert dt.month == 1
        assert dt.day == 1

    def test_parse_date_timestamp_seconds(self):
        """秒时间戳格式"""
        date_str, dt = parse_date("1735689600")  # 2025-01-01 00:00:00 UTC
        assert dt.year == 2025
        assert dt.month == 1

    def test_parse_date_timestamp_milliseconds(self):
        """毫秒时间戳格式"""
        date_str, dt = parse_date("1735689600000")  # 2025-01-01 00:00:00 UTC
        assert dt.year == 2025
        assert dt.month == 1
