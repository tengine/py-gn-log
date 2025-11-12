import logging

from gnlog.init import Initializer, LOCAL_LOG_FORMAT


class TestInitializer:
    """Initializer クラスのテスト"""

    def setup_method(self):
        """各テストの前にログハンドラをクリア"""
        logging.root.handlers.clear()

    def teardown_method(self):
        """各テストの後にログハンドラをクリア"""
        logging.root.handlers.clear()

    def test_initializer_creates_stream_handler_by_default(self, monkeypatch):
        """K_SERVICE がない場合、StreamHandler が作成されること"""
        monkeypatch.delenv("K_SERVICE", raising=False)
        monkeypatch.delenv("LOG_FILE_PATH", raising=False)

        initializer = Initializer(log_level=logging.INFO)

        assert isinstance(initializer.handler, logging.StreamHandler)
        assert initializer.log_level_default == logging.INFO

    def test_initializer_creates_json_formatter_on_cloud_run(self, monkeypatch):
        """K_SERVICE がある場合、JsonFormatter が使用されること"""
        monkeypatch.setenv("K_SERVICE", "test-service")

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
        logger = logging.getLogger("test.logger")

        # 既存のハンドラを追加
        dummy_handler = logging.StreamHandler()
        logger.addHandler(dummy_handler)
        assert len(logger.handlers) == 1

        # clear_handlers=True で既存ハンドラがクリアされること
        initializer.apply("test.logger", clear_handlers=True)
        assert len(logger.handlers) == 0

    def test_apply_add_handler(self):
        """apply() の add_handler オプションが動作すること"""
        initializer = Initializer(log_level=logging.INFO)
        logger = initializer.apply("test.logger", add_handler=True)

        # ロガーにハンドラが追加されていること
        assert len(logger.handlers) == 1
        assert logger.handlers[0] == initializer.handler


class TestLocalLogFormat:
    """LOCAL_LOG_FORMAT 定数のテスト"""

    def test_local_log_format_is_defined(self):
        """LOCAL_LOG_FORMAT が定義されていること"""
        assert LOCAL_LOG_FORMAT is not None
        assert isinstance(LOCAL_LOG_FORMAT, str)
        assert len(LOCAL_LOG_FORMAT) > 0
