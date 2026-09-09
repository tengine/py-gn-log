import contextvars
import json
import logging
import threading

import pytest

from gnlog import Initializer, context
from gnlog.context import ContextFilter


@pytest.fixture(autouse=True)
def _clean_context():
    context.clear()
    yield
    context.clear()


def _record(msg: str = "message") -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


class TestContextApi:
    """bind / set / clear / get のテスト"""

    def test_get_is_empty_by_default(self):
        """何も置いていなければ空であること"""
        assert dict(context.get()) == {}

    def test_bind_sets_and_restores(self):
        """bind() のブロック内だけ値が置かれ、抜けると元に戻ること"""
        with context.bind(trace_id="t1"):
            assert context.get()["trace_id"] == "t1"
        assert "trace_id" not in context.get()

    def test_bind_restores_on_exception(self):
        """例外でブロックを抜けても元に戻ること"""
        with pytest.raises(RuntimeError), context.bind(trace_id="t1"):
            raise RuntimeError("boom")
        assert "trace_id" not in context.get()

    def test_bind_nests_and_inner_overrides(self):
        """入れ子にでき、内側の値が同じキーを上書きし、抜けると外側の値に戻ること"""
        with context.bind(trace_id="outer", site="tokyo"):
            with context.bind(trace_id="inner"):
                assert dict(context.get()) == {"trace_id": "inner", "site": "tokyo"}
            assert dict(context.get()) == {"trace_id": "outer", "site": "tokyo"}

    def test_set_inside_bind_persists_after_block(self):
        """bind() のブロック内で set() した値は、ブロックを抜けても残ること"""
        context.set(a="1")
        with context.bind(b="2"):
            context.set(c="3")
            assert dict(context.get()) == {"a": "1", "b": "2", "c": "3"}
        assert dict(context.get()) == {"a": "1", "c": "3"}

    def test_bind_restores_only_its_own_keys_when_overridden_inside(self):
        """bind() のブロック内で同じキーを set() しても、抜けると突入前の値に戻ること"""
        context.set(trace_id="before")
        with context.bind(trace_id="bound"):
            context.set(trace_id="inside")
            assert context.get()["trace_id"] == "inside"
        assert context.get()["trace_id"] == "before"

    def test_mapping_argument_allows_non_identifier_keys(self):
        """位置引数の Mapping で、識別子にならないキーも置けること"""
        context.set({"logging.googleapis.com/trace": "projects/p/traces/t"})
        with context.bind({"a/b": 1}, site="tokyo"):
            assert dict(context.get()) == {
                "logging.googleapis.com/trace": "projects/p/traces/t",
                "a/b": 1,
                "site": "tokyo",
            }
        assert dict(context.get()) == {
            "logging.googleapis.com/trace": "projects/p/traces/t"
        }

    def test_keyword_overrides_mapping(self):
        """Mapping とキーワード引数に同じキーがあればキーワード引数が優先されること"""
        context.set({"site": "osaka"}, site="tokyo")
        assert context.get()["site"] == "tokyo"

    def test_set_persists_until_clear(self):
        """set() した値は clear() するまで残ること"""
        context.set(trace_id="t1")
        context.set(site="tokyo")
        assert dict(context.get()) == {"trace_id": "t1", "site": "tokyo"}
        context.clear()
        assert dict(context.get()) == {}

    def test_get_is_read_only(self):
        """get() の戻り値を破壊的に変更できないこと"""
        context.set(trace_id="t1")
        with pytest.raises(TypeError):
            context.get()["trace_id"] = "changed"  # type: ignore[index]

    @pytest.mark.parametrize(
        "key",
        # インスタンス属性だけでなく、メソッドやクラス属性 (hasattr が True になるもの) も含む
        ["message", "name", "asctime", "levelname", "getMessage", "__dict__"],
    )
    def test_reserved_keys_are_rejected(self, key):
        """LogRecord が持つ名前 (属性・メソッド) と同じキーは受け付けないこと"""
        with pytest.raises(ValueError, match="LogRecord"):
            context.set(**{key: "x"})
        with pytest.raises(ValueError, match="LogRecord"), context.bind(**{key: "x"}):
            pass


class TestContextFilter:
    """ContextFilter のテスト"""

    def test_injects_context_into_record(self):
        """文脈の値が record の属性として注入されること"""
        record = _record()
        with context.bind(trace_id="t1", site="tokyo"):
            assert ContextFilter().filter(record) is True
        assert record.trace_id == "t1"  # type: ignore[attr-defined]
        assert record.site == "tokyo"  # type: ignore[attr-defined]

    def test_none_value_is_not_injected(self):
        """値が None のキーは record に注入しないこと"""
        record = _record()
        with context.bind(trace_id="t1", site=None):
            ContextFilter().filter(record)
        assert record.trace_id == "t1"  # type: ignore[attr-defined]
        assert not hasattr(record, "site")

    def test_record_attribute_takes_precedence(self):
        """record にすでにある属性 (extra= で渡したもの) を上書きしないこと"""
        record = _record()
        record.trace_id = "from-extra"  # type: ignore[attr-defined]
        with context.bind(trace_id="from-context"):
            ContextFilter().filter(record)
        assert record.trace_id == "from-extra"  # type: ignore[attr-defined]

    def test_thread_does_not_inherit_but_copy_context_does(self):
        """threading.Thread は文脈を継承しないが、copy_context().run で引き継げること"""
        seen: dict[str, object] = {}

        def work(label: str) -> None:
            record = _record()
            ContextFilter().filter(record)
            seen[label] = getattr(record, "trace_id", None)

        with context.bind(trace_id="t1"):
            t1 = threading.Thread(target=work, args=("plain",))
            t1.start()
            t1.join()
            ctx = contextvars.copy_context()
            t2 = threading.Thread(target=ctx.run, args=(work, "copied"))
            t2.start()
            t2.join()

        assert seen == {"plain": None, "copied": "t1"}


class TestInitializerIntegration:
    """Initializer 経由で JSON 出力に文脈が載ることのテスト"""

    @pytest.fixture(autouse=True)
    def _reset_root(self):
        logging.root.handlers.clear()
        yield
        logging.root.handlers.clear()

    def test_context_appears_in_json_output_of_unapplied_logger(self, capsys):
        """apply() していないロガー経由でも、JSON 出力に文脈のキーが載ること"""
        Initializer(log_level=logging.INFO, verbose=False, json=True)
        logger = logging.getLogger("test.context.not_applied")

        with context.bind(trace_id="t1", site="tokyo"):
            logger.info("inside")
        logger.info("outside")

        lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        assert len(lines) == 2
        assert lines[0]["message"] == "inside"
        assert lines[0]["trace_id"] == "t1"
        assert lines[0]["site"] == "tokyo"
        assert lines[1]["message"] == "outside"
        assert "trace_id" not in lines[1]
        assert "site" not in lines[1]

    def test_extra_overrides_context_in_json_output(self, capsys):
        """extra= で渡した値が文脈の値より優先されること"""
        Initializer(log_level=logging.INFO, verbose=False, json=True)
        logger = logging.getLogger("test.context.extra")

        with context.bind(trace_id="from-context"):
            logger.info("msg", extra={"trace_id": "from-extra"})

        line = json.loads(capsys.readouterr().out.strip())
        assert line["trace_id"] == "from-extra"

    def test_filter_survives_handler_clear_order(self, capsys):
        """Initializer() が root.handlers をクリアしても文脈の注入が失われないこと"""
        # 利用側が Filter を root に付ける方式では Initializer() の後に付ける必要があったが、
        # handler 側に付けているので順序を気にする必要がない
        Initializer(log_level=logging.INFO, verbose=False, json=True)
        Initializer(log_level=logging.INFO, verbose=False, json=True)  # 2 回目でも同じ

        with context.bind(trace_id="t1"):
            logging.getLogger("test.context.reinit").info("msg")

        out = capsys.readouterr().out.splitlines()
        assert len(out) == 1  # ハンドラは重複しない
        assert json.loads(out[0])["trace_id"] == "t1"
