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
    2. 引用文字列 (改行を含まない) を ``<str>`` に置き換える。二重引用符で囲まれたもの、
       または単一引用符で囲まれたもののうち前後が ASCII の英数字・下線でないもの
       (can't のようなアポストロフィは引用符とみなさない)
    3. 数値を ``<num>`` に置き換える。ASCII の数字の並びで、3 桁ごとのカンマ区切り・小数部・
       指数部 (e10, E-3 など) を含めて 1 つの数値とし、前後は ASCII の単語境界で区切る
    4. 先頭 300 文字に切り詰める
    5. ``surface``、``operation``、``error_type``、正規化したメッセージのそれぞれについて
       ``\\`` を ``\\\\`` に、``|`` を ``\\|`` に escape してから ``|`` で連結し、
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
# 単一引用符は、前後が英数字・下線でないときだけ引用文字列の区切りとみなす
# (can't / won't のようなアポストロフィを引用符と誤認しないため)。
_QUOTED_PATTERN = re.compile(r"\"[^\"\n]*\"|(?<![0-9A-Za-z_])'[^'\n]*'(?![0-9A-Za-z_])")
# 数値は桁区切りのカンマ・小数部・指数部を含めて 1 つにまとめる。
# \b と \d を ASCII に限定し、他言語 (JavaScript 等) の正規表現と同じ意味にする。
_NUMBER_PATTERN = re.compile(r"\b\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][+-]?\d+)?\b", re.ASCII)

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


def _escape_component(value: str) -> str:
    """連結の区切り文字 ``|`` が値に含まれていても区切りと区別できるように escape する"""
    return value.replace("\\", "\\\\").replace("|", "\\|")


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
        ``surface|operation|error_type|正規化したメッセージ`` (各要素は ``\\`` と ``|`` を
        escape 済み) の UTF-8 SHA-1 の 16 進表現の先頭 16 文字
    """
    components = [surface, operation, error_type, normalize_message(message)]
    source = "|".join(_escape_component(c) for c in components)
    return hashlib.sha1(source.encode("utf-8")).hexdigest()[:FINGERPRINT_LENGTH]
