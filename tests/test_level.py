import logging
import os
import pytest

from gnlog import level


class TestParse:
    """level.parse() 関数のテスト"""

    def test_parse_debug(self):
        assert level.parse("DEBUG") == logging.DEBUG
        assert level.parse("debug") == logging.DEBUG

    def test_parse_info(self):
        assert level.parse("INFO") == logging.INFO
        assert level.parse("info") == logging.INFO

    def test_parse_warn(self):
        assert level.parse("WARN") == logging.WARNING
        assert level.parse("warn") == logging.WARNING

    def test_parse_warning(self):
        assert level.parse("WARNING") == logging.WARNING
        assert level.parse("warning") == logging.WARNING

    def test_parse_error(self):
        assert level.parse("ERROR") == logging.ERROR
        assert level.parse("error") == logging.ERROR

    def test_parse_critical(self):
        assert level.parse("CRITICAL") == logging.CRITICAL
        assert level.parse("critical") == logging.CRITICAL

    def test_parse_unknown_returns_default(self):
        """未知のログレベルはデフォルト値を返す"""
        assert level.parse("UNKNOWN") == logging.INFO
        assert level.parse("invalid", default=logging.ERROR) == logging.ERROR


class TestFromEnv:
    """level.from_env() 関数のテスト"""

    def test_from_env_default(self, monkeypatch):
        """環境変数が未設定の場合はINFOを返す"""
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        assert level.from_env() == logging.INFO

    def test_from_env_debug(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        assert level.from_env() == logging.DEBUG

    def test_from_env_error(self, monkeypatch):
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        assert level.from_env() == logging.ERROR

    def test_from_env_lowercase(self, monkeypatch):
        """小文字の環境変数値も正しく解釈される"""
        monkeypatch.setenv("LOG_LEVEL", "warning")
        assert level.from_env() == logging.WARNING


class TestToStr:
    """level.to_str() 関数のテスト"""

    def test_to_str_debug(self):
        assert level.to_str(logging.DEBUG) == "DEBUG"

    def test_to_str_info(self):
        assert level.to_str(logging.INFO) == "INFO"

    def test_to_str_warning(self):
        assert level.to_str(logging.WARNING) == "WARNING"

    def test_to_str_error(self):
        assert level.to_str(logging.ERROR) == "ERROR"

    def test_to_str_critical(self):
        assert level.to_str(logging.CRITICAL) == "CRITICAL"

    def test_to_str_unknown(self):
        """未知のログレベル値は 'unknown(#N)' 形式を返す"""
        assert level.to_str(99) == "unknown(#99)"
