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

from datetime import datetime
import logging
import threading
from typing import Any, Dict

from pythonjsonlogger.json import JsonFormatter as OriginalJsonFormatter

# Cloud Logging の labels フィールドのキー
# https://cloud.google.com/logging/docs/agent/logging/configuration#special-fields
CLOUD_LOGGING_LABELS_KEY = "logging.googleapis.com/labels"


class JsonFormatter(OriginalJsonFormatter):
    """Google Cloud Logging 向けの JSON フォーマッター

    python-json-logger をベースに、Cloud Logging で認識される
    特別なフィールド（timestamp, severity, labels）を追加します。
    """

    def __init__(self, labels: dict[str, str] | None = None) -> None:
        super().__init__()
        self._labels = labels or {}

    def parse(self) -> list[str]:
        """ログレコードから抽出するフィールドを指定

        Returns:
            出力するフィールド名のリスト
            name: ロガー名、message: ログメッセージ、stack_info: スタックトレース情報
        """
        return ["name", "message", "stack_info"]

    def add_fields(
        self,
        log_data: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Dict[str, Any],
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
        log_data["timestamp"] = datetime.fromtimestamp(record.created).strftime(
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
        # 載せ替えは ERROR 以上に限定する。
        if record.levelno >= logging.ERROR and log_data.get("exc_info"):
            log_data["stack_trace"] = log_data.pop("exc_info")
