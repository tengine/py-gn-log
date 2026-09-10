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
            # アポストロフィは引用符とみなさない
            (
                "can't connect to database, won't retry",
                "can't connect to database, won't retry",
            ),
            ("user 'bob' can't login", "user <str> can't login"),
            ("it's 'quoted'.", "it's <str>."),
            # 閉じ引用符の直後に英数字が続いても引用文字列として扱う (所有格)
            ("user 'bob's account is locked", "user <str>s account is locked"),
            # 桁区切りと指数部を含めて 1 つの数値
            ("count 1,234 rows", "count <num> rows"),
            ("count 9,876,543 rows", "count <num> rows"),
            ("timeout after 1.5e10 ns", "timeout after <num> ns"),
            ("tolerance 2E-3 exceeded", "tolerance <num> exceeded"),
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

    def test_is_stable_for_grouped_numbers(self):
        """桁区切りの件数だけが違うメッセージは同じ fingerprint になること"""
        a = build_fingerprint("w", "op", "validation", "rejected 1,234 rows")
        b = build_fingerprint("w", "op", "validation", "rejected 9,876,543 rows")
        assert a == b

    def test_differs_for_different_errors_with_apostrophes(self):
        """アポストロフィを含む別種のメッセージは違う fingerprint になること"""
        a = build_fingerprint(
            "w", "op", "infra", "can't connect to database, won't retry"
        )
        b = build_fingerprint("w", "op", "infra", "can't parse payload, won't retry")
        assert a != b

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

    def test_delimiter_in_values_does_not_collide(self):
        """値に区切り文字 | が含まれていても、別の組み合わせと同じ値にならないこと"""
        a = build_fingerprint("worker|orders", "create", "validation", "boom")
        b = build_fingerprint("worker", "orders|create", "validation", "boom")
        assert a != b

    def test_escapes_backslash_and_delimiter(self):
        """規則どおり \\ と | を escape してから連結すること"""
        expected = hashlib.sha1(
            "worker\\|orders|create|validation|a\\\\b".encode()
        ).hexdigest()[:16]
        assert (
            build_fingerprint("worker|orders", "create", "validation", "a\\b")
            == expected
        )

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
