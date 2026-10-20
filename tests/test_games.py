from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.main import app
from app.models.game import Game


pytestmark = pytest.mark.usefixtures("auth_environment")


@pytest.fixture
def games_client():
    db = MagicMock(spec=Session)
    app.dependency_overrides[get_db] = lambda: db

    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def sample_game():
    return Game(
        id=7,
        name="Catan",
        minimum_players=3,
        maximum_players=4,
        playtime=60,
        difficulty="Medium",
        categories=["Strategy"],
    )


def test_get_game_success(games_client, sample_game):
    client, db = games_client
    db.get.return_value = sample_game

    response = client.get("/api/games/7")

    assert response.status_code == 200
    assert response.json()["game"]["name"] == "Catan"
    db.get.assert_called_once_with(Game, 7)


def test_get_game_not_found(games_client):
    client, db = games_client
    db.get.return_value = None

    response = client.get("/api/games/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Game not found"}


def test_browse_games(games_client, sample_game):
    client, db = games_client

    query = db.query.return_value
    query.count.return_value = 1
    query.order_by.return_value.offset.return_value.limit.return_value.all.return_value = [
        sample_game
    ]

    response = client.get("/api/games?page=1&limit=10")

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["page"] == 1
    assert response.json()["games"][0]["id"] == 7


def test_games_apply_filters(games_client, sample_game):
    client, db = games_client
    query = db.query.return_value

    query.filter.return_value = query
    query.count.return_value = 1
    query.order_by.return_value = query
    query.offset.return_value = query
    query.limit.return_value = query
    query.all.return_value = [sample_game]

    response = client.get(
        "/api/games",
        params={
            "search": "Catan",
            "players": 4,
            "category": "Strategy",
            "difficulty": "Medium",
            "playtime": 60,
        },
    )

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert query.filter.call_count == 5


@pytest.mark.parametrize(
    "params",
    [
        {"players": 0},
        {"page": 0},
        {"limit": 0},
        {"limit": 101},
        {"difficulty": "Impossible"},
        {"playtime": -10},
    ],
)
def test_invalid_game_filters(games_client, params):
    client, db = games_client

    response = client.get("/api/games", params=params)

    assert response.status_code == 422
    db.query.assert_not_called()
