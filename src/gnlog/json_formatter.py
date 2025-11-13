from datetime import datetime
import logging
from typing import Any, Dict

from pythonjsonlogger.json import JsonFormatter as OriginalJsonFormatter

# https://nhairs.github.io/python-json-logger/latest/reference/pythonjsonlogger/json/#pythonjsonlogger.json.JsonFormatter.add_fields
# https://acata.hatenadiary.jp/entry/2020/12/28/235631
# https://github.com/nhairs/python-json-logger?tab=readme-ov-file
# https://zenn.dev/knowledgework/articles/cloud-logging-special-payload-fields
class JsonFormatter(OriginalJsonFormatter):
    def parse(self):
        return ["name", "message", "stack_info"]

    def add_fields(self, log_data: Dict[str, Any], record: logging.LogRecord, message_dict: Dict[str, Any]):
        super().add_fields(log_data, record, message_dict)

        log_data["timestamp"] = datetime.fromtimestamp(record.created).strftime("%Y-%m-%dT%H:%M:%S.%fZ")

        if log_data.get("level"):
            # Pythonのログレベルのアッパーケースを流用
            log_data["severity"] = log_data["level"].upper()
        else:
            log_data["severity"] = record.levelname
