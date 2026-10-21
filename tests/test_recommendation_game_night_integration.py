"""End-to-end game-night + recommendation workflow through the real API.

Isolated SQLite, production-like sessions (autoflush disabled), real JWTs.
Game nights, invitations, RSVPs, and selections are created only through the
merged Issue #4 endpoints; only users, friendships, and collections are seeded.
"""

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
from app.models.preference import Preference
from app.models.user import User
from app.models.user_game import UserGame


HOST, ACCEPTED, PENDING = 1, 2, 3
# Game 1: host. Game 2: accepted friend only. Game 3: pending friend only.
# Game 4: both friends. Game 5: host, but needs at least three players.
OWNERSHIP = [
    (HOST, 1), (ACCEPTED, 2), (PENDING, 3), (ACCEPTED, 4), (PENDING, 4), (HOST, 5),
]


@pytest.fixture
def workflow(auth_environment):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[
        User.__table__, Game.__table__, UserGame.__table__, Preference.__table__,
        GameNight.__table__, GameNightMember.__table__, GameNightGame.__table__,
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
            for i in (HOST, ACCEPTED, PENDING)
        ])
        db.add_all([
            Game(id=i, name=f"Game {i}", minimum_players=3 if i == 5 else 2,
                 maximum_players=6, playtime=60, difficulty="Medium", categories=["Strategy"])
            for i in range(1, 6)
        ])
        db.flush()
        db.add_all([
            Friend(requester_id=HOST, receiver_id=i, status="accepted") for i in (ACCEPTED, PENDING)
        ])
        db.add_all([UserGame(user_id=u, game_id=g, status="owned") for u, g in OWNERSHIP])
        db.commit()

    def override_db():
        with factory() as db:
            yield db

    previous = app.dependency_overrides.copy()
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        engine.dispose()


def auth(user_id):
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def create_night(client):
    response = client.post("/api/game-nights", headers=auth(HOST), json={
        "name": "Friday", "starts_at": "2030-05-01T18:00:00Z", "location": "Campus",
        "invitee_ids": [ACCEPTED, PENDING],
    })
    assert response.status_code == 201, response.text
    night_id = response.json()["game_night"]["id"]
    assert rsvp(client, night_id, ACCEPTED, "accepted").status_code == 200
    return night_id


def rsvp(client, night_id, user_id, status):
    return client.put(f"/api/game-nights/{night_id}/rsvp", headers=auth(user_id),
                      json={"status": status})


def recommend(client, night_id, user_id=HOST):
    return client.post("/api/recommendations", headers=auth(user_id), json={
        "mode": "game_night", "game_night_id": night_id, "max_playtime": 60,
    })


def recommended(client, night_id, user_id=HOST):
    response = recommend(client, night_id, user_id)
    assert response.status_code == 200, response.text
    return {r["game"]["id"]: [o["id"] for o in r["owners"]]
            for r in response.json()["recommendations"]}


def selected(client, night_id):
    games = client.get(f"/api/game-nights/{night_id}/games", headers=auth(HOST)).json()["games"]
    return sorted(g["game"]["id"] for g in games if g["selected"])


def select(client, night_id, game_id, user_id=HOST):
    return client.post(f"/api/game-nights/{night_id}/games", headers=auth(user_id),
                       json={"game_id": game_id})


def test_recommendations_use_host_and_accepted_attendees_only(workflow):
    client = workflow
    night_id = create_night(client)
    members = client.get(f"/api/game-nights/{night_id}/members", headers=auth(HOST)).json()["members"]
    assert {(m["user"]["id"], m["status"]) for m in members} == {
        (HOST, "accepted"), (ACCEPTED, "accepted"), (PENDING, "pending"),
    }

    # Game 3 belongs only to the pending invitee; game 4's pending co-owner is hidden.
    # Game 5 needs three players, so the default player_count of two excludes it.
    assert recommended(client, night_id) == {1: [HOST], 2: [ACCEPTED], 4: [ACCEPTED]}
    reasons = [r["reason"] for r in recommend(client, night_id).json()["recommendations"]]
    assert all(reason.startswith("Supports 2 players") for reason in reasons)


def test_pending_invitee_gains_access_after_accepting(workflow):
    client = workflow
    night_id = create_night(client)
    assert recommend(client, night_id, PENDING).status_code == 403

    assert rsvp(client, night_id, PENDING, "accepted").json() == {
        "game_night_id": night_id, "status": "accepted",
    }
    # Three participants now: game 5 qualifies and both friends own game 4.
    expected = {1: [HOST], 2: [ACCEPTED], 3: [PENDING], 4: [ACCEPTED, PENDING], 5: [HOST]}
    assert recommended(client, night_id, PENDING) == expected
    assert recommended(client, night_id, ACCEPTED) == expected


def test_host_adds_recommended_game_to_existing_night(workflow):
    client = workflow
    night_id = create_night(client)
    top = recommend(client, night_id).json()["recommendations"][0]["game"]["id"]

    response = select(client, night_id, top)
    assert response.status_code == 201
    assert response.json() == {"game_id": top, "game_night_id": night_id}
    assert select(client, night_id, top).status_code == 409
    assert selected(client, night_id) == [top]

    # Accepted attendees may request recommendations but not select games.
    assert recommend(client, night_id, ACCEPTED).status_code == 200
    assert select(client, night_id, 2, ACCEPTED).status_code == 403
    assert selected(client, night_id) == [top]


def test_declining_attendee_is_excluded_and_their_selections_cleaned_up(workflow):
    client = workflow
    night_id = create_night(client)
    assert rsvp(client, night_id, PENDING, "accepted").status_code == 200
    for game_id in (2, 4):
        assert select(client, night_id, game_id).status_code == 201

    assert rsvp(client, night_id, ACCEPTED, "declined").status_code == 200
    # Game 2 lost its only eligible owner; game 4 is still owned by an attendee.
    assert selected(client, night_id) == [4]
    assert recommended(client, night_id) == {1: [HOST], 3: [PENDING], 4: [PENDING]}
    assert recommend(client, night_id, ACCEPTED).status_code == 403


def test_leaving_attendee_is_excluded_and_their_selections_cleaned_up(workflow):
    client = workflow
    night_id = create_night(client)
    assert rsvp(client, night_id, PENDING, "accepted").status_code == 200
    for game_id in (2, 3, 4):
        assert select(client, night_id, game_id).status_code == 201

    assert client.delete(f"/api/game-nights/{night_id}/members/{PENDING}",
                         headers=auth(PENDING)).status_code == 204
    # Game 3 lost its only owner; game 4 remains owned by the accepted friend.
    assert selected(client, night_id) == [2, 4]
    assert recommended(client, night_id) == {1: [HOST], 2: [ACCEPTED], 4: [ACCEPTED]}
    assert recommend(client, night_id, PENDING).status_code == 403

    assert client.delete(f"/api/game-nights/{night_id}/members/{ACCEPTED}",
                         headers=auth(HOST)).status_code == 204
    assert selected(client, night_id) == []
    # Only the host remains: the default player_count of one is below every minimum.
    assert recommended(client, night_id) == {}
