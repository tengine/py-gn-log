"""
リクエストやタスク単位の文脈 (trace_id 等) を全ログ行に付けるためのモジュール

``contextvars.ContextVar`` に置いた値を、``ContextFilter`` が各 ``LogRecord`` の
属性として注入します。JSON 形式では python-json-logger が record の属性をそのまま
出力するため、置いたキー名がそのまま JSON のキーになります。

Examples:
    >>> import gnlog.context
    >>> with gnlog.context.bind(trace_id="abc123", site="tokyo"):
    ...     logger.info("処理開始")   # {"trace_id": "abc123", "site": "tokyo", ...}

注意:
    ``threading.Thread`` は ContextVar を継承しません。スレッドをまたいで文脈を
    引き継ぐには ``contextvars.copy_context().run(...)`` を使ってください。
    ``asyncio`` のタスクは生成時点の文脈を自動的に引き継ぎます。
"""

import logging
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from types import MappingProxyType
from typing import Any

# 現在の文脈。値は不変の Mapping として扱い、更新のたびに新しい dict に置き換える
# (ContextVar の値を破壊的に変更すると、他のタスクやスレッドに漏れるため)。
_EMPTY: Mapping[str, Any] = MappingProxyType({})
_context: ContextVar[Mapping[str, Any]] = ContextVar("gnlog_context", default=_EMPTY)

# LogRecord が自前で持つ名前 (インスタンス属性・クラス属性・メソッド)。これらと同じキーは
# record を壊すか、ContextFilter の hasattr 判定で注入されないまま欠落するので受け付けない
# (logging の extra= と同じ制約)。hasattr と同じ基準にするため dir() から作る。
_RESERVED_KEYS: frozenset[str] = frozenset(
    dir(logging.LogRecord("", 0, "", 0, "", (), None))
) | {"message", "asctime"}


def _validate_keys(values: Mapping[str, Any]) -> None:
    reserved = sorted(k for k in values if k in _RESERVED_KEYS)
    if reserved:
        raise ValueError(
            f"Context keys conflict with LogRecord attributes: {reserved}. "
            "Choose different key names."
        )


def get() -> Mapping[str, Any]:
    """現在の文脈を返す

    Returns:
        現在の文脈 (読み取り専用の Mapping)。何も置かれていなければ空
    """
    return _context.get()


def set(**values: Any) -> None:
    """現在の文脈に値を追加または上書きする

    ``bind()`` と違い、明示的に ``clear()`` するか、呼び出し元の Context が
    終わるまで残ります。リクエストの開始時に置き、終了時に ``clear()`` する
    使い方を想定しています。

    Args:
        **values: 文脈に置くキーと値。キーは JSON 出力のキー名になる

    Raises:
        ValueError: LogRecord の属性名と同じキーが含まれる場合
    """
    _validate_keys(values)
    _context.set(MappingProxyType({**_context.get(), **values}))


def clear() -> None:
    """現在の文脈をすべて消す"""
    _context.set(_EMPTY)


@contextmanager
def bind(**values: Any) -> Iterator[None]:
    """with ブロックの間だけ文脈に値を追加する

    ブロックを抜けると、ここで置いたキーだけを入る前の状態に戻します (例外で抜けた
    場合も同様)。ブロックの中で ``set()`` が足した他のキーは残ります。
    入れ子にでき、内側の値が同じキーを上書きします。

    Args:
        **values: 文脈に置くキーと値。キーは JSON 出力のキー名になる

    Raises:
        ValueError: LogRecord の属性名と同じキーが含まれる場合

    Examples:
        >>> with bind(trace_id="abc123"):
        ...     logger.info("...")  # trace_id が付く
        >>> logger.info("...")      # trace_id は付かない
    """
    _validate_keys(values)
    before = _context.get()
    _context.set(MappingProxyType({**before, **values}))
    try:
        yield
    finally:
        # ContextVar.reset() は突入時点の Mapping 全体に戻すため、ブロック内で set() が
        # 足したキーまで巻き戻してしまう。ここで置いたキーだけを元に戻す。
        current = _context.get()
        restored = {k: v for k, v in current.items() if k not in values}
        restored.update({k: before[k] for k in values if k in before})
        _context.set(MappingProxyType(restored))


class ContextFilter(logging.Filter):
    """現在の文脈を LogRecord の属性として注入する Filter

    record にすでに同名の属性がある場合 (``extra=`` で明示的に渡された場合) は
    そちらを優先し、上書きしません。

    ロガーに付けた Filter は伝播してきた record には適用されないため、この Filter は
    handler に付けてください (``Initializer`` は自身の handler に付けます)。
    """

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in _context.get().items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True
