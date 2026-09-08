"""
ログレベルの変換・取得を行うユーティリティモジュール

文字列とログレベル定数の相互変換や、環境変数からのログレベル取得を提供します。
"""

import logging
import os


def parse(s: str, default: int = logging.INFO) -> int:
    """ログレベルの文字列を整数に変換するユーティリティ関数

    Args:
        s: ログレベルを表す文字列（大文字・小文字を問わない）
           例: "DEBUG", "info", "Warning"
        default: 未知のログレベルが指定された場合に返すデフォルト値

    Returns:
        logging モジュールのログレベル定数
        例: logging.INFO, logging.DEBUG など

    Examples:
        >>> parse("INFO")
        20  # logging.INFO
        >>> parse("unknown", default=logging.ERROR)
        40  # logging.ERROR
    """
    s_upper = s.upper()

    # WARN と WARNING の両方をサポート
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
    """環境変数 LOG_LEVEL からログレベルを取得する関数

    環境変数 LOG_LEVEL が設定されていない場合は INFO を返します。

    Returns:
        logging モジュールのログレベル定数

    Examples:
        >>> # LOG_LEVEL=DEBUG が設定されている場合
        >>> from_env()
        10  # logging.DEBUG

        >>> # LOG_LEVEL が未設定の場合
        >>> from_env()
        20  # logging.INFO
    """
    log_level_str = os.getenv("LOG_LEVEL", "INFO")
    return parse(log_level_str, default=logging.INFO)


def to_str(level: int) -> str:
    """ログレベルの整数を文字列に変換するユーティリティ関数

    Args:
        level: logging モジュールのログレベル定数
               例: logging.INFO, logging.DEBUG など

    Returns:
        ログレベルを表す文字列（大文字）
        未知のログレベルの場合は "unknown(#N)" 形式の文字列

    Examples:
        >>> to_str(logging.INFO)
        'INFO'
        >>> to_str(99)
        'unknown(#99)'
    """
    level_map = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRITICAL",
    }
    return level_map.get(level, f"unknown(#{level})")
