import pytest

from gnlog import context, trace
from gnlog.trace import TraceContext

TRACE_ID = "4bf92f3577b34da6a3ce929d0e0e4736"
SPAN_HEX = "00f067aa0ba902b7"


@pytest.fixture(autouse=True)
def _clean():
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


class TestFormatTraceparent:
    def test_formats_when_known(self):
        """span_id と sampled が分かっていれば組み立てること"""
        assert (
            trace.format_traceparent(TraceContext(TRACE_ID, SPAN_HEX, False))
            == f"00-{TRACE_ID}-{SPAN_HEX}-00"
        )

    @pytest.mark.parametrize(
        "t",
        [TraceContext(TRACE_ID, SPAN_HEX, None), TraceContext(TRACE_ID, None, True)],
    )
    def test_none_when_unknown(self, t):
        """span_id か sampled が不明なら None (不正な値を組み立てない) こと"""
        assert trace.format_traceparent(t) is None


class TestHeaders:
    def test_header_value_is_case_insensitive(self):
        """header_value はヘッダ名の大文字小文字を区別しないこと"""
        assert trace.header_value({"TraceParent": "x"}, "traceparent") == "x"
        assert trace.header_value({}, "traceparent") is None

    def test_from_headers_reads_only_traceparent(self):
        """共通部の from_headers は traceparent だけを見ること"""
        assert trace.from_headers({"traceparent": f"00-{TRACE_ID}-{SPAN_HEX}-01"}) == (
            TraceContext(TRACE_ID, SPAN_HEX, True)
        )
        assert (
            trace.from_headers({"X-Cloud-Trace-Context": f"{TRACE_ID}/1;o=1"}) is None
        )

    def test_to_headers_round_trip(self):
        """to_headers() の出力を from_headers() で読むと同じ trace に戻ること"""
        t = TraceContext(TRACE_ID, SPAN_HEX, True)
        assert trace.from_headers(trace.to_headers(t)) == t

    def test_to_headers_empty_when_unknown_or_absent(self):
        """trace が無い、または span_id / sampled が不明なら空であること"""
        assert trace.to_headers() == {}
        assert trace.to_headers(TraceContext(TRACE_ID)) == {}


class TestContextBinding:
    def test_bind_sets_current_and_fields(self):
        """bind() は current() と、渡したフィールドをブロックの間だけ置くこと"""
        t = TraceContext(TRACE_ID, SPAN_HEX, True)
        with trace.bind(t, {"trace_id": TRACE_ID}):
            assert trace.current() == t
            assert context.get()["trace_id"] == TRACE_ID
        assert trace.current() is None
        assert "trace_id" not in context.get()

    def test_bind_without_fields(self):
        """フィールドを渡さなければ current() だけを置くこと"""
        t = TraceContext(TRACE_ID)
        with trace.bind(t):
            assert trace.current() == t
            assert dict(context.get()) == {}

    def test_set_and_clear_remove_only_given_keys(self):
        """set() は clear() まで残り、clear() は指定したキーだけを文脈から消すこと"""
        context.set(site="tokyo")
        trace.set(TraceContext(TRACE_ID), {"trace_id": TRACE_ID})
        trace.clear(["trace_id"])
        assert trace.current() is None
        assert dict(context.get()) == {"site": "tokyo"}

    def test_bind_headers_yields_trace(self):
        """bind_headers() は traceparent から取り出した trace を返し、current() に置くこと"""
        with trace.bind_headers({"traceparent": f"00-{TRACE_ID}-{SPAN_HEX}-01"}) as t:
            assert t == TraceContext(TRACE_ID, SPAN_HEX, True)
            assert trace.current() == t
