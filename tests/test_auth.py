import importlib
import pkgutil

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.core.database import Base, get_db
from app.core.security import decode_access_token
from app.main import app
from app.repository import user as user_repository
from app.services import user as user_service

for module in pkgutil.iter_modules(models.__path__):
    importlib.import_module(f"app.models.{module.name}")

USER = {"name": "Bob", "email": "bob@gmail.com", "password": "supersecret"}


@pytest.fixture
def client(auth_environment):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables["users"]])
    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def post(client, path, **overrides):
    payload = USER | overrides
    if path == "login":
        payload.pop("name")
    return client.post(f"/api/auth/{path}", json=payload)


def test_register_and_login(client):
    user = post(client, "register", email=" Bob@Gmail.com ")
    assert user.status_code == 201
    assert user.json()["user"]["email"] == "bob@gmail.com"
    assert "password_hash" not in user.json()["user"]

    response = post(client, "login", email="BOB@GMAIL.COM")
    assert response.status_code == 200

    body = response.json()
    assert body["token_type"] == "bearer"
    assert decode_access_token(body["access_token"]) == user.json()["user"]["id"]


@pytest.mark.parametrize(("path", "overrides", "status"), [
    ("register", {"email": "BOB@gmail.com"}, 409), ("register", {"name": ""}, 422),
    ("register", {"name": "   "}, 422), ("register", {"email": "bob@"}, 422),
    ("register", {"password": "a" * 7}, 422),
])
def test_register_rejects_bad_requests(client, path, overrides, status):
    post(client, "register")
    assert post(client, path, **overrides).status_code == status


def test_register_trims_name(client):
    assert post(client, "register", name="  Bob  ").json()["user"]["name"] == "Bob"


def test_login_failures_return_identical_responses(client):
    post(client, "register")
    wrong_password = post(client, "login", password="wrongpassword")
    unknown_email = post(client, "login", email="nobody@gmail.com")
    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert response.json() == {"detail": "Invalid email or password"}
        assert response.headers["WWW-Authenticate"] == "Bearer"


def test_login_verifies_password_for_unknown_email(client, monkeypatch):
    calls = []
    original = user_service.verify_password
    monkeypatch.setattr(user_service, "verify_password", lambda *args: calls.append(args) or original(*args))
    post(client, "login", email="nobody@gmail.com")
    assert len(calls) == 1


def test_register_duplicate_email_database_error_returns_409(client, monkeypatch):
    post(client, "register")
    monkeypatch.setattr(user_repository, "get_user_by_email", lambda db, email: None)
    assert post(client, "register").status_code == 409


def test_register_reraises_unrelated_integrity_errors(client, monkeypatch):
    def fail(*args, **kwargs):
        raise IntegrityError("INSERT", {}, Exception("NOT NULL constraint failed: users.name"))

    monkeypatch.setattr(user_repository, "create_user", fail)
    with pytest.raises(IntegrityError):
        post(client, "register")
