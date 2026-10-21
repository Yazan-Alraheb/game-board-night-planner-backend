
import importlib
import pkgutil

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import models
from app.core.database import Base, get_db
from app.main import app
from app.models.game import Game
from app.models.user_game import UserGame

from fastapi import Depends, Header, HTTPException

from app.api.dependencies import get_current_user
from app.models.user import User

for module in pkgutil.iter_modules(models.__path__):
    importlib.import_module(f"app.models.{module.name}")


@pytest.fixture
def db_client(auth_environment):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, connection_record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(
        engine,
        tables=[
            Base.metadata.tables["users"],
            Base.metadata.tables["games"],
            Base.metadata.tables["user_games"],
        ],
    )

    session_factory = sessionmaker(bind=engine)

    def override_get_db():
        with session_factory() as db:
            yield db

    def override_get_current_user(
        x_test_user_id: int = Header(...),
        db=Depends(get_db),
    ):
        user = db.get(User, x_test_user_id)

        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Test user not found",
            )

        return user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    try:
        with TestClient(app) as client:
            yield client, session_factory
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def create_user(session_factory, name, email):
    with session_factory() as db:
        user = User(
            name=name,
            email=email,
            password_hash="test-only-password-hash",
        )

        db.add(user)
        db.commit()
        db.refresh(user)

        return user.id, {
            "X-Test-User-ID": str(user.id)
        }


def create_game(session_factory, name):
    with session_factory() as db:
        game = Game(
            name=name,
            description=f"Test game: {name}",
            minimum_players=2,
            maximum_players=6,
            playtime=30,
            difficulty="Easy",
            categories=["Party"],
        )

        db.add(game)
        db.commit()
        db.refresh(game)

        return game.id


def test_collection_filters_by_user_and_status(db_client):
    client, session_factory = db_client

    bob_id, bob_headers = create_user(
        session_factory, "Bob", "bob@example.com"
    )
    alice_id, alice_headers = create_user(
        session_factory, "Alice", "alice@example.com"
    )

    catan_id = create_game(session_factory, "Catan")
    flip7_id = create_game(session_factory, "Flip 7")

    # Bob owns Catan and has Flip 7 on his wishlist
    response = client.post(
        f"/api/users/{bob_id}/collection",
        headers=bob_headers,
        json={"game_id": catan_id, "status": "owned"},
    )
    assert response.status_code == 201

    response = client.post(
        f"/api/users/{bob_id}/collection",
        headers=bob_headers,
        json={"game_id": flip7_id, "status": "wishlist"},
    )
    assert response.status_code == 201

    # Alice only owns Flip 7
    response = client.post(
        f"/api/users/{alice_id}/collection",
        headers=alice_headers,
        json={"game_id": flip7_id, "status": "owned"},
    )
    assert response.status_code == 201

    # Verify Bob's complete collection
    response = client.get(
        f"/api/users/{bob_id}/collection",
        headers=bob_headers,
    )

    assert response.status_code == 200
    assert {
        (item["game"]["id"], item["status"])
        for item in response.json()["games"]
    } == {
        (catan_id, "owned"),
        (flip7_id, "wishlist"),
    }

    # Verify owned status filtering
    response = client.get(
        f"/api/users/{bob_id}/collection",
        params={"status": "owned"},
        headers=bob_headers,
    )

    assert response.status_code == 200
    assert [item["game"]["id"] for item in response.json()["games"]] == [
        catan_id
    ]

    # Verify wishlist status filtering
    response = client.get(
        f"/api/users/{bob_id}/collection",
        params={"status": "wishlist"},
        headers=bob_headers,
    )

    assert response.status_code == 200
    assert [item["game"]["id"] for item in response.json()["games"]] == [
        flip7_id
    ]

    # Bob cannot access Alice's collection
    response = client.get(
        f"/api/users/{alice_id}/collection",
        headers=bob_headers,
    )

    assert response.status_code == 403

    # Alice collection only contains her game
    response = client.get(
        f"/api/users/{alice_id}/collection",
        headers=alice_headers,
    )

    assert response.status_code == 200
    assert [item["game"]["id"] for item in response.json()["games"]] == [
        flip7_id
    ]


def test_collection_duplicate_returns_409(db_client):
    client, session_factory = db_client

    user_id, headers = create_user(
        session_factory, "Bob", "bob@example.com"
    )
    game_id = create_game(session_factory, "Flip 7")

    path = f"/api/users/{user_id}/collection"
    payload = {"game_id": game_id, "status": "owned"}

    first = client.post(path, json=payload, headers=headers)
    second = client.post(path, json=payload, headers=headers)

    assert first.status_code == 201
    assert second.status_code == 409

    # Check that only one database row exists
    with session_factory() as db:
        count = db.scalar(
            select(func.count())
            .select_from(UserGame)
            .where(
                UserGame.user_id == user_id,
                UserGame.game_id == game_id,
            )
        )

    assert count == 1


def test_collection_update_and_delete_persist(db_client):
    client, session_factory = db_client

    user_id, headers = create_user(
        session_factory, "Bob", "bob@example.com"
    )
    game_id = create_game(session_factory, "Catan")

    collection_path = f"/api/users/{user_id}/collection"
    game_path = f"{collection_path}/{game_id}"

    # Add the game
    response = client.post(
        collection_path,
        headers=headers,
        json={"game_id": game_id, "status": "owned"},
    )
    assert response.status_code == 201

    # Update owned -> wishlist
    response = client.put(
        game_path,
        headers=headers,
        json={"status": "wishlist"},
    )
    assert response.status_code == 200

    # Confirm change was saved
    with session_factory() as db:
        entry = db.get(UserGame, (user_id, game_id))
        assert entry is not None
        assert entry.status == "wishlist"

    # Delete the game
    response = client.delete(game_path, headers=headers)
    assert response.status_code == 204

    # Confirm the record was actually deleted
    with session_factory() as db:
        assert db.get(UserGame, (user_id, game_id)) is None


    response = client.delete(game_path, headers=headers)
    assert response.status_code == 404


def test_collection_database_prevents_duplicates(db_client):
    client, session_factory = db_client

    user_id, _ = create_user(
        session_factory, "Bob", "bob@example.com"
    )
    game_id = create_game(session_factory, "Catan")

    with session_factory() as db:
        db.add(
            UserGame(
                user_id=user_id,
                game_id=game_id,
                status="owned",
            )
        )
        db.commit()

    with session_factory() as db:
        db.add(
            UserGame(
                user_id=user_id,
                game_id=game_id,
                status="wishlist",
            )
        )

        with pytest.raises(IntegrityError):
            db.commit()

        db.rollback()

    # The original record must remain unchanged
    with session_factory() as db:
        entry = db.get(UserGame, (user_id, game_id))

        assert entry is not None
        assert entry.status == "owned"


@pytest.mark.parametrize(
    "game_id",
    [0, -1, 2_147_483_648, 999999999999999],
)
def test_post_rejects_invalid_game_ids(db_client, game_id):
    client, session_factory = db_client

    user_id, headers = create_user(
        session_factory, "Bob", "bob@example.com"
    )

    response = client.post(
        f"/api/users/{user_id}/collection",
        headers=headers,
        json={"game_id": game_id, "status": "owned"},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "game_id",
    [0, -1, 2_147_483_648, 999999999999999],
)
def test_delete_rejects_invalid_game_ids(db_client, game_id):
    client, session_factory = db_client

    user_id, headers = create_user(
        session_factory, "Bob", "bob@example.com"
    )

    response = client.delete(
        f"/api/users/{user_id}/collection/{game_id}",
        headers=headers,
    )

    assert response.status_code == 422
