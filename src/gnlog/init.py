"""
ロギングの初期化と設定を行うモジュール

環境変数に応じて適切なログハンドラとフォーマッターを設定します。
Cloud Run 環境では自動的に JSON 形式で出力します。
"""

import logging
import logging.handlers
import os
import sys

from . import json_formatter, level

# ローカル環境用のログフォーマット
# 参考: https://docs.python.org/3/library/logging.html#formatter-objects
LOCAL_LOG_FORMAT = (
    "%(asctime)s %(levelname)s pid:%(process)s %(message)s:%(filename)s:%(lineno)d"
)

# Cloud Run 上で自動設定される環境変数。
# いずれかが存在すれば Cloud Run 環境と判定する。
# - K_SERVICE: Cloud Run Service でのみ自動設定される
#   https://cloud.google.com/run/docs/container-contract#services-env-vars
# - CLOUD_RUN_JOB: Cloud Run Job でのみ自動設定される
#   https://cloud.google.com/run/docs/container-contract#jobs-env-vars
# - CLOUD_RUN_WORKER_POOL: Cloud Run Worker Pool でのみ自動設定される
#   https://cloud.google.com/run/docs/container-contract#worker-pools-env-vars
_CLOUD_RUN_ENV_VARS = ("K_SERVICE", "CLOUD_RUN_JOB", "CLOUD_RUN_WORKER_POOL")


def is_cloud_run() -> bool:
    """Cloud Run (Service / Job / Worker Pool) 上で実行されているかを判定

    Cloud Run Service では ``K_SERVICE`` が、Cloud Run Job では ``CLOUD_RUN_JOB``
    が、Cloud Run Worker Pool では ``CLOUD_RUN_WORKER_POOL`` が自動設定される
    (いずれも排他的)。いずれかが存在すれば Cloud Run 上と判定する。

    Returns:
        Cloud Run 上で実行されている場合は True
    """
    return any(os.getenv(name) is not None for name in _CLOUD_RUN_ENV_VARS)


class Initializer:
    """ロギングシステムの初期化クラス

    環境変数に基づいてログハンドラとフォーマッターを設定します。

    環境変数:
        K_SERVICE: Cloud Run Service で自動設定される。存在する場合は JSON フォーマットを使用
        CLOUD_RUN_JOB: Cloud Run Job で自動設定される。存在する場合は JSON フォーマットを使用
        CLOUD_RUN_WORKER_POOL: Cloud Run Worker Pool で自動設定される。存在する場合は JSON フォーマットを使用
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
        verbose: bool = True,
        set_root_level: bool = True,
    ):
        """Initializer を初期化

        環境変数に基づいて適切なログハンドラとフォーマッターを作成し、
        ルートロガーに設定します。

        Args:
            log_level: ログレベル。None の場合は環境変数 LOG_LEVEL から取得
            output_path: ログファイルのパス。None の場合は環境変数 LOG_FILE_PATH を使用
            log_format: ログフォーマット文字列。None の場合は環境変数 LOG_FORMAT を使用
            labels: Cloud Logging の labels に追加するキーと値
            verbose: True の場合、初期化と apply() の過程を診断用に標準エラー出力へ
                出力する。Cloud Run では標準エラー出力も Cloud Logging に取り込まれ、
                構造化されていないエントリとして混じるため、不要なら False を指定する
            set_root_level: True の場合、ルートロガーの level も log_level に揃える。
                False の場合はルートロガーの level を変更しない (Python の既定は WARNING
                なので、apply() していないロガーの INFO / DEBUG は出力されない)
        """
        self.verbose = verbose
        self._diag("Initializer starting")
        # print_loggers("at the start of Initializer.__init__")

        handler: logging.Handler

        # Cloud Run 環境（Service / Job のいずれか）かどうかで分岐
        if is_cloud_run():
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
        # ローカル変数の絞り込み後の型 (StreamHandler | RotatingFileHandler) ではなく
        # 一般の Handler として公開する (利用側で別の Handler を代入できるようにする)
        self.handler: logging.Handler = handler
        self.log_level_default = log_level

        # ルートロガーの既存ハンドラをクリア（重複出力を防ぐため）
        if logging.root.hasHandlers():
            self._diag(f"clearing handlers of logging.root: {logging.root.handlers}")
            logging.root.handlers.clear()

        # ルートロガーにハンドラを追加
        logging.root.addHandler(handler)

        # ルートロガーの level を handler と揃える。
        # これを行わないとルートの level は Python の既定 (WARNING) のままなので、
        # apply() していないロガー (logging.getLogger(__name__) で取っただけのもの) の
        # INFO / DEBUG は handler に届く前に捨てられる。
        if set_root_level:
            logging.root.setLevel(log_level)

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
        if clear_handlers and logger.hasHandlers():
            self._diag(f"clearing handlers of logger {logger.name}: {logger.handlers}")
            logger.handlers.clear()
        if add_handler:
            logger.addHandler(self.handler)
        if self.verbose:
            _print_logger(logger, "Initializer initialized logger")
        return logger

    def _diag(self, message: str) -> None:
        """診断用メッセージを標準エラー出力に出力（verbose が True の場合のみ）

        Args:
            message: 出力する文字列
        """
        if self.verbose:
            print(message, file=sys.stderr)


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
