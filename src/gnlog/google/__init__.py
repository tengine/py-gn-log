"""
gnlog.google - Google Cloud 向けの実装

共通部 (``gnlog.context`` / ``gnlog.fingerprint`` / ``gnlog.level`` / ``gnlog.output`` /
``gnlog.trace``) は provider を知らず、このサブパッケージが共通部を使います。
利用側は ``gnlog.google.cloud_run`` を入口にしてください。

このモジュール自体は何も import しません (``gnlog.google.cloud_run`` の
``is_cloud_run`` だけを使う場合に、Cloud Logging 向けの依存を読み込まないため)。
"""
