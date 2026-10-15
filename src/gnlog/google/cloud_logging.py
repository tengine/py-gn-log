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
import threading
from collections import Counter
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

# python-json-logger がクラス logging.LogRecord から出力するフィールド
# (クラス JsonFormatter のメソッド parse が返すもの)
_RECORD_FIELDS: tuple[str, ...] = ("name", "message", "stack_info")

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
            name: ロガー名、message: ログメッセージ、stack_info: スタックトレース情報
            (値が無い行では、メソッド add_fields がキーを取り除く)
        """
        return list(_RECORD_FIELDS)

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

        # stack_info=True を指定していない行では、フィールド stack_info (引数 rename_fields で
        # 名前を変えていればその名前) の値が None になる。python-json-logger は parse() が返す
        # フィールドを値が None でも出力するので、値の無いキーを取り除く (#48)
        stack_info_key = self.rename_fields.get("stack_info", "stack_info")
        if log_data.get(stack_info_key) is None:
            log_data.pop(stack_info_key, None)

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
