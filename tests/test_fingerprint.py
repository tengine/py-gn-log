import hashlib

import pytest

from gnlog.fingerprint import build_fingerprint, normalize_message


class TestNormalizeMessage:
    """normalize_message のテスト"""

    @pytest.mark.parametrize(
        ("message", "expected"),
        [
            ("order 123 not found", "order <num> not found"),
            ("ratio 0.75 exceeded", "ratio <num> exceeded"),
            ('user "alice" missing', "user <str> missing"),
            ("user 'bob' missing", "user <str> missing"),
            (
                "id 3f2504e0-4f89-11d3-9a0c-0305e82c3301 gone",
                "id <uuid> gone",
            ),
            (
                "id 3F2504E0-4F89-11D3-9A0C-0305E82C3301 gone",
                "id <uuid> gone",
            ),
            # 引用文字列の中の数値は <str> にまとまる
            ('code "E123"', "code <str>"),
            # 識別子に含まれる数字は単語境界で区切られていないので置き換えない
            ("table t1 locked", "table t1 locked"),
            ("no variable parts", "no variable parts"),
        ],
    )
    def test_replaces_variable_parts(self, message, expected):
        """UUID / 引用文字列 / 数値が置き換えられること"""
        assert normalize_message(message) == expected

    def test_truncates_to_max_length(self):
        """先頭 300 文字に切り詰められること"""
        normalized = normalize_message("x" * 500)
        assert len(normalized) == 300

    def test_truncates_after_replacement(self):
        """置き換えを行ってから切り詰めること"""
        message = "a" * 298 + " 12345"
        # 置き換え後は "a"*298 + " <num>" (304 文字) → 先頭 300 文字
        assert normalize_message(message) == "a" * 298 + " <"

    def test_custom_max_length(self):
        """max_length を指定できること"""
        assert normalize_message("abcdef", max_length=3) == "abc"


class TestBuildFingerprint:
    """build_fingerprint のテスト"""

    def test_is_stable_for_same_kind_of_error(self):
        """可変部だけが違うメッセージは同じ fingerprint になること"""
        a = build_fingerprint(
            "worker", "orders.create", "validation", "order 1 missing"
        )
        b = build_fingerprint(
            "worker", "orders.create", "validation", "order 2 missing"
        )
        assert a == b

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"surface": "other"},
            {"operation": "other"},
            {"error_type": "other"},
            {"message": "other message"},
        ],
    )
    def test_changes_when_any_component_changes(self, kwargs):
        """surface / operation / error_type / メッセージのいずれかが違えば値が変わること"""
        base = {
            "surface": "worker",
            "operation": "orders.create",
            "error_type": "validation",
            "message": "order missing",
        }
        assert build_fingerprint(**base) != build_fingerprint(**{**base, **kwargs})

    def test_is_first_16_hex_chars_of_sha1(self):
        """規則どおり、連結文字列の UTF-8 SHA-1 の先頭 16 文字であること"""
        expected = hashlib.sha1(
            "worker|orders.create|validation|order <num> missing".encode()
        ).hexdigest()[:16]
        assert (
            build_fingerprint(
                "worker", "orders.create", "validation", "order 1 missing"
            )
            == expected
        )

    def test_reference_value_for_other_language_implementations(self):
        """他言語の実装と値を揃えるための参照値 (規則を変えない限りこの値は変わらない)"""
        value = build_fingerprint(
            "worker",
            "orders.create",
            "validation",
            'order 123 for "alice" not found (id=3f2504e0-4f89-11d3-9a0c-0305e82c3301)',
        )
        assert value == "fc2673ac3981f22c"
