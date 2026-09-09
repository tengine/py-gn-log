"""
ログ出力の共通部 (provider を知らない)

出力形式の決定 (環境変数 ``GNLOG_FORMAT``)、テキスト形式の handler、ルートロガーへの
組み込みを提供します。どの formatter を使うか、どの環境でどの形式にするかは
provider ごとのサブパッケージ (``gnlog.google.cloud_run`` など) が決め、
このモジュールの関数を組み合わせて入口 (``setup_logging()``) を作ります。
"""

import logging
import logging.handlers
import os
import sys
from collections.abc import Callable
from typing import TextIO

from . import context, level

# テキスト形式の既定のフォーマット
# 参考: https://docs.python.org/3/library/logging.html#formatter-objects
TEXT_LOG_FORMAT = (
    "%(asctime)s %(levelname)s pid:%(process)s %(message)s:%(filename)s:%(lineno)d"
)

# 出力形式を明示的に指定する環境変数とその値。
# 未設定なら provider の入口が渡す既定 (Cloud Run 上かどうか等) に従う。
GNLOG_FORMAT_ENV_VAR = "GNLOG_FORMAT"
GNLOG_FORMAT_JSON = "json"
GNLOG_FORMAT_TEXT = "text"

# テキスト形式の出力先とフォーマットを指定する環境変数
LOG_FILE_PATH_ENV_VAR = "LOG_FILE_PATH"
LOG_FORMAT_ENV_VAR = "LOG_FORMAT"


def use_json_output(
    json: bool | None = None, default: bool | Callable[[], bool] = False
) -> bool:
    """JSON 形式で出力するかどうかを決定

    優先順位は 引数 ``json`` > 環境変数 ``GNLOG_FORMAT`` > ``default``。

    Args:
        json: True なら JSON、False ならテキスト。None の場合は環境変数と default から決める
        default: 引数も環境変数も無いときの既定。bool か、bool を返す呼び出し可能オブジェクト
            (provider の入口が「Cloud Run 上かどうか」のような判定を渡す)

    Returns:
        JSON 形式で出力する場合は True

    Raises:
        ValueError: 環境変数 GNLOG_FORMAT の値が "json" / "text" のいずれでもない場合
    """
    if json is not None:
        return json
    value = os.getenv(GNLOG_FORMAT_ENV_VAR)
    if value is None or value == "":
        return default() if callable(default) else default
    normalized = value.strip().lower()
    if normalized == GNLOG_FORMAT_JSON:
        return True
    if normalized == GNLOG_FORMAT_TEXT:
        return False
    raise ValueError(
        f"Invalid value {value!r} for environment variable {GNLOG_FORMAT_ENV_VAR}: "
        f"expected {GNLOG_FORMAT_JSON!r} or {GNLOG_FORMAT_TEXT!r}"
    )


def text_handler(
    output_path: str | None = None, log_format: str | None = None
) -> logging.Handler:
    """テキスト形式の handler を作る

    Args:
        output_path: ログファイルのパス。None なら環境変数 LOG_FILE_PATH、それも無ければ標準出力
        log_format: フォーマット文字列。None なら環境変数 LOG_FORMAT、それも無ければ TEXT_LOG_FORMAT

    Returns:
        標準出力の StreamHandler、またはローテーションするファイル handler
    """
    handler: logging.Handler
    if output_path is None:
        output_path = os.getenv(LOG_FILE_PATH_ENV_VAR)
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
        log_format = os.getenv(LOG_FORMAT_ENV_VAR, TEXT_LOG_FORMAT)
    handler.setFormatter(logging.Formatter(log_format))
    return handler


def stream_handler(
    formatter: logging.Formatter, stream: TextIO | None = None
) -> logging.Handler:
    """指定した formatter で標準出力 (または任意のストリーム) に出す handler を作る

    Args:
        formatter: 使う formatter (provider の JSON formatter 等)
        stream: 出力先。None なら標準出力

    Returns:
        StreamHandler
    """
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(formatter)
    return handler


class LoggingSetup:
    """``install()`` の結果。組み込んだ handler と、ロガーごとの設定を行う ``apply()`` を持つ

    Attributes:
        handler: ルートロガーに組み込んだ handler。gnlog.context の文脈を注入する Filter が付いている
        log_level_default: 既定のログレベル
        verbose: 診断出力を標準エラー出力に出すかどうか
    """

    def __init__(self, handler: logging.Handler, log_level: int, verbose: bool) -> None:
        self.handler: logging.Handler = handler
        self.log_level_default = log_level
        self.verbose = verbose

    def apply(
        self,
        name: str,
        log_level: int | None = None,
        propagate: bool | None = None,
        clear_handlers: bool = False,
        add_handler: bool = False,
    ) -> logging.Logger:
        """指定された名前のロガーに設定を適用

        Args:
            name: ロガー名（通常は __name__ を指定）
            log_level: ログレベル。None の場合は既定のログレベルを使用
            propagate: 親ロガーへの伝播を制御。None の場合は変更しない
            clear_handlers: True の場合、既存のハンドラをクリア
            add_handler: True の場合、組み込んだ handler をこのロガーにも追加

        Returns:
            設定されたロガーオブジェクト
        """
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
            _print_logger(logger, "gnlog initialized logger")
        return logger

    def _diag(self, message: str) -> None:
        """診断用メッセージを標準エラー出力に出力（verbose が True の場合のみ）"""
        if self.verbose:
            print(message, file=sys.stderr)


def install(
    handler: logging.Handler,
    log_level: int | None = None,
    set_root_level: bool = True,
    verbose: bool = True,
) -> LoggingSetup:
    """handler をルートロガーに組み込む

    gnlog.context の文脈を注入する Filter を handler に付け、ログレベルを設定し、
    ルートロガーの既存 handler を取り除いてから追加します。

    Args:
        handler: 組み込む handler
        log_level: ログレベル。None なら環境変数 LOG_LEVEL から取得
        set_root_level: True ならルートロガーの level も log_level に揃える
            (logging.basicConfig(level=...) と同じ振る舞い)。False ならルートロガーの
            level を変更しない (Python の既定は WARNING なので、apply() していない
            ロガーの INFO / DEBUG は出力されない)
        verbose: True の場合、組み込みと apply() の過程を診断用に標準エラー出力へ出す。
            Cloud Run など標準エラー出力もログ基盤に取り込まれる環境では、構造化されて
            いないエントリとして混じるため、不要なら False を指定する

    Returns:
        組み込んだ handler と apply() を持つ LoggingSetup
    """
    setup = LoggingSetup(handler, log_level if log_level is not None else 0, verbose)
    setup._diag("gnlog setup starting")

    # 文脈 (gnlog.context) を全 record に注入する Filter を handler に付ける。
    # ルートロガーに付けると伝播してきた record には適用されないため handler に付ける。
    handler.addFilter(context.ContextFilter())

    # ログレベル（引数 > 環境変数 > デフォルト）
    if log_level is None:
        log_level = level.from_env()
    handler.setLevel(log_level)
    setup.log_level_default = log_level

    # ルートロガーの既存ハンドラをクリア（重複出力を防ぐため）
    if logging.root.hasHandlers():
        setup._diag(f"clearing handlers of logging.root: {logging.root.handlers}")
        logging.root.handlers.clear()
    logging.root.addHandler(handler)

    # ルートロガーの level を handler と揃える。これを行わないとルートの level は
    # Python の既定 (WARNING) のままなので、apply() していないロガーの INFO / DEBUG は
    # handler に届く前に捨てられる。
    if set_root_level:
        logging.root.setLevel(log_level)
    return setup


def print_loggers(prefix: str) -> None:
    """全てのロガーの状態をデバッグ出力 (標準エラー出力)

    Args:
        prefix: 各行の先頭に付加する文字列
    """
    _print_logger(logging.root, prefix)
    _print_loggers(logging.root, prefix)


def _print_loggers(parent: logging.Logger, prefix: str) -> None:
    for logger in parent.getChildren():
        _print_logger(logger, prefix)
        _print_loggers(logger, prefix)


def _print_logger(logger: logging.Logger, prefix: str) -> None:
    print(
        f"{prefix}\t{logger.name=}\tlogger.parent={logger.parent.name if logger.parent else 'no_parent'}\t{logger.level=}\t{logger.propagate=}\tlen(logger.getChildren())={len(logger.getChildren())}\tlen(logger.handlers)={len(logger.handlers)}\t{logger.handlers=}",
        file=sys.stderr,
    )
