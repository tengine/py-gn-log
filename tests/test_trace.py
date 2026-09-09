import json
import logging

import pytest

from gnlog import Initializer, context, trace
from gnlog.trace import TraceContext

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_HEX = "00f067aa0ba902b7"
SPAN_DEC = str(int(SPAN_HEX, 16))


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    context.clear()
    trace.clear()
    yield
    trace.clear()
    context.clear()


class TestParseTraceparent:
    def test_parses_valid_header(self):
        """version 00 の traceparent を trace_id / span_id / sampled に分解すること"""
        t = trace.parse_traceparent(f"00-{TRACE_ID}-{SPAN_HEX}-01")
        assert t == TraceContext(TRACE_ID, SPAN_HEX, True)

    def test_not_sampled_flag(self):
        """flags の下位ビットが 0 なら sampled は False であること"""
        t = trace.parse_traceparent(f"00-{TRACE_ID}-{SPAN_HEX}-00")
        assert t is not None and t.sampled is False

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            "garbage",
            f"01-{TRACE_ID}-{SPAN_HEX}-01",  # 未対応の version
            f"00-{TRACE_ID.upper()}-{SPAN_HEX}-01",  # 大文字は不正
            f"00-{'0' * 32}-{SPAN_HEX}-01",  # trace_id がすべて 0
            f"00-{TRACE_ID}-{'0' * 16}-01",  # span_id がすべて 0
            f"00-{TRACE_ID}-{SPAN_HEX}",  # flags 無し
        ],
    )
    def test_rejects_invalid(self, value):
        """不正な値は None を返すこと"""
        assert trace.parse_traceparent(value) is None


class TestParseCloudTraceContext:
    def test_parses_full_form(self):
        """TRACE_ID/SPAN_ID;o=1 を解釈し、10 進の span を 16 桁の 16 進にすること"""
        t = trace.parse_cloud_trace_context(f"{TRACE_ID}/{SPAN_DEC};o=1")
        assert t == TraceContext(TRACE_ID, SPAN_HEX, True)

    def test_without_option_has_unknown_sampled(self):
        """;o= が無ければ sampled は None であること"""
        t = trace.parse_cloud_trace_context(f"{TRACE_ID}/{SPAN_DEC}")
        assert t == TraceContext(TRACE_ID, SPAN_HEX, None)

    def test_without_span(self):
        """SPAN_ID が無ければ span_id は None であること"""
        t = trace.parse_cloud_trace_context(f"{TRACE_ID};o=0")
        assert t == TraceContext(TRACE_ID, None, False)

    def test_uppercase_trace_id_is_lowered(self):
        """大文字の TRACE_ID は小文字に揃えること"""
        t = trace.parse_cloud_trace_context(TRACE_ID.upper())
        assert t is not None and t.trace_id == TRACE_ID

    def test_zero_span_is_treated_as_unknown(self):
        """SPAN_ID が 0 なら span_id は None であること"""
        t = trace.parse_cloud_trace_context(f"{TRACE_ID}/0;o=1")
        assert t == TraceContext(TRACE_ID, None, True)

    @pytest.mark.parametrize(
        "value", [None, "", "abc", f"{'0' * 32}/1;o=1", f"{TRACE_ID}/x"]
    )
    def test_rejects_invalid(self, value):
        """不正な値は None を返すこと"""
        assert trace.parse_cloud_trace_context(value) is None


class TestFromHeaders:
    def test_prefers_traceparent(self):
        """traceparent と X-Cloud-Trace-Context が両方あれば traceparent を使うこと"""
        headers = {
            "traceparent": f"00-{TRACE_ID}-{SPAN_HEX}-01",
            "X-Cloud-Trace-Context": f"{'a' * 32}/1;o=0",
        }
        assert trace.from_headers(headers) == TraceContext(TRACE_ID, SPAN_HEX, True)

    def test_falls_back_to_cloud_trace_context_case_insensitively(self):
        """traceparent が無ければ X-Cloud-Trace-Context を大文字小文字を問わず読むこと"""
        headers = {"x-cloud-trace-context": f"{TRACE_ID}/{SPAN_DEC};o=1"}
        assert trace.from_headers(headers) == TraceContext(TRACE_ID, SPAN_HEX, True)

    def test_returns_none_without_headers(self):
        """どちらのヘッダも無ければ None であること"""
        assert trace.from_headers({"content-type": "application/json"}) is None


class TestLogFields:
    def test_builds_special_fields_with_project_id(self):
        """プロジェクト ID があれば Cloud Logging の特殊フィールドを組み立てること"""
        fields = trace.log_fields(TraceContext(TRACE_ID, SPAN_HEX, True), "my-project")
        assert fields == {
            "logging.googleapis.com/trace": f"projects/my-project/traces/{TRACE_ID}",
            "logging.googleapis.com/spanId": SPAN_HEX,
            "logging.googleapis.com/trace_sampled": True,
        }

    def test_omits_unknown_span_and_sampled(self):
        """span_id / sampled が不明ならそのフィールドを付けないこと"""
        fields = trace.log_fields(TraceContext(TRACE_ID), "my-project")
        assert fields == {
            "logging.googleapis.com/trace": f"projects/my-project/traces/{TRACE_ID}"
        }

    def test_uses_env_project_id(self, monkeypatch):
        """プロジェクト ID の引数が無ければ環境変数 GOOGLE_CLOUD_PROJECT を使うこと"""
        monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "env-project")
        fields = trace.log_fields(TraceContext(TRACE_ID))
        assert fields["logging.googleapis.com/trace"].startswith(
            "projects/env-project/"
        )

    def test_empty_without_project_id(self):
        """プロジェクト ID が決まらなければ何も付けないこと (既定値を持たない)"""
        assert trace.log_fields(TraceContext(TRACE_ID, SPAN_HEX, True)) == {}


class TestBindAndSet:
    def test_bind_puts_fields_in_context_and_restores(self):
        """bind() のブロック内だけ文脈に特殊フィールドと current() が置かれること"""
        t = TraceContext(TRACE_ID, SPAN_HEX, True)
        with trace.bind(t, project_id="p"):
            assert trace.current() == t
            assert context.get()["logging.googleapis.com/spanId"] == SPAN_HEX
        assert trace.current() is None
        assert "logging.googleapis.com/trace" not in context.get()

    def test_bind_with_none_does_nothing(self):
        """trace が None ならブロック内でも何も置かないこと"""
        with trace.bind(None, project_id="p"):
            assert trace.current() is None
            assert dict(context.get()) == {}

    def test_bind_without_project_keeps_current_for_propagation(self):
        """プロジェクト ID が無くても current() は置かれ、下流への引き継ぎに使えること"""
        t = TraceContext(TRACE_ID, SPAN_HEX, True)
        with trace.bind(t):
            assert trace.current() == t
            assert dict(context.get()) == {}
            assert trace.to_headers()["traceparent"] == f"00-{TRACE_ID}-{SPAN_HEX}-01"

    def test_set_and_clear_keep_other_context_keys(self):
        """set() は clear() まで残り、clear() は trace 以外の文脈を消さないこと"""
        context.set(site="tokyo")
        trace.set(TraceContext(TRACE_ID, SPAN_HEX, True), project_id="p")
        assert "logging.googleapis.com/trace" in context.get()
        trace.clear()
        assert trace.current() is None
        assert dict(context.get()) == {"site": "tokyo"}

    def test_bind_headers_yields_trace(self):
        """bind_headers() は取り出した trace を返し、ブロック内で文脈に置くこと"""
        headers = {"traceparent": f"00-{TRACE_ID}-{SPAN_HEX}-01"}
        with trace.bind_headers(headers, project_id="p") as t:
            assert t == TraceContext(TRACE_ID, SPAN_HEX, True)
            assert context.get()["logging.googleapis.com/trace"].endswith(TRACE_ID)


class TestToHeaders:
    def test_builds_both_headers(self):
        """traceparent と X-Cloud-Trace-Context の両方を組み立てること"""
        headers = trace.to_headers(TraceContext(TRACE_ID, SPAN_HEX, True))
        assert headers == {
            "traceparent": f"00-{TRACE_ID}-{SPAN_HEX}-01",
            "X-Cloud-Trace-Context": f"{TRACE_ID}/{SPAN_DEC};o=1",
        }

    def test_round_trip(self):
        """to_headers() の出力を from_headers() で読むと同じ trace に戻ること"""
        t = TraceContext(TRACE_ID, SPAN_HEX, False)
        assert trace.from_headers(trace.to_headers(t)) == t

    def test_unknown_span_and_sampled(self):
        """span_id / sampled が不明なら traceparent は 0 埋め、Cloud 形式は省略すること"""
        headers = trace.to_headers(TraceContext(TRACE_ID))
        assert headers["traceparent"] == f"00-{TRACE_ID}-{'0' * 16}-00"
        assert headers["X-Cloud-Trace-Context"] == TRACE_ID

    def test_empty_without_current(self):
        """trace が無ければ空の dict であること"""
        assert trace.to_headers() == {}


class TestJsonOutput:
    @pytest.fixture(autouse=True)
    def _reset_root(self):
        logging.root.handlers.clear()
        yield
        logging.root.handlers.clear()

    def test_special_fields_appear_in_json_lines(self, capsys):
        """Initializer 経由の JSON 出力に Cloud Logging の特殊フィールドが載ること"""
        Initializer(log_level=logging.INFO, verbose=False, json=True)
        logger = logging.getLogger("test.trace.json")
        headers = {"X-Cloud-Trace-Context": f"{TRACE_ID}/{SPAN_DEC};o=1"}

        with trace.bind_headers(headers, project_id="my-project"):
            logger.info("inside")
        logger.info("outside")

        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert lines[0]["logging.googleapis.com/trace"] == (
            f"projects/my-project/traces/{TRACE_ID}"
        )
        assert lines[0]["logging.googleapis.com/spanId"] == SPAN_HEX
        assert lines[0]["logging.googleapis.com/trace_sampled"] is True
        assert "logging.googleapis.com/trace" not in lines[1]
