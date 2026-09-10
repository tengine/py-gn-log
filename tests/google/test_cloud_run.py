import logging

import pytest

from gnlog.fingerprint import build_fingerprint
from gnlog.google.cloud_run import is_cloud_run, setup_logging, use_json_output
from gnlog.output import TEXT_LOG_FORMAT
from gnlog.google.cloud_logging import JsonFormatter


class TestSetupLogging:
    """setup_logging() のテスト"""

    def _reset_loggers(self):
        """ルートロガーとテスト用ロガーの状態をリセット

        ``test.logger`` のような名前付きロガーは logging モジュールにグローバルに
        保持され、テスト間でハンドラ等の状態がリークする。さらに pytest が
        ログキャプチャ用の ``LogCaptureHandler`` を差し込むため、``apply()`` 系
        テストのハンドラ数アサーションが実行環境 (例: ``--cov`` 有無) によって
        壊れる。各テストの前後でルートと ``test.logger`` のハンドラを
        明示的にクリアして状態を分離する。
        """
        logging.root.handlers.clear()
        logging.root.setLevel(logging.WARNING)
        test_logger = logging.getLogger("test.logger")
        test_logger.handlers.clear()
        test_logger.propagate = True

    def setup_method(self):
        """各テストの前にログハンドラをクリア"""
        self._reset_loggers()

    def teardown_method(self):
        """各テストの後にログハンドラをクリア"""
        self._reset_loggers()

    def test_setup_creates_stream_handler_by_default(self, monkeypatch):
        """Cloud Run 環境変数がない場合、StreamHandler が作成されること"""
        monkeypatch.delenv("K_SERVICE", raising=False)
        monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
        monkeypatch.delenv("CLOUD_RUN_WORKER_POOL", raising=False)
        monkeypatch.delenv("LOG_FILE_PATH", raising=False)

        setup = setup_logging(log_level=logging.INFO)

        assert isinstance(setup.handler, logging.StreamHandler)
        assert setup.log_level_default == logging.INFO
        # ローカル環境では JsonFormatter は使われないこと
        from gnlog.google.cloud_logging import JsonFormatter

        assert not isinstance(setup.handler.formatter, JsonFormatter)

    def test_setup_creates_json_formatter_on_cloud_run_service(self, monkeypatch):
        """K_SERVICE がある場合 (Cloud Run Service)、JsonFormatter が使用されること"""
        monkeypatch.setenv("K_SERVICE", "test-service")
        monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
        monkeypatch.delenv("CLOUD_RUN_WORKER_POOL", raising=False)

        setup = setup_logging(log_level=logging.INFO)

        assert isinstance(setup.handler, logging.StreamHandler)
        # JsonFormatter が設定されていることを確認
        from gnlog.google.cloud_logging import JsonFormatter

        assert isinstance(setup.handler.formatter, JsonFormatter)

    def test_setup_creates_json_formatter_on_cloud_run_job(self, monkeypatch):
        """CLOUD_RUN_JOB がある場合 (Cloud Run Job)、JsonFormatter が使用されること"""
        # Cloud Run Job では K_SERVICE は設定されず CLOUD_RUN_JOB のみが設定される
        monkeypatch.delenv("K_SERVICE", raising=False)
        monkeypatch.setenv("CLOUD_RUN_JOB", "test-job")
        monkeypatch.delenv("CLOUD_RUN_WORKER_POOL", raising=False)

        setup = setup_logging(log_level=logging.INFO)

        assert isinstance(setup.handler, logging.StreamHandler)
        # JsonFormatter が設定されていることを確認
        from gnlog.google.cloud_logging import JsonFormatter

        assert isinstance(setup.handler.formatter, JsonFormatter)

    def test_setup_creates_json_formatter_on_cloud_run_worker_pool(self, monkeypatch):
        """CLOUD_RUN_WORKER_POOL がある場合 (Worker Pool)、JsonFormatter が使われること"""
        # Worker Pool では K_SERVICE / CLOUD_RUN_JOB は設定されず
        # CLOUD_RUN_WORKER_POOL のみが設定される
        monkeypatch.delenv("K_SERVICE", raising=False)
        monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
        monkeypatch.setenv("CLOUD_RUN_WORKER_POOL", "test-worker-pool")

        setup = setup_logging(log_level=logging.INFO)

        assert isinstance(setup.handler, logging.StreamHandler)
        # JsonFormatter が設定されていることを確認
        from gnlog.google.cloud_logging import JsonFormatter

        assert isinstance(setup.handler.formatter, JsonFormatter)

    def test_setup_passes_json_ensure_ascii_to_formatter(self, monkeypatch):
        """json_ensure_ascii が JsonFormatter に渡されること"""
        monkeypatch.setenv("K_SERVICE", "test-service")

        setup = setup_logging(
            log_level=logging.INFO, verbose=False, json_ensure_ascii=False
        )

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="日本語",
            args=(),
            exc_info=None,
        )
        assert setup.handler.formatter is not None
        assert "日本語" in setup.handler.formatter.format(record)

    def test_setup_passes_error_event_and_surface_to_formatter(self, monkeypatch):
        """error_event と surface が JsonFormatter に渡されること"""
        monkeypatch.setenv("K_SERVICE", "test-service")

        setup = setup_logging(
            log_level=logging.INFO,
            verbose=False,
            error_event="app_error",
            surface="worker",
        )

        record = logging.LogRecord(
            name="app",
            level=logging.ERROR,
            pathname="test.py",
            lineno=1,
            msg="failed",
            args=(),
            exc_info=None,
        )
        assert setup.handler.formatter is not None
        import json

        log_dict = json.loads(setup.handler.formatter.format(record))
        assert log_dict["event"] == "app_error"
        assert log_dict["fingerprint"] == build_fingerprint(
            "worker", "app", "unknown", "failed"
        )

    def test_setup_respects_log_level_parameter(self):
        """log_level パラメータが反映されること"""
        setup = setup_logging(log_level=logging.DEBUG)
        assert setup.log_level_default == logging.DEBUG
        assert setup.handler.level == logging.DEBUG

    def test_setup_uses_env_log_level_when_none(self, monkeypatch):
        """log_level が None の場合、環境変数から読み込むこと"""
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        setup = setup_logging()
        assert setup.log_level_default == logging.ERROR

    def test_setup_adds_handler_to_root_logger(self):
        """ルートロガーにハンドラが追加されること"""
        setup = setup_logging(log_level=logging.INFO)
        assert len(logging.root.handlers) == 1
        assert logging.root.handlers[0] == setup.handler

    def test_apply_returns_configured_logger(self):
        """apply() がロガーを返し、設定が適用されること"""
        setup = setup_logging(log_level=logging.INFO)
        logger = setup.apply("test.logger")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.logger"
        assert logger.level == logging.INFO

    def test_apply_with_custom_log_level(self):
        """apply() で個別のログレベルを指定できること"""
        setup = setup_logging(log_level=logging.INFO)
        logger = setup.apply("test.logger", log_level=logging.DEBUG)

        assert logger.level == logging.DEBUG

    def test_apply_with_propagate_false(self):
        """apply() で propagate を False に設定できること"""
        setup = setup_logging(log_level=logging.INFO)
        logger = setup.apply("test.logger", propagate=False)

        assert logger.propagate is False

    def test_apply_clear_handlers(self):
        """apply() の clear_handlers オプションが動作すること"""
        setup = setup_logging(log_level=logging.INFO)
        # pytest のログキャプチャや他テストの影響を避けるため固有のロガー名を使う
        logger_name = "test.apply_clear_handlers"
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()

        # 既存のハンドラを追加
        dummy_handler = logging.StreamHandler()
        logger.addHandler(dummy_handler)
        assert len(logger.handlers) == 1

        # clear_handlers=True で既存ハンドラがクリアされること
        setup.apply(logger_name, clear_handlers=True)
        assert len(logger.handlers) == 0

    def test_apply_add_handler(self):
        """apply() の add_handler オプションが動作すること"""
        setup = setup_logging(log_level=logging.INFO)
        # pytest のログキャプチャや他テストの影響を避けるため固有のロガー名を使う
        logger_name = "test.apply_add_handler"
        logging.getLogger(logger_name).handlers.clear()
        logger = setup.apply(logger_name, add_handler=True)

        # ロガーにハンドラが追加されていること
        assert len(logger.handlers) == 1
        assert logger.handlers[0] == setup.handler

    def test_root_level_follows_log_level_by_default(self):
        """既定では apply() していないロガーの INFO も handler に届くこと"""
        records: list[logging.LogRecord] = []

        class Collector(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        setup_logging(log_level=logging.INFO, verbose=False)
        collector = Collector()
        logging.root.addHandler(collector)
        try:
            other = logging.getLogger("test.not_applied_module")
            other.setLevel(logging.NOTSET)  # 親 (root) の level に従わせる
            other.info("INFO from a module that was not applied")
        finally:
            logging.root.removeHandler(collector)

        assert [r.getMessage() for r in records] == [
            "INFO from a module that was not applied"
        ]

    def test_set_root_level_false_keeps_root_level(self):
        """set_root_level=False ではルートロガーの level を変更しないこと"""
        logging.root.setLevel(logging.WARNING)

        setup_logging(log_level=logging.DEBUG, verbose=False, set_root_level=False)

        assert logging.root.level == logging.WARNING

    def test_verbose_default_prints_diagnostics_to_stderr(self, capsys):
        """既定 (verbose=True) では診断出力が標準エラー出力に出ること"""
        setup = setup_logging(log_level=logging.INFO)
        setup.apply("test.verbose_default", clear_handlers=True)

        captured = capsys.readouterr()
        assert "gnlog setup starting" in captured.err
        assert "gnlog initialized logger" in captured.err
        assert captured.out == ""

    def test_verbose_false_suppresses_diagnostics(self, capsys):
        """verbose=False では診断出力が一切出ないこと"""
        # 既存ハンドラがある状態でも "clearing handlers" が出ないことを確認する
        logging.root.addHandler(logging.NullHandler())
        logger_name = "test.verbose_false"
        logging.getLogger(logger_name).addHandler(logging.NullHandler())

        setup = setup_logging(log_level=logging.INFO, verbose=False)
        setup.apply(logger_name, clear_handlers=True)

        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out == ""


class TestUseJsonOutput:
    """use_json_output 関数と setup_logging(json=...) のテスト"""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        for name in ("K_SERVICE", "CLOUD_RUN_JOB", "CLOUD_RUN_WORKER_POOL"):
            monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv("GNLOG_FORMAT", raising=False)
        monkeypatch.delenv("LOG_FILE_PATH", raising=False)
        logging.root.handlers.clear()
        yield
        logging.root.handlers.clear()

    def test_defaults_to_cloud_run_detection(self, monkeypatch):
        """引数も環境変数もない場合は Cloud Run 上かどうかで決まること"""
        assert use_json_output() is False
        monkeypatch.setenv("K_SERVICE", "svc")
        assert use_json_output() is True

    def test_env_json_forces_json_outside_cloud_run(self, monkeypatch):
        """GNLOG_FORMAT=json なら Cloud Run 外でも JSON になること"""
        monkeypatch.setenv("GNLOG_FORMAT", "json")
        assert use_json_output() is True
        setup = setup_logging(log_level=logging.INFO, verbose=False)
        assert isinstance(setup.handler.formatter, JsonFormatter)

    def test_env_text_forces_text_on_cloud_run(self, monkeypatch):
        """GNLOG_FORMAT=text なら Cloud Run 上でもテキストになること"""
        monkeypatch.setenv("K_SERVICE", "svc")
        monkeypatch.setenv("GNLOG_FORMAT", "text")
        assert use_json_output() is False
        setup = setup_logging(log_level=logging.INFO, verbose=False)
        assert not isinstance(setup.handler.formatter, JsonFormatter)

    def test_env_value_is_case_insensitive(self, monkeypatch):
        """GNLOG_FORMAT の値は大文字小文字と前後の空白を区別しないこと"""
        monkeypatch.setenv("GNLOG_FORMAT", " JSON ")
        assert use_json_output() is True

    def test_env_empty_is_treated_as_unset(self, monkeypatch):
        """GNLOG_FORMAT が空文字なら未設定と同じ扱いになること"""
        monkeypatch.setenv("GNLOG_FORMAT", "")
        assert use_json_output() is False

    def test_env_invalid_value_raises(self, monkeypatch):
        """GNLOG_FORMAT が json / text 以外なら分かるメッセージで ValueError になること"""
        monkeypatch.setenv("GNLOG_FORMAT", "yaml")
        with pytest.raises(ValueError, match="GNLOG_FORMAT.*'json' or 'text'"):
            use_json_output()

    def test_argument_overrides_env_and_cloud_run(self, monkeypatch):
        """引数 json は環境変数と Cloud Run 判定より優先されること"""
        monkeypatch.setenv("K_SERVICE", "svc")
        monkeypatch.setenv("GNLOG_FORMAT", "json")
        assert use_json_output(False) is False
        setup = setup_logging(log_level=logging.INFO, verbose=False, json=False)
        assert not isinstance(setup.handler.formatter, JsonFormatter)

    def test_setup_json_true_outside_cloud_run(self):
        """setup_logging(json=True) で Cloud Run 外でも JsonFormatter が使われること"""
        setup = setup_logging(log_level=logging.INFO, verbose=False, json=True)
        assert isinstance(setup.handler.formatter, JsonFormatter)

    def test_log_format_json_is_still_a_format_string(self, monkeypatch):
        """LOG_FORMAT の意味は変えない (LOG_FORMAT=json は format 文字列として扱われ失敗する)"""
        monkeypatch.setenv("LOG_FORMAT", "json")
        with pytest.raises(ValueError):
            setup_logging(log_level=logging.INFO, verbose=False)


class TestIsCloudRun:
    """is_cloud_run 関数のテスト"""

    def test_returns_false_when_no_env_vars(self, monkeypatch):
        """Cloud Run 環境変数がない場合は False を返すこと"""
        monkeypatch.delenv("K_SERVICE", raising=False)
        monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
        monkeypatch.delenv("CLOUD_RUN_WORKER_POOL", raising=False)

        assert is_cloud_run() is False

    def test_returns_true_on_cloud_run_service(self, monkeypatch):
        """K_SERVICE がある場合 (Cloud Run Service) は True を返すこと"""
        monkeypatch.setenv("K_SERVICE", "test-service")
        monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
        monkeypatch.delenv("CLOUD_RUN_WORKER_POOL", raising=False)

        assert is_cloud_run() is True

    def test_returns_true_on_cloud_run_job(self, monkeypatch):
        """CLOUD_RUN_JOB がある場合 (Cloud Run Job) は True を返すこと"""
        monkeypatch.delenv("K_SERVICE", raising=False)
        monkeypatch.setenv("CLOUD_RUN_JOB", "test-job")
        monkeypatch.delenv("CLOUD_RUN_WORKER_POOL", raising=False)

        assert is_cloud_run() is True

    def test_returns_true_on_cloud_run_worker_pool(self, monkeypatch):
        """CLOUD_RUN_WORKER_POOL がある場合 (Worker Pool) は True を返すこと"""
        monkeypatch.delenv("K_SERVICE", raising=False)
        monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
        monkeypatch.setenv("CLOUD_RUN_WORKER_POOL", "test-worker-pool")

        assert is_cloud_run() is True


class TestLocalLogFormat:
    """TEXT_LOG_FORMAT 定数のテスト"""

    def test_local_log_format_is_defined(self):
        """TEXT_LOG_FORMAT が定義されていること"""
        assert TEXT_LOG_FORMAT is not None
        assert isinstance(TEXT_LOG_FORMAT, str)
        assert len(TEXT_LOG_FORMAT) > 0
