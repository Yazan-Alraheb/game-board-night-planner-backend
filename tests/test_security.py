import pytest
from pwdlib.exceptions import UnknownHashError

from app.core.security import hash_password, verify_password


def test_correct_password_matches_hash():
    password = "GameNight-secret-123!"
    password_hash = hash_password(password)

    assert verify_password(password, password_hash)


def test_incorrect_password_does_not_match():
    password_hash = hash_password("GameNight-secret-123!")

    assert not verify_password("wrong-password", password_hash)


def test_same_password_produces_different_salted_hashes():
    password = "GameNight-secret-123!"

    first_hash = hash_password(password)
    second_hash = hash_password(password)

    assert first_hash != second_hash
    assert verify_password(password, first_hash)
    assert verify_password(password, second_hash)


def test_hash_does_not_contain_plaintext_password():
    password = "GameNight-secret-123!"

    assert password not in hash_password(password)


def test_password_hash_uses_argon2():
    password = "GameNight-secret-123!"

    password_hash = hash_password(password)

    assert password_hash.startswith("$argon2id$")


def test_malformed_password_hash():
    with pytest.raises(UnknownHashError):
        verify_password(
            "GameNight-secret-123!",
            "not-a-valid-password-hash",
        )
