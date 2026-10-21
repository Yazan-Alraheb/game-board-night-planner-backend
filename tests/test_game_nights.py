from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app
from app.models.friend import Friend
from app.models.game import Game
from app.models.game_night import GameNight
from app.models.game_night_game import GameNightGame
from app.models.game_night_member import GameNightMember
from app.models.user import User
from app.models.user_game import UserGame


EXPECTED_ROUTES = {
    ("/api/game-nights", "GET"),
    ("/api/game-nights", "POST"),
    ("/api/game-nights/{id}", "GET"),
    ("/api/game-nights/{id}", "PUT"),
    ("/api/game-nights/{id}", "DELETE"),
    ("/api/game-nights/{id}/members", "GET"),
    ("/api/game-nights/{id}/members", "POST"),
    ("/api/game-nights/{id}/rsvp", "PUT"),
    ("/api/game-nights/{id}/members/{user_id}", "DELETE"),
    ("/api/game-nights/{id}/games", "GET"),
    ("/api/game-nights/{id}/games", "POST"),
    ("/api/game-nights/{id}/games/{game_id}", "DELETE"),
}


def test_game_night_api_contract():
    openapi = app.openapi()
    paths = openapi["paths"]

    actual_routes = {
        (path, method.upper())
        for path, operations in paths.items()
        for method in operations
    }

    missing_routes = EXPECTED_ROUTES - actual_routes
    assert not missing_routes, f"Missing routes: {missing_routes}"

    assert "requestBody" in paths["/api/game-nights"]["post"]
    assert "requestBody" in paths["/api/game-nights/{id}"]["put"]
    assert "requestBody" in paths["/api/game-nights/{id}/members"]["post"]
    assert "requestBody" in paths["/api/game-nights/{id}/rsvp"]["put"]
    assert "requestBody" in paths["/api/game-nights/{id}/games"]["post"]

    assert "201" in paths["/api/game-nights"]["post"]["responses"]
    assert "204" in paths["/api/game-nights/{id}"]["delete"]["responses"]


@pytest.fixture
def game_nights(auth_environment):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[
        User.__table__, Game.__table__, UserGame.__table__, GameNight.__table__,
        GameNightMember.__table__, GameNightGame.__table__,
    ])
    # The PostgreSQL-only friend-pair index uses least()/greatest(); SQLite lacks them.
    metadata = MetaData()
    User.__table__.to_metadata(metadata)
    friends = Friend.__table__.to_metadata(metadata)
    friends.indexes.remove(next(i for i in friends.indexes if i.name == "uq_active_friend_pair"))
    friends.create(engine)

    # Match production: SessionLocal disables autoflush.
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add_all([
            User(id=i, name=f"Player {i}", email=f"secret{i}@example.com",
                 password_hash="private-hash")
            for i in range(1, 6)
        ])
        db.add_all([
            Game(id=i, name=f"Game {i}", minimum_players=2, maximum_players=6,
                 playtime=60, difficulty="Medium", categories=["Strategy"])
            for i in range(1, 4)
        ])
        db.flush()
        db.add_all([
            Friend(requester_id=1, receiver_id=i, status="accepted") for i in (2, 3, 4)
        ])
        db.add(GameNight(id=1, host_id=1, name="Night", location="Home",
                         starts_at=datetime(2030, 1, 1, 18, tzinfo=timezone.utc)))
        db.flush()
        db.add_all([
            GameNightMember(game_night_id=1, user_id=i, status="accepted") for i in (1, 2, 3)
        ])
        # Game 1: only user 2. Game 2: users 2 and 3. Game 3: host only.
        # User 3's wishlist copy of game 1 must not keep it selected.
        db.add_all([
            UserGame(user_id=u, game_id=g, status=s) for u, g, s in [
                (2, 1, "owned"), (2, 2, "owned"), (3, 2, "owned"),
                (1, 3, "owned"), (3, 1, "wishlist"),
            ]
        ])
        db.add_all([GameNightGame(game_night_id=1, game_id=g) for g in (1, 2, 3)])
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client, factory
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()


def auth(user_id):
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def selected_ids(factory):
    with factory() as db:
        return sorted(row.game_id for row in db.query(GameNightGame).filter_by(game_night_id=1))


def test_decline_removes_only_games_without_remaining_accepted_owner(game_nights):
    client, factory = game_nights
    response = client.put("/api/game-nights/1/rsvp", headers=auth(2), json={"status": "declined"})
    assert response.status_code == 200
    assert response.json() == {"game_night_id": 1, "status": "declined"}
    # Game 1 lost its only accepted owner; game 2 is still owned by user 3.
    assert selected_ids(factory) == [2, 3]
    games = client.get("/api/game-nights/1/games", headers=auth(1)).json()["games"]
    owners = {g["game"]["id"]: [o["id"] for o in g["owners"]] for g in games}
    assert owners == {2: [3], 3: [1]}


def test_accepting_keeps_selected_games(game_nights):
    client, factory = game_nights
    response = client.put("/api/game-nights/1/rsvp", headers=auth(3), json={"status": "accepted"})
    assert response.status_code == 200
    assert selected_ids(factory) == [1, 2, 3]


@pytest.mark.parametrize("actor", [1, 2])
def test_removing_accepted_member_cleans_up_their_only_owned_games(game_nights, actor):
    client, factory = game_nights
    # Host removal and self-removal share the same cleanup path.
    assert client.delete("/api/game-nights/1/members/2", headers=auth(actor)).status_code == 204
    assert selected_ids(factory) == [2, 3]
    with factory() as db:
        assert db.get(GameNightMember, (1, 2)) is None


def test_removing_last_remaining_owner_removes_shared_game(game_nights):
    client, factory = game_nights
    assert client.delete("/api/game-nights/1/members/2", headers=auth(1)).status_code == 204
    assert client.delete("/api/game-nights/1/members/3", headers=auth(1)).status_code == 204
    assert selected_ids(factory) == [3]


def test_removing_pending_member_keeps_selected_games(game_nights):
    client, factory = game_nights
    with factory() as db:
        db.add(GameNightMember(game_night_id=1, user_id=4, status="pending"))
        db.add(UserGame(user_id=4, game_id=1, status="owned"))
        db.commit()
    assert client.delete("/api/game-nights/1/members/4", headers=auth(1)).status_code == 204
    assert selected_ids(factory) == [1, 2, 3]


def test_invitation_response_matches_contract(game_nights):
    client, _ = game_nights
    response = client.post("/api/game-nights/1/members", headers=auth(1), json={"user_id": 4})
    assert response.status_code == 201
    assert response.json() == {
        "member": {
            "user": {"id": 4, "name": "Player 4", "bio": None, "avatar_url": None},
            "status": "pending",
        }
    }
    members = client.get("/api/game-nights/1/members", headers=auth(1)).json()["members"]
    assert {"user": {"id": 4, "name": "Player 4", "bio": None, "avatar_url": None},
            "status": "pending"} in members

    schemas = app.openapi()["components"]["schemas"]
    assert schemas["GameNightMemberResponse"]["required"] == ["member"]


def test_timestamps_are_serialized_as_utc(game_nights):
    client, _ = game_nights
    body = {"name": "Late night", "starts_at": "2030-05-01T18:00:00-07:00", "location": "Campus"}
    created = client.post("/api/game-nights", headers=auth(1), json=body)
    assert created.status_code == 201
    night = created.json()["game_night"]
    assert night["starts_at"] == "2030-05-02T01:00:00Z"
    assert night["created_at"].endswith("Z")

    fetched = client.get(f"/api/game-nights/{night['id']}", headers=auth(1)).json()["game_night"]
    assert fetched["starts_at"] == "2030-05-02T01:00:00Z"
    assert fetched["created_at"] == night["created_at"]

    updated = client.put(f"/api/game-nights/{night['id']}", headers=auth(1), json={
        **body, "starts_at": "2030-05-03T09:30:00+02:00",
    })
    assert updated.json()["game_night"]["starts_at"] == "2030-05-03T07:30:00Z"


def test_naive_start_time_is_rejected(game_nights):
    client, _ = game_nights
    body = {"name": "Night", "starts_at": "2030-05-01T18:00:00", "location": "Campus"}
    assert client.post("/api/game-nights", headers=auth(1), json=body).status_code == 422
