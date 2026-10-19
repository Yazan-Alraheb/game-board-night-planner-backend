import time

import jwt
import pytest
from fastapi.testclient import TestClient
from jwt.exceptions import InvalidTokenError
from pydantic import ValidationError

from app.core.auth_settings import AuthSettings, get_auth_settings
from app.core.security import create_access_token, decode_access_token
from app.main import app


pytestmark = pytest.mark.usefixtures("auth_environment")


def test_auth_settings_are_cached(monkeypatch, jwt_secret):
    settings = get_auth_settings()
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "5")
    assert get_auth_settings() is settings
    claims = jwt.decode(create_access_token(42), jwt_secret, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == 1800
    get_auth_settings.cache_clear()
    assert get_auth_settings().jwt_access_token_expire_minutes == 5


def test_startup_with_valid_settings():
    with TestClient(app) as client:
        assert get_auth_settings.cache_info().currsize == 1
        response = client.get("/")
        assert response.status_code == 200
        assert response.json() == {"message": "Game Board Night Planner API"}


@pytest.mark.parametrize("secret", [None, "", "short"])
def test_startup_rejects_missing_or_invalid_secret(monkeypatch, secret):
    if secret is None:
        monkeypatch.delenv("JWT_SECRET_KEY")
    else:
        monkeypatch.setenv("JWT_SECRET_KEY", secret)
    with pytest.raises(ValidationError):
        with TestClient(app):
            pytest.fail("Application started with invalid settings")


@pytest.mark.parametrize("lifetime", ["0", "-1", "invalid"])
def test_startup_rejects_invalid_lifetime(monkeypatch, lifetime):
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", lifetime)
    with pytest.raises(ValidationError):
        with TestClient(app):
            pytest.fail("Application started with invalid settings")


def valid_claims():
    now = int(time.time())
    return {"sub": "42", "iat": now - 60, "exp": now + 600}


def sign(claims, secret=None, algorithm="HS256"):
    if secret is None and algorithm != "none":
        secret = get_auth_settings().jwt_secret_key.get_secret_value()
    return jwt.encode(claims, secret, algorithm=algorithm)


def test_valid_token_round_trip(jwt_secret):
    before = int(time.time())
    token = create_access_token(42)
    after = int(time.time())
    assert decode_access_token(token) == 42
    claims = jwt.decode(token, jwt_secret, algorithms=["HS256"])
    assert claims["sub"] == "42"
    assert before <= claims["iat"] <= after
    assert claims["exp"] - claims["iat"] == 30 * 60


def test_expired_token():
    now = int(time.time())
    token = sign({"sub": "42", "iat": now - 120, "exp": now - 60})
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(token)


@pytest.mark.parametrize("subject", ["9" * 5000, "9" * 19, "2147483648"])
def test_subject_exceeds_postgresql_integer_range(subject):
    claims = valid_claims()
    claims["sub"] = subject
    with pytest.raises(InvalidTokenError):
        decode_access_token(sign(claims))


def test_maximum_user_id_round_trip():
    assert decode_access_token(create_access_token(2147483647)) == 2147483647


def test_create_token_above_maximum_user_id():
    with pytest.raises(ValueError):
        create_access_token(2147483648)


def test_incorrect_signature():
    token = sign(valid_claims(), secret="different-test-secret-of-at-least-32-bytes")
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(token)


def test_tampered_payload():
    token = sign(valid_claims())
    header, _, signature = token.split(".")
    payload = jwt.utils.base64url_encode(b'{"sub":"99","iat":1,"exp":9999999999}').decode()
    with pytest.raises(jwt.InvalidSignatureError):
        decode_access_token(f"{header}.{payload}.{signature}")


@pytest.mark.parametrize("claim", ["sub", "exp", "iat"])
def test_missing_claim(claim):
    claims = valid_claims()
    del claims[claim]
    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_access_token(sign(claims))


@pytest.mark.parametrize("subject", [None, True, 42, "", "0", "-1", "+1", "01", " 1", "1 ", "1.5", "abc", "١"])
def test_malformed_subject(subject):
    claims = valid_claims()
    claims["sub"] = subject
    with pytest.raises(InvalidTokenError):
        decode_access_token(sign(claims))


@pytest.mark.parametrize("claim", ["iat", "exp"])
@pytest.mark.parametrize("value", [None, True, "not-a-time", "1234567890", 1234567890.5, [], {}])
def test_invalid_timestamps(claim, value):
    claims = valid_claims()
    claims[claim] = value
    with pytest.raises(InvalidTokenError):
        decode_access_token(sign(claims))


def test_future_issued_token():
    now = int(time.time())
    with pytest.raises(jwt.ImmatureSignatureError):
        decode_access_token(sign({"sub": "42", "iat": now + 600, "exp": now + 1200}))


@pytest.mark.parametrize("offset", [0, -1])
def test_expiration_must_follow_issuance(offset):
    now = int(time.time())
    with pytest.raises(InvalidTokenError):
        decode_access_token(sign({"sub": "42", "iat": now, "exp": now + offset}))


@pytest.mark.parametrize("algorithm", ["HS384", "HS512", "none"])
def test_unsupported_algorithm(algorithm):
    token = sign(valid_claims(), algorithm=algorithm)
    with pytest.raises(jwt.InvalidAlgorithmError):
        decode_access_token(token)


@pytest.mark.parametrize("user_id", [True, False, 0, -1, "42", 1.5, None])
def test_invalid_user_id_when_creating(user_id):
    with pytest.raises(ValueError):
        create_access_token(user_id)


def test_configurable_lifetime(monkeypatch, jwt_secret):
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "5")
    claims = jwt.decode(create_access_token(42), jwt_secret, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] == 300


@pytest.mark.parametrize("operation", [lambda: create_access_token(42), lambda: decode_access_token("token")])
def test_missing_secret(monkeypatch, operation):
    monkeypatch.delenv("JWT_SECRET_KEY")
    with pytest.raises(ValidationError):
        operation()


@pytest.mark.parametrize("secret", ["", "short", " " * 32, "é" * 15])
def test_invalid_secret(monkeypatch, secret):
    monkeypatch.setenv("JWT_SECRET_KEY", secret)
    with pytest.raises(ValidationError):
        create_access_token(42)


def test_secret_length_uses_utf8_bytes(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "é" * 16)
    assert decode_access_token(create_access_token(42)) == 42


@pytest.mark.parametrize("lifetime", ["0", "-1", "abc", "1.5", ""])
def test_invalid_lifetime(monkeypatch, lifetime):
    monkeypatch.setenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", lifetime)
    with pytest.raises(ValidationError):
        create_access_token(42)


def test_boolean_lifetime_is_rejected():
    with pytest.raises(ValidationError):
        AuthSettings(jwt_access_token_expire_minutes=True)


def test_dotenv_ignores_unrelated_settings(tmp_path, monkeypatch, jwt_secret):
    monkeypatch.delenv("JWT_SECRET_KEY")
    env_file = tmp_path / ".env"
    env_file.write_text(
        f"JWT_SECRET_KEY={jwt_secret}\nDATABASE_URL=unused\nUNRELATED_SETTING=value\n",
        encoding="utf-8",
    )
    settings = AuthSettings(_env_file=env_file)
    assert settings.jwt_secret_key.get_secret_value() == jwt_secret
    assert settings.jwt_access_token_expire_minutes == 30
    assert "database_url" not in settings.model_dump()
    assert "unrelated_setting" not in settings.model_dump()


def test_secret_below_32_utf8_bytes_is_rejected(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "é" * 15 + "a")

    with pytest.raises(ValidationError):
        create_access_token(42)
