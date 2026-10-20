import importlib
import pkgutil

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.core.database import Base, get_db
from app.core.security import decode_access_token
from app.main import app

for module in pkgutil.iter_modules(models.__path__):
    importlib.import_module(f"app.models.{module.name}")

USER = {"name": "Bob", "email": "bob@gmail.com", "password": "supersecret"}


@pytest.fixture
def client(auth_environment):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Base.metadata.tables["users"]])
    app.dependency_overrides[get_db] = lambda: (yield sessionmaker(bind=engine)())
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def post(client, path, **overrides):
    return client.post(f"/api/auth/{path}", json=USER | overrides)


def test_register_and_login(client):
    user = post(client, "register", email=" Bob@Gmail.com ")
    assert user.status_code == 201
    assert user.json()["email"] == "bob@gmail.com"
    assert "password_hash" not in user.json()
    token = post(client, "login", email="BOB@GMAIL.COM").json()["access_token"]
    assert decode_access_token(token) == user.json()["id"]


@pytest.mark.parametrize(("path", "overrides", "status"), [
    ("register", {"email": "BOB@gmail.com"}, 409), ("register", {"name": ""}, 422),
    ("register", {"email": "bob@"}, 422), ("register", {"password": "a" * 7}, 422),
    ("login", {"password": "wrongpassword"}, 401), ("login", {"email": "nobody@gmail.com"}, 401),
])
def test_rejects_bad_requests(client, path, overrides, status):
    post(client, "register")
    assert post(client, path, **overrides).status_code == status