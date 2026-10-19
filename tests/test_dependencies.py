import inspect
import time
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import dependencies
from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.user import User


pytestmark = pytest.mark.usefixtures("auth_environment")


@pytest.fixture
def session():
    db = MagicMock(spec=Session)
    db.get.return_value = User(id=42, name="Player", email="player@example.com")
    return db


@pytest.fixture
def client(session):
    app = FastAPI()
    app.dependency_overrides[get_db] = lambda: session

    @app.get("/current-user")
    def current_user(user: User = Depends(get_current_user)):
        assert user is session.get.return_value
        return {"id": user.id}

    with TestClient(app) as test_client:
        yield test_client


def assert_unauthorized(response):
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Could not validate credentials"}


@pytest.mark.parametrize("scheme", ["Bearer", "bearer"])
def test_valid_token(client, session, scheme):
    response = client.get(
        "/current-user", headers={"Authorization": f"{scheme} {create_access_token(42)}"}
    )
    assert response.status_code == 200
    assert response.json() == {"id": 42}
    session.get.assert_called_once_with(User, 42)
    session.close.assert_not_called()


def test_get_current_user_is_synchronous():
    assert not inspect.iscoroutinefunction(get_current_user)


@pytest.mark.parametrize(
    "authorization",
    [None, "", "Bearer", "Bearer ", "Basic abc", "Token abc", "Bearer not-a-jwt", "Bearer a b"],
)
def test_missing_or_malformed_credentials(client, session, authorization):
    headers = {} if authorization is None else {"Authorization": authorization}
    assert_unauthorized(client.get("/current-user", headers=headers))
    session.get.assert_not_called()


@pytest.mark.parametrize("kind", ["expired", "tampered", "wrong-signature", "unsupported"])
def test_invalid_token(client, session, jwt_secret, kind):
    now = int(time.time())
    claims = {"sub": "42", "iat": now - 120, "exp": now + 600}
    secret = jwt_secret
    algorithm = "HS256"
    if kind == "expired":
        claims["exp"] = now - 60
    elif kind == "wrong-signature":
        secret = "different-test-signing-secret-at-least-32-bytes"
    elif kind == "unsupported":
        algorithm = "HS512"
    token = jwt.encode(claims, secret, algorithm=algorithm)
    if kind == "tampered":
        header, _, signature = token.split(".")
        payload = jwt.utils.base64url_encode(b'{"sub":"99"}').decode()
        token = f"{header}.{payload}.{signature}"
    assert_unauthorized(client.get("/current-user", headers={"Authorization": f"Bearer {token}"}))
    session.get.assert_not_called()


def test_user_no_longer_exists(client, session):
    session.get.return_value = None
    assert_unauthorized(client.get(
        "/current-user", headers={"Authorization": f"Bearer {create_access_token(42)}"}
    ))
    session.get.assert_called_once_with(User, 42)


def test_database_failure_propagates(client, session):
    session.get.side_effect = SQLAlchemyError("Database unavailable")
    with pytest.raises(SQLAlchemyError, match="Database unavailable"):
        client.get("/current-user", headers={"Authorization": f"Bearer {create_access_token(42)}"})


def test_unexpected_decoder_error_propagates(client, session, monkeypatch):
    def broken_decoder(token):
        raise RuntimeError("Programming error")

    monkeypatch.setattr(dependencies, "decode_access_token", broken_decoder)
    with pytest.raises(RuntimeError, match="Programming error"):
        client.get("/current-user", headers={"Authorization": "Bearer token"})
    session.get.assert_not_called()
