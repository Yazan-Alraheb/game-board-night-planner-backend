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



def setup_games_query(db, games, total=None):
    query = db.query.return_value

    query.filter.return_value = query
    query.order_by.return_value = query
    query.offset.return_value = query
    query.limit.return_value = query

    query.count.return_value = len(games) if total is None else total
    query.all.return_value = games

    return query


def test_browse_games_empty(games_client):
    client, db = games_client
    setup_games_query(db, [])

    response = client.get("/api/games")

    assert response.status_code == 200
    assert response.json()["games"] == []
    assert response.json()["total"] == 0
    assert response.json()["page"] == 1


def test_browse_multiple_games(games_client, sample_game):
    client, db = games_client

    second_game = Game(
        id=8,
        name="Flip 7",
        minimum_players=3,
        maximum_players=18,
        playtime=20,
        difficulty="Easy",
        categories=["Card Game", "Party"],
    )

    setup_games_query(db, [sample_game, second_game])

    response = client.get("/api/games")

    assert response.status_code == 200

    data = response.json()

    assert data["total"] == 2
    assert len(data["games"]) == 2

    assert data["games"][0]["name"] == "Catan"
    assert data["games"][1]["name"] == "Flip 7"
    assert data["games"][1]["id"] == 8


@pytest.mark.parametrize(
    "page, limit, expected_offset",
    [
        (1, 10, 0),
        (2, 10, 10),
        (3, 5, 10),
        (4, 20, 60),
    ],
)
def test_games_pagination(
    games_client, page, limit, expected_offset
):
    client, db = games_client
    query = setup_games_query(db, [], total=100)

    response = client.get(
        "/api/games",
        params={"page": page, "limit": limit},
    )

    assert response.status_code == 200
    assert response.json()["page"] == page
    assert response.json()["total"] == 100

    query.offset.assert_called_once_with(expected_offset)
    query.limit.assert_called_once_with(limit)


@pytest.mark.parametrize(
    "params",
    [
        {"search": "Catan"},
        {"players": 4},
        {"category": "Strategy"},
        {"difficulty": "Medium"},
        {"playtime": 60},
    ],
)
def test_individual_game_filters(games_client, sample_game, params):
    client, db = games_client
    query = setup_games_query(db, [sample_game])

    response = client.get("/api/games", params=params)

    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert response.json()["games"][0]["name"] == "Catan"

    query.filter.assert_called_once()


def test_browse_games_without_filters(games_client, sample_game):
    client, db = games_client
    query = setup_games_query(db, [sample_game])

    response = client.get("/api/games")

    assert response.status_code == 200
    assert response.json()["total"] == 1

    query.filter.assert_not_called()


def test_get_game_response_fields(games_client, sample_game):
    client, db = games_client
    db.get.return_value = sample_game

    response = client.get("/api/games/7")

    assert response.status_code == 200

    game = response.json()["game"]

    assert game["id"] == 7
    assert game["name"] == "Catan"
    assert game["minimum_players"] == 3
    assert game["maximum_players"] == 4
    assert game["playtime"] == 60
    assert game["difficulty"] == "Medium"
    assert game["categories"] == ["Strategy"]


@pytest.mark.parametrize(
    "game_id",
    [
        "abc",
        "7.5",
        "Catan",
    ],
)
def test_get_game_invalid_id(games_client, game_id):
    client, db = games_client

    response = client.get(f"/api/games/{game_id}")

    assert response.status_code == 422
    db.get.assert_not_called()


@pytest.mark.parametrize(
    "params",
    [
        {"players": "four"},
        {"page": "two"},
        {"limit": "many"},
        {"playtime": "fast"},
        {"players": -5},
        {"page": -2},
        {"limit": -1},
    ],
)
def test_invalid_game_filter_types(games_client, params):
    client, db = games_client

    response = client.get("/api/games", params=params)

    assert response.status_code == 422
    db.query.assert_not_called()
