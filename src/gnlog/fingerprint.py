"""
ERROR 以上のログを同種ごとにまとめる (dedup する) ための fingerprint を作るモジュール

Cloud Error Reporting は severity=ERROR かつ stack_trace のあるログを自動で
グループ化しますが、例外を伴わない ERROR や、メッセージに可変部 (ID、件数、
引用文字列) が多いエラーはグループ化に頼れません。このモジュールは、メッセージの
可変部を置き換えて正規化し、分類と組み合わせた短いハッシュを作ります。

正規化とハッシュの規則は、他言語 (TypeScript 等) の実装と値を揃えるための契約です。
規則を変えるときは README の記述と、対になる実装もあわせて変えてください。

規則:
    1. UUID (8-4-4-4-12 の 16 進数、大文字小文字を問わない) を ``<uuid>`` に置き換える
    2. 二重引用符または単一引用符で囲まれた文字列 (改行を含まない) を ``<str>`` に置き換える
    3. 数値 (整数または小数。単語境界で区切られたもの) を ``<num>`` に置き換える
    4. 先頭 300 文字に切り詰める
    5. ``surface | operation | error_type | 正規化したメッセージ`` を ``|`` で連結し、
       UTF-8 の SHA-1 の 16 進表現の先頭 16 文字を fingerprint とする
"""

import hashlib
import re

# 正規化後のメッセージの最大長 (文字数)
MAX_MESSAGE_LENGTH = 300

# fingerprint の長さ (SHA-1 の 16 進表現の先頭から取る文字数)
FINGERPRINT_LENGTH = 16

# 置き換えの規則。適用順が結果に影響するため、この順序を変えないこと。
# (UUID は数値を含むため先に置き換える。引用文字列の中の数値も <str> にまとめる)
_UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_QUOTED_PATTERN = re.compile(r"\"[^\"\n]*\"|'[^'\n]*'")
_NUMBER_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\b")

UUID_PLACEHOLDER = "<uuid>"
STR_PLACEHOLDER = "<str>"
NUM_PLACEHOLDER = "<num>"


def normalize_message(message: str, max_length: int = MAX_MESSAGE_LENGTH) -> str:
    """メッセージの可変部を置き換えて正規化する

    Args:
        message: ログメッセージ
        max_length: 切り詰める長さ (文字数)

    Returns:
        UUID を ``<uuid>``、引用文字列を ``<str>``、数値を ``<num>`` に置き換え、
        先頭 ``max_length`` 文字に切り詰めた文字列

    Examples:
        >>> normalize_message('order 123 for "alice" not found')
        'order <num> for <str> not found'
    """
    normalized = _UUID_PATTERN.sub(UUID_PLACEHOLDER, message)
    normalized = _QUOTED_PATTERN.sub(STR_PLACEHOLDER, normalized)
    normalized = _NUMBER_PATTERN.sub(NUM_PLACEHOLDER, normalized)
    return normalized[:max_length]


def build_fingerprint(
    surface: str, operation: str, error_type: str, message: str
) -> str:
    """同種のエラーで同じ値になる短いハッシュを作る

    Args:
        surface: サービスやコンポーネントの名前 (例: ``"worker"``)。無ければ空文字
        operation: 操作名 (例: ``"orders.create"``)
        error_type: エラーの分類 (例: ``"validation"``, ``"infra"``)
        message: ログメッセージ。``normalize_message()`` で正規化してから使う

    Returns:
        ``surface|operation|error_type|正規化したメッセージ`` の UTF-8 SHA-1 の
        16 進表現の先頭 16 文字
    """
    source = "|".join([surface, operation, error_type, normalize_message(message)])
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]
