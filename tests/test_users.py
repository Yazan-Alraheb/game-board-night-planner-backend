from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.main import app
from app.models.user import User
from app.models.preference import Preference


pytestmark = pytest.mark.usefixtures("auth_environment")


def test_get_user_returns_public_profile():
    mock_db = MagicMock(spec=Session)

    mock_user = User(
        id=42,
        name="Player",
        email="player@example.com",
        password_hash="secret-hash",
        bio="I love strategy games!",
        avatar_url=None,
    )

    mock_db.get.return_value = mock_user

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: mock_user

    try:
        with TestClient(app) as client:
            response = client.get("/api/users/42")

        assert response.status_code == 200
        assert response.json() == {
            "user": {
                "id": 42,
                "name": "Player",
                "bio": "I love strategy games!",
                "avatar_url": None,
            }
        }

        mock_db.get.assert_called_once_with(User, 42)

    finally:
        app.dependency_overrides.clear()


def test_get_user_not_found():
    mock_db = MagicMock(spec=Session)
    mock_db.get.return_value = None

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: User(
        id=42,
        name="Player",
        email="player@example.com",
    )

    try:
        with TestClient(app) as client:
            response = client.get("/api/users/999")

        assert response.status_code == 404
        assert response.json() == {"detail": "User not found"}
        mock_db.get.assert_called_once_with(User, 999)

    finally:
        app.dependency_overrides.clear()


def test_update_user_success():
    mock_db = MagicMock(spec=Session)

    mock_user = User(
        id=42,
        name="Player",
        email="player@example.com",
        password_hash="test-hash",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        bio=None,
        avatar_url=None,
    )

    mock_db.get.return_value = mock_user

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: mock_user

    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/users/42",
                json={
                    "name": "Player One",
                    "bio": "I love strategy games!",
                    "avatar_url": None,
                },
            )

        assert response.status_code == 200

        assert response.json() == {
            "user": {
                "id": 42,
                "email": "player@example.com",
                "created_at": "2026-01-01T00:00:00Z",
                "name": "Player One",
                "bio": "I love strategy games!",
                "avatar_url": None,
            }
        }

        mock_db.get.assert_called_once_with(User, 42)
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once_with(mock_user)

    finally:
        app.dependency_overrides.clear()


def test_update_user_forbidden():
    mock_db = MagicMock(spec=Session)

    current_user = User(
        id=42,
        name="Player",
        email="player@example.com",
        password_hash="test-hash",
    )

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: current_user

    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/users/99",
                json={
                    "name": "New Name",
                    "bio": "Changed biography",
                    "avatar_url": None,
                },
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "You can only update your own profile"
        }

        mock_db.get.assert_not_called()
        mock_db.commit.assert_not_called()

    finally:
        app.dependency_overrides.clear()


def test_update_user_not_found():
    mock_db = MagicMock(spec=Session)
    mock_db.get.return_value = None

    current_user = User(
        id=42,
        name="Player",
        email="player@example.com",
        password_hash="test-hash",
    )

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: current_user

    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/users/42",
                json={
                    "name": "Updated Player",
                    "bio": "New biography",
                    "avatar_url": None,
                },
            )

        assert response.status_code == 404
        assert response.json() == {"detail": "User not found"}

        mock_db.get.assert_called_once_with(User, 42)
        mock_db.commit.assert_not_called()
        mock_db.refresh.assert_not_called()

    finally:
        app.dependency_overrides.clear()


def test_get_user_preferences_success():
    mock_db = MagicMock(spec=Session)

    current_user = User(
        id=42,
        name="Player",
        email="player@example.com",
        password_hash="test-hash",
    )

    mock_preferences = Preference(
        id=1,
        user_id=42,
        favorite_categories=["Strategy", "Cooperative"],
        disliked_categories=["Party"],
        preferred_difficulty="Medium",
        preferred_playtime=60,
    )

    mock_db.query.return_value.filter.return_value.first.return_value = (
        mock_preferences
    )

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: current_user

    try:
        with TestClient(app) as client:
            response = client.get("/api/users/42/preferences")

        assert response.status_code == 200
        assert response.json() == {
            "preferences": {
                "id": 1,
                "user_id": 42,
                "favorite_categories": ["Strategy", "Cooperative"],
                "disliked_categories": ["Party"],
                "preferred_difficulty": "Medium",
                "preferred_playtime": 60,
            }
        }

        mock_db.query.assert_called_once_with(Preference)

    finally:
        app.dependency_overrides.clear()


def test_get_user_preferences_forbidden():
    mock_db = MagicMock(spec=Session)

    current_user = User(
        id=42,
        name="Player",
        email="player@example.com",
        password_hash="test-hash",
    )

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: current_user

    try:
        with TestClient(app) as client:
            response = client.get("/api/users/99/preferences")

        assert response.status_code == 403
        assert response.json() == {
            "detail": "You can only view your own preferences"
        }

        mock_db.query.assert_not_called()

    finally:
        app.dependency_overrides.clear()


def test_get_user_preferences_not_found():
    mock_db = MagicMock(spec=Session)
    mock_db.query.return_value.filter.return_value.first.return_value = None

    current_user = User(
        id=42,
        name="Player",
        email="player@example.com",
        password_hash="test-hash",
    )

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: current_user

    try:
        with TestClient(app) as client:
            response = client.get("/api/users/42/preferences")

        assert response.status_code == 404
        assert response.json() == {"detail": "Preferences not found"}

        mock_db.query.assert_called_once_with(Preference)
        mock_db.commit.assert_not_called()

    finally:
        app.dependency_overrides.clear()


def test_update_existing_preferences():
    mock_db = MagicMock(spec=Session)

    current_user = User(
        id=42,
        name="Player",
        email="player@example.com",
        password_hash="test-hash",
    )

    existing_preferences = Preference(
        id=1,
        user_id=42,
        favorite_categories=["Party"],
        disliked_categories=[],
        preferred_difficulty="Easy",
        preferred_playtime=30,
    )

    mock_db.query.return_value.filter.return_value.first.return_value = (
        existing_preferences
    )

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: current_user

    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/users/42/preferences",
                json={
                    "favorite_categories": ["Strategy", "Cooperative"],
                    "disliked_categories": ["Party"],
                    "preferred_difficulty": "Medium",
                    "preferred_playtime": 60,
                },
            )

        assert response.status_code == 200
        assert response.json() == {
            "preferences": {
                "id": 1,
                "user_id": 42,
                "favorite_categories": ["Strategy", "Cooperative"],
                "disliked_categories": ["Party"],
                "preferred_difficulty": "Medium",
                "preferred_playtime": 60,
            }
        }

        mock_db.add.assert_not_called()
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once_with(existing_preferences)

    finally:
        app.dependency_overrides.clear()


def test_create_user_preferences():
    mock_db = MagicMock(spec=Session)

    current_user = User(
        id=42,
        name="Player",
        email="player@example.com",
        password_hash="test-hash",
    )

    # Simulate a user who has no saved preferences
    mock_db.query.return_value.filter.return_value.first.return_value = None

    # Simulate the database assigning an ID when the record is saved
    def assign_preference_id():
        added_preferences = mock_db.add.call_args.args[0]
        added_preferences.id = 1

    mock_db.commit.side_effect = assign_preference_id

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: current_user

    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/users/42/preferences",
                json={
                    "favorite_categories": ["Strategy", "Cooperative"],
                    "disliked_categories": [],
                    "preferred_difficulty": "Medium",
                    "preferred_playtime": 60,
                },
            )

        assert response.status_code == 200
        assert response.json() == {
            "preferences": {
                "id": 1,
                "user_id": 42,
                "favorite_categories": ["Strategy", "Cooperative"],
                "disliked_categories": [],
                "preferred_difficulty": "Medium",
                "preferred_playtime": 60,
            }
        }

        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()

        created_preferences = mock_db.add.call_args.args[0]
        assert isinstance(created_preferences, Preference)
        assert created_preferences.user_id == 42
        mock_db.refresh.assert_called_once_with(created_preferences)

    finally:
        app.dependency_overrides.clear()


def test_update_user_preferences_forbidden():
    mock_db = MagicMock(spec=Session)

    current_user = User(
        id=42,
        name="Player",
        email="player@example.com",
        password_hash="test-hash",
    )

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: current_user

    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/users/99/preferences",
                json={
                    "favorite_categories": ["Strategy"],
                    "disliked_categories": ["Party"],
                    "preferred_difficulty": "Medium",
                    "preferred_playtime": 60,
                },
            )

        assert response.status_code == 403
        assert response.json() == {
            "detail": "You can only update your own preferences"
        }

        mock_db.query.assert_not_called()
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "invalid_data",
    [
        {
            "favorite_categories": ["Strategy"],
            "disliked_categories": [],
            "preferred_difficulty": "Impossible",
            "preferred_playtime": 60,
        },
        {
            "favorite_categories": ["Strategy"],
            "disliked_categories": [],
            "preferred_difficulty": "Medium",
            "preferred_playtime": -30,
        },
        {
            "favorite_categories": "Strategy",
            "disliked_categories": [],
        },
        {
            "favorite_categories": ["Strategy"],
        },
        {
            "favorite_categories": ["Strategy"],
            "disliked_categories": [123],
        },
    ],
)
def test_update_user_preferences_invalid_data(invalid_data):
    mock_db = MagicMock(spec=Session)

    current_user = User(
        id=42,
        name="Player",
        email="player@example.com",
        password_hash="test-hash",
    )

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: current_user

    try:
        with TestClient(app) as client:
            response = client.put(
                "/api/users/42/preferences",
                json=invalid_data,
            )

        assert response.status_code == 422

        mock_db.query.assert_not_called()
        mock_db.add.assert_not_called()
        mock_db.commit.assert_not_called()

    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    "method, url, request_data",
    [
        ("GET", "/api/users/42", None),
        (
            "PUT",
            "/api/users/42",
            {"name": "Updated Player"},
        ),
        ("GET", "/api/users/42/preferences", None),
        (
            "PUT",
            "/api/users/42/preferences",
            {
                "favorite_categories": ["Strategy"],
                "disliked_categories": [],
            },
        ),
    ],
)
def test_user_endpoints_require_authentication(method, url, request_data):
    mock_db = MagicMock(spec=Session)

    # Mock the database, but NOT authentication.
    app.dependency_overrides[get_db] = lambda: mock_db

    try:
        with TestClient(app) as client:
            response = client.request(
                method,
                url,
                json=request_data,
            )

        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert response.json() == {
            "detail": "Could not validate credentials"
        }

        mock_db.get.assert_not_called()
        mock_db.query.assert_not_called()
        mock_db.commit.assert_not_called()

    finally:
        app.dependency_overrides.clear()


def test_update_user_rolls_back_on_commit_failure():
    mock_db = MagicMock(spec=Session)

    current_user = User(
        id=42,
        name="Player",
        email="player@example.com",
        password_hash="test-hash",
    )

    mock_db.get.return_value = current_user
    mock_db.commit.side_effect = SQLAlchemyError("Database error")

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: current_user

    try:
        with TestClient(app) as client:
            with pytest.raises(SQLAlchemyError, match="Database error"):
                client.put(
                    "/api/users/42",
                    json={
                        "name": "Updated Player",
                        "bio": None,
                        "avatar_url": None,
                    },
                )

        mock_db.commit.assert_called_once()
        mock_db.rollback.assert_called_once()
        mock_db.refresh.assert_not_called()

    finally:
        app.dependency_overrides.clear()


def test_update_preferences_rolls_back_on_commit_failure():
    mock_db = MagicMock(spec=Session)

    current_user = User(
        id=42,
        name="Player",
        email="player@example.com",
        password_hash="test-hash",
    )

    existing_preferences = Preference(
        id=1,
        user_id=42,
        favorite_categories=["Party"],
        disliked_categories=[],
        preferred_difficulty="Easy",
        preferred_playtime=30,
    )

    mock_db.query.return_value.filter.return_value.first.return_value = (
        existing_preferences
    )
    mock_db.commit.side_effect = SQLAlchemyError("Database error")

    app.dependency_overrides[get_db] = lambda: mock_db
    app.dependency_overrides[get_current_user] = lambda: current_user

    try:
        with TestClient(app) as client:
            with pytest.raises(SQLAlchemyError, match="Database error"):
                client.put(
                    "/api/users/42/preferences",
                    json={
                        "favorite_categories": ["Strategy"],
                        "disliked_categories": ["Party"],
                        "preferred_difficulty": "Medium",
                        "preferred_playtime": 60,
                    },
                )

        mock_db.add.assert_not_called()
        mock_db.commit.assert_called_once()
        mock_db.rollback.assert_called_once()
        mock_db.refresh.assert_not_called()

    finally:
        app.dependency_overrides.clear()

# Mocked unit tests: these simulate the loser of an insert race; no real
# PostgreSQL connections or concurrent transactions are exercised here.
def preference_unique_error(sqlstate="23505", table="preferences",
                            constraint="preferences_user_id_key"):
    original = Exception("simulated PostgreSQL constraint failure")
    original.sqlstate = sqlstate
    original.diag = SimpleNamespace(table_name=table, constraint_name=constraint)
    return IntegrityError("INSERT", {}, original)


def call_preferences_update(db):
    from app.api.v1.users import update_user_preferences
    from app.schemas.preference import PreferenceUpdate

    return update_user_preferences(
        id=42,
        preferences_data=PreferenceUpdate(
            favorite_categories=["Strategy"], disliked_categories=[],
            preferred_difficulty="Hard", preferred_playtime=90,
        ),
        db=db,
        current_user=User(id=42),
    )


def test_preferences_insert_conflict_retries_after_rollback():
    db = MagicMock(spec=Session)
    winner = Preference(id=7, user_id=42, favorite_categories=["Party"])
    db.query.return_value.filter.return_value.first.side_effect = [None, winner]
    db.commit.side_effect = [preference_unique_error(), None]

    # Inspect the session state at the second query, before loading the winner.
    original_query = db.query.return_value

    def query_after_rollback(*args):
        if db.query.call_count == 2:
            db.rollback.assert_called_once()
        return original_query

    db.query.side_effect = query_after_rollback

    result = call_preferences_update(db)

    assert result == {"preferences": winner}
    assert winner.favorite_categories == ["Strategy"]
    assert winner.disliked_categories == []
    assert winner.preferred_difficulty == "Hard"
    assert winner.preferred_playtime == 90
    db.add.assert_called_once()
    assert db.commit.call_count == 2
    db.rollback.assert_called_once()
    db.refresh.assert_called_once_with(winner)


@pytest.mark.parametrize("error", [
    preference_unique_error(sqlstate="23503"),
    preference_unique_error(constraint="preferences_pkey"),
    preference_unique_error(table="other_table"),
    SQLAlchemyError("unrelated failure"),
])
def test_preferences_unrelated_insert_errors_propagate(error):
    db = MagicMock(spec=Session)
    db.query.return_value.filter.return_value.first.return_value = None
    db.commit.side_effect = error

    with pytest.raises(type(error)) as caught:
        call_preferences_update(db)

    assert caught.value is error
    db.rollback.assert_called_once()
    db.commit.assert_called_once()
    db.query.assert_called_once()
    db.refresh.assert_not_called()


@pytest.mark.parametrize("missing_winner", [False, True])
def test_preferences_conflict_retry_failure_propagates(missing_winner):
    db = MagicMock(spec=Session)
    winner = None if missing_winner else Preference(id=7, user_id=42)
    db.query.return_value.filter.return_value.first.side_effect = [None, winner]
    conflict = preference_unique_error()
    failure = SQLAlchemyError("retry failed")
    db.commit.side_effect = [conflict, failure]

    with pytest.raises(SQLAlchemyError) as caught:
        call_preferences_update(db)

    assert caught.value is (conflict if missing_winner else failure)
    assert db.rollback.call_count == 2
    assert db.commit.call_count == (1 if missing_winner else 2)
    db.refresh.assert_not_called()


def test_preferences_existing_row_integrity_error_is_not_retried():
    db = MagicMock(spec=Session)
    db.query.return_value.filter.return_value.first.return_value = Preference(
        id=7, user_id=42,
    )
    error = preference_unique_error()
    db.commit.side_effect = error

    with pytest.raises(IntegrityError) as caught:
        call_preferences_update(db)

    assert caught.value is error
    db.commit.assert_called_once()
    db.rollback.assert_called_once()
    db.query.assert_called_once()


@pytest.fixture
def authenticated_users_client():
    db = MagicMock(spec=Session)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: User(id=42)
    try:
        with TestClient(app) as client:
            yield client, db
    finally:
        app.dependency_overrides.clear()


def test_get_another_users_public_profile(authenticated_users_client):
    client, db = authenticated_users_client
    db.get.return_value = User(
        id=99, name="Another player", email="private@example.com",
        password_hash="private-hash", bio="Hello", avatar_url=None,
    )

    response = client.get("/api/users/99")

    assert response.status_code == 200
    assert response.json() == {"user": {
        "id": 99, "name": "Another player", "bio": "Hello", "avatar_url": None,
    }}
    db.get.assert_called_once_with(User, 99)
    db.commit.assert_not_called()


@pytest.mark.parametrize("method,suffix,body", [
    ("GET", "", None),
    ("PUT", "", {"name": "Player"}),
    ("GET", "/preferences", None),
    ("PUT", "/preferences", {
        "favorite_categories": [], "disliked_categories": [],
    }),
])
@pytest.mark.parametrize("path_id", ["not-an-integer", "1.5", "0", "-1"])
def test_user_path_ids(authenticated_users_client, method, suffix, body, path_id):
    client, db = authenticated_users_client
    db.get.return_value = None

    response = client.request(method, f"/api/users/{path_id}{suffix}", json=body)

    if path_id in ("not-an-integer", "1.5"):
        assert response.status_code == 422
        assert response.json()["detail"][0]["loc"] == ["path", "id"]
        db.get.assert_not_called()
    elif method == "GET" and suffix == "":
        assert response.status_code == 404
        db.get.assert_called_once_with(User, int(path_id))
    else:
        assert response.status_code == 403
        db.get.assert_not_called()
    db.query.assert_not_called()
    db.commit.assert_not_called()


# /api/users is now the valid user-search endpoint, covered by friend tests.
@pytest.mark.parametrize("url", ["/api/users//preferences"])
def test_missing_user_path_id(authenticated_users_client, url):
    client, db = authenticated_users_client
    assert client.get(url).status_code == 404
    db.get.assert_not_called()
    db.query.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize("explicit_null", [False, True])
@pytest.mark.parametrize("preferences", [False, True])
def test_put_replaces_optional_fields(authenticated_users_client,
                                     explicit_null, preferences):
    client, db = authenticated_users_client
    if preferences:
        record = Preference(
            id=7, user_id=42, favorite_categories=["Strategy"],
            disliked_categories=["Party"], preferred_difficulty="Hard",
            preferred_playtime=90,
        )
        db.query.return_value.filter.return_value.first.return_value = record
        url = "/api/users/42/preferences"
        body = {"favorite_categories": [], "disliked_categories": []}
        optional_fields = ("preferred_difficulty", "preferred_playtime")
        key = "preferences"
    else:
        record = User(
            id=42, name="Old name", email="owner@example.com",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            bio="Old bio", avatar_url="https://example.com/avatar.png",
        )
        db.get.return_value = record
        url = "/api/users/42"
        body = {"name": "New name"}
        optional_fields = ("bio", "avatar_url")
        key = "user"
    if explicit_null:
        body.update(dict.fromkeys(optional_fields))

    response = client.put(url, json=body)

    assert response.status_code == 200
    for field in optional_fields:
        assert getattr(record, field) is None
        assert response.json()[key][field] is None
    for field, value in body.items():
        assert getattr(record, field) == value
    db.add.assert_not_called()
    db.commit.assert_called_once()
    db.refresh.assert_called_once_with(record)


@pytest.mark.parametrize("body", [{}, {"bio": "Hello"}, {"name": None}])
def test_profile_put_requires_name(authenticated_users_client, body):
    client, db = authenticated_users_client

    response = client.put("/api/users/42", json=body)

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "name"]
    db.get.assert_not_called()
    db.commit.assert_not_called()


def test_users_openapi_documents_expected_responses():
    schema = app.openapi()
    expected = {
        ("/api/users/{id}", "get"): {"200", "401", "404", "422"},
        ("/api/users/{id}", "put"): {"200", "401", "403", "404", "422"},
        ("/api/users/{id}/preferences", "get"): {
            "200", "401", "403", "404", "422",
        },
        ("/api/users/{id}/preferences", "put"): {"200", "401", "403", "422"},
    }
    for (path, method), codes in expected.items():
        operation = schema["paths"][path][method]
        assert operation["tags"] == ["Users / Preferences"]
        assert set(operation["responses"]) == codes
        assert operation["security"] == [{"HTTPBearer": []}]
        assert operation["responses"]["422"]["content"]["application/json"][
            "schema"
        ]["$ref"].endswith("/HTTPValidationError")


@pytest.mark.parametrize("name", ["", " ", "\t\n"])
def test_profile_put_rejects_blank_name(authenticated_users_client, name):
    client, db = authenticated_users_client
    response = client.put("/api/users/42", json={"name": name})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "name"]
    db.commit.assert_not_called()


def test_profile_put_trims_name(authenticated_users_client):
    client, db = authenticated_users_client
    db.get.return_value = User(
        id=42, name="Old", email="owner@example.com",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    response = client.put("/api/users/42", json={"name": "  Player One \t"})
    assert response.status_code == 200
    assert response.json()["user"]["name"] == "Player One"
    assert response.json()["user"]["created_at"] == "2026-01-01T00:00:00Z"
    assert db.get.return_value.name == "Player One"


@pytest.mark.parametrize("suffix,body", [
    ("", {"name": "Player", "email": "changed@example.com"}),
    ("/preferences", {
        "favorite_categories": [], "disliked_categories": [], "user_id": 99,
    }),
])
def test_update_rejects_extra_fields(authenticated_users_client, suffix, body):
    client, db = authenticated_users_client
    response = client.put(f"/api/users/42{suffix}", json=body)
    assert response.status_code == 422
    assert response.json()["detail"][0]["type"] == "extra_forbidden"
    db.get.assert_not_called()
    db.query.assert_not_called()
    db.commit.assert_not_called()


@pytest.mark.parametrize("uri", [
    "https://example.com/avatar.png", "ftp://example.com/avatar.png",
    "urn:example:avatar", "mailto:player@example.com", None,
])
def test_profile_put_accepts_uri(authenticated_users_client, uri):
    client, db = authenticated_users_client
    db.get.return_value = User(
        id=42, name="Player", email="owner@example.com",
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    response = client.put("/api/users/42", json={"name": "Player", "avatar_url": uri})
    assert response.status_code == 200
    assert response.json()["user"]["avatar_url"] == uri
    assert db.get.return_value.avatar_url == uri


@pytest.mark.parametrize("uri", ["", "not a URI", "/relative/avatar.png"])
def test_profile_put_rejects_invalid_uri(authenticated_users_client, uri):
    client, db = authenticated_users_client
    response = client.put("/api/users/42", json={"name": "Player", "avatar_url": uri})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "avatar_url"]
    db.commit.assert_not_called()


def test_user_contract_openapi_constraints():
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["UserResponse"]["properties"]["created_at"]["format"] == "date-time"
    assert "created_at" in schemas["UserResponse"]["required"]
    for model in ("UserUpdate", "PreferenceUpdate"):
        assert schemas[model]["additionalProperties"] is False
    assert schemas["UserUpdate"]["properties"]["name"]["minLength"] == 1
    assert {"type": "string", "format": "uri"} in schemas["UserUpdate"][
        "properties"
    ]["avatar_url"]["anyOf"]
