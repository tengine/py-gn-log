import json
import logging

from gnlog.json_formatter import JsonFormatter


class TestJsonFormatter:
    """JsonFormatter クラスのテスト"""

    def test_parse_returns_expected_fields(self):
        """parse() が期待するフィールドを返すこと"""
        formatter = JsonFormatter()
        fields = formatter.parse()
        assert fields == ["name", "message", "stack_info"]

    def test_format_adds_timestamp(self):
        """format() が timestamp フィールドを追加すること"""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        log_dict = json.loads(formatted)

        assert "timestamp" in log_dict
        # タイムスタンプ形式の検証（ISO 8601形式）
        assert "T" in log_dict["timestamp"]
        assert log_dict["timestamp"].endswith("Z")

    def test_format_adds_severity(self):
        """format() が severity フィールドを追加すること"""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.WARNING,
            pathname="test.py",
            lineno=10,
            msg="Warning message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        log_dict = json.loads(formatted)

        assert "severity" in log_dict
        assert log_dict["severity"] == "WARNING"

    def test_format_includes_name_and_message(self):
        """format() が name と message を含むこと"""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="my.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test log message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        log_dict = json.loads(formatted)

        assert log_dict["name"] == "my.logger"
        assert log_dict["message"] == "Test log message"

    def test_format_different_log_levels(self):
        """異なるログレベルで severity が正しく設定されること"""
        formatter = JsonFormatter()

        test_cases = [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRITICAL"),
        ]

        for log_level, expected_severity in test_cases:
            record = logging.LogRecord(
                name="test",
                level=log_level,
                pathname="test.py",
                lineno=1,
                msg="message",
                args=(),
                exc_info=None,
            )
            formatted = formatter.format(record)
            log_dict = json.loads(formatted)
            assert log_dict["severity"] == expected_severity

    def test_format_output_is_valid_json(self):
        """format() の出力が有効なJSONであること"""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        # JSON としてパース可能であることを確認
        log_dict = json.loads(formatted)
        assert isinstance(log_dict, dict)

    def test_format_adds_thread_labels(self):
        """format() が Cloud Logging の labels にスレッド情報を追加すること"""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        log_dict = json.loads(formatted)

        # Cloud Logging の labels キーが存在すること
        labels_key = "logging.googleapis.com/labels"
        assert labels_key in log_dict

        labels = log_dict[labels_key]
        # thread_id と thread_name が含まれていること
        assert "thread_id" in labels
        assert "thread_name" in labels
        # thread_id は文字列であること
        assert isinstance(labels["thread_id"], str)
        # thread_id は record.thread と一致すること
        assert labels["thread_id"] == str(record.thread)

    def test_format_with_custom_labels(self):
        """コンストラクタで指定したカスタム labels が出力に含まれること"""
        custom_labels = {"service": "my-service", "version": "1.0.0"}
        formatter = JsonFormatter(labels=custom_labels)
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        log_dict = json.loads(formatted)

        labels_key = "logging.googleapis.com/labels"
        labels = log_dict[labels_key]

        # カスタム labels が含まれていること
        assert labels["service"] == "my-service"
        assert labels["version"] == "1.0.0"
        # スレッド情報も含まれていること
        assert "thread_id" in labels
        assert "thread_name" in labels

    def test_format_with_empty_labels(self):
        """labels に空の辞書を指定した場合もスレッド情報が追加されること"""
        formatter = JsonFormatter(labels={})
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        log_dict = json.loads(formatted)

        labels_key = "logging.googleapis.com/labels"
        labels = log_dict[labels_key]

        # スレッド情報が含まれていること
        assert "thread_id" in labels
        assert "thread_name" in labels

    def test_format_with_none_labels(self):
        """labels に None を指定した場合もスレッド情報が追加されること"""
        formatter = JsonFormatter(labels=None)
        record = logging.LogRecord(
            name="test_logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        log_dict = json.loads(formatted)

        labels_key = "logging.googleapis.com/labels"
        labels = log_dict[labels_key]

        # スレッド情報が含まれていること
        assert "thread_id" in labels
        assert "thread_name" in labels

    def _format_with_exception(self, level: int) -> dict:
        import sys

        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test_logger",
            level=level,
            pathname="test.py",
            lineno=10,
            msg="failed",
            args=(),
            exc_info=exc_info,
        )
        return json.loads(formatter.format(record))

    def test_format_moves_exc_info_to_stack_trace_for_error(self):
        """ERROR 以上の例外情報を Error Reporting が認識する stack_trace に載せ替えること"""
        log_dict = self._format_with_exception(logging.ERROR)
        assert "Traceback" in log_dict["stack_trace"]
        assert "ValueError: boom" in log_dict["stack_trace"]
        assert "exc_info" not in log_dict

    def test_format_keeps_exc_info_for_warning(self):
        """WARNING 以下の例外情報は exc_info のまま残すこと (Error Reporting に載せない)"""
        log_dict = self._format_with_exception(logging.WARNING)
        assert "Traceback" in log_dict["exc_info"]
        assert "stack_trace" not in log_dict

    def test_format_without_exc_info_has_no_stack_trace(self):
        """例外情報がない場合は stack_trace を追加しないこと"""
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="failed",
            args=(),
            exc_info=None,
        )
        log_dict = json.loads(formatter.format(record))
        assert "stack_trace" not in log_dict
        assert "exc_info" not in log_dict

    def test_format_does_not_overwrite_explicit_stack_trace(self):
        """呼び出し側が明示的に指定した stack_trace を上書きしないこと"""
        import sys

        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="failed",
            args=(),
            exc_info=exc_info,
        )
        record.stack_trace = "custom stack trace"
        log_dict = json.loads(formatter.format(record))
        assert log_dict["stack_trace"] == "custom stack trace"
        assert "Traceback" in log_dict["exc_info"]
