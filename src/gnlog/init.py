"""
ロギングの初期化と設定を行うモジュール

環境変数に応じて適切なログハンドラとフォーマッターを設定します。
Cloud Run 環境では自動的に JSON 形式で出力します。
"""

import logging
import logging.handlers
import os
import sys

from . import json_formatter
from . import level

# ローカル環境用のログフォーマット
# 参考: https://docs.python.org/3/library/logging.html#formatter-objects
LOCAL_LOG_FORMAT = (
    "%(asctime)s %(levelname)s pid:%(process)s %(message)s:%(filename)s:%(lineno)d"
)


class Initializer:
    """ロギングシステムの初期化クラス

    環境変数に基づいてログハンドラとフォーマッターを設定します。

    環境変数:
        K_SERVICE: Cloud Run 環境で自動設定される。存在する場合は JSON フォーマットを使用
        LOG_LEVEL: ログレベル（DEBUG, INFO, WARNING, ERROR, CRITICAL）
        LOG_FILE_PATH: ログファイルのパス（指定時はファイルに出力）
        LOG_FORMAT: ログフォーマット文字列（ローカル環境のみ）

    Attributes:
        handler: 設定されたログハンドラ
        log_level_default: デフォルトのログレベル

    Examples:
        >>> # 基本的な使い方
        >>> initializer = Initializer(log_level=logging.INFO)
        >>> logger = initializer.apply("my_app")

        >>> # 環境変数からログレベルを取得
        >>> initializer = Initializer()
        >>> logger = initializer.apply("my_app")
    """

    def __init__(
        self,
        log_level: int | None = None,
        output_path: str | None = None,
        log_format: str | None = None,
        labels: dict[str, str] | None = None,
    ):
        """Initializer を初期化

        環境変数に基づいて適切なログハンドラとフォーマッターを作成し、
        ルートロガーに設定します。

        Args:
            log_level: ログレベル。None の場合は環境変数 LOG_LEVEL から取得
            output_path: ログファイルのパス。None の場合は環境変数 LOG_FILE_PATH を使用
            log_format: ログフォーマット文字列。None の場合は環境変数 LOG_FORMAT を使用
        """
        print("Initializer starting", file=sys.stderr)
        # print_loggers("at the start of Initializer.__init__")

        handler: logging.Handler

        # Cloud Run 環境（K_SERVICE が設定されている）かどうかで分岐
        if os.getenv("K_SERVICE") is not None:
            # Cloud Run: JSON フォーマットで標準出力に出力
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(json_formatter.JsonFormatter(labels=labels))
        else:
            # ローカル環境: 指定された出力先とフォーマットを使用
            if output_path is None:
                output_path = os.getenv("LOG_FILE_PATH")
            if output_path is None:
                handler = logging.StreamHandler(sys.stdout)
            else:
                handler = logging.handlers.RotatingFileHandler(
                    output_path,
                    maxBytes=1024 * 1024 * 5,  # 5MiB
                    backupCount=5,
                    encoding="utf-8",
                )

            if log_format is None:
                log_format = os.getenv("LOG_FORMAT", LOCAL_LOG_FORMAT)
            handler.setFormatter(logging.Formatter(log_format))

        # ログレベルを設定（引数 > 環境変数 > デフォルト）
        if log_level is None:
            log_level = level.from_env()
        handler.setLevel(log_level)
        self.handler = handler
        self.log_level_default = log_level

        # ルートロガーの既存ハンドラをクリア（重複出力を防ぐため）
        if logging.root.hasHandlers():
            print(
                f"clearing handlers of logging.root: {logging.root.handlers}",
                file=sys.stderr,
            )
            logging.root.handlers.clear()

        # ルートロガーにハンドラを追加
        logging.root.addHandler(handler)

        # print_loggers("at the end of Initializer.__init__")

    def apply(
        self,
        name: str,
        log_level: int | None = None,
        propagate: bool | None = None,
        clear_handlers: bool = False,
        add_handler: bool = False,
    ) -> logging.Logger:
        """指定された名前のロガーに設定を適用

        既存のロガーを取得し、ログレベルやハンドラなどの設定を適用します。

        Args:
            name: ロガー名（通常は __name__ を指定）
            log_level: ログレベル。None の場合はデフォルトのログレベルを使用
            propagate: 親ロガーへの伝播を制御。None の場合は変更しない
            clear_handlers: True の場合、既存のハンドラをクリア
            add_handler: True の場合、このInitializerのハンドラを追加

        Returns:
            設定されたロガーオブジェクト

        Examples:
            >>> initializer = Initializer()
            >>> logger = initializer.apply("my_module")
            >>> logger = initializer.apply("debug_module", log_level=logging.DEBUG)
        """
        # 指定された名前のロガーを取得
        logger = logging.getLogger(name)
        if log_level is None:
            log_level = self.log_level_default
        logger.setLevel(log_level)
        if propagate is not None:
            logger.propagate = propagate
        if clear_handlers:
            if logger.hasHandlers():
                print(
                    f"clearing handlers of logger {logger.name}: {logger.handlers}",
                    file=sys.stderr,
                )
                logger.handlers.clear()
        if add_handler:
            logger.addHandler(self.handler)
        _print_logger(logger, "Initializer initialized logger")
        return logger


def print_loggers(prefix: str) -> None:
    """全てのロガーの状態をデバッグ出力

    ルートロガーとその子ロガーすべての状態を標準エラー出力に表示します。
    デバッグ用の関数です。

    Args:
        prefix: 各行の先頭に付加する文字列
    """
    _print_logger(logging.root, prefix)
    _print_loggers(logging.root, prefix)


def _print_loggers(parent: logging.Logger, prefix: str) -> None:
    """指定されたロガーの子ロガーを再帰的に出力（内部関数）

    Args:
        parent: 親ロガー
        prefix: 各行の先頭に付加する文字列
    """
    for logger in parent.getChildren():
        _print_logger(logger, prefix)
        # 再帰的に子ロガーも出力
        _print_loggers(logger, prefix)


def _print_logger(logger: logging.Logger, prefix: str) -> None:
    """ロガーの詳細情報を標準エラー出力に表示（内部関数）

    Args:
        logger: 情報を出力するロガー
        prefix: 行の先頭に付加する文字列
    """
    print(
        f"{prefix}\t{logger.name=}\tlogger.parent={logger.parent.name if logger.parent else 'no_parent'}\t{logger.level=}\t{logger.propagate=}\tlen(logger.getChildren())={len(logger.getChildren())}\tlen(logger.handlers)={len(logger.handlers)}\t{logger.handlers=}",
        file=sys.stderr,
    )
