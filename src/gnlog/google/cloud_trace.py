"""
Cloud Trace と連携して、全ログ行に trace / spanId を付けるためのモジュール

Cloud Run はリクエストごとに ``X-Cloud-Trace-Context`` ヘッダ (と W3C の ``traceparent``)
を付けます。Cloud Logging は JSON の特殊フィールド ``logging.googleapis.com/trace``
(``projects/<PROJECT_ID>/traces/<TRACE_ID>``)、``logging.googleapis.com/spanId``、
``logging.googleapis.com/trace_sampled`` を認識してログエントリを trace に紐付けます。

このモジュールは、共通部 :mod:`gnlog.trace` の上に、``X-Cloud-Trace-Context`` の解釈と
Cloud Logging の特殊フィールドの出力を載せたものです。

Examples:
    >>> from gnlog.google import cloud_trace
    >>> with cloud_trace.bind_headers(request.headers, project_id="my-project"):
    ...     logger.info("処理開始")   # {"logging.googleapis.com/trace": "projects/my-project/traces/...", ...}
    ...     httpx.get(url, headers=cloud_trace.to_headers())  # 下流に trace を引き継ぐ

プロジェクト ID は引数、無ければ環境変数 ``GOOGLE_CLOUD_PROJECT`` から取ります。
どちらにも無い場合は trace のフィールドを付けません (既定値で本番のプロジェクト ID を
持たないため)。その場合でも :func:`current` と :func:`to_headers` は動作するので、
下流への引き継ぎはできます。

参考:
- https://cloud.google.com/logging/docs/structured-logging#special-payload-fields
- https://cloud.google.com/trace/docs/trace-context
"""

import os
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

from .. import trace as _trace
from ..trace import TRACEPARENT_HEADER, TraceContext

# Cloud Logging の特殊フィールド名
TRACE_KEY = "logging.googleapis.com/trace"
SPAN_ID_KEY = "logging.googleapis.com/spanId"
TRACE_SAMPLED_KEY = "logging.googleapis.com/trace_sampled"
_FIELD_KEYS = (TRACE_KEY, SPAN_ID_KEY, TRACE_SAMPLED_KEY)

# Cloud Run が付けるヘッダ名
CLOUD_TRACE_CONTEXT_HEADER = "X-Cloud-Trace-Context"

# プロジェクト ID を読む環境変数
PROJECT_ID_ENV_VAR = "GOOGLE_CLOUD_PROJECT"

# X-Cloud-Trace-Context: TRACE_ID/SPAN_ID;o=TRACE_TRUE (SPAN_ID は 10 進、;o= は省略可)
# https://cloud.google.com/trace/docs/trace-context#legacy-http-header
_CLOUD_TRACE_CONTEXT_PATTERN = re.compile(
    r"^(?P<trace_id>[0-9a-fA-F]{32})(?:/(?P<span_id>\d{1,20}))?(?:;o=(?P<option>[01]))?$"
)
_MAX_SPAN_ID = 2**64 - 1

# 共通部の関数をこのモジュールからも使えるようにする
current = _trace.current
parse_traceparent = _trace.parse_traceparent


def parse_cloud_trace_context(value: str | None) -> TraceContext | None:
    """Cloud Run が付ける ``X-Cloud-Trace-Context`` ヘッダを解釈する

    ``TRACE_ID/SPAN_ID;o=TRACE_TRUE`` の形式。SPAN_ID は 10 進で、Cloud Logging の
    ``spanId`` に合わせて 16 桁の 16 進に変換する。

    Args:
        value: ヘッダの値。None や不正な形式なら None を返す

    Returns:
        解釈した TraceContext。``;o=`` が無ければ sampled は None
    """
    if value is None:
        return None
    m = _CLOUD_TRACE_CONTEXT_PATTERN.match(value.strip())
    if m is None:
        return None
    trace_id = m["trace_id"].lower()
    if trace_id == _trace.INVALID_TRACE_ID:
        return None
    span_id: str | None = None
    if m["span_id"] is not None:
        span_int = int(m["span_id"])
        if 0 < span_int <= _MAX_SPAN_ID:
            span_id = f"{span_int:016x}"
    sampled = None if m["option"] is None else m["option"] == "1"
    return TraceContext(trace_id=trace_id, span_id=span_id, sampled=sampled)


def from_headers(headers: Mapping[str, Any]) -> TraceContext | None:
    """受信ヘッダ (または Pub/Sub の属性など同じ形の Mapping) から trace を取り出す

    ``traceparent`` を優先し、無ければ ``X-Cloud-Trace-Context`` を見る。
    キーの大文字小文字は区別しない。

    Args:
        headers: ヘッダ名と値の Mapping

    Returns:
        解釈した TraceContext。どちらのヘッダも無いか不正なら None
    """
    trace = _trace.from_headers(headers)
    if trace is None:
        trace = parse_cloud_trace_context(
            _trace.header_value(headers, CLOUD_TRACE_CONTEXT_HEADER)
        )
    return trace


def project_id_from_env() -> str | None:
    """環境変数 ``GOOGLE_CLOUD_PROJECT`` からプロジェクト ID を取る (未設定なら None)"""
    value = os.getenv(PROJECT_ID_ENV_VAR)
    return value if value else None


def log_fields(trace: TraceContext, project_id: str | None = None) -> dict[str, Any]:
    """trace から Cloud Logging の特殊フィールドを組み立てる

    Args:
        trace: 対象の trace
        project_id: プロジェクト ID。None なら環境変数から取る

    Returns:
        ``logging.googleapis.com/trace`` / ``spanId`` / ``trace_sampled`` の dict。
        プロジェクト ID が決まらなければ空 (trace のフィールドは付けない)
    """
    if project_id is None:
        project_id = project_id_from_env()
    if not project_id:
        return {}
    fields: dict[str, Any] = {
        TRACE_KEY: f"projects/{project_id}/traces/{trace.trace_id}"
    }
    if trace.span_id is not None:
        fields[SPAN_ID_KEY] = trace.span_id
    if trace.sampled is not None:
        fields[TRACE_SAMPLED_KEY] = trace.sampled
    return fields


def _context_fields(trace: TraceContext, project_id: str | None) -> dict[str, Any]:
    """文脈に置くフィールド。不明な spanId / trace_sampled は None にして、
    外側の bind() や前の set() の値が残らないようにする (None は ContextFilter が注入しない)"""
    fields = log_fields(trace, project_id)
    if not fields:
        return {}
    return {SPAN_ID_KEY: None, TRACE_SAMPLED_KEY: None, **fields}


def set(trace: TraceContext | None, project_id: str | None = None) -> None:
    """現在の文脈に trace と Cloud Logging の特殊フィールドを置く (``clear()`` するまで残る)

    Args:
        trace: 置く trace。None なら何もしない
        project_id: プロジェクト ID。None なら環境変数から取る
    """
    if trace is None:
        return
    _trace.set(trace, _context_fields(trace, project_id))


def clear() -> None:
    """現在の文脈から trace と Cloud Logging の特殊フィールドを消す"""
    _trace.clear(_FIELD_KEYS)


@contextmanager
def bind(trace: TraceContext | None, project_id: str | None = None) -> Iterator[None]:
    """with ブロックの間だけ trace と Cloud Logging の特殊フィールドを文脈に置く

    Args:
        trace: 置く trace。None ならブロックの間も何も置かない
        project_id: プロジェクト ID。None なら環境変数から取る
    """
    fields = _context_fields(trace, project_id) if trace is not None else None
    with _trace.bind(trace, fields):
        yield


@contextmanager
def bind_headers(
    headers: Mapping[str, Any], project_id: str | None = None
) -> Iterator[TraceContext | None]:
    """受信ヘッダから trace を取り出し、with ブロックの間だけ文脈に置く

    Args:
        headers: 受信ヘッダ (または同じ形の Mapping)
        project_id: プロジェクト ID。None なら環境変数から取る

    Yields:
        取り出した TraceContext (無ければ None)
    """
    trace = from_headers(headers)
    with bind(trace, project_id):
        yield trace


def to_headers(trace: TraceContext | None = None) -> dict[str, str]:
    """他サービスを呼び出すときに付ける trace のヘッダを組み立てる

    ``traceparent`` は span_id と sampled の両方が分かっているときだけ付ける
    (:func:`gnlog.trace.format_traceparent` を参照)。``X-Cloud-Trace-Context`` は
    省略で不明を表せるので常に付ける。

    Args:
        trace: 対象の trace。None なら現在の文脈の trace を使う

    Returns:
        ``traceparent`` (分かっているときのみ) と ``X-Cloud-Trace-Context`` の dict。
        trace が無ければ空
    """
    if trace is None:
        trace = current()
    if trace is None:
        return {}
    headers = _trace.to_headers(trace)
    cloud = trace.trace_id
    if trace.span_id is not None:
        cloud += f"/{int(trace.span_id, 16)}"
    if trace.sampled is not None:
        cloud += f";o={1 if trace.sampled else 0}"
    headers[CLOUD_TRACE_CONTEXT_HEADER] = cloud
    return headers


__all__ = [
    "CLOUD_TRACE_CONTEXT_HEADER",
    "PROJECT_ID_ENV_VAR",
    "SPAN_ID_KEY",
    "TRACEPARENT_HEADER",
    "TRACE_KEY",
    "TRACE_SAMPLED_KEY",
    "TraceContext",
    "bind",
    "bind_headers",
    "clear",
    "current",
    "from_headers",
    "log_fields",
    "parse_cloud_trace_context",
    "parse_traceparent",
    "project_id_from_env",
    "set",
    "to_headers",
]
