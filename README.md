# py-gn-log

## インストール

### uvを使う場合

```
uv add git+ssh://git@github.com/tengine/py-gn-log
```

ブランチを指定する場合

```
uv add git+ssh://git@github.com/tengine/py-gn-log --branch (ブランチ名)
```

## 使い方

### 基本的な使い方

```python
import logging
from gnlog import Initializer

# ロギングを初期化
initializer = Initializer(log_level=logging.INFO)

# ロガーを取得して使用
logger = initializer.apply(__name__)
logger.info("Application started")
logger.error("An error occurred")
```

`__name__` は呼び出すモジュールの名前(この場合は .py ファイルの名前から拡張子を除いたもの)を表す特殊な変数です。詳しくは [Python チュートリアル » 6. モジュール](https://docs.python.org/ja/3/tutorial/modules.html) あるいは [Python 言語リファレンス » 3. データモデル » module.__name__](https://docs.python.org/ja/3/reference/datamodel.html#module.__name__) を参照してください。

### 環境変数による設定

#### ログレベルの設定

環境変数 `LOG_LEVEL` でログレベルを指定できます。

```bash
export LOG_LEVEL=DEBUG
```

指定可能な値: `DEBUG`, `INFO`, `WARN`, `WARNING`, `ERROR`, `CRITICAL`

```python
from gnlog import Initializer

# 環境変数 LOG_LEVEL からログレベルを読み込む
initializer = Initializer()
logger = initializer.apply("my_app")
```

#### ログファイルへの出力

環境変数 `LOG_FILE_PATH` でログファイルのパスを指定できます。

```bash
export LOG_FILE_PATH=/var/log/myapp.log
```

#### ログフォーマットのカスタマイズ

環境変数 `LOG_FORMAT` でログフォーマットを指定できます。

```bash
export LOG_FORMAT="%(asctime)s [%(levelname)s] %(message)s"
```

### Cloud Run での使用

環境変数 `K_SERVICE` が設定されている場合（Cloud Run 環境）、自動的に JSON 形式でログを出力します。

```python
from gnlog import Initializer

# Cloud Run では自動的に JSON フォーマットが使用される
initializer = Initializer()
logger = initializer.apply("my_service")
logger.info("Service started", extra={"user_id": 123})
```

出力例:
```json
{
  "name": "my_service",
  "message": "Service started",
  "timestamp": "2025-01-15T10:30:45.123456Z",
  "severity": "INFO",
  "user_id": 123
}
```

### ログレベルのユーティリティ関数

```python
from gnlog import level
import logging

# 文字列からログレベルを取得
log_level = level.parse("ERROR")  # => logging.ERROR

# 環境変数からログレベルを取得
log_level = level.from_env()  # LOG_LEVEL 環境変数から取得

# ログレベルを文字列に変換
level_str = level.to_str(logging.INFO)  # => "INFO"
```

### 高度な使い方

#### ロガーごとに異なる設定を適用

```python
from gnlog import Initializer
import logging

initializer = Initializer(log_level=logging.INFO)

# 特定のロガーは DEBUG レベルで出力
debug_logger = initializer.apply("debug_module", log_level=logging.DEBUG)

# 親ロガーへの伝播を無効化
isolated_logger = initializer.apply("isolated", propagate=False)

# 既存のハンドラをクリアして新規追加
clean_logger = initializer.apply("clean", clear_handlers=True, add_handler=True)
```

## 開発者向け

### 前提条件

- [uv](https://docs.astral.sh/uv/)
