import os
import logging


def parse(s, default=logging.INFO) -> int:
    """ログレベルの文字列を整数に変換するユーティリティ関数"""
    s_upper = s.upper()
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARN": logging.WARNING,
        "WARNING": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
    }
    return level_map.get(s_upper, default)


def from_env() -> int:
    """環境変数 LOG_LEVEL からログレベルを取得する関数"""
    log_level_str = os.getenv("LOG_LEVEL", "INFO")
    return parse(log_level_str, default=logging.INFO)


def to_str(level: int) -> str:
    """ログレベルの整数を文字列に変換するユーティリティ関数"""
    level_map = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRITICAL",
    }
    return level_map.get(level, f"unknown(#{level})")
