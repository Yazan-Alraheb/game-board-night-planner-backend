from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.game import Game
from app.models.user import User
from app.models.user_game import UserGame


pytestmark = pytest.mark.usefixtures("auth_environment")


@pytest.fixture
def collection_client():
    db = MagicMock(spec=Session)

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: User(id=42)

    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        app.dependency_overrides.clear()


def test_get_collection_success(collection_client):
    client, db = collection_client

    db.get.return_value = User(id=42)

    game = Game(
        id=7,
        name="Catan",
        minimum_players=3,
        maximum_players=4,
        playtime=60,
        difficulty="Medium",
    )

    entry = UserGame(
        user_id=42,
        game_id=7,
        status="owned",
    )
    entry.game = game

    db.query.return_value.options.return_value.filter.return_value.all.return_value = [
        entry
    ]

    response = client.get("/api/users/42/collection")

    assert response.status_code == 200
    assert response.json()["games"][0]["game"]["name"] == "Catan"
    assert response.json()["games"][0]["status"] == "owned"


def test_collection_forbidden(collection_client):
    client, db = collection_client

    response = client.get("/api/users/99/collection")

    assert response.status_code == 403
    db.get.assert_not_called()


def test_add_game_to_collection(collection_client):
    client, db = collection_client

    db.get.side_effect = [
        Game(id=7),
        None,
    ]

    response = client.post(
        "/api/users/42/collection",
        json={
            "game_id": 7,
            "status": "owned",
        },
    )

    assert response.status_code == 201
    assert response.json() == {
        "game_id": 7,
        "status": "owned",
    }

    db.add.assert_called_once()
    db.commit.assert_called_once()


def test_duplicate_game(collection_client):
    client, db = collection_client

    db.get.side_effect = [
        Game(id=7),
        UserGame(user_id=42, game_id=7, status="owned"),
    ]

    response = client.post(
        "/api/users/42/collection",
        json={"game_id": 7, "status": "wishlist"},
    )

    assert response.status_code == 409
    db.commit.assert_not_called()


def test_update_collection_status(collection_client):
    client, db = collection_client

    entry = UserGame(
        user_id=42,
        game_id=7,
        status="wishlist",
    )

    db.get.return_value = entry

    response = client.put(
        "/api/users/42/collection/7",
        json={"status": "owned"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "owned"
    assert entry.status == "owned"

    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(entry)


def test_remove_collection_game(collection_client):
    client, db = collection_client

    entry = UserGame(
        user_id=42,
        game_id=7,
        status="owned",
    )

    db.get.return_value = entry

    response = client.delete("/api/users/42/collection/7")

    assert response.status_code == 204
    assert response.content == b""

    db.delete.assert_called_once_with(entry)
    db.commit.assert_called_once()


def test_invalid_collection_status(collection_client):
    client, db = collection_client

    response = client.post(
        "/api/users/42/collection",
        json={
            "game_id": 7,
            "status": "playing",
        },
    )

    assert response.status_code == 422
    db.commit.assert_not_called()


def test_add_game_rolls_back_on_failure(collection_client):
    client, db = collection_client

    db.get.side_effect = [
        Game(id=7),
        None,
    ]

    db.commit.side_effect = SQLAlchemyError("Database failure")

    with pytest.raises(SQLAlchemyError):
        client.post(
            "/api/users/42/collection",
            json={"game_id": 7, "status": "owned"},
        )

    db.rollback.assert_called_once()


@pytest.fixture
def collection_edge_db():
    """Mock the database and authenticate as user 42."""
    mock_db = MagicMock(spec=Session)

    current_user = User(
        id=42,
        name="Test Player",
        email="test@example.com",
        password_hash="test-hash",
    )

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: current_user

    try:
        yield mock_db, current_user
    finally:
        app.dependency_overrides.clear()


def test_get_collection_user_not_found(collection_edge_db):
    mock_db, _ = collection_edge_db
    mock_db.get.return_value = None

    with TestClient(app) as client:
        response = client.get("/api/users/42/collection")

    assert response.status_code == 404
    assert response.json()["detail"] == "User not found"


def test_get_empty_collection(collection_edge_db):
    mock_db, current_user = collection_edge_db
    mock_db.get.return_value = current_user

    mock_db.query.return_value.options.return_value.filter.return_value.all.return_value = []

    with TestClient(app) as client:
        response = client.get("/api/users/42/collection")

    assert response.status_code == 200
    assert response.json()["games"] == []


def test_add_nonexistent_game(collection_edge_db):
    mock_db, _ = collection_edge_db
    mock_db.get.return_value = None

    with TestClient(app) as client:
        response = client.post(
            "/api/users/42/collection",
            json={"game_id": 9999, "status": "owned"},
        )

    assert response.status_code == 404
    mock_db.get.assert_called_once_with(Game, 9999)
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()


@pytest.mark.parametrize("method", ["put", "delete"])
def test_modify_nonexistent_collection_game(collection_edge_db, method):
    mock_db, _ = collection_edge_db
    mock_db.get.return_value = None

    path = "/api/users/42/collection/9999"

    with TestClient(app) as client:
        if method == "put":
            response = client.put(path, json={"status": "wishlist"})
        else:
            response = client.delete(path)

    assert response.status_code == 404
    mock_db.get.assert_called_once_with(UserGame, (42, 9999))
    mock_db.commit.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"game_id": 0, "status": "owned"},
        {"game_id": -1, "status": "owned"},
        {"game_id": 2, "status": "playing"},
        {"game_id": 2},
        {"game_id": 2, "status": "owned", "extra": "invalid"},
    ],
)
def test_add_collection_invalid_data(collection_edge_db, payload):
    mock_db, _ = collection_edge_db

    with TestClient(app) as client:
        response = client.post(
            "/api/users/42/collection",
            json=payload,
        )

    assert response.status_code == 422
    mock_db.add.assert_not_called()
    mock_db.commit.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "playing"},
        {},
        {"status": "owned", "extra": "invalid"},
    ],
)
def test_update_collection_invalid_data(collection_edge_db, payload):
    mock_db, _ = collection_edge_db

    with TestClient(app) as client:
        response = client.put(
            "/api/users/42/collection/2",
            json=payload,
        )

    assert response.status_code == 422
    mock_db.commit.assert_not_called()


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_modify_another_users_collection(collection_edge_db, method):
    mock_db, _ = collection_edge_db

    with TestClient(app) as client:
        if method == "post":
            response = client.post(
                "/api/users/99/collection",
                json={"game_id": 2, "status": "owned"},
            )
        elif method == "put":
            response = client.put(
                "/api/users/99/collection/2",
                json={"status": "wishlist"},
            )
        else:
            response = client.delete("/api/users/99/collection/2")

    assert response.status_code == 403
    mock_db.commit.assert_not_called()
