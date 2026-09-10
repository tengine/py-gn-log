"""
分散トレースの文脈 (W3C Trace Context) を扱う共通部 (provider を知らない)

``TraceContext`` と、W3C の ``traceparent`` ヘッダの解釈・組み立て、現在の trace を
文脈に置く関数を提供します。ログに出すフィールド (Cloud Logging の特殊フィールド等) の
形は provider ごとに違うので、provider のサブパッケージ (``gnlog.google.cloud_trace`` 等)
がこのモジュールの ``bind()`` / ``set()`` に ``fields`` として渡します。

参考:
- https://www.w3.org/TR/trace-context/
"""

import re
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from . import context

# W3C のヘッダ名
TRACEPARENT_HEADER = "traceparent"

# traceparent: version-trace_id-parent_id-flags (version 00 のみ対応)
# https://www.w3.org/TR/trace-context/#traceparent-header-field-values
_TRACEPARENT_PATTERN = re.compile(
    r"^00-(?P<trace_id>[0-9a-f]{32})-(?P<span_id>[0-9a-f]{16})-(?P<flags>[0-9a-f]{2})$"
)
INVALID_TRACE_ID = "0" * 32
INVALID_SPAN_ID = "0" * 16


@dataclass(frozen=True)
class TraceContext:
    """1 つのリクエスト / 処理に対応する trace の識別子

    Attributes:
        trace_id: 32 桁の 16 進 (小文字)
        span_id: 16 桁の 16 進 (小文字)。不明なら None
        sampled: トレースにサンプリングされているか。不明なら None
    """

    trace_id: str
    span_id: str | None = None
    sampled: bool | None = None


# 現在の trace。ログに出すフィールドは gnlog.context に置き、送信ヘッダの組み立てに使う
# TraceContext 自体はここに持つ (ログには出さない)。
_current: ContextVar[TraceContext | None] = ContextVar("gnlog_trace", default=None)


def parse_traceparent(value: str | None) -> TraceContext | None:
    """W3C の ``traceparent`` ヘッダを解釈する

    Args:
        value: ヘッダの値。None や不正な形式なら None を返す

    Returns:
        解釈した TraceContext。trace_id / span_id がすべて 0 の無効値も None
    """
    if value is None:
        return None
    m = _TRACEPARENT_PATTERN.match(value.strip())
    if m is None:
        return None
    trace_id, span_id = m["trace_id"], m["span_id"]
    if trace_id == INVALID_TRACE_ID or span_id == INVALID_SPAN_ID:
        return None
    sampled = bool(int(m["flags"], 16) & 0x01)
    return TraceContext(trace_id=trace_id, span_id=span_id, sampled=sampled)


def format_traceparent(trace: TraceContext) -> str | None:
    """W3C の ``traceparent`` ヘッダの値を組み立てる

    ``traceparent`` は parent-id と flags が必須で「不明」を表せないため、span_id と
    sampled の両方が分かっているときだけ組み立てる。

    Args:
        trace: 対象の trace

    Returns:
        ヘッダの値。span_id か sampled が不明なら None
    """
    if trace.span_id is None or trace.sampled is None:
        return None
    flags = "01" if trace.sampled else "00"
    return f"00-{trace.trace_id}-{trace.span_id}-{flags}"


def header_value(headers: Mapping[str, Any], name: str) -> str | None:
    """大文字小文字を区別せずにヘッダの値を取り出す

    Args:
        headers: ヘッダ名と値の Mapping (Pub/Sub の属性など同じ形のものでもよい)
        name: ヘッダ名

    Returns:
        値の文字列。無ければ None
    """
    lowered = name.lower()
    for key, value in headers.items():
        if isinstance(key, str) and key.lower() == lowered:
            return str(value) if value is not None else None
    return None


def from_headers(headers: Mapping[str, Any]) -> TraceContext | None:
    """受信ヘッダの ``traceparent`` から trace を取り出す (provider 固有のヘッダは見ない)

    Args:
        headers: ヘッダ名と値の Mapping

    Returns:
        解釈した TraceContext。無いか不正なら None
    """
    return parse_traceparent(header_value(headers, TRACEPARENT_HEADER))


def to_headers(trace: TraceContext | None = None) -> dict[str, str]:
    """他サービスを呼び出すときに付ける ``traceparent`` ヘッダを組み立てる

    Args:
        trace: 対象の trace。None なら現在の文脈の trace を使う

    Returns:
        ``traceparent`` の dict。trace が無いか、span_id / sampled が不明なら空
    """
    if trace is None:
        trace = current()
    if trace is None:
        return {}
    value = format_traceparent(trace)
    return {TRACEPARENT_HEADER: value} if value is not None else {}


def current() -> TraceContext | None:
    """現在の文脈の trace を返す (無ければ None)"""
    return _current.get()


def set(trace: TraceContext | None, fields: Mapping[str, Any] | None = None) -> None:
    """現在の文脈に trace を置く (``clear()`` するまで残る)

    Args:
        trace: 置く trace。None なら何もしない
        fields: あわせて :mod:`gnlog.context` に置くログ用のフィールド (provider が組み立てる)
    """
    if trace is None:
        return
    _current.set(trace)
    if fields:
        context.set(fields)


def clear(field_keys: Iterable[str] = ()) -> None:
    """現在の文脈から trace と、指定したログ用フィールドを消す

    Args:
        field_keys: :mod:`gnlog.context` から取り除くキー (provider が置いたフィールド名)
    """
    _current.set(None)
    # このモジュールの set() 関数が組み込みの set を隠しているので frozenset を使う
    keys = frozenset(field_keys)
    if not keys:
        return
    remaining = {k: v for k, v in context.get().items() if k not in keys}
    context.clear()
    if remaining:
        context.set(remaining)


@contextmanager
def bind(
    trace: TraceContext | None, fields: Mapping[str, Any] | None = None
) -> Iterator[None]:
    """with ブロックの間だけ trace を文脈に置く

    Args:
        trace: 置く trace。None ならブロックの間も何も置かない
        fields: あわせて :mod:`gnlog.context` に置くログ用のフィールド (provider が組み立てる)
    """
    if trace is None:
        yield
        return
    token = _current.set(trace)
    try:
        if fields:
            with context.bind(fields):
                yield
        else:
            yield
    finally:
        _current.reset(token)


@contextmanager
def bind_headers(headers: Mapping[str, Any]) -> Iterator[TraceContext | None]:
    """受信ヘッダの ``traceparent`` から trace を取り出し、with ブロックの間だけ文脈に置く

    ログ用のフィールドは置かない (provider のサブパッケージの ``bind_headers()`` を使う)。

    Args:
        headers: 受信ヘッダ (または同じ形の Mapping)

    Yields:
        取り出した TraceContext (無ければ None)
    """
    trace = from_headers(headers)
    with bind(trace):
        yield trace
