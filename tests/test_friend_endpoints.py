"""Friendship integration tests with real JWTs and an isolated SQLite database.

SQLite uses min/max in place of PostgreSQL least/greatest. Only a cloned test
schema is adapted; production metadata and its partial index remain unchanged.
PostgreSQL diagnostic failures are simulated explicitly in the unit tests below.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Index, MetaData, create_engine, event, func, select
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateIndex
from sqlalchemy.pool import StaticPool

from app.api.v1.friend_requests import create_friend_request, update_friend_request
from app.api.v1.friends import remove_friend
from app.core.database import get_db
from app.core.security import create_access_token
from app.main import app
from app.models.friend import Friend
from app.models.user import User
from app.schemas.friend import FriendRequestCreate, FriendRequestUpdate


@pytest.fixture
def friendship_db(auth_environment):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    metadata = MetaData()
    User.__table__.to_metadata(metadata)
    table = Friend.__table__.to_metadata(metadata)
    table.indexes.remove(next(i for i in table.indexes if i.name == "uq_active_friend_pair"))
    Index(
        "uq_active_friend_pair",
        func.min(table.c.requester_id, table.c.receiver_id),
        func.max(table.c.requester_id, table.c.receiver_id),
        unique=True, sqlite_where=table.c.status.in_(["pending", "accepted"]),
    )
    metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([
            User(id=i, name=name, email=f"private{i}@example.com",
                 password_hash=f"private-hash-{i}", bio=f"Bio {i}")
            for i, name in [(1, "Alice"), (2, "Bob"), (3, "Carol"), (4, "Bobby")]
        ])
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


def auth(user_id=1):
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


def insert_request(factory, sender=1, recipient=2, status="pending"):
    with factory() as db:
        row = Friend(requester_id=sender, receiver_id=recipient, status=status)
        db.add(row)
        db.commit()
        return row.id


def assert_public(profile):
    assert set(profile) == {"id", "name", "bio", "avatar_url"}
    assert "email" not in profile
    assert "password_hash" not in profile


def test_create_request_persists_sender_and_response(friendship_db):
    client, factory = friendship_db
    response = client.post("/api/friend-requests", headers=auth(), json={"user_id": 2})
    assert response.status_code == 201
    body = response.json()["friend_request"]
    assert set(body) == {"id", "requester_id", "receiver_id", "status", "created_at"}
    assert (body["requester_id"], body["receiver_id"], body["status"]) == (1, 2, "pending")
    assert body["created_at"]
    with factory() as db:
        row = db.get(Friend, body["id"])
        assert (row.requester_id, row.receiver_id, row.status) == (1, 2, "pending")


@pytest.mark.parametrize("recipient,expected", [(1, 400), (999, 404)])
def test_create_invalid_recipient(friendship_db, recipient, expected):
    client, factory = friendship_db
    response = client.post("/api/friend-requests", headers=auth(), json={"user_id": recipient})
    assert response.status_code == expected
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Friend)) == 0


@pytest.mark.parametrize("sender,recipient", [(1, 2), (2, 1)])
@pytest.mark.parametrize("status", ["pending", "accepted"])
def test_duplicate_in_either_direction(friendship_db, sender, recipient, status):
    client, factory = friendship_db
    original = insert_request(factory, sender, recipient, status)
    response = client.post("/api/friend-requests", headers=auth(), json={"user_id": 2})
    assert response.status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Friend)) == 1
        assert db.get(Friend, original).status == status


@pytest.mark.parametrize("sender,recipient", [(1, 2), (2, 1)])
def test_declined_request_allows_new_request(friendship_db, sender, recipient):
    client, factory = friendship_db
    original = insert_request(factory, sender, recipient, "declined")
    response = client.post("/api/friend-requests", headers=auth(), json={"user_id": 2})
    assert response.status_code == 201
    with factory() as db:
        assert db.get(Friend, original).status == "declined"
        assert db.scalar(select(func.count()).select_from(Friend)) == 2


@pytest.mark.parametrize("kind", [None, "incoming", "outgoing"])
def test_list_requests_is_scoped_to_current_user(friendship_db, kind):
    client, factory = friendship_db
    outgoing = insert_request(factory, 1, 2)
    incoming = insert_request(factory, 3, 1)
    insert_request(factory, 2, 4)
    insert_request(factory, 1, 4, "declined")
    insert_request(factory, 2, 3, "accepted")
    response = client.get("/api/friend-requests", headers=auth(),
                          params={} if kind is None else {"type": kind})
    assert response.status_code == 200
    expected = {outgoing, incoming} if kind is None else {incoming if kind == "incoming" else outgoing}
    assert {r["id"] for r in response.json()["requests"]} == expected
    for row in response.json()["requests"]:
        assert row["status"] == "pending"
        assert set(row) == {"id", "requester_id", "receiver_id", "status", "created_at"}


def test_empty_lists(friendship_db):
    client, _ = friendship_db
    for path, key in [("/api/friend-requests", "requests"), ("/api/friends", "friends")]:
        response = client.get(path, headers=auth())
        assert response.status_code == 200
        assert response.json() == {key: []}


@pytest.mark.parametrize("status", ["accepted", "declined"])
def test_recipient_resolves_once(friendship_db, status):
    client, factory = friendship_db
    request_id = insert_request(factory)
    path = f"/api/friend-requests/{request_id}"
    response = client.put(path, headers=auth(2), json={"status": status})
    assert response.status_code == 200
    assert response.json()["friend_request"]["status"] == status
    with factory() as db:
        assert db.get(Friend, request_id).status == status
    for repeated in ("accepted", "declined"):
        assert client.put(path, headers=auth(2), json={"status": repeated}).status_code == 409
    with factory() as db:
        assert db.get(Friend, request_id).status == status
    assert client.get("/api/friend-requests", headers=auth(2)).json() == {"requests": []}


@pytest.mark.parametrize("actor", [1, 3])
def test_sender_and_other_user_cannot_resolve(friendship_db, actor):
    client, factory = friendship_db
    request_id = insert_request(factory)
    response = client.put(f"/api/friend-requests/{request_id}", headers=auth(actor),
                          json={"status": "accepted"})
    assert response.status_code == 403
    with factory() as db:
        assert db.get(Friend, request_id).status == "pending"


def test_missing_request(friendship_db):
    client, _ = friendship_db
    assert client.put("/api/friend-requests/999", headers=auth(),
                      json={"status": "accepted"}).status_code == 404


def test_friends_in_both_directions_are_public(friendship_db):
    client, factory = friendship_db
    insert_request(factory, 1, 2, "accepted")
    insert_request(factory, 3, 1, "accepted")
    insert_request(factory, 1, 4)
    insert_request(factory, 2, 4, "accepted")
    response = client.get("/api/friends", headers=auth())
    assert response.status_code == 200
    assert [u["id"] for u in response.json()["friends"]] == [2, 3]
    for user in response.json()["friends"]:
        assert_public(user)


@pytest.mark.parametrize("sender,recipient", [(1, 2), (2, 1)])
def test_remove_friend_uses_other_users_id(friendship_db, sender, recipient):
    client, factory = friendship_db
    row_id = insert_request(factory, sender, recipient, "accepted")
    unrelated = insert_request(factory, 2, 3, "accepted")
    response = client.delete("/api/friends/2", headers=auth())
    assert response.status_code == 204
    assert response.content == b""
    with factory() as db:
        assert db.get(Friend, row_id) is None
        assert db.get(Friend, unrelated) is not None
    assert client.delete("/api/friends/2", headers=auth()).status_code == 404


@pytest.mark.parametrize("status", ["pending", "declined", "accepted"])
def test_remove_does_not_touch_others_or_unaccepted_requests(friendship_db, status):
    client, factory = friendship_db
    row_id = insert_request(factory, 2, 3, status)
    assert client.delete("/api/friends/3", headers=auth()).status_code == 404
    if status != "accepted":
        assert client.delete("/api/friends/3", headers=auth(2)).status_code == 404
    with factory() as db:
        assert db.get(Friend, row_id).status == status


def test_removed_friend_can_request_again(friendship_db):
    client, factory = friendship_db
    insert_request(factory, 1, 2, "accepted")
    assert client.delete("/api/friends/2", headers=auth()).status_code == 204
    response = client.post("/api/friend-requests", headers=auth(2), json={"user_id": 1})
    assert response.status_code == 201
    assert response.json()["friend_request"]["status"] == "pending"


@pytest.mark.parametrize("search,expected", [
    (None, [2, 4, 3]), (" bOB ", [2, 4]), ("CAR", [3]),
    ("private2@example.com", []), ("no such user", []), ("   ", [2, 4, 3]),
    ("' OR 1=1 --", []),
])
def test_user_search_is_public_and_excludes_self(friendship_db, search, expected):
    client, _ = friendship_db
    response = client.get("/api/users", headers=auth(),
                          params={} if search is None else {"search": search})
    assert response.status_code == 200
    assert [u["id"] for u in response.json()["users"]] == expected
    for user in response.json()["users"]:
        assert_public(user)


ENDPOINTS = [
    ("post", "/api/friend-requests", {"user_id": 2}),
    ("get", "/api/friend-requests", None),
    ("put", "/api/friend-requests/1", {"status": "accepted"}),
    ("delete", "/api/friend-requests/1", None),
    ("get", "/api/friends", None),
    ("delete", "/api/friends/2", None),
    ("get", "/api/users", None),
]


@pytest.mark.parametrize("method,path,body", ENDPOINTS)
@pytest.mark.parametrize("credential", [None, "Bearer invalid", "Basic abc", "missing-user", "expired"])
def test_all_endpoints_require_real_bearer_auth(friendship_db, method, path, body, credential):
    client, _ = friendship_db
    if credential == "missing-user":
        credential = auth(999)["Authorization"]
    elif credential == "expired":
        import jwt
        credential = "Bearer " + jwt.encode(
            {"sub": "1", "iat": 1, "exp": 2},
            "test-only-signing-secret-for-jwt-tests-with-at-least-64-bytes-of-data",
            algorithm="HS256",
        )
    response = client.request(method, path, json=body,
                              headers={} if credential is None else {"Authorization": credential})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Could not validate credentials"}


@pytest.mark.parametrize("body", [{}, {"user_id": 0}, {"user_id": -1},
    {"user_id": "bad"}, {"user_id": None}, {"user_id": 2, "requester_id": 3}])
def test_create_body_validation(friendship_db, body):
    client, _ = friendship_db
    assert client.post("/api/friend-requests", headers=auth(), json=body).status_code == 422


@pytest.mark.parametrize("body", [{}, {"status": "pending"}, {"status": None},
    {"status": "ACCEPTED"}, {"status": "accepted", "receiver_id": 1}])
def test_update_body_validation(friendship_db, body):
    client, _ = friendship_db
    assert client.put("/api/friend-requests/1", headers=auth(), json=body).status_code == 422


@pytest.mark.parametrize("path", ["/api/friend-requests?type=all", "/api/friend-requests?type=",
    "/api/friend-requests?type=Incoming", "/api/friends/not-an-id"])
def test_query_and_path_validation(friendship_db, path):
    client, _ = friendship_db
    method = "delete" if path.startswith("/api/friends/") else "get"
    assert client.request(method, path, headers=auth()).status_code == 422


def test_resolution_path_requires_integer(friendship_db):
    client, _ = friendship_db
    assert client.put("/api/friend-requests/not-an-id", headers=auth(),
                      json={"status": "accepted"}).status_code == 422


@pytest.mark.parametrize("method,path,body", [
    ("post", "/api/friend-requests", {"user_id": 10**100}),
    ("put", f"/api/friend-requests/{10**100}", {"status": "accepted"}),
    ("delete", f"/api/friends/{10**100}", None),
])
def test_oversized_ids_are_rejected_before_database_access(friendship_db, method, path, body):
    client, _ = friendship_db
    # Oversized IDs must fail validation instead of reaching the database.
    assert client.request(method, path, headers=auth(), json=body).status_code == 422


@pytest.mark.parametrize("first_status", ["pending", "accepted"])
def test_test_database_prevents_reverse_active_pair(friendship_db, first_status):
    _, factory = friendship_db
    insert_request(factory, 1, 2, first_status)
    with factory() as db:
        db.add(Friend(requester_id=2, receiver_id=1, status="pending"))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def test_postgresql_index_is_partial_and_direction_independent():
    index = next(i for i in Friend.__table__.indexes if i.name == "uq_active_friend_pair")
    ddl = str(CreateIndex(index).compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))
    assert "CREATE UNIQUE INDEX uq_active_friend_pair" in ddl
    assert "least(requester_id, receiver_id)" in ddl
    assert "greatest(requester_id, receiver_id)" in ddl
    assert "WHERE status IN ('pending', 'accepted')" in ddl


def pg_integrity(sqlstate="23505", constraint="uq_active_friend_pair"):
    original = Exception("simulated PostgreSQL failure")
    original.sqlstate = sqlstate
    original.diag = SimpleNamespace(table_name="friends", constraint_name=constraint)
    return IntegrityError("INSERT", {}, original)


def mock_creation_db(error):
    db = MagicMock(spec=Session)
    db.get.return_value = User(id=2)
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.scalar.return_value = None
    db.commit.side_effect = error
    return db


def test_duplicate_insert_race_rolls_back_before_409():
    db = mock_creation_db(pg_integrity())
    with pytest.raises(HTTPException) as caught:
        create_friend_request(FriendRequestCreate(user_id=2), db, User(id=1))
    assert caught.value.status_code == 409
    db.rollback.assert_called_once()
    db.refresh.assert_not_called()
    assert db.mock_calls.index(next(c for c in db.mock_calls if c[0] == "commit")) < db.mock_calls.index(next(c for c in db.mock_calls if c[0] == "rollback"))


def test_unrelated_integrity_error_is_not_a_duplicate():
    error = pg_integrity("23503", "friends_receiver_id_fkey")
    db = mock_creation_db(error)
    with pytest.raises(IntegrityError) as caught:
        create_friend_request(FriendRequestCreate(user_id=2), db, User(id=1))
    assert caught.value is error
    db.rollback.assert_called_once()


@pytest.mark.parametrize("sqlstate,table,constraint", [
    ("23503", "friends", "uq_active_friend_pair"),
    ("23505", "other_table", "uq_active_friend_pair"),
    ("23505", "friends", "other_unique_index"),
    (None, None, None),
])
def test_only_expected_postgresql_constraint_is_translated(sqlstate, table, constraint):
    error = pg_integrity(sqlstate, constraint)
    error.orig.diag.table_name = table
    db = mock_creation_db(error)
    with pytest.raises(IntegrityError) as caught:
        create_friend_request(FriendRequestCreate(user_id=2), db, User(id=1))
    assert caught.value is error
    db.rollback.assert_called_once()


@pytest.mark.parametrize("operation", ["create", "resolve", "remove"])
def test_database_commit_failures_roll_back(operation):
    error = SQLAlchemyError("simulated commit failure")
    db = mock_creation_db(error)
    if operation == "resolve":
        db.get.return_value = Friend(id=1, requester_id=1, receiver_id=2, status="pending")
        db.execute.return_value.rowcount = 1
    elif operation == "remove":
        db.query.return_value.filter.return_value.first.return_value = Friend(
            id=1, requester_id=1, receiver_id=2, status="accepted")
    with pytest.raises(SQLAlchemyError) as caught:
        if operation == "create":
            create_friend_request(FriendRequestCreate(user_id=2), db, User(id=1))
        elif operation == "resolve":
            update_friend_request(1, FriendRequestUpdate(status="accepted"), db, User(id=2))
        else:
            remove_friend(2, db, User(id=1))
    assert caught.value is error
    db.rollback.assert_called_once()


@pytest.mark.parametrize("first_status,second_status", [
    ("accepted", "declined"), ("declined", "accepted"),
])
def test_stale_resolution_cannot_overwrite_already_resolved_request(
    friendship_db, first_status, second_status,
):
    # Model two requests that both loaded the pending row before either commit.
    _, factory = friendship_db
    request_id = insert_request(factory)
    with factory() as first, factory() as second:
        first_row = first.get(Friend, request_id)
        second_row = second.get(Friend, request_id)
        assert first_row.status == second_row.status == "pending"
        response = update_friend_request(
            request_id, FriendRequestUpdate(status=first_status), first, User(id=2),
        )
        assert response["friend_request"] is first_row
        assert first_row.status == first_status
        with pytest.raises(HTTPException) as caught:
            update_friend_request(
                request_id, FriendRequestUpdate(status=second_status), second, User(id=2),
            )
        assert caught.value.status_code == 409
    with factory() as db:
        assert db.get(Friend, request_id).status == first_status


def test_resolution_update_failure_rolls_back():
    db = MagicMock(spec=Session)
    db.get.return_value = Friend(id=1, requester_id=1, receiver_id=2, status="pending")
    error = SQLAlchemyError("simulated update failure")
    db.execute.side_effect = error
    with pytest.raises(SQLAlchemyError) as caught:
        update_friend_request(1, FriendRequestUpdate(status="accepted"), db, User(id=2))
    assert caught.value is error
    db.rollback.assert_called_once()
    db.commit.assert_not_called()


def test_atomic_resolution_conflict_rolls_back():
    db = MagicMock(spec=Session)
    db.get.return_value = Friend(id=1, requester_id=1, receiver_id=2, status="pending")
    db.execute.return_value.rowcount = 0
    with pytest.raises(HTTPException) as caught:
        update_friend_request(1, FriendRequestUpdate(status="accepted"), db, User(id=2))
    assert caught.value.status_code == 409
    db.rollback.assert_called_once()
    db.commit.assert_not_called()
    db.refresh.assert_not_called()


@pytest.mark.parametrize("method", ["post", "put", "delete"])
@pytest.mark.parametrize("value", [0, -1, 2_147_483_648])
def test_id_bounds_reject_invalid_values_before_business_queries(friendship_db, method, value):
    client, factory = friendship_db
    statements = []
    engine = factory.kw["bind"]

    def record_sql(connection, cursor, statement, parameters, context, executemany):
        statements.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", record_sql)
    try:
        path = "/api/friend-requests" if method != "delete" else "/api/friends"
        if method != "post":
            path += f"/{value}"
        body = {"user_id": value} if method == "post" else {"status": "accepted"}
        response = client.request(method, path, headers=auth(),
                                  json=None if method == "delete" else body)
        assert response.status_code == 422
        # The authentication lookup is allowed; no invalid ID reaches a query.
        assert len(statements) == 1
        assert "users" in statements[0][0]
        assert statements[0][1] == (1,)
    finally:
        event.remove(engine, "before_cursor_execute", record_sql)


@pytest.mark.parametrize("method", ["post", "put", "delete"])
def test_maximum_supported_id_passes_validation(friendship_db, method):
    client, _ = friendship_db
    path = "/api/friend-requests" if method != "delete" else "/api/friends"
    if method != "post":
        path += "/2147483647"
    body = {"user_id": 2_147_483_647} if method == "post" else {"status": "accepted"}
    response = client.request(method, path, headers=auth(),
                              json=None if method == "delete" else body)
    assert response.status_code == 404


@pytest.mark.parametrize("path,method,codes", [
    ("/api/friend-requests", "post", {"201", "400", "401", "404", "409"}),
    ("/api/friend-requests", "get", {"200", "401"}),
    ("/api/friend-requests/{id}", "put", {"200", "401", "403", "404", "409", "422"}),
    ("/api/friend-requests/{id}", "delete", {"204", "401", "403", "404", "409", "422"}),
    ("/api/friends", "get", {"200", "401"}),
    ("/api/friends/{id}", "delete", {"204", "401", "404"}),
    ("/api/users", "get", {"200", "401"}),
])
def test_openapi_documents_contract_errors(path, method, codes):
    schema = app.openapi()
    operation = schema["paths"][path][method]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert codes <= set(operation["responses"])
    for code in codes - {"200", "201", "204", "422"}:
        reference = operation["responses"][code]["content"]["application/json"]["schema"]["$ref"]
        error_schema = schema["components"]["schemas"][reference.rsplit("/", 1)[1]]
        assert error_schema["required"] == ["detail"]
        assert error_schema["properties"]["detail"]["type"] == "string"
        assert error_schema["additionalProperties"] is False
