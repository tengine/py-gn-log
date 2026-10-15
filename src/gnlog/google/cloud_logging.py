"""
Google Cloud Logging 用の JSON フォーマッター

Cloud Logging の構造化ログに適した形式でログを出力します。
time と severity フィールドを自動的に追加します。

参考:
- https://nhairs.github.io/python-json-logger/latest/reference/pythonjsonlogger/json/#pythonjsonlogger.json.JsonFormatter.add_fields
- https://acata.hatenadiary.jp/entry/2020/12/28/235631
- https://github.com/nhairs/python-json-logger?tab=readme-ov-file
- https://zenn.dev/knowledgework/articles/cloud-logging-special-payload-fields
- https://cloud.google.com/error-reporting/docs/formatting-error-messages
"""

import logging
import sys
import threading
import traceback
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from typing import Any

from pythonjsonlogger.json import JsonFormatter as OriginalJsonFormatter

from .. import fingerprint

# Cloud Logging の labels フィールドのキー
# https://cloud.google.com/logging/docs/agent/logging/configuration#special-fields
CLOUD_LOGGING_LABELS_KEY = "logging.googleapis.com/labels"

# error_event 指定時に ERROR 以上のログへ付けるフィールド名
ERROR_EVENT_KEY = "event"
ERROR_TYPE_KEY = "error_type"
OPERATION_KEY = "operation"
FINGERPRINT_KEY = "fingerprint"

# error_type が指定されなかったときの値
ERROR_TYPE_UNKNOWN = "unknown"

# python-json-logger がすべての行に、クラス logging.LogRecord から出力するフィールド
# (クラス JsonFormatter のメソッド parse が返すもの)
_PARSED_FIELDS: tuple[str, ...] = ("name", "message")

# python-json-logger がクラス logging.LogRecord から出力するフィールド。stack_info は
# parse が返さなくても、stack_info=True を指定した行にだけ python-json-logger が出力する。
# 関数 validate_rename_fields が、変換後の名前との重なりを見るのに使う
_RECORD_FIELDS: tuple[str, ...] = (*_PARSED_FIELDS, "stack_info")

# クラス JsonFormatter が、親クラスのメソッド add_fields の後で読み書きするキー。
# 引数 rename_fields の変換前・変換後に使うと、値がフォーマッターに上書きされるか、
# フォーマッターの処理 (フィールド severity の決定、フィールド stack_trace への載せ替え、
# 引数 error_event のフィールド) が働かなくなるので受け付けない
_RENAME_RESERVED_KEYS: frozenset[str] = frozenset(
    {
        "time",
        "level",
        "severity",
        CLOUD_LOGGING_LABELS_KEY,
        "exc_info",
        "stack_trace",
        ERROR_EVENT_KEY,
        ERROR_TYPE_KEY,
        OPERATION_KEY,
        FINGERPRINT_KEY,
    }
)


def validate_rename_fields(rename_fields: dict[str, str]) -> None:
    """引数 rename_fields が、出力するフィールドの値を失わせないかを検査する

    次のどれかに当たると、値がフォーマッターに上書きされるか、フォーマッターの処理が
    働かなくなるか、名前が重なった片方の値が出力から失われるので受け付けない。

    - 変換前・変換後のどちらかに、クラス JsonFormatter が読み書きするキー (``time``・
      ``level``・``severity``・``logging.googleapis.com/labels``・``exc_info``・
      ``stack_trace``・``event``・``error_type``・``operation``・``fingerprint``) がある
    - 複数の変換前の名前を、同じ変換後の名前に対応させている
    - 変換後の名前が、名前を変えていないフィールド ``name``・``message``・``stack_info``
      と同じ (``{"name": "message", "message": "msg"}`` のように、そのフィールドの名前も
      変えるなら受け付ける)

    ログを書くときに渡すキー (引数 extra などで渡すキーと、ログのメッセージに渡す辞書のキー)
    との重なりは、ここでは分からないので検査しない。

    Args:
        rename_fields: 変換前のキー名から変換後のキー名への辞書

    Raises:
        TypeError: キーか値に文字列でないものがある場合
        ValueError: 上のどれかに当たる場合
    """
    # 型注釈 dict[str, str] に反するキーと値は受け付けない。たとえば文字列でない値は、
    # JSON のキー null や 1 として、利用者に知らされずに出力される
    not_str = sorted(
        repr(name)
        for name in [*rename_fields, *rename_fields.values()]
        if not isinstance(name, str)
    )
    if not_str:
        raise TypeError(f"rename_fields keys and values must be str: {not_str}")
    reserved = sorted(
        (set(rename_fields) | set(rename_fields.values())) & _RENAME_RESERVED_KEYS
    )
    if reserved:
        raise ValueError(
            f"rename_fields conflicts with keys JsonFormatter reads or writes: {reserved}. "
            "Choose different key names."
        )
    duplicated = sorted(
        name for name, count in Counter(rename_fields.values()).items() if count > 1
    )
    if duplicated:
        raise ValueError(
            f"rename_fields maps multiple keys to the same name: {duplicated}. "
            "Choose different key names."
        )
    overwritten = sorted(
        name
        for name in set(rename_fields.values())
        if name in _RECORD_FIELDS and name not in rename_fields
    )
    if overwritten:
        raise ValueError(
            f"rename_fields renames keys to names of fields that are not renamed: {overwritten}. "
            "Rename those fields as well, or choose different key names."
        )


def _validation_error_types() -> tuple[type[BaseException], ...]:
    """入力の検証の例外のクラスを、読み込み済みのモジュールから取り出す

    pydantic と FastAPI の入力の検証の例外は、メッセージに入力の値 (リクエストやレスポンスの
    本文) が入る。このモジュールは pydantic と FastAPI を import しない。例外が作られていれば、
    そのクラスのモジュールは読み込み済みなので、sys.modules から取り出せば足りる。

    Returns:
        クラス pydantic_core.ValidationError (pydantic.ValidationError と同じクラス) と、
        クラス fastapi.exceptions.ValidationException (RequestValidationError と
        ResponseValidationError の親クラス) のうち、読み込み済みのもの。
        ValidationException の無い FastAPI (pydantic v1 を使う版) は対象にしない
    """
    types: list[type[BaseException]] = []
    pydantic_core = sys.modules.get("pydantic_core")
    if pydantic_core is not None:
        types.append(pydantic_core.ValidationError)
    fastapi_exceptions = sys.modules.get("fastapi.exceptions")
    validation_exception = getattr(fastapi_exceptions, "ValidationException", None)
    if validation_exception is not None:
        types.append(validation_exception)
    return tuple(types)


def _exception_chain(exc: BaseException) -> Iterator[BaseException]:
    """例外と、それにつながる例外 (__cause__・__context__・ExceptionGroup の子) を順にたどる"""
    seen: set[int] = set()
    stack = [exc]
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        stack.extend(
            e for e in (current.__cause__, current.__context__) if e is not None
        )
        if isinstance(current, BaseExceptionGroup):
            stack.extend(current.exceptions)


def _loc_part_without_input(part: Any) -> str:
    """入力の検証の例外の場所 (loc) の要素のうち、番号と識別子の形の文字列だけを残す

    辞書の値を検証した例外では、辞書のキー (入力の値) が場所に入るため。
    """
    if isinstance(part, int) or (
        isinstance(part, str) and part.isascii() and part.isidentifier()
    ):
        return str(part)
    return "<key>"


def _as_list(value: Any) -> list[Any]:
    """入力の検証の例外の errors() の戻り値か、その要素の場所 (loc) を、要素の列にする

    FastAPI の ValidationException は errors に任意の値を受け付ける。文字列・bytes・辞書は
    反復すると 1 文字・1 バイト・1 キーずつになるので、反復できない値と同じく 1 つの要素として扱う。
    """
    if isinstance(value, (str, bytes, bytearray, Mapping)) or not isinstance(
        value, Iterable
    ):
        return [value]
    return list(value)


def _str_without_input(value: Any) -> str:
    """入力の検証の例外の errors() の要素の種類 (type) か説明 (msg) を書く

    文字列ならそのまま書き、文字列でなければ、入力の値を含みうるので中身を出さず、
    型の名前だけを ``<dict>`` のように書く (無いときの None も ``<NoneType>`` になる)。
    """
    if isinstance(value, str):
        return value
    return f"<{type(value).__name__}>"


def _error_without_input(error: Any) -> str:
    """入力の検証の例外の errors() の 1 つの要素を、場所 (loc)・種類 (type)・説明 (msg) だけで書く

    pydantic の要素は辞書だが、FastAPI の ValidationException は任意の要素の列を受け付ける。
    辞書でない要素は入力の値を含みうるので、中身を出さず、型の名前だけを ``<str>`` のように書く。
    """
    if not isinstance(error, Mapping):
        return f"<{type(error).__name__}>"
    loc = ".".join(_loc_part_without_input(p) for p in _as_list(error.get("loc", ())))
    kind = _str_without_input(error.get("type"))
    description = _str_without_input(error.get("msg"))
    return f"{loc} [{kind}] {description}"


def _message_without_input(exc: Any) -> str:
    """入力の検証の例外のメッセージを、errors() の要素ごとに関数 _error_without_input で書いて作る

    例: ``1 validation error(s) (input omitted): age [int_parsing] Input should be a valid integer``
    """
    errors = _as_list(exc.errors())
    details = "; ".join(_error_without_input(e) for e in errors)
    return f"{len(errors)} validation error(s) (input omitted): {details}"


def _replace_validation_messages(
    te: traceback.TracebackException,
    exc: BaseException,
    types: tuple[type[BaseException], ...],
) -> None:
    """TracebackException の連鎖のうち、入力の検証の例外に当たる箇所のメッセージを差し替える

    クラス traceback.TracebackException は、元の例外の __cause__・__context__・
    ExceptionGroup の子を、同じ形でたどって組み立てる (組み立てない箇所は None になる)。
    そのため、2 つの連鎖を同時にたどれば、対応する箇所が分かる。ほかの例外は、
    標準の traceback と同じ整形 (str の失敗の扱い・提案の付け足し・注記) のまま出る。
    メッセージは非公開の属性 _str にあるので、それを差し替える (Python 3.13 で確かめた)。
    差し替えた後に str(TracebackException) が差し替えたメッセージを返さなければ (属性が
    使われなくなった版)、入力の値を出力しないように例外 RuntimeError を出す。
    元の例外は書き換えない。

    Args:
        te: exc から作った TracebackException
        exc: 元の例外
        types: 入力の検証の例外のクラス (関数 _validation_error_types の戻り値)
    """
    stack: list[tuple[traceback.TracebackException, BaseException]] = [(te, exc)]
    while stack:
        current_te, current = stack.pop()
        if isinstance(current, types):
            message = _message_without_input(current)
            # 非公開の属性なので、型の定義 (typeshed) に無い
            current_te._str = message  # type: ignore[attr-defined]
            if str(current_te) != message:
                # from None で、処理中の例外 (入力の検証の例外) を連鎖に含めない。含めると、
                # logging が整形の失敗を標準エラー出力に出すときに、入力の値も出してしまう
                raise RuntimeError(
                    "Cannot omit input values from a validation error: "
                    "traceback.TracebackException no longer uses the attribute _str "
                    "for the exception message in this Python version."
                ) from None
        if current_te.__cause__ is not None and current.__cause__ is not None:
            stack.append((current_te.__cause__, current.__cause__))
        if current_te.__context__ is not None and current.__context__ is not None:
            stack.append((current_te.__context__, current.__context__))
        if current_te.exceptions and isinstance(current, BaseExceptionGroup):
            stack.extend(zip(current_te.exceptions, current.exceptions))


class JsonFormatter(OriginalJsonFormatter):
    """Google Cloud Logging 向けの JSON フォーマッター

    python-json-logger をベースに、Cloud Logging で認識される
    特別なフィールド（time, severity, labels）を追加します。

    フィールド ``time`` にはクラス ``logging.LogRecord`` の作成時刻を入れ、引数 ``extra``
    などで渡された ``time`` は上書きします。ログエントリーの時刻を呼び出し側が指定するための
    特別なフィールド (キー ``seconds`` と ``nanos`` を持つオブジェクトの ``timestamp``、
    ``timestampSeconds`` と ``timestampNanos`` の組) は上書きせずに出力します。
    Cloud Logging の文書では、これらは ``time`` より先に読まれます。

    フィールド ``stack_info`` は、``stack_info=True`` を指定してログを書いた行だけに出力します。

    例外の連鎖に入力の検証の例外 (pydantic の ``ValidationError``、FastAPI の
    ``RequestValidationError`` と ``ResponseValidationError``) があれば、その例外の
    メッセージから入力の値を除き、場所・種類・説明だけを出力します (メソッド formatException)。
    """

    def __init__(
        self,
        labels: dict[str, str] | None = None,
        json_ensure_ascii: bool = True,
        error_event: str | None = None,
        surface: str | None = None,
        rename_fields: dict[str, str] | None = None,
    ) -> None:
        """JsonFormatter を初期化

        Args:
            labels: Cloud Logging の labels に追加するキーと値
            error_event: 指定すると、severity ERROR 以上のログに分類と dedup 用の
                フィールドを付ける。``event`` にこの値、``error_type`` に extra で
                渡された分類 (未指定なら "unknown")、``operation`` に extra で渡された
                操作名 (未指定ならロガー名)、``fingerprint`` に同種のエラーで同じ値に
                なる短いハッシュが入る。None (既定) なら何も付けない
            surface: fingerprint の入力に使うサービスやコンポーネントの名前。
                error_event 指定時のみ使われる。None なら空文字として扱う
            json_ensure_ascii: True の場合、非 ASCII 文字を \\uXXXX に escape して出力する
                (python-json-logger の既定と同じ)。False の場合は日本語などをそのまま
                出力する。Cloud Logging 上の見え方はどちらでも変わらないが、標準出力を
                直接読む場面 (ローカル実行、docker logs、CI のログ) では False のほうが
                読みやすい
            rename_fields: 出力するフィールドの、変換前の名前から変換後の名前への辞書 (例: ``{"name": "logger"}``)。
                python-json-logger の同名の引数にそのまま渡す。名前が変わるのは
                python-json-logger が出力するフィールド (``name``・``message``・``stack_info``
                と、引数 extra などで渡したフィールドと、ログのメッセージに渡した辞書のキー) で、
                このクラスが後から入れるフィールドの名前は変わらない。None (既定) なら名前を変えない

        Raises:
            TypeError: rename_fields のキーか値に文字列でないものがある場合
            ValueError: rename_fields が、出力するフィールドの値を失わせる場合。
                条件は関数 validate_rename_fields を参照
        """
        if rename_fields is not None:
            validate_rename_fields(rename_fields)
        super().__init__(
            json_ensure_ascii=json_ensure_ascii, rename_fields=rename_fields
        )
        self._labels = labels or {}
        self._error_event = error_event
        self._surface = surface or ""

    def parse(self) -> list[str]:
        """ログレコードから抽出するフィールドを指定

        Returns:
            出力するフィールド名のリスト
            name: ロガー名、message: ログメッセージ。stack_info は返さない。
            返すと python-json-logger が値が None でも出力するので、stack_info=True を
            指定した行にだけ python-json-logger が出力するのに任せる
        """
        return list(_PARSED_FIELDS)

    # 戻り値の型は親クラス (python-json-logger) に合わせる。python-json-logger は、引数
    # exc_info_as_array を指定すると行のリストを返すので、logging.Formatter の str と
    # 合わない (python-json-logger 自身も type: ignore を付けている)
    def formatException(self, ei: Any) -> str | list[str]:  # type: ignore[override]
        """例外の情報を整形する (フィールド exc_info と stack_trace の値)

        例外の連鎖 (__cause__・__context__・ExceptionGroup の子) に、入力の検証の例外
        (pydantic と FastAPI) があれば、その例外のメッセージから入力の値を除いて出す (#49)。
        ほかの例外とその traceback は、親クラスと同じ形で出す。

        Args:
            ei: クラス logging.LogRecord の exc_info (例外のクラス・例外・traceback の組)

        Raises:
            RuntimeError: 入力の検証の例外のメッセージを差し替えられない Python の版の場合
                (関数 _replace_validation_messages を参照)。入力の値を出力しないために出す
        """
        exc = ei[1]
        types = _validation_error_types()
        if (
            exc is None
            or not types
            or not any(isinstance(e, types) for e in _exception_chain(exc))
        ):
            return super().formatException(ei)
        # logging.Formatter.formatException が呼ぶ traceback.print_exception と同じ引数で作る
        te = traceback.TracebackException(type(exc), exc, ei[2], compact=True)
        _replace_validation_messages(te, exc, types)
        formatted = "".join(te.format()).removesuffix("\n")
        return formatted.splitlines() if self.exc_info_as_array else formatted

    def add_fields(
        self,
        log_data: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        """ログデータに追加のフィールドを設定

        Cloud Logging 用の time, severity, labels フィールドを追加します。

        Args:
            log_data: ログデータの辞書（出力されるJSON）
            record: Python の LogRecord オブジェクト
            message_dict: ログメッセージに含まれる追加データ
        """
        # 親クラスの add_fields を呼び出して基本フィールドを追加
        super().add_fields(log_data, record, message_dict)

        # 時刻を RFC 3339 形式 (UTC、マイクロ秒まで) の文字列でフィールド time に入れる。
        # Cloud Logging がログエントリーの時刻 (ログエントリーのフィールド LogEntry.timestamp)
        # として読む文字列のフィールドは time だけで、文字列のフィールド timestamp は
        # 読まれる形に含まれない。
        # https://cloud.google.com/logging/docs/agent/logging/configuration#special-fields
        # (Logging エージェントの設定の文書。Cloud Run の文書 https://docs.cloud.google.com/run/docs/logging
        # も、構造化ログの特別なフィールドの説明としてこの文書を参照している)
        # extra などで渡された time は、この値で上書きする
        log_data["time"] = datetime.fromtimestamp(record.created, tz=UTC).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )

        # severity フィールドを追加（Cloud Logging でログレベルとして認識される）
        if log_data.get("level"):
            # log_data に level フィールドが存在する場合は、大文字に変換して severity として流用
            log_data["severity"] = log_data["level"].upper()
        else:
            # level フィールドがない場合は LogRecord の levelname を使用
            log_data["severity"] = record.levelname

        # Cloud Logging の labels にスレッド情報を追加
        current_thread = threading.current_thread()
        labels = log_data.get(CLOUD_LOGGING_LABELS_KEY, {})
        labels.update(self._labels)
        labels["thread_id"] = str(record.thread)
        labels["thread_name"] = current_thread.name
        log_data[CLOUD_LOGGING_LABELS_KEY] = labels

        # severity ERROR 以上の例外情報を Cloud Error Reporting が認識できる形にする。
        # python-json-logger はトレースバックを exc_info フィールドに出力するが、
        # Error Reporting が自動収集するのは message / stack_trace / exception
        # フィールドのみのため、exc_info のままでは Error Reporting に載らない。
        # WARNING 以下 (処理を継続できた失敗など) を誤ってエラー集計させないため、
        # 載せ替えは ERROR 以上に限定する。呼び出し側が明示的に stack_trace を
        # 指定している場合は上書きしない。
        if (
            record.levelno >= logging.ERROR
            and log_data.get("exc_info")
            and "stack_trace" not in log_data
        ):
            log_data["stack_trace"] = log_data.pop("exc_info")

        # error_event 指定時は ERROR 以上のログに分類と dedup 用の fingerprint を付ける
        if self._error_event is not None and record.levelno >= logging.ERROR:
            self._add_error_fields(log_data, record)

    def _add_error_fields(
        self, log_data: dict[str, Any], record: logging.LogRecord
    ) -> None:
        """ERROR 以上のログに event / error_type / operation / fingerprint を付ける

        呼び出し側が extra で明示的に渡した値は上書きしない。

        Args:
            log_data: ログデータの辞書（出力されるJSON）
            record: Python の LogRecord オブジェクト
        """
        log_data.setdefault(ERROR_EVENT_KEY, self._error_event)
        # JSON に出力する値と fingerprint の入力を同じ文字列にする
        # (出力された JSON から fingerprint を再計算できるようにするため)
        error_type = str(log_data.get(ERROR_TYPE_KEY) or ERROR_TYPE_UNKNOWN)
        operation = str(log_data.get(OPERATION_KEY) or record.name)
        log_data[ERROR_TYPE_KEY] = error_type
        log_data[OPERATION_KEY] = operation
        if FINGERPRINT_KEY not in log_data:
            # 引数 rename_fields でフィールド message の名前を変えていても、出力した値を読む
            message = log_data.get(self.rename_fields.get("message", "message"))
            if not isinstance(message, str):
                message = record.getMessage()
            log_data[FINGERPRINT_KEY] = fingerprint.build_fingerprint(
                self._surface, operation, error_type, message
            )
