import logging

from gnlog.init import Initializer, LOCAL_LOG_FORMAT, is_cloud_run


class TestInitializer:
    """Initializer クラスのテスト"""

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
        test_logger = logging.getLogger("test.logger")
        test_logger.handlers.clear()
        test_logger.propagate = True

    def setup_method(self):
        """各テストの前にログハンドラをクリア"""
        self._reset_loggers()

    def teardown_method(self):
        """各テストの後にログハンドラをクリア"""
        self._reset_loggers()

    def test_initializer_creates_stream_handler_by_default(self, monkeypatch):
        """Cloud Run 環境変数がない場合、StreamHandler が作成されること"""
        monkeypatch.delenv("K_SERVICE", raising=False)
        monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
        monkeypatch.delenv("CLOUD_RUN_WORKER_POOL", raising=False)
        monkeypatch.delenv("LOG_FILE_PATH", raising=False)

        initializer = Initializer(log_level=logging.INFO)

        assert isinstance(initializer.handler, logging.StreamHandler)
        assert initializer.log_level_default == logging.INFO
        # ローカル環境では JsonFormatter は使われないこと
        from gnlog.json_formatter import JsonFormatter

        assert not isinstance(initializer.handler.formatter, JsonFormatter)

    def test_initializer_creates_json_formatter_on_cloud_run_service(self, monkeypatch):
        """K_SERVICE がある場合 (Cloud Run Service)、JsonFormatter が使用されること"""
        monkeypatch.setenv("K_SERVICE", "test-service")
        monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
        monkeypatch.delenv("CLOUD_RUN_WORKER_POOL", raising=False)

        initializer = Initializer(log_level=logging.INFO)

        assert isinstance(initializer.handler, logging.StreamHandler)
        # JsonFormatter が設定されていることを確認
        from gnlog.json_formatter import JsonFormatter

        assert isinstance(initializer.handler.formatter, JsonFormatter)

    def test_initializer_creates_json_formatter_on_cloud_run_job(self, monkeypatch):
        """CLOUD_RUN_JOB がある場合 (Cloud Run Job)、JsonFormatter が使用されること"""
        # Cloud Run Job では K_SERVICE は設定されず CLOUD_RUN_JOB のみが設定される
        monkeypatch.delenv("K_SERVICE", raising=False)
        monkeypatch.setenv("CLOUD_RUN_JOB", "test-job")
        monkeypatch.delenv("CLOUD_RUN_WORKER_POOL", raising=False)

        initializer = Initializer(log_level=logging.INFO)

        assert isinstance(initializer.handler, logging.StreamHandler)
        # JsonFormatter が設定されていることを確認
        from gnlog.json_formatter import JsonFormatter

        assert isinstance(initializer.handler.formatter, JsonFormatter)

    def test_initializer_creates_json_formatter_on_cloud_run_worker_pool(
        self, monkeypatch
    ):
        """CLOUD_RUN_WORKER_POOL がある場合 (Worker Pool)、JsonFormatter が使われること"""
        # Worker Pool では K_SERVICE / CLOUD_RUN_JOB は設定されず
        # CLOUD_RUN_WORKER_POOL のみが設定される
        monkeypatch.delenv("K_SERVICE", raising=False)
        monkeypatch.delenv("CLOUD_RUN_JOB", raising=False)
        monkeypatch.setenv("CLOUD_RUN_WORKER_POOL", "test-worker-pool")

        initializer = Initializer(log_level=logging.INFO)

        assert isinstance(initializer.handler, logging.StreamHandler)
        # JsonFormatter が設定されていることを確認
        from gnlog.json_formatter import JsonFormatter

        assert isinstance(initializer.handler.formatter, JsonFormatter)

    def test_initializer_respects_log_level_parameter(self):
        """log_level パラメータが反映されること"""
        initializer = Initializer(log_level=logging.DEBUG)
        assert initializer.log_level_default == logging.DEBUG
        assert initializer.handler.level == logging.DEBUG

    def test_initializer_uses_env_log_level_when_none(self, monkeypatch):
        """log_level が None の場合、環境変数から読み込むこと"""
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        initializer = Initializer()
        assert initializer.log_level_default == logging.ERROR

    def test_initializer_adds_handler_to_root_logger(self):
        """ルートロガーにハンドラが追加されること"""
        initializer = Initializer(log_level=logging.INFO)
        assert len(logging.root.handlers) == 1
        assert logging.root.handlers[0] == initializer.handler

    def test_apply_returns_configured_logger(self):
        """apply() がロガーを返し、設定が適用されること"""
        initializer = Initializer(log_level=logging.INFO)
        logger = initializer.apply("test.logger")

        assert isinstance(logger, logging.Logger)
        assert logger.name == "test.logger"
        assert logger.level == logging.INFO

    def test_apply_with_custom_log_level(self):
        """apply() で個別のログレベルを指定できること"""
        initializer = Initializer(log_level=logging.INFO)
        logger = initializer.apply("test.logger", log_level=logging.DEBUG)

        assert logger.level == logging.DEBUG

    def test_apply_with_propagate_false(self):
        """apply() で propagate を False に設定できること"""
        initializer = Initializer(log_level=logging.INFO)
        logger = initializer.apply("test.logger", propagate=False)

        assert logger.propagate is False

    def test_apply_clear_handlers(self):
        """apply() の clear_handlers オプションが動作すること"""
        initializer = Initializer(log_level=logging.INFO)
        # pytest のログキャプチャや他テストの影響を避けるため固有のロガー名を使う
        logger_name = "test.apply_clear_handlers"
        logger = logging.getLogger(logger_name)
        logger.handlers.clear()

        # 既存のハンドラを追加
        dummy_handler = logging.StreamHandler()
        logger.addHandler(dummy_handler)
        assert len(logger.handlers) == 1

        # clear_handlers=True で既存ハンドラがクリアされること
        initializer.apply(logger_name, clear_handlers=True)
        assert len(logger.handlers) == 0

    def test_apply_add_handler(self):
        """apply() の add_handler オプションが動作すること"""
        initializer = Initializer(log_level=logging.INFO)
        # pytest のログキャプチャや他テストの影響を避けるため固有のロガー名を使う
        logger_name = "test.apply_add_handler"
        logging.getLogger(logger_name).handlers.clear()
        logger = initializer.apply(logger_name, add_handler=True)

        # ロガーにハンドラが追加されていること
        assert len(logger.handlers) == 1
        assert logger.handlers[0] == initializer.handler

    def test_verbose_default_prints_diagnostics_to_stderr(self, capsys):
        """既定 (verbose=True) では診断出力が標準エラー出力に出ること"""
        initializer = Initializer(log_level=logging.INFO)
        initializer.apply("test.verbose_default", clear_handlers=True)

        captured = capsys.readouterr()
        assert "Initializer starting" in captured.err
        assert "Initializer initialized logger" in captured.err
        assert captured.out == ""

    def test_verbose_false_suppresses_diagnostics(self, capsys):
        """verbose=False では診断出力が一切出ないこと"""
        # 既存ハンドラがある状態でも "clearing handlers" が出ないことを確認する
        logging.root.addHandler(logging.NullHandler())
        logger_name = "test.verbose_false"
        logging.getLogger(logger_name).addHandler(logging.NullHandler())

        initializer = Initializer(log_level=logging.INFO, verbose=False)
        initializer.apply(logger_name, clear_handlers=True)

        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out == ""


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
    """LOCAL_LOG_FORMAT 定数のテスト"""

    def test_local_log_format_is_defined(self):
        """LOCAL_LOG_FORMAT が定義されていること"""
        assert LOCAL_LOG_FORMAT is not None
        assert isinstance(LOCAL_LOG_FORMAT, str)
        assert len(LOCAL_LOG_FORMAT) > 0
