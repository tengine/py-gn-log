"""
Google Cloud Logging 用の JSON フォーマッター

Cloud Logging の構造化ログに適した形式でログを出力します。
timestamp と severity フィールドを自動的に追加します。

参考:
- https://nhairs.github.io/python-json-logger/latest/reference/pythonjsonlogger/json/#pythonjsonlogger.json.JsonFormatter.add_fields
- https://acata.hatenadiary.jp/entry/2020/12/28/235631
- https://github.com/nhairs/python-json-logger?tab=readme-ov-file
- https://zenn.dev/knowledgework/articles/cloud-logging-special-payload-fields
- https://cloud.google.com/error-reporting/docs/formatting-error-messages
"""

import logging
import threading
from datetime import UTC, datetime
from typing import Any

from pythonjsonlogger.json import JsonFormatter as OriginalJsonFormatter

from . import fingerprint

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


class JsonFormatter(OriginalJsonFormatter):
    """Google Cloud Logging 向けの JSON フォーマッター

    python-json-logger をベースに、Cloud Logging で認識される
    特別なフィールド（timestamp, severity, labels）を追加します。
    """

    def __init__(
        self,
        labels: dict[str, str] | None = None,
        json_ensure_ascii: bool = True,
        error_event: str | None = None,
        surface: str | None = None,
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
        """
        super().__init__(json_ensure_ascii=json_ensure_ascii)
        self._labels = labels or {}
        self._error_event = error_event
        self._surface = surface or ""

    def parse(self) -> list[str]:
        """ログレコードから抽出するフィールドを指定

        Returns:
            出力するフィールド名のリスト
            name: ロガー名、message: ログメッセージ、stack_info: スタックトレース情報
        """
        return ["name", "message", "stack_info"]

    def add_fields(
        self,
        log_data: dict[str, Any],
        record: logging.LogRecord,
        message_dict: dict[str, Any],
    ) -> None:
        """ログデータに追加のフィールドを設定

        Cloud Logging 用の timestamp, severity, labels フィールドを追加します。

        Args:
            log_data: ログデータの辞書（出力されるJSON）
            record: Python の LogRecord オブジェクト
            message_dict: ログメッセージに含まれる追加データ
        """
        # 親クラスの add_fields を呼び出して基本フィールドを追加
        super().add_fields(log_data, record, message_dict)

        # ISO 8601 形式のタイムスタンプを追加（Cloud Logging が認識）
        # "Z" サフィックスと一致するよう UTC で整形する (Cloud Run は TZ=UTC のため出力は従来と同一)
        log_data["timestamp"] = datetime.fromtimestamp(record.created, tz=UTC).strftime(
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
        error_type = log_data.get(ERROR_TYPE_KEY) or ERROR_TYPE_UNKNOWN
        operation = log_data.get(OPERATION_KEY) or record.name
        log_data[ERROR_TYPE_KEY] = error_type
        log_data[OPERATION_KEY] = operation
        if FINGERPRINT_KEY not in log_data:
            message = log_data.get("message")
            if not isinstance(message, str):
                message = record.getMessage()
            log_data[FINGERPRINT_KEY] = fingerprint.build_fingerprint(
                self._surface, str(operation), str(error_type), message
            )
