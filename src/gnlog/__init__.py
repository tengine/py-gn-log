"""
gnlog - Groovenauts ログユーティリティパッケージ

Python の標準 logging モジュールを拡張し、環境変数による設定や構造化ログの出力を
サポートします。

このパッケージの直下は provider (Google Cloud / AWS 等) を知らない共通部です。
ロギングの設定の入口は provider ごとのサブパッケージにあります
(Cloud Run なら ``gnlog.google.cloud_run.setup_logging``)。
"""

from . import context, fingerprint, level, output, trace

__all__ = [
    "context",
    "fingerprint",
    "level",
    "output",
    "trace",
]
