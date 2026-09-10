"""
Cloud Run 向けのロギングの入口

``setup_logging()`` が、Cloud Run 上 (または ``GNLOG_FORMAT=json`` / ``json=True``) なら
Cloud Logging 向けの JSON 形式、それ以外ならテキスト形式でルートロガーを設定します。

Examples:
    >>> from gnlog.google.cloud_run import setup_logging
    >>> setup = setup_logging()
    >>> logger = setup.apply(__name__)

``is_cloud_run()`` だけを使う場合、このモジュールの import では Cloud Logging 向けの
依存 (python-json-logger) を読み込みません。
"""

import os

from .. import output

# Cloud Run 上で自動設定される環境変数。いずれかが存在すれば Cloud Run 環境と判定する。
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


def use_json_output(json: bool | None = None) -> bool:
    """JSON 形式で出力するかどうかを決定 (引数 > 環境変数 GNLOG_FORMAT > Cloud Run 上かどうか)

    Args:
        json: True なら JSON、False ならテキスト。None の場合は環境変数と実行環境から決める

    Returns:
        JSON 形式で出力する場合は True

    Raises:
        ValueError: 環境変数 GNLOG_FORMAT の値が "json" / "text" のいずれでもない場合
    """
    return output.use_json_output(json, default=is_cloud_run)


def setup_logging(
    log_level: int | None = None,
    output_path: str | None = None,
    log_format: str | None = None,
    labels: dict[str, str] | None = None,
    verbose: bool = True,
    set_root_level: bool = True,
    json_ensure_ascii: bool = True,
    json: bool | None = None,
    error_event: str | None = None,
    surface: str | None = None,
) -> output.LoggingSetup:
    """Cloud Run 向けにルートロガーを設定する

    環境変数:
        K_SERVICE / CLOUD_RUN_JOB / CLOUD_RUN_WORKER_POOL: Cloud Run が自動設定する。
            存在する場合は Cloud Logging 向けの JSON 形式を使う
        GNLOG_FORMAT: 出力形式を明示的に指定する (json または text)。
            未設定なら上記の Cloud Run の環境変数の有無で自動判定する
        LOG_LEVEL: ログレベル (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        LOG_FILE_PATH: ログファイルのパス (テキスト形式のみ)
        LOG_FORMAT: ログフォーマット文字列 (テキスト形式のみ)

    Args:
        log_level: ログレベル。None の場合は環境変数 LOG_LEVEL から取得
        output_path: ログファイルのパス (テキスト形式のみ)。None の場合は環境変数 LOG_FILE_PATH
        log_format: ログフォーマット文字列 (テキスト形式のみ)。None の場合は環境変数 LOG_FORMAT
        labels: Cloud Logging の labels に追加するキーと値
        verbose: True の場合、初期化と apply() の過程を診断用に標準エラー出力へ出す。
            Cloud Run では標準エラー出力も Cloud Logging に取り込まれ、構造化されていない
            エントリとして混じるため、不要なら False を指定する
        set_root_level: True の場合、ルートロガーの level も log_level に揃える
        json_ensure_ascii: JSON 形式で出力する際に、非 ASCII 文字を \\\\uXXXX に escape するか
            どうか。False にすると日本語などをそのまま出力する
        json: True なら JSON 形式、False ならテキスト形式。None の場合は環境変数 GNLOG_FORMAT
            に従い、それも未設定なら Cloud Run 上かどうかで自動判定する
        error_event: 指定すると、JSON 形式で severity ERROR 以上のログに分類と dedup 用の
            フィールド (event / error_type / operation / fingerprint) を付ける。
            詳しくは gnlog.google.cloud_logging.JsonFormatter を参照
        surface: fingerprint の入力に使うサービスやコンポーネントの名前 (error_event 指定時のみ)

    Returns:
        組み込んだ handler と apply() を持つ LoggingSetup
    """
    if use_json_output(json):
        # is_cloud_run() だけを使う利用側が python-json-logger を読み込まずに済むよう、
        # Cloud Logging 向け formatter はここで初めて import する
        from . import cloud_logging

        handler = output.stream_handler(
            cloud_logging.JsonFormatter(
                labels=labels,
                json_ensure_ascii=json_ensure_ascii,
                error_event=error_event,
                surface=surface,
            )
        )
    else:
        handler = output.text_handler(output_path, log_format)
    return output.install(
        handler, log_level=log_level, set_root_level=set_root_level, verbose=verbose
    )
