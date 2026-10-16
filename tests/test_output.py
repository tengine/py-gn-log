import logging
import subprocess
import sys

import pytest

from gnlog import output


class TestUseJsonOutput:
    """output.use_json_output の default 引数のテスト (環境変数の扱いは google/test_cloud_run.py)"""

    @pytest.fixture(autouse=True)
    def _clean_env(self, monkeypatch):
        monkeypatch.delenv("GNLOG_FORMAT", raising=False)

    def test_default_bool(self):
        """引数も環境変数も無ければ default (bool) を返すこと"""
        assert output.use_json_output() is False
        assert output.use_json_output(default=True) is True

    def test_default_callable_is_evaluated_lazily(self, monkeypatch):
        """default は呼び出し可能でもよく、引数か環境変数で決まるときは呼ばれないこと"""
        calls: list[int] = []

        def detect() -> bool:
            calls.append(1)
            return True

        assert output.use_json_output(default=detect) is True
        assert calls == [1]
        assert output.use_json_output(json=False, default=detect) is False
        monkeypatch.setenv("GNLOG_FORMAT", "text")
        assert output.use_json_output(default=detect) is False
        assert calls == [1]


class TestInstall:
    """output.install / LoggingSetup のテスト"""

    @pytest.fixture(autouse=True)
    def _reset_root(self):
        logging.root.handlers.clear()
        logging.root.setLevel(logging.WARNING)
        yield
        logging.root.handlers.clear()
        logging.root.setLevel(logging.WARNING)

    def test_install_attaches_context_filter_and_root_handler(self):
        """handler に ContextFilter が付き、ルートロガーに組み込まれること"""
        from gnlog.context import ContextFilter

        handler = output.text_handler()
        setup = output.install(handler, log_level=logging.INFO, verbose=False)
        assert setup.handler is handler
        assert any(isinstance(f, ContextFilter) for f in handler.filters)
        assert logging.root.handlers == [handler]
        assert logging.root.level == logging.INFO
        assert setup.log_level_default == logging.INFO

    def test_handler_attribute_is_typed_as_generic_handler(self):
        """LoggingSetup.handler は一般の Handler として差し替えられること (型と実行時)"""
        setup = output.install(
            output.text_handler(), log_level=logging.INFO, verbose=False
        )
        setup.handler = logging.NullHandler()
        assert isinstance(setup.handler, logging.NullHandler)

    @pytest.mark.parametrize("set_root_level", [True, False])
    def test_applied_logger_below_log_level_reaches_handler(self, set_root_level):
        """apply() で level を log_level より低くしたロガーの行が、handler に届くこと (#47)

        LOG_LEVEL=WARNING で運用するアプリでも、apply() したロガー (操作ログなど) の
        INFO だけは出せるようにするため。handler が log_level で絞ると、この行は捨てられる。
        """
        collector = _Collector()
        setup = output.install(
            collector,
            log_level=logging.WARNING,
            set_root_level=set_root_level,
            verbose=False,
        )
        logger_name = "test.output.applied_below_log_level"
        try:
            logger = setup.apply(logger_name, log_level=logging.INFO)
            logger.info("INFO from a logger applied with INFO")
        finally:
            logging.getLogger(logger_name).setLevel(logging.NOTSET)

        assert collector.messages() == ["INFO from a logger applied with INFO"]

    def test_logger_not_applied_is_filtered_by_root_level(self):
        """apply() していないロガーの行は、ルートロガーの level (log_level) で絞られること

        handler が level で絞らなくても、log_level より低い行は出ないことを確かめる。
        """
        collector = _Collector()
        output.install(collector, log_level=logging.INFO, verbose=False)
        other = logging.getLogger("test.output.not_applied")
        other.setLevel(logging.NOTSET)  # 親 (root) の level に従わせる
        other.debug("DEBUG from a logger that was not applied")
        other.info("INFO from a logger that was not applied")

        assert collector.messages() == ["INFO from a logger that was not applied"]


class _Collector(logging.Handler):
    """受け取った record を集める handler"""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self) -> list[str]:
        return [r.getMessage() for r in self.records]


class TestImportIsolation:
    """共通部が provider を import しないことのテスト (#30)"""

    @staticmethod
    def _loaded_after(import_stmt: str) -> set[str]:
        code = (
            f"import sys; {import_stmt}; "
            "print(' '.join(sorted(m for m in sys.modules "
            "if m.startswith('gnlog') or m.startswith('pythonjsonlogger'))))"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], check=True, capture_output=True, text=True
        ).stdout
        return set(out.split())

    def test_gnlog_does_not_import_google_subpackage(self):
        """import gnlog は gnlog.google と python-json-logger を読み込まないこと"""
        loaded = self._loaded_after("import gnlog")
        assert not any(m.startswith("gnlog.google") for m in loaded), loaded
        assert not any(m.startswith("pythonjsonlogger") for m in loaded), loaded

    def test_cloud_run_module_does_not_import_json_logger(self):
        """is_cloud_run だけの利用 (gnlog.google.cloud_run の import) では python-json-logger を読み込まないこと"""
        loaded = self._loaded_after("from gnlog.google.cloud_run import is_cloud_run")
        assert not any(m.startswith("pythonjsonlogger") for m in loaded), loaded
        assert "gnlog.google.cloud_logging" not in loaded, loaded
