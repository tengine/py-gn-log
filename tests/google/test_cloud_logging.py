import json
import logging
from datetime import UTC, datetime

import pytest

from gnlog.fingerprint import build_fingerprint
from gnlog.google.cloud_logging import JsonFormatter


class TestJsonFormatter:
    """JsonFormatter クラスのテスト"""

    def test_parse_returns_expected_fields(self):
        """parse() が期待するフィールドを返すこと"""
        formatter = JsonFormatter()
        fields = formatter.parse()
        assert fields == ["name", "message"]

    def test_format_adds_time_in_rfc3339_utc(self):
        """format() が時刻を RFC 3339 形式 (UTC、マイクロ秒まで) でフィールド time に入れること"""
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
        record.created = datetime(2026, 10, 10, 0, 0, 0, 123456, tzinfo=UTC).timestamp()

        formatted = formatter.format(record)
        log_dict = json.loads(formatted)

        assert log_dict["time"] == "2026-10-10T00:00:00.123456Z"
        # Cloud Logging がログエントリーの時刻として読まない文字列のフィールド timestamp は出さない
        assert "timestamp" not in log_dict

    def test_format_overwrites_time_passed_by_extra(self):
        """引数 extra で渡したフィールド time を、クラス LogRecord の作成時刻で上書きすること"""
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
        record.created = datetime(2026, 10, 10, 0, 0, 0, 123456, tzinfo=UTC).timestamp()
        record.time = "not a time"

        formatted = formatter.format(record)
        log_dict = json.loads(formatted)

        assert log_dict["time"] == "2026-10-10T00:00:00.123456Z"

    def test_format_keeps_entry_time_fields_passed_by_extra(self):
        """extra で渡したログエントリーの時刻のフィールドを、上書きせずに出力すること"""
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
        record.timestamp = {"seconds": 1791590400, "nanos": 0}
        record.timestampSeconds = 1791590400
        record.timestampNanos = 0

        formatted = formatter.format(record)
        log_dict = json.loads(formatted)

        assert log_dict["timestamp"] == {"seconds": 1791590400, "nanos": 0}
        assert log_dict["timestampSeconds"] == 1791590400
        assert log_dict["timestampNanos"] == 0

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

    def _format_with_stack_info(
        self, sinfo: str | None, rename_fields: dict[str, str] | None
    ) -> dict:
        formatter = JsonFormatter(rename_fields=rename_fields)
        record = logging.LogRecord(
            name="my.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test log message",
            args=(),
            exc_info=None,
            sinfo=sinfo,
        )
        return json.loads(formatter.format(record))

    @pytest.mark.parametrize(
        ("rename_fields", "key"),
        [(None, "stack_info"), ({"stack_info": "stack"}, "stack")],
    )
    def test_format_omits_stack_info_without_stack(self, rename_fields, key):
        """stack_info=True を指定していない行には、フィールド stack_info (名前を変えていればその名前) を出さないこと (#48)

        値が常に null のキーが付くと、出力の形を決めて検査する利用側では決めた形に無いキーになり、
        BigQuery へのシンクでは常に NULL の列ができるため。
        """
        log_dict = self._format_with_stack_info(None, rename_fields)
        assert key not in log_dict
        assert "stack_info" not in log_dict

    @pytest.mark.parametrize(
        ("rename_fields", "key"),
        [(None, "stack_info"), ({"stack_info": "stack"}, "stack")],
    )
    def test_format_keeps_stack_info_with_stack(self, rename_fields, key):
        """stack_info=True を指定した行には、これまでどおりフィールド stack_info (名前を変えていればその名前) を出すこと"""
        sinfo = 'Stack (most recent call last):\n  File "app.py", line 1, in <module>'
        log_dict = self._format_with_stack_info(sinfo, rename_fields)
        assert log_dict[key] == sinfo

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

    @pytest.mark.parametrize("level", ["debug", 5, None])
    def test_format_severity_ignores_level_passed_by_extra(self, level):
        """extra などで渡したフィールド level で severity を変えず、level はそのまま出力すること (#44)

        ERROR のログが別の重大度として扱われると、severity で絞り込むクエリ・ログベースの指標・
        Error Reporting の対象から外れる。文字列でない level で、ログの行が失われることも無くす。
        """
        formatter = JsonFormatter(error_event="app_error")
        record = logging.LogRecord(
            name="app",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="boom",
            args=(),
            exc_info=None,
        )
        record.level = level
        log_dict = json.loads(formatter.format(record))
        assert log_dict["severity"] == "ERROR"
        assert log_dict["level"] == level
        assert log_dict["event"] == "app_error"

    def test_format_severity_ignores_level_in_context(self):
        """gnlog.context で置いたフィールド level でも、severity を変えないこと (#44)"""
        import io

        from gnlog import context

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(JsonFormatter())
        handler.addFilter(context.ContextFilter())
        logger = logging.getLogger("test.cloud_logging.level_in_context")
        logger.addHandler(handler)
        logger.propagate = False
        try:
            with context.bind(level="debug"):
                logger.error("boom")
        finally:
            logger.removeHandler(handler)
            logger.propagate = True
        log_dict = json.loads(stream.getvalue())
        assert log_dict["severity"] == "ERROR"
        assert log_dict["level"] == "debug"

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

    def _format_error_fields(self, level=logging.ERROR, extra=None, **kwargs) -> dict:
        formatter = JsonFormatter(**kwargs)
        record = logging.LogRecord(
            name="app.orders",
            level=level,
            pathname="test.py",
            lineno=10,
            msg="order %s not found",
            args=(123,),
            exc_info=None,
        )
        for key, value in (extra or {}).items():
            setattr(record, key, value)
        return json.loads(formatter.format(record))

    def test_error_fields_are_not_added_by_default(self):
        """error_event 未指定なら ERROR でも分類や fingerprint を付けないこと"""
        log_dict = self._format_error_fields()
        for key in ("event", "error_type", "operation", "fingerprint"):
            assert key not in log_dict

    def test_error_fields_added_for_error_with_defaults(self):
        """error_event 指定時、ERROR に既定値 (unknown / ロガー名) で付けること"""
        log_dict = self._format_error_fields(error_event="app_error", surface="worker")
        assert log_dict["event"] == "app_error"
        assert log_dict["error_type"] == "unknown"
        assert log_dict["operation"] == "app.orders"
        assert log_dict["fingerprint"] == build_fingerprint(
            "worker", "app.orders", "unknown", "order 123 not found"
        )

    def test_error_fields_use_extra_values(self):
        """extra で渡した error_type / operation を使い、fingerprint にも反映すること"""
        log_dict = self._format_error_fields(
            error_event="app_error",
            surface="worker",
            extra={"error_type": "validation", "operation": "orders.get"},
        )
        assert log_dict["error_type"] == "validation"
        assert log_dict["operation"] == "orders.get"
        assert log_dict["fingerprint"] == build_fingerprint(
            "worker", "orders.get", "validation", "order 123 not found"
        )

    def test_error_fields_emit_same_string_as_hashed_for_non_str_values(self):
        """operation / error_type が文字列でなくても、出力と fingerprint の入力が同じ文字列になること"""
        log_dict = self._format_error_fields(
            error_event="app_error",
            surface="worker",
            extra={"error_type": 42, "operation": ["a", "b"]},
        )
        assert log_dict["error_type"] == "42"
        assert log_dict["operation"] == "['a', 'b']"
        # 出力された JSON の値だけから fingerprint を再計算できる
        assert log_dict["fingerprint"] == build_fingerprint(
            "worker", log_dict["operation"], log_dict["error_type"], log_dict["message"]
        )

    def test_error_fields_do_not_overwrite_explicit_event_and_fingerprint(self):
        """extra で渡した event / fingerprint を上書きしないこと"""
        log_dict = self._format_error_fields(
            error_event="app_error",
            extra={"event": "custom_event", "fingerprint": "deadbeefdeadbeef"},
        )
        assert log_dict["event"] == "custom_event"
        assert log_dict["fingerprint"] == "deadbeefdeadbeef"

    def test_error_fields_added_for_critical(self):
        """CRITICAL にも付けること"""
        log_dict = self._format_error_fields(
            level=logging.CRITICAL, error_event="app_error"
        )
        assert log_dict["event"] == "app_error"

    def test_error_fields_not_added_for_warning(self):
        """WARNING 以下には付けないこと"""
        log_dict = self._format_error_fields(
            level=logging.WARNING, error_event="app_error"
        )
        for key in ("event", "error_type", "operation", "fingerprint"):
            assert key not in log_dict

    def test_error_fields_surface_defaults_to_empty(self):
        """surface 未指定なら空文字として fingerprint を計算すること"""
        log_dict = self._format_error_fields(error_event="app_error")
        assert log_dict["fingerprint"] == build_fingerprint(
            "", "app.orders", "unknown", "order 123 not found"
        )

    def _format_japanese_message(self, **kwargs) -> str:
        formatter = JsonFormatter(**kwargs)
        record = logging.LogRecord(
            name="test_logger",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg="マスタが未登録です",
            args=(),
            exc_info=None,
        )
        return formatter.format(record)

    def test_format_escapes_non_ascii_by_default(self):
        """既定では非 ASCII 文字が \\uXXXX に escape されること (python-json-logger と同じ)"""
        formatted = self._format_japanese_message()
        assert "マスタが未登録です" not in formatted
        assert "\\u30de\\u30b9\\u30bf" in formatted  # "マスタ"
        assert json.loads(formatted)["message"] == "マスタが未登録です"

    def test_format_keeps_non_ascii_when_json_ensure_ascii_false(self):
        """json_ensure_ascii=False では非 ASCII 文字がそのまま出力されること"""
        formatted = self._format_japanese_message(json_ensure_ascii=False)
        assert "マスタが未登録です" in formatted
        assert json.loads(formatted)["message"] == "マスタが未登録です"

    def test_format_renames_fields_with_rename_fields(self):
        """引数 rename_fields で、ロガー名と、引数 extra で渡したフィールドの名前が変わること"""
        formatter = JsonFormatter(rename_fields={"name": "logger", "user_id": "uid"})
        record = logging.LogRecord(
            name="audit_log",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.user_id = 123
        log_dict = json.loads(formatter.format(record))
        assert log_dict["logger"] == "audit_log"
        assert "name" not in log_dict
        assert log_dict["uid"] == 123
        assert "user_id" not in log_dict
        # このクラスが後から入れるフィールドの名前は変わらない
        assert log_dict["severity"] == "INFO"
        assert "time" in log_dict

    @pytest.mark.parametrize(
        "key",
        [
            "time",
            "level",
            "severity",
            "logging.googleapis.com/labels",
            "exc_info",
            "stack_trace",
            "event",
            "error_type",
            "operation",
            "fingerprint",
        ],
    )
    def test_rename_fields_rejects_keys_the_formatter_reads_or_writes(self, key):
        """このクラスが読み書きするキーは、引数 rename_fields の変換前にも変換後にも使えないこと"""
        with pytest.raises(ValueError, match="rename_fields"):
            JsonFormatter(rename_fields={key: "renamed"})
        with pytest.raises(ValueError, match="rename_fields"):
            JsonFormatter(rename_fields={"name": key})

    @pytest.mark.parametrize(
        "rename_fields",
        [
            # 複数のキーを同じ名前に変える
            {"a": "x", "b": "x"},
            # 名前を変えていない name・message・stack_info と同じ名前に変える
            {"name": "message"},
            {"user_id": "name"},
            {"detail": "message"},
            {"user_id": "stack_info"},
        ],
    )
    def test_rename_fields_rejects_names_that_overlap(self, rename_fields):
        """変換後の名前が重なり、片方の値が出力から失われる引数 rename_fields を拒むこと"""
        with pytest.raises(ValueError, match="rename_fields"):
            JsonFormatter(rename_fields=rename_fields)

    @pytest.mark.parametrize(
        "rename_fields",
        [
            {"name": None},
            {"name": 1},
            {"name": ["x"]},
            {1: "x"},
        ],
    )
    def test_rename_fields_rejects_keys_and_values_that_are_not_str(
        self, rename_fields
    ):
        """引数 rename_fields のキーか値に文字列でないものがあれば例外 TypeError にすること"""
        with pytest.raises(TypeError, match="rename_fields"):
            JsonFormatter(rename_fields=rename_fields)

    def test_rename_fields_allows_swapping_names(self):
        """名前を変えるフィールドどうしなら、変換後の名前が元の名前と同じでも受け付けること"""
        formatter = JsonFormatter(rename_fields={"name": "message", "message": "msg"})
        record = logging.LogRecord(
            name="audit_log",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        log_dict = json.loads(formatter.format(record))
        assert log_dict["message"] == "audit_log"
        assert log_dict["msg"] == "Test message"
        assert "name" not in log_dict

    def test_error_fields_fingerprint_uses_renamed_message(self):
        """フィールド message の名前を変えても、出力したメッセージからフィールド fingerprint の値を計算すること"""
        formatter = JsonFormatter(
            error_event="app_error", rename_fields={"message": "msg"}
        )
        # 辞書を渡すと、python-json-logger は辞書のキー message の値を出力する
        record = logging.LogRecord(
            name="app.orders",
            level=logging.ERROR,
            pathname="test.py",
            lineno=10,
            msg={"message": "order 123 not found"},
            args=(),
            exc_info=None,
        )
        log_dict = json.loads(formatter.format(record))
        assert log_dict["msg"] == "order 123 not found"
        assert log_dict["fingerprint"] == build_fingerprint(
            "", "app.orders", "unknown", "order 123 not found"
        )

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


class TestValidationErrorInput:
    """入力の検証の例外のメッセージから、入力の値を除いて出力することのテスト (#49)

    pydantic と FastAPI の入力の検証の例外は、メッセージに入力の値 (リクエストや
    レスポンスの本文。個人情報やトークンを含みうる) が入る。そのまま出力すると、
    ログに入力の値が残る。
    """

    SECRET = "token-abc123"
    EMAIL = "taro@example.com"

    @staticmethod
    def _format(exc: BaseException, level: int = logging.ERROR) -> dict:
        record = logging.LogRecord(
            name="app",
            level=level,
            pathname="test.py",
            lineno=10,
            msg="会員の登録に失敗",
            args=(),
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return json.loads(JsonFormatter().format(record))

    def _pydantic_error(self) -> Exception:
        import pydantic

        class Member(pydantic.BaseModel):
            email: str
            age: int

        try:
            Member.model_validate({"email": self.EMAIL, "age": self.SECRET})
        except pydantic.ValidationError as e:
            return e
        raise AssertionError("ValidationError が送出されなかった")

    def _fastapi_error(self, name: str) -> Exception:
        from fastapi import exceptions

        error_class = getattr(exceptions, name)
        errors = [
            {
                "type": "int_parsing",
                "loc": ("body", "age"),
                "msg": "Input should be a valid integer",
                "input": self.SECRET,
            }
        ]
        try:
            raise error_class(errors, body={"email": self.EMAIL, "age": self.SECRET})
        except exceptions.ValidationException as e:
            return e
        raise AssertionError(f"{name} が送出されなかった")

    def test_pydantic_validation_error_omits_input(self):
        """pydantic の ValidationError は、入力の値を除き、場所と種類だけをフィールド stack_trace に出すこと"""
        stack_trace = self._format(self._pydantic_error())["stack_trace"]
        assert self.SECRET not in stack_trace
        assert self.EMAIL not in stack_trace
        assert "Traceback (most recent call last)" in stack_trace
        assert stack_trace.endswith(
            "pydantic_core._pydantic_core.ValidationError: "
            "1 validation error(s) (input omitted): age [int_parsing]"
        )

    def test_pydantic_message_with_input_is_not_output(self):
        """pydantic の組み込みの説明 (msg) も出さないこと

        説明には、タグで型を選ぶ union (discriminated union) のタグの値のように、入力の値を
        埋め込むものがある。
        """
        from typing import Literal

        import pydantic

        class Cat(pydantic.BaseModel):
            kind: Literal["cat"]

        class Dog(pydantic.BaseModel):
            kind: Literal["dog"]

        class Pet(pydantic.BaseModel):
            pet: Cat | Dog = pydantic.Field(discriminator="kind")

        try:
            Pet.model_validate({"pet": {"kind": self.SECRET}})
        except pydantic.ValidationError as e:
            stack_trace = self._format(e)["stack_trace"]
        assert self.SECRET not in stack_trace
        assert stack_trace.endswith(
            "1 validation error(s) (input omitted): pet [union_tag_invalid]"
        )

    def test_warning_exc_info_omits_input(self):
        """WARNING 以下で出すフィールド exc_info からも、入力の値を除くこと"""
        log_dict = self._format(self._pydantic_error(), level=logging.WARNING)
        assert "stack_trace" not in log_dict
        assert self.SECRET not in log_dict["exc_info"]
        assert "(input omitted): age [int_parsing]" in log_dict["exc_info"]

    @pytest.mark.parametrize(
        "name", ["RequestValidationError", "ResponseValidationError"]
    )
    def test_fastapi_validation_error_omits_input(self, name):
        """FastAPI の入力の検証の例外も、入力の値を除いて出すこと"""
        stack_trace = self._format(self._fastapi_error(name))["stack_trace"]
        assert self.SECRET not in stack_trace
        assert self.EMAIL not in stack_trace
        assert stack_trace.endswith(
            f"fastapi.exceptions.{name}: "
            "1 validation error(s) (input omitted): body.age [int_parsing]"
        )

    def test_fastapi_errors_that_are_not_dicts_omit_input(self):
        """FastAPI の例外の errors() の要素が辞書でなくても、整形を失敗させずに、中身を出さないこと

        FastAPI の ValidationException は、errors に任意の要素の列を受け付ける。
        辞書でない要素は入力の値を含みうるので、型の名前だけを出す。
        """
        from fastapi.exceptions import RequestValidationError

        try:
            raise RequestValidationError([f"age is invalid: {self.SECRET}"])
        except RequestValidationError as e:
            stack_trace = self._format(e)["stack_trace"]
        assert self.SECRET not in stack_trace
        assert stack_trace.endswith(
            "fastapi.exceptions.RequestValidationError: "
            "1 validation error(s) (input omitted): <str>"
        )

    def test_fastapi_error_loc_that_is_a_str(self):
        """errors() の要素の場所 (loc) が文字列なら、1 文字ずつではなく 1 つの要素として出すこと"""
        from fastapi.exceptions import RequestValidationError

        try:
            raise RequestValidationError(
                [{"type": "missing", "loc": "body", "msg": "Field required"}]
            )
        except RequestValidationError as e:
            stack_trace = self._format(e)["stack_trace"]
        assert stack_trace.endswith(
            "1 validation error(s) (input omitted): body [missing]"
        )

    @pytest.mark.parametrize(
        ("errors", "expected"),
        [
            (None, "<NoneType>"),
            (f"age is invalid: {SECRET}", "<str>"),
            ({"loc": ("age",), "type": "t", "msg": "m"}, "age [t]"),
        ],
    )
    def test_fastapi_errors_that_are_not_a_sequence(self, errors, expected):
        """FastAPI の例外の errors() が要素の列でなければ、1 つの要素として扱うこと

        反復できない値で整形を失敗させず、文字列や辞書を 1 文字ずつ・キーごとに数えないため。
        辞書でない値は、要素と同じく中身を出さない。
        """
        from fastapi.exceptions import RequestValidationError

        try:
            raise RequestValidationError(errors)
        except RequestValidationError as e:
            stack_trace = self._format(e)["stack_trace"]
        assert self.SECRET not in stack_trace
        assert stack_trace.endswith(
            f"1 validation error(s) (input omitted): {expected}"
        )

    @pytest.mark.parametrize("kind", [None, f"bad type: {SECRET}"])
    def test_fastapi_error_values_that_are_not_identifiers(self, kind):
        """errors() の要素の種類 (type) が識別子の形の文字列でなければ型の名前だけを、場所 (loc) が bytes なら <key> を出すこと

        アプリが作る FastAPI の例外では、種類にも任意の値が入りうる。bytes の場所を 1 バイトずつ
        数字で出すと、中身が読めてしまう。
        """
        from fastapi.exceptions import RequestValidationError

        errors = [{"loc": self.SECRET.encode(), "type": kind, "msg": self.SECRET}]
        try:
            raise RequestValidationError(errors)
        except RequestValidationError as e:
            stack_trace = self._format(e)["stack_trace"]
        assert self.SECRET not in stack_trace
        expected = "<NoneType>" if kind is None else "<str>"
        assert stack_trace.endswith(
            f"1 validation error(s) (input omitted): <key> [{expected}]"
        )

    @pytest.mark.parametrize("link", ["cause", "context"])
    def test_validation_error_in_chain_omits_input(self, link):
        """例外の連鎖 (__cause__ か __context__) の中の入力の検証の例外も、入力の値を除いて出すこと

        ほかの例外のメッセージは書き換えない。
        """
        validation_error = self._pydantic_error()
        try:
            if link == "cause":
                raise RuntimeError("会員の登録に失敗") from validation_error
            try:
                raise validation_error
            except Exception:
                raise RuntimeError("会員の登録に失敗")
        except RuntimeError as e:
            stack_trace = self._format(e)["stack_trace"]
        assert self.SECRET not in stack_trace
        assert "(input omitted): age [int_parsing]" in stack_trace
        assert "RuntimeError: 会員の登録に失敗" in stack_trace

    def test_validation_error_in_exception_group_omits_input(self):
        """ExceptionGroup の子の入力の検証の例外も、入力の値を除いて出すこと

        ExceptionGroup のメッセージと、ほかの子のメッセージは書き換えない。
        """
        try:
            raise ExceptionGroup(
                "複数の処理が失敗", [ValueError("別の失敗"), self._pydantic_error()]
            )
        except ExceptionGroup as e:
            stack_trace = self._format(e)["stack_trace"]
        assert self.SECRET not in stack_trace
        assert "(input omitted): age [int_parsing]" in stack_trace
        assert "ExceptionGroup: 複数の処理が失敗" in stack_trace
        assert "ValueError: 別の失敗" in stack_trace

    def test_loc_key_from_input_is_omitted(self):
        """場所 (loc) に入った辞書のキーのうち、識別子の形でないもの (入力の値でありうる) は出さないこと"""
        import pydantic

        class Scores(pydantic.BaseModel):
            scores: dict[str, int]

        try:
            Scores.model_validate({"scores": {self.EMAIL: self.SECRET}})
        except pydantic.ValidationError as e:
            stack_trace = self._format(e)["stack_trace"]
        assert self.EMAIL not in stack_trace
        assert self.SECRET not in stack_trace
        assert "(input omitted): scores.<key> [int_parsing]" in stack_trace

    def test_other_exception_with_failing_str_in_chain(self):
        """連鎖に入力の検証の例外があっても、__str__ が例外を出すほかの例外を標準の traceback と同じに出すこと

        整形ごと失敗すると、ログの行がまるごと出力されないため。
        """

        class Broken(Exception):
            def __str__(self) -> str:
                raise RuntimeError("str failed")

        try:
            try:
                raise self._pydantic_error()
            except Exception:
                raise Broken()
        except Broken as e:
            stack_trace = self._format(e)["stack_trace"]
        assert self.SECRET not in stack_trace
        assert "(input omitted): age [int_parsing]" in stack_trace
        assert stack_trace.endswith("Broken: <exception str() failed>")

    def test_other_exception_suggestion_in_chain(self):
        """連鎖に入力の検証の例外があっても、ほかの例外に traceback が付け足す出力 (提案と注記) を消さないこと"""
        validation_error = self._pydantic_error()

        def lookup() -> int:
            valuee = 1  # noqa: F841 (NameError の提案に出す名前)
            try:
                raise validation_error
            except Exception:
                return value  # type: ignore[name-defined]  # noqa: F821

        try:
            lookup()
        except NameError as e:
            e.add_note("会員の登録の途中")
            stack_trace = self._format(e)["stack_trace"]
        assert self.SECRET not in stack_trace
        assert (
            "NameError: name 'value' is not defined. Did you mean: 'valuee'?\n"
            "会員の登録の途中"
        ) in stack_trace

    def test_raises_when_message_cannot_be_replaced(self, monkeypatch):
        """TracebackException のメッセージを差し替えられない Python の版では、入力の値を出さずに例外を出すこと

        入力の値を除く仕組みは、TracebackException の非公開の属性 _str に頼る。属性が使われなく
        なった版では、代入がエラーを出さずに効かなくなり、入力の値がそのまま出力されてしまう。
        """
        import traceback

        class UnreplaceableTracebackException(traceback.TracebackException):
            """メッセージを _str 以外から返す TracebackException (属性の名前が変わった版の代わり)"""

            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._message_of_other_version = self._str

            def __str__(self) -> str:
                return self._message_of_other_version

        monkeypatch.setattr(
            traceback, "TracebackException", UnreplaceableTracebackException
        )
        with pytest.raises(RuntimeError, match="TracebackException"):
            self._format(self._pydantic_error())

    def test_logging_error_does_not_show_input(self, monkeypatch, capsys):
        """メッセージを差し替えられず整形が失敗したとき、logging が標準エラー出力に出す traceback にも入力の値を出さないこと

        logging は整形の失敗を、例外の連鎖ごと標準エラー出力に出す。処理中の入力の検証の例外が
        連鎖に入ると、入力の値も出てしまう。Cloud Run では標準エラー出力も Cloud Logging に入る。
        """
        import io
        import traceback

        class UnreplaceableTracebackException(traceback.TracebackException):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self._message_of_other_version = self._str

            def __str__(self) -> str:
                return self._message_of_other_version

        monkeypatch.setattr(
            traceback, "TracebackException", UnreplaceableTracebackException
        )
        handler = logging.StreamHandler(io.StringIO())
        handler.setFormatter(JsonFormatter())
        logger = logging.getLogger("test.cloud_logging.unreplaceable")
        logger.addHandler(handler)
        logger.propagate = False
        validation_error = self._pydantic_error()
        try:
            try:
                raise validation_error
            except Exception:
                logger.exception("会員の登録に失敗")
        finally:
            logger.removeHandler(handler)
            logger.propagate = True
        err = capsys.readouterr().err
        assert "--- Logging error ---" in err
        assert "RuntimeError: Cannot omit input values" in err
        assert self.SECRET not in err

    def test_other_exception_is_not_rewritten(self):
        """入力の検証の例外を含まない例外は、これまでどおり logging.Formatter と同じ形で出すこと"""
        try:
            raise ValueError(f"boom {self.SECRET}")
        except ValueError as e:
            exc_info = (type(e), e, e.__traceback__)
            stack_trace = self._format(e)["stack_trace"]
        assert stack_trace == logging.Formatter().formatException(exc_info)

    def test_original_exception_is_not_modified(self):
        """出力のために、元の例外のメッセージを書き換えないこと"""
        error = self._pydantic_error()
        self._format(error)
        assert self.SECRET in str(error)

    def test_does_not_import_pydantic_or_fastapi(self):
        """クラス JsonFormatter は、例外を出力するときも pydantic と FastAPI を読み込まないこと"""
        import subprocess
        import sys

        code = (
            "import json, logging, sys\n"
            "from gnlog.google.cloud_logging import JsonFormatter\n"
            "try:\n"
            "    raise ValueError('boom')\n"
            "except ValueError:\n"
            "    ei = sys.exc_info()\n"
            "record = logging.LogRecord('app', logging.ERROR, 'x.py', 1, 'm', (), ei)\n"
            "json.loads(JsonFormatter().format(record))\n"
            "print(' '.join(sorted(m for m in sys.modules "
            "if m.split('.')[0] in ('pydantic', 'pydantic_core', 'fastapi'))))\n"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], check=True, capture_output=True, text=True
        ).stdout
        assert out.split() == []
