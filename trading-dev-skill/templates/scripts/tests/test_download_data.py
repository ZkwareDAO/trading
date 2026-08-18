#!/usr/bin/env python3
"""scripts/download_data.py 测试。

该脚本是开箱路径第一步（README 步骤 3），此前零覆盖。
重点覆盖三类风险：
1. 代理凭据脱敏——原实现直接 print 整个 proxies dict，会把
   http://user:pass@host 的密码写进终端与 CI 日志
2. 分页游标推进与去重——直接决定回测数据是否含重复 K 线
3. --days 边界——负数/0 会算出起点晚于终点，静默产出空数据

脚本不是包内模块（scripts/ 无 __init__.py），故用 importlib 按路径加载。
"""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "download_data",
    Path(__file__).resolve().parents[1] / "download_data.py",
)
dd = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dd)


# ── 代理脱敏（对应审查 C1：凭据泄漏） ──────────────────────────

class TestRedactProxy:
    def test_password_is_redacted(self):
        """带密码的代理 URL 必须隐去密码，保留用户名与主机便于排障。"""
        out = dd._redact_proxy("http://alice:s3cr3t@203.0.113.9:8080")

        assert "s3cr3t" not in out
        assert "alice" in out
        assert "203.0.113.9:8080" in out

    def test_url_without_password_unchanged(self):
        url = "http://203.0.113.9:8080"
        assert dd._redact_proxy(url) == url

    def test_password_with_special_chars_redacted(self):
        """密码含特殊字符时同样不可泄漏。"""
        out = dd._redact_proxy("http://u:p%40ss-w0rd!@203.0.113.9:1080")

        assert "p%40ss-w0rd!" not in out
        assert "***" in out

    def test_get_proxies_returns_none_when_unset(self, monkeypatch):
        for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            monkeypatch.delenv(var, raising=False)

        assert dd._get_proxies() is None

    def test_get_proxies_reads_env(self, monkeypatch):
        for var in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("HTTPS_PROXY", "http://203.0.113.9:8080")

        assert dd._get_proxies() == {"https": "http://203.0.113.9:8080"}


# ── K 线转换（数据正确性） ────────────────────────────────────

def _raw_kline(open_ms: int, close_price: str = "100.0") -> list:
    """Binance 原始 12 列格式，只有前 6 列会被使用。"""
    return [open_ms, "99.0", "101.0", "98.0", close_price, "12.5",
            open_ms + 59_999, "1250.0", 10, "6.0", "600.0", "0"]


class TestKlinesToDataframe:
    def test_empty_rows_returns_empty_frame_with_columns(self):
        df = dd.klines_to_dataframe([])

        assert df.empty
        assert list(df.columns) == dd.CSV_COLUMNS

    def test_keeps_only_six_columns(self):
        df = dd.klines_to_dataframe([_raw_kline(1_700_000_000_000)])

        assert list(df.columns) == dd.CSV_COLUMNS

    def test_numeric_columns_are_float(self):
        df = dd.klines_to_dataframe([_raw_kline(1_700_000_000_000)])

        for col in ("open", "high", "low", "close", "volume"):
            assert df[col].dtype == float

    def test_duplicate_timestamps_dropped(self):
        """分页边界会返回重复 K 线；不去重会让回测出现重复 bar。"""
        ts = 1_700_000_000_000
        df = dd.klines_to_dataframe([_raw_kline(ts), _raw_kline(ts), _raw_kline(ts + 60_000)])

        assert len(df) == 2

    def test_rows_sorted_by_timestamp(self):
        ts = 1_700_000_000_000
        df = dd.klines_to_dataframe([_raw_kline(ts + 120_000), _raw_kline(ts)])

        assert list(df["timestamp"]) == sorted(df["timestamp"])

    def test_timestamp_is_utc_string(self):
        df = dd.klines_to_dataframe([_raw_kline(1_700_000_000_000)])

        assert "+00:00" in df["timestamp"].iloc[0]


# ── 分页拉取（游标推进 / 错误处理） ───────────────────────────

def _resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    r.text = json.dumps(payload)
    return r


class TestFetchKlines:
    def test_stops_on_empty_response(self):
        with patch.object(dd.requests, "get", return_value=_resp([])):
            rows = dd.fetch_klines("BTCUSDT", "1m", 0, 60_000)

        assert rows == []

    def test_paginates_until_end(self):
        """游标必须严格推进，直到覆盖 end_ms——否则死循环或漏数据。"""
        start, step = 1_700_000_000_000, 60_000
        page1 = [_raw_kline(start + i * step) for i in range(3)]
        page2 = [_raw_kline(start + (3 + i) * step) for i in range(2)]
        pages = [_resp(page1), _resp(page2), _resp([])]

        with patch.object(dd.requests, "get", side_effect=pages), \
             patch.object(dd.time, "sleep"):
            rows = dd.fetch_klines("BTCUSDT", "1m", start, start + 10 * step)

        assert len(rows) == 5

    def test_cursor_advances_past_last_kline(self):
        """第二次请求的 startTime 必须 > 首页最后一根，避免重复拉同一页。"""
        start, step = 1_700_000_000_000, 60_000
        captured = []

        def fake_get(url, params=None, proxies=None, timeout=None):
            captured.append(params["startTime"])
            return _resp([_raw_kline(start)] if len(captured) == 1 else [])

        with patch.object(dd.requests, "get", side_effect=fake_get), \
             patch.object(dd.time, "sleep"):
            dd.fetch_klines("BTCUSDT", "1m", start, start + 10 * step)

        assert captured[1] == start + step

    def test_http_error_exits_nonzero(self):
        """Binance 返回非 200 时必须失败退出，不可当成空数据继续。"""
        with patch.object(dd.requests, "get", return_value=_resp({"msg": "bad"}, status=418)):
            with pytest.raises(SystemExit) as exc:
                dd.fetch_klines("BTCUSDT", "1m", 0, 60_000)

        assert exc.value.code == 1

    def test_network_error_exits_nonzero(self):
        with patch.object(dd.requests, "get",
                          side_effect=dd.requests.RequestException("conn refused")):
            with pytest.raises(SystemExit) as exc:
                dd.fetch_klines("BTCUSDT", "1m", 0, 60_000)

        assert exc.value.code == 1


# ── CLI 参数校验（对应审查 I3） ───────────────────────────────

class TestCliValidation:
    @pytest.mark.parametrize("days", ["-5", "0"])
    def test_non_positive_days_rejected(self, days, monkeypatch):
        """days < 1 会让起点晚于终点、静默产出空数据，必须提前拦截。"""
        monkeypatch.setattr(sys, "argv",
                            ["download_data.py", "--symbol", "BTCUSDT", "--days", days])

        with pytest.raises(SystemExit) as exc:
            dd.main()

        assert exc.value.code == 2  # argparse 参数错误

    def test_blank_symbol_rejected(self, monkeypatch):
        monkeypatch.setattr(sys, "argv",
                            ["download_data.py", "--symbol", " , ", "--days", "1"])

        with pytest.raises(SystemExit) as exc:
            dd.main()

        assert exc.value.code == 2


# ── 落盘（路径约定） ──────────────────────────────────────────

class TestDownloadSymbol:
    def test_writes_csv_to_interval_subdir(self, tmp_path):
        """输出路径必须是 {data_dir}/{interval}/{SYMBOL}_{interval}.csv，
        与 settings.yaml 的 csv_dir / profiles 的 data_dir 约定一致。"""
        rows = [_raw_kline(1_700_000_000_000 + i * 60_000) for i in range(3)]

        with patch.object(dd, "fetch_klines", return_value=rows):
            out = dd.download_symbol("btcusdt", "1m", 1, str(tmp_path))

        assert out == tmp_path / "1m" / "BTCUSDT_1m.csv"
        assert out.exists()
        assert out.read_text(encoding="utf-8").splitlines()[0] == ",".join(dd.CSV_COLUMNS)

    def test_returns_none_when_no_data(self, tmp_path):
        with patch.object(dd, "fetch_klines", return_value=[]):
            assert dd.download_symbol("BTCUSDT", "1m", 1, str(tmp_path)) is None
