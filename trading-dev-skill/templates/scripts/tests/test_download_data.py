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
from datetime import date, datetime, timezone
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

    def test_http_error_raises(self):
        """Binance 返回非 200 时必须失败，不可当成空数据继续。

        改为 raise 而非 sys.exit：多 symbol 时第 2 个失败若直接退进程，
        第 3、4 个永不下载。退出码语义由 main 保证（见 TestMainExitCode）。
        """
        with patch.object(dd.requests, "get", return_value=_resp({"msg": "bad"}, status=418)):
            with pytest.raises(RuntimeError, match="418"):
                dd.fetch_klines("BTCUSDT", "1m", 0, 60_000)

    def test_network_error_raises(self):
        with patch.object(dd.requests, "get",
                          side_effect=dd.requests.RequestException("conn refused")):
            with pytest.raises(RuntimeError, match="请求异常"):
                dd.fetch_klines("BTCUSDT", "1m", 0, 60_000)


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


# ── main 退出码（对外契约，不随 fetch_klines 改为 raise 而变） ──

class TestMainExitCode:
    def _argv(self, monkeypatch, *extra):
        monkeypatch.setattr(
            sys, "argv",
            ["download_data.py", "--symbol", "BTCUSDT", "--days", "1", *extra],
        )

    def test_download_failure_still_exits_1(self, monkeypatch, tmp_path):
        """fetch_klines 改为 raise 后，进程退出码必须仍是 1。

        否则 CI / 批量脚本会把下载失败当成成功。
        """
        self._argv(monkeypatch, "--data-dir", str(tmp_path))
        with patch.object(dd, "download_symbol",
                          side_effect=RuntimeError("Binance 返回 418")):
            with pytest.raises(SystemExit) as exc:
                dd.main()

        assert exc.value.code == 1

    def test_one_symbol_failure_does_not_block_others(self, monkeypatch, tmp_path):
        """第 1 个 symbol 失败时，后续 symbol 仍必须被尝试。

        原实现在 fetch_klines 内 sys.exit，多 symbol 场景下后面的永不下载。
        """
        monkeypatch.setattr(
            sys, "argv",
            ["download_data.py", "--symbol", "BTCUSDT,ETHUSDT,SOLUSDT",
             "--days", "1", "--data-dir", str(tmp_path)],
        )
        attempted = []

        def flaky(symbol, *a, **kw):
            attempted.append(symbol)
            if symbol == "BTCUSDT":
                raise RuntimeError("conn refused")
            return tmp_path / f"{symbol}.csv"

        with patch.object(dd, "download_symbol", side_effect=flaky):
            with pytest.raises(SystemExit) as exc:
                dd.main()

        assert attempted == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        assert exc.value.code == 1  # 有失败仍非零退出


# ── 现有 CSV 读取（增量补齐的起点来源） ──────────────────────

class TestReadExistingCsv:
    def test_missing_file_returns_none(self, tmp_path):
        assert dd.read_existing_csv(tmp_path / "nope.csv") is None

    def test_reads_iso_timestamps(self, tmp_path):
        p = tmp_path / "a.csv"
        p.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2026-08-20 00:00:00+00:00,1,2,0.5,1.5,10\n"
            "2026-08-20 00:01:00+00:00,1,2,0.5,1.5,10\n",
            encoding="utf-8",
        )
        df = dd.read_existing_csv(p)

        assert len(df) == 2
        assert str(df["timestamp"].max()) == "2026-08-20 00:01:00+00:00"

    def test_reads_legacy_millisecond_timestamps(self, tmp_path):
        """历史 CSV 可能是 Binance 原始毫秒格式，不能被当成坏文件丢弃。"""
        p = tmp_path / "b.csv"
        p.write_text(
            "timestamp,open,high,low,close,volume\n"
            "1787184000000,1,2,0.5,1.5,10\n",
            encoding="utf-8",
        )
        df = dd.read_existing_csv(p)

        assert len(df) == 1
        assert df["timestamp"].iloc[0].year == 2026

    def test_missing_timestamp_column_returns_none(self, tmp_path):
        p = tmp_path / "c.csv"
        p.write_text("open,high\n1,2\n", encoding="utf-8")

        assert dd.read_existing_csv(p) is None

    def test_unparseable_timestamps_return_none(self, tmp_path):
        p = tmp_path / "d.csv"
        p.write_text("timestamp,open\nnot-a-date,1\n", encoding="utf-8")

        assert dd.read_existing_csv(p) is None


# ── merge（历史保全 + 残缺末根修复） ──────────────────────────

def _df(rows):
    """rows: [(ts_str, volume)] → 6 列 DataFrame（timestamp 为 tz-aware）。"""
    import pandas as pd
    return pd.DataFrame({
        "timestamp": pd.to_datetime([r[0] for r in rows], utc=True),
        "open": [1.0] * len(rows),
        "high": [2.0] * len(rows),
        "low": [0.5] * len(rows),
        "close": [1.5] * len(rows),
        "volume": [r[1] for r in rows],
    })


class TestMergeKlines:
    def test_history_is_preserved(self):
        """核心回归：新数据不得抹掉旧历史（原实现裸 to_csv 会销毁）。"""
        old = _df([("2026-06-01 00:00:00+00:00", 1.0),
                   ("2026-06-01 00:01:00+00:00", 2.0)])
        new = _df([("2026-08-20 00:00:00+00:00", 3.0)])

        out = dd.merge_klines(old, new)

        assert len(out) == 3
        assert str(out["timestamp"].min()) == "2026-06-01 00:00:00+00:00"

    def test_new_value_overwrites_partial_last_bar(self):
        """崩溃时未闭合落盘的残缺末根，必须被重新拉到的完整值覆盖。

        这是补齐起点取末根本身（而非 +1 周期）的配套保证。
        """
        old = _df([("2026-08-20 00:00:00+00:00", 239.3)])  # 残缺 volume
        new = _df([("2026-08-20 00:00:00+00:00", 240.0)])  # 完整 volume

        out = dd.merge_klines(old, new)

        assert len(out) == 1
        assert out["volume"].iloc[0] == 240.0

    def test_result_is_sorted(self):
        old = _df([("2026-08-20 00:05:00+00:00", 1.0)])
        new = _df([("2026-08-20 00:00:00+00:00", 1.0)])

        out = dd.merge_klines(old, new)

        assert list(out["timestamp"]) == sorted(out["timestamp"])

    def test_none_old_returns_new(self):
        new = _df([("2026-08-20 00:00:00+00:00", 1.0)])

        assert len(dd.merge_klines(None, new)) == 1


# ── 分块规划（纯函数，决定请求数量级） ────────────────────────

def _utc(y, m, d, hh=0, mm=0):
    from datetime import datetime, timezone
    return datetime(y, m, d, hh, mm, tzinfo=timezone.utc)


class TestPlanChunks:
    def test_sub_day_gap_uses_fapi_only(self):
        """缺口不足一天时只出 fapi 块，不为几小时数据下载整天 zip。

        这是 daily/monthly 分支的对齐条件自然导出的结果（daily 要求
        cursor + 1天 <= end_dt），非独立守卫。
        """
        chunks = dd.plan_chunks(
            _utc(2026, 8, 21, 0, 0), _utc(2026, 8, 21, 6, 0), date(2026, 8, 21)
        )

        assert [c[0] for c in chunks] == ["fapi"]

    def test_sub_day_gap_never_hits_archive_at_any_offset(self):
        """跨多个起点穷举：<1 天的缺口在任何偏移下都不得触发归档下载。

        单点用例挡不住"某些偏移下误切出 daily 块"这类回归。
        允许切成多个 fapi 块（跨午夜的零头会在整天边界处断开），
        断言的是**不出现归档块** —— 归档 zip 覆盖整天/整月，对几小时的
        缺口是浪费且可能 404。
        """
        from datetime import timedelta
        base = _utc(2026, 8, 18)
        for start_off in range(0, 72 * 60, 37):
            for dur in (1, 59, 60, 61, 300, 1439):
                s = base + timedelta(minutes=start_off)
                chunks = dd.plan_chunks(s, s + timedelta(minutes=dur), date(2026, 8, 21))
                kinds = {c[0] for c in chunks}
                assert kinds == {"fapi"}, (
                    f"offset={start_off} dur={dur} 切出了 {chunks}"
                )

    def test_complete_past_month_uses_monthly(self):
        """完整且已结束的月份走 monthly zip —— 1 次请求顶一个月。"""
        chunks = dd.plan_chunks(
            _utc(2026, 6, 1), _utc(2026, 7, 1), date(2026, 8, 21)
        )

        assert chunks == [("monthly", 2026, 6)]

    def test_current_month_does_not_use_monthly(self):
        """当月 monthly zip 尚未发布（实测 404），必须降级为 daily/fapi。"""
        chunks = dd.plan_chunks(
            _utc(2026, 8, 1), _utc(2026, 8, 21), date(2026, 8, 21)
        )

        assert not any(c[0] == "monthly" for c in chunks)
        assert all(c[0] in ("daily", "fapi") for c in chunks)

    def test_unfinished_month_not_monthly_even_when_gap_spans_it(self):
        """缺口跨过整个当月时，month_is_over 是唯一阻止 monthly 的条件。

        上一个用例里 next_month_start > end_dt 本身就挡住了 monthly，
        故移除 month_is_over 守卫它也不会红（已实测该变异存活）。
        本用例把 end_dt 推到 09-01，让守卫成为唯一防线：today 仍在 8 月，
        8 月未结束 → monthly zip 会 404，必须走 daily。
        """
        chunks = dd.plan_chunks(
            _utc(2026, 8, 1), _utc(2026, 9, 1), date(2026, 8, 21)
        )

        assert ("monthly", 2026, 8) not in chunks
        assert chunks[0][0] == "daily"

    def test_past_days_use_daily(self):
        chunks = dd.plan_chunks(
            _utc(2026, 8, 18), _utc(2026, 8, 20), date(2026, 8, 21)
        )

        assert chunks == [("daily", date(2026, 8, 18)), ("daily", date(2026, 8, 19))]

    def test_today_tail_uses_fapi(self):
        """今天的 daily zip 未发布（实测 404），尾部必须走 fapi。"""
        chunks = dd.plan_chunks(
            _utc(2026, 8, 20), _utc(2026, 8, 21, 7, 0), date(2026, 8, 21)
        )

        assert chunks[0] == ("daily", date(2026, 8, 20))
        assert chunks[-1][0] == "fapi"

    def test_cross_month_gap_mixes_monthly_daily_fapi(self):
        """长缺口的典型形态：完整月 + 零头天 + 今日 fapi 尾。"""
        chunks = dd.plan_chunks(
            _utc(2026, 6, 1), _utc(2026, 8, 21, 7, 0), date(2026, 8, 21)
        )
        kinds = [c[0] for c in chunks]

        assert ("monthly", 2026, 6) in chunks
        assert ("monthly", 2026, 7) in chunks
        assert kinds[-1] == "fapi"
        # 关键收益：跨 2.5 月只需 ~23 块，而逐页 fapi 需 ~350 次请求
        assert len(chunks) < 30

    def test_unaligned_start_still_uses_archive_for_bulk(self):
        """回归（真实 E2E 发现）：起点未对齐整天时，仍必须用上归档。

        原实现的零头分支直接 fapi 到 end_dt 并 break，于是 06-02 03:18 这样的
        起点把整个跨月缺口退化成单个巨型 fapi 范围 —— 实测翻到 13500+ 根仍在跑，
        归档一次都没用上。正确行为是先补到当天边界，然后回到循环继续切块。
        """
        chunks = dd.plan_chunks(
            _utc(2026, 6, 2, 3, 18), _utc(2026, 8, 21, 9, 18), date(2026, 8, 21)
        )
        kinds = [c[0] for c in chunks]

        assert kinds[0] == "fapi"          # 先补 06-02 03:18 → 06-03 00:00
        assert ("monthly", 2026, 7) in chunks  # 7 月整月仍走归档
        assert kinds.count("fapi") <= 3, f"fapi 块过多，归档未生效: {kinds}"

    def test_no_gaps_between_chunks_when_start_unaligned(self):
        """未对齐起点下块必须严格首尾相接，否则静默丢数据。"""
        from datetime import timedelta
        start = _utc(2026, 6, 2, 3, 18)
        end = _utc(2026, 8, 21, 9, 18)
        chunks = dd.plan_chunks(start, end, date(2026, 8, 21))

        def bounds(chunk):
            from datetime import datetime, timezone
            kind, *key = chunk
            if kind == "monthly":
                s = datetime(key[0], key[1], 1, tzinfo=timezone.utc)
                import calendar
                return s, s + timedelta(days=calendar.monthrange(key[0], key[1])[1])
            if kind == "daily":
                s = datetime(key[0].year, key[0].month, key[0].day, tzinfo=timezone.utc)
                return s, s + timedelta(days=1)
            return (datetime.fromtimestamp(key[0] / 1000, timezone.utc),
                    datetime.fromtimestamp(key[1] / 1000, timezone.utc))

        cursor = start
        for chunk in chunks:
            s, e = bounds(chunk)
            assert s == cursor, f"块 {chunk} 起点 {s} 与前一块终点 {cursor} 不接"
            cursor = e
        assert cursor >= end

    def test_empty_when_start_not_before_end(self):
        assert dd.plan_chunks(_utc(2026, 8, 21), _utc(2026, 8, 21), date(2026, 8, 21)) == []

    def test_chunks_are_contiguous_and_ordered(self):
        """块必须首尾相接、无重叠、无空隙 —— 否则静默丢数据。"""
        chunks = dd.plan_chunks(
            _utc(2026, 6, 1), _utc(2026, 8, 21, 7, 0), date(2026, 8, 21)
        )
        starts = []
        for kind, *key in chunks:
            if kind == "monthly":
                starts.append(_utc(key[0], key[1], 1))
            elif kind == "daily":
                starts.append(_utc(key[0].year, key[0].month, key[0].day))
            else:
                from datetime import datetime, timezone
                starts.append(datetime.fromtimestamp(key[0] / 1000, timezone.utc))

        assert starts == sorted(starts)
        assert len(starts) == len(set(starts))


# ── 归档 zip 解析与下载 ───────────────────────────────────────

def _archive_zip(rows, header=True):
    """构造归档格式 zip（内含单个 12 列 CSV）。"""
    import io
    import zipfile

    lines = []
    if header:
        lines.append(",".join(dd.ARCHIVE_COLUMNS))
    for ms in rows:
        lines.append(
            f"{ms},69310.10,69373.10,69286.70,69362.70,235.919,"
            f"{ms + 59999},16357854.08,6346,154.235,10694561.98,0"
        )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BTCUSDT-1m-2026-08-20.csv", "\n".join(lines))
    return buf.getvalue()


class TestArchiveZipToDataframe:
    def test_parses_12_col_with_header(self):
        """归档 CSV 首行是表头，按无表头读会把表头当数据行。"""
        payload = _archive_zip([1_787_184_000_000, 1_787_184_060_000])
        df = dd.archive_zip_to_dataframe(payload)

        assert list(df.columns) == dd.CSV_COLUMNS
        assert len(df) == 2

    def test_parses_12_col_without_header(self):
        """部分历史归档包不带表头，两种都要能吃。"""
        payload = _archive_zip([1_787_184_000_000], header=False)
        df = dd.archive_zip_to_dataframe(payload)

        assert len(df) == 1

    def test_timestamp_converted_to_iso_string(self):
        """必须输出与 fapi 路径一致的 ISO 字符串，否则回测侧会重写整个 CSV。"""
        payload = _archive_zip([1_787_184_000_000])
        df = dd.archive_zip_to_dataframe(payload)

        assert df["timestamp"].iloc[0] == "2026-08-20 00:00:00+00:00"

    def test_numeric_columns_are_float(self):
        payload = _archive_zip([1_787_184_000_000])
        df = dd.archive_zip_to_dataframe(payload)

        for col in ("open", "high", "low", "close", "volume"):
            assert df[col].dtype == float


class TestFetchArchiveChunk:
    def test_404_returns_none_without_raising(self):
        """归档未发布该区间属正常（当天/当月），调用方降级 fapi，不可抛。"""
        with patch.object(dd.requests, "get", return_value=_resp({}, status=404)):
            out = dd.fetch_archive_chunk("BTCUSDT", "1m", "daily", date(2026, 8, 21))

        assert out is None

    def test_retries_then_succeeds_on_ssl_error(self):
        """实测归档 GET 会间歇抛 SSL EOF，首次失败立即重试即 200。

        无重试则 --days 365（12 个 zip）几乎必然中途失败。
        """
        ok = MagicMock()
        ok.status_code = 200
        ok.content = _archive_zip([1_787_184_000_000])
        attempts = [
            dd.requests.RequestException("SSL: UNEXPECTED_EOF_WHILE_READING"),
            ok,
        ]

        with patch.object(dd.requests, "get", side_effect=attempts), \
             patch.object(dd.time, "sleep"):
            out = dd.fetch_archive_chunk("BTCUSDT", "1m", "daily", date(2026, 8, 20))

        assert out is not None and len(out) == 1

    def test_raises_after_exhausting_retries(self):
        with patch.object(dd.requests, "get",
                          side_effect=dd.requests.RequestException("SSL EOF")), \
             patch.object(dd.time, "sleep"):
            with pytest.raises(RuntimeError, match="归档下载失败"):
                dd.fetch_archive_chunk("BTCUSDT", "1m", "daily", date(2026, 8, 20))

    def test_monthly_and_daily_urls(self):
        monthly = dd._archive_url("BTCUSDT", "1m", "monthly", (2026, 7))
        daily = dd._archive_url("BTCUSDT", "1m", "daily", date(2026, 8, 20))

        assert monthly.endswith("/monthly/klines/BTCUSDT/1m/BTCUSDT-1m-2026-07.zip")
        assert daily.endswith("/daily/klines/BTCUSDT/1m/BTCUSDT-1m-2026-08-20.zip")


# ── 增量落盘（本次改动的核心行为） ────────────────────────────

class TestIncrementalDownload:
    def test_existing_history_is_not_destroyed(self, tmp_path):
        """核心回归：跑第二次不得把第一次的历史抹掉。

        原实现裸 to_csv，--days 15 会让 6-7 月的历史永久消失。
        """
        csv = tmp_path / "1m" / "BTCUSDT_1m.csv"
        csv.parent.mkdir(parents=True)
        csv.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2026-06-01 00:00:00+00:00,1,2,0.5,1.5,10\n"
            "2026-06-01 00:01:00+00:00,1,2,0.5,1.5,10\n",
            encoding="utf-8",
        )
        new_rows = [_raw_kline(1_787_184_000_000)]

        with patch.object(dd, "fetch_klines", return_value=new_rows), \
             patch.object(dd, "fetch_archive_chunk", return_value=None), \
             patch.object(dd.time, "sleep"):
            out = dd.download_symbol("BTCUSDT", "1m", 30, str(tmp_path))

        result = dd.read_existing_csv(out)
        assert len(result) >= 3, "旧历史被抹掉了"
        assert str(result["timestamp"].min()) == "2026-06-01 00:00:00+00:00"

    def test_gap_start_is_existing_last_bar(self, tmp_path):
        """补齐起点必须是末根本身，而非末根 + 1 周期。

        崩溃时未闭合落盘的残缺末根需要被重新拉取覆盖；+1min 会让它永久污染。
        """
        csv = tmp_path / "1m" / "BTCUSDT_1m.csv"
        csv.parent.mkdir(parents=True)
        csv.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2026-08-20 00:00:00+00:00,1,2,0.5,1.5,239.3\n",
            encoding="utf-8",
        )
        captured = {}

        def spy(start_dt, end_dt, today):
            captured["start"] = start_dt
            return []

        with patch.object(dd, "plan_chunks", side_effect=spy):
            dd.download_symbol("BTCUSDT", "1m", 30, str(tmp_path))

        assert captured["start"].isoformat() == "2026-08-20T00:00:00+00:00"

    def test_force_overwrites_and_ignores_existing(self, tmp_path):
        """--force 是明确的逃生口：忽略现有 CSV，按 --days 全量重下。"""
        csv = tmp_path / "1m" / "BTCUSDT_1m.csv"
        csv.parent.mkdir(parents=True)
        csv.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2026-06-01 00:00:00+00:00,1,2,0.5,1.5,10\n",
            encoding="utf-8",
        )
        new_rows = [_raw_kline(1_787_184_000_000)]

        with patch.object(dd, "fetch_klines", return_value=new_rows), \
             patch.object(dd, "fetch_archive_chunk", return_value=None), \
             patch.object(dd.time, "sleep"):
            out = dd.download_symbol("BTCUSDT", "1m", 1, str(tmp_path), force=True)

        result = dd.read_existing_csv(out)
        assert str(result["timestamp"].min()).startswith("2026-08-20"), "旧数据未被覆盖"

    def test_up_to_date_csv_skips_download(self, tmp_path):
        """CSV 已是最新时不该发任何请求。"""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        csv = tmp_path / "1m" / "BTCUSDT_1m.csv"
        csv.parent.mkdir(parents=True)
        csv.write_text(
            "timestamp,open,high,low,close,volume\n"
            f"{now.isoformat(sep=' ')},1,2,0.5,1.5,10\n",
            encoding="utf-8",
        )

        with patch.object(dd, "fetch_klines") as fk, \
             patch.object(dd, "fetch_archive_chunk") as fa:
            out = dd.download_symbol("BTCUSDT", "1m", 30, str(tmp_path))

        assert out is not None
        fk.assert_not_called()
        fa.assert_not_called()

    def test_archive_chunk_is_used_for_long_gap(self, tmp_path):
        """长缺口必须走归档，而不是逐页 fapi —— 这是请求数从 350 降到 ~23 的关键。"""
        csv = tmp_path / "1m" / "BTCUSDT_1m.csv"
        csv.parent.mkdir(parents=True)
        csv.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2026-06-01 00:00:00+00:00,1,2,0.5,1.5,10\n",
            encoding="utf-8",
        )
        archive_df = dd.archive_zip_to_dataframe(_archive_zip([1_787_184_000_000]))

        with patch.object(dd, "fetch_archive_chunk",
                          return_value=archive_df) as fa, \
             patch.object(dd, "fetch_klines", return_value=[]), \
             patch.object(dd.time, "sleep"):
            dd.download_symbol("BTCUSDT", "1m", 30, str(tmp_path))

        assert fa.called, "长缺口未走归档"
        kinds = {call.args[2] for call in fa.call_args_list}
        assert "monthly" in kinds

    def test_written_timestamps_are_iso_strings(self, tmp_path):
        """落盘格式必须是 ISO 字符串，否则回测侧 _ensure_normalized_csv 会重写整个文件。"""
        new_rows = [_raw_kline(1_787_184_000_000)]

        with patch.object(dd, "fetch_klines", return_value=new_rows), \
             patch.object(dd, "fetch_archive_chunk", return_value=None), \
             patch.object(dd.time, "sleep"):
            out = dd.download_symbol("BTCUSDT", "1m", 1, str(tmp_path))

        second_line = out.read_text(encoding="utf-8").splitlines()[1]
        assert second_line.startswith("2026-08-20 00:00:00+00:00")


# ── 显式区间入口（回测侧自动下载的复用点） ────────────────────

class TestDownloadRange:
    """download_range: 区间由调用方给定，不从现有 CSV 末根推导。

    回测侧需要「补到 warm-up 起点之前」这类由策略参数算出的区间，
    download_symbol 的末根推导表达不了，故抽出本入口。
    """

    def test_range_comes_from_args_not_csv_last_bar(self, tmp_path):
        """核心差异：现有 CSV 末根不得影响下载区间。

        download_symbol 会把起点定在末根（2026-08-20），download_range
        必须严格用传入的 2026-06-10 —— 否则回测永远补不到 warm-up 之前的数据。
        """
        csv = tmp_path / "1m" / "BTCUSDT_1m.csv"
        csv.parent.mkdir(parents=True)
        csv.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2026-08-20 00:00:00+00:00,1,2,0.5,1.5,10\n",
            encoding="utf-8",
        )
        captured = {}

        def spy(start_dt, end_dt, today):
            captured["start"] = start_dt
            captured["end"] = end_dt
            return []

        with patch.object(dd, "plan_chunks", side_effect=spy):
            dd.download_range(
                "BTCUSDT", "1m",
                datetime(2026, 6, 10, tzinfo=timezone.utc),
                datetime(2026, 6, 12, tzinfo=timezone.utc),
                str(tmp_path),
            )

        assert captured["start"] == datetime(2026, 6, 10, tzinfo=timezone.utc)
        assert captured["end"] == datetime(2026, 6, 12, tzinfo=timezone.utc)

    def test_existing_history_is_merged_not_destroyed(self, tmp_path):
        """回测反复运行会多次调用本函数，历史不得被抹掉。"""
        csv = tmp_path / "1m" / "BTCUSDT_1m.csv"
        csv.parent.mkdir(parents=True)
        csv.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2026-06-01 00:00:00+00:00,1,2,0.5,1.5,10\n",
            encoding="utf-8",
        )
        new_rows = [_raw_kline(1_787_184_000_000)]  # 2026-08-20 00:00

        with patch.object(dd, "fetch_klines", return_value=new_rows), \
             patch.object(dd, "fetch_archive_chunk", return_value=None), \
             patch.object(dd.time, "sleep"):
            out = dd.download_range(
                "BTCUSDT", "1m",
                datetime(2026, 8, 20, tzinfo=timezone.utc),
                datetime(2026, 8, 20, 1, tzinfo=timezone.utc),
                str(tmp_path),
            )

        result = dd.read_existing_csv(out)
        assert str(result["timestamp"].min()) == "2026-06-01 00:00:00+00:00"
        assert len(result) >= 2

    def test_written_timestamps_are_iso_strings(self, tmp_path):
        """落盘格式必须与 download_symbol 一致（ISO 字符串）。

        写成毫秒整数会让回测侧 _ensure_normalized_csv 重写整个文件
        —— 190 万行的 1m CSV 每次回测启动都重写一遍。
        """
        new_rows = [_raw_kline(1_787_184_000_000)]

        with patch.object(dd, "fetch_klines", return_value=new_rows), \
             patch.object(dd, "fetch_archive_chunk", return_value=None), \
             patch.object(dd.time, "sleep"):
            out = dd.download_range(
                "BTCUSDT", "1m",
                datetime(2026, 8, 20, tzinfo=timezone.utc),
                datetime(2026, 8, 20, 1, tzinfo=timezone.utc),
                str(tmp_path),
            )

        assert out.read_text(encoding="utf-8").splitlines()[1].startswith(
            "2026-08-20 00:00:00+00:00"
        )

    def test_returns_none_when_no_data_and_no_existing_csv(self, tmp_path):
        """无数据且无现有 CSV → None，让调用方能判定失败。"""
        with patch.object(dd, "fetch_klines", return_value=[]), \
             patch.object(dd, "fetch_archive_chunk", return_value=None):
            out = dd.download_range(
                "BTCUSDT", "1m",
                datetime(2026, 8, 20, tzinfo=timezone.utc),
                datetime(2026, 8, 20, 1, tzinfo=timezone.utc),
                str(tmp_path),
            )

        assert out is None

    def test_long_gap_uses_archive(self, tmp_path):
        """长区间必须走归档 —— 请求数从 ~350 降到 ~23 的关键。"""
        archive_df = dd.archive_zip_to_dataframe(_archive_zip([1_787_184_000_000]))

        with patch.object(dd, "fetch_archive_chunk", return_value=archive_df) as fa, \
             patch.object(dd, "fetch_klines", return_value=[]), \
             patch.object(dd.time, "sleep"):
            dd.download_range(
                "BTCUSDT", "1m",
                datetime(2026, 6, 1, tzinfo=timezone.utc),
                datetime(2026, 8, 20, tzinfo=timezone.utc),
                str(tmp_path),
            )

        kinds = {call.args[2] for call in fa.call_args_list}
        assert "monthly" in kinds

    def test_existing_param_avoids_reread(self, tmp_path):
        """调用方传入 existing 时不得再读盘。

        1m CSV 常有百万行级（190 万行 ~3.4s），download_symbol 已读过一次，
        重读一遍会让每次下载凭空多几秒。
        """
        csv = tmp_path / "1m" / "BTCUSDT_1m.csv"
        csv.parent.mkdir(parents=True)
        csv.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2026-06-01 00:00:00+00:00,1,2,0.5,1.5,10\n",
            encoding="utf-8",
        )
        preread = dd.read_existing_csv(csv)

        with patch.object(dd, "read_existing_csv") as rec, \
             patch.object(dd, "fetch_klines", return_value=[]), \
             patch.object(dd, "fetch_archive_chunk", return_value=None):
            dd.download_range(
                "BTCUSDT", "1m",
                datetime(2026, 8, 20, tzinfo=timezone.utc),
                datetime(2026, 8, 20, 1, tzinfo=timezone.utc),
                str(tmp_path),
                existing=preread,
            )

        rec.assert_not_called()

    def test_download_symbol_still_derives_range_from_last_bar(self, tmp_path):
        """回归锚点：download_symbol 委托给 download_range 后行为不变。

        它的职责仍是「从末根推导区间」，CLI 契约不受重构影响。
        """
        csv = tmp_path / "1m" / "BTCUSDT_1m.csv"
        csv.parent.mkdir(parents=True)
        csv.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2026-08-20 00:00:00+00:00,1,2,0.5,1.5,239.3\n",
            encoding="utf-8",
        )
        captured = {}

        def spy(symbol, interval, start_dt, end_dt, data_dir, proxies=None, **kw):
            captured["start"] = start_dt
            return None

        with patch.object(dd, "download_range", side_effect=spy):
            dd.download_symbol("BTCUSDT", "1m", 30, str(tmp_path))

        assert captured["start"].isoformat() == "2026-08-20T00:00:00+00:00"


# ── 归档 zip 原始行解析（运行时补洞不落盘路径） ────────────────

class TestArchiveZipToRows:
    def test_parses_12_col_with_header(self):
        payload = _archive_zip([1_787_184_000_000, 1_787_184_060_000])
        rows = dd.archive_zip_to_rows(payload)

        assert len(rows) == 2
        assert all(len(r) == 12 for r in rows)
        # open_time 为 int 毫秒，与 fapi 裸数组同构
        assert rows[0][0] == 1_787_184_000_000
        assert isinstance(rows[0][0], int)

    def test_parses_without_header(self):
        payload = _archive_zip([1_787_184_000_000], header=False)
        rows = dd.archive_zip_to_rows(payload)
        assert len(rows) == 1

    def test_empty_zip_returns_empty_list(self):
        import io
        import zipfile

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w"):
            pass
        # 空 zip（无成员）→ []；非法输入不在调用契约内
        assert dd.archive_zip_to_rows(buf.getvalue()) == []


# ── fetch_range_rows：归档优先 + fapi 兜底，不落盘 ─────────────


class TestFetchRangeRows:
    def test_sub_day_range_uses_fapi_only(self):
        """不足一天的缺口只产生 fapi 块，不请求归档。"""
        start, end = _utc(2026, 8, 20, 12), _utc(2026, 8, 20, 14)
        with patch.object(dd, "fetch_klines",
                          return_value=[_raw_kline(1_787_184_000_000)]) as m_fapi, \
             patch.object(dd, "fetch_archive_chunk") as m_arch:
            rows = dd.fetch_range_rows("BTCUSDT", "1m", start, end, None)

        assert len(rows) == 1
        m_fapi.assert_called_once()
        m_arch.assert_not_called()

    def test_full_past_month_uses_archive(self):
        """完整且已结束的自然月 → monthly 归档，不打 fapi。"""
        start, end = _utc(2026, 7, 1), _utc(2026, 8, 1)
        arch_rows = [_raw_kline(1_784_563_200_000), _raw_kline(1_784_563_260_000)]
        with patch.object(dd, "fetch_archive_chunk",
                          return_value=arch_rows) as m_arch, \
             patch.object(dd, "fetch_klines") as m_fapi:
            rows = dd.fetch_range_rows("BTCUSDT", "1m", start, end, None)

        assert rows == arch_rows
        m_arch.assert_called_once()
        assert m_arch.call_args[0][2] == "monthly"
        assert m_arch.call_args.kwargs["as_rows"] is True
        m_fapi.assert_not_called()

    def test_archive_404_falls_back_to_fapi(self):
        """归档未发布（None）→ 该块用 fapi 分页兜底。"""
        start, end = _utc(2026, 7, 1), _utc(2026, 8, 1)
        fapi_rows = [_raw_kline(1_784_563_200_000)]
        with patch.object(dd, "fetch_archive_chunk", return_value=None), \
             patch.object(dd, "fetch_klines",
                          return_value=fapi_rows) as m_fapi:
            rows = dd.fetch_range_rows("BTCUSDT", "1m", start, end, None)

        assert rows == fapi_rows
        m_fapi.assert_called_once()

    def test_dedupes_and_sorts_by_open_time(self):
        """归档/fapi 边界重复的 open_time 去重后按时间排序。"""
        start, end = _utc(2026, 8, 20, 12), _utc(2026, 8, 20, 14)
        raw = [
            _raw_kline(1_787_184_060_000, "102.0"),
            _raw_kline(1_787_184_000_000, "100.0"),
            _raw_kline(1_787_184_000_000, "100.5"),  # 同刻重复，保最后一条
        ]
        with patch.object(dd, "fetch_klines", return_value=raw):
            rows = dd.fetch_range_rows("BTCUSDT", "1m", start, end, None)

        assert [r[0] for r in rows] == [1_787_184_000_000, 1_787_184_060_000]
        assert rows[0][4] == "100.5"

    def test_symbol_uppercased(self):
        start, end = _utc(2026, 8, 20, 12), _utc(2026, 8, 20, 14)
        with patch.object(dd, "fetch_klines", return_value=[]) as m_fapi:
            dd.fetch_range_rows("btcusdt", "1m", start, end, None)
        assert m_fapi.call_args[0][0] == "BTCUSDT"


class TestFetchArchiveChunkAsRows:
    def test_as_rows_returns_raw_rows(self):
        ok = MagicMock()
        ok.status_code = 200
        ok.content = _archive_zip([1_787_184_000_000])
        with patch.object(dd.requests, "get", return_value=ok):
            out = dd.fetch_archive_chunk(
                "BTCUSDT", "1m", "daily", date(2026, 8, 20), as_rows=True
            )
        assert isinstance(out, list)
        assert out[0][0] == 1_787_184_000_000

    def test_404_still_none_in_rows_mode(self):
        with patch.object(dd.requests, "get", return_value=_resp({}, status=404)):
            out = dd.fetch_archive_chunk(
                "BTCUSDT", "1m", "daily", date(2026, 8, 21), as_rows=True
            )
        assert out is None
