"""Messaging integration tests: isolated SQLite, real JWT authentication.

PostgreSQL DDL is compiled offline and uniqueness diagnostics are simulated;
these tests do not claim live PostgreSQL concurrency coverage.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Index, MetaData, create_engine, create_mock_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import conversations as routes
from app.core.database import Base, get_db
from app.core.security import create_access_token
from app.main import app
from app.models.conversation import Conversation
from app.models.conversation_member import ConversationMember
from app.models.friend import Friend
from app.models.game_night import GameNight
from app.models.game_night_member import GameNightMember
from app.models.message import Message
from app.models.user import User
from app.schemas.conversation import ConversationCreate
from app.schemas.message import MessageCreate


@pytest.fixture
def chat(auth_environment):
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=[
        User.__table__, GameNight.__table__, GameNightMember.__table__,
        Conversation.__table__, ConversationMember.__table__, Message.__table__,
    ])
    metadata = MetaData()
    User.__table__.to_metadata(metadata)
    table = Friend.__table__.to_metadata(metadata)
    table.indexes.remove(next(i for i in table.indexes if i.name == "uq_active_friend_pair"))
    Index(
        "uq_active_friend_pair", func.min(table.c.requester_id, table.c.receiver_id),
        func.max(table.c.requester_id, table.c.receiver_id), unique=True,
        sqlite_where=table.c.status.in_(["pending", "accepted"]),
    )
    table.create(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all([
            User(id=i, name=f"Player {i}", email=f"private{i}@example.com",
                 password_hash=f"private-hash-{i}", bio=f"Bio {i}")
            for i in range(1, 6)
        ])
        db.flush()
        db.add_all([
            Friend(requester_id=a, receiver_id=b, status="accepted")
            for a, b in [(1, 2), (3, 1), (3, 4), (4, 5)]
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


def create(client, participants=None, kind="private", actor=1, **extra):
    return client.post("/api/conversations", headers=auth(actor), json={
        "participant_ids": [2] if participants is None else participants,
        "type": kind, **extra,
    })


def conversation_id(client, **kwargs):
    response = create(client, **kwargs)
    assert response.status_code == 201, response.text
    return response.json()["conversation"]["id"]


def game_night(factory):
    with factory() as db:
        night = GameNight(
            host_id=1, name="Game night", starts_at=datetime.now(timezone.utc), location="Campus",
        )
        db.add(night)
        db.flush()
        night_id = night.id
        db.add_all([
            GameNightMember(game_night_id=night_id, user_id=2, status="accepted"),
            GameNightMember(game_night_id=night_id, user_id=3, status="pending"),
            GameNightMember(game_night_id=night_id, user_id=4, status="declined"),
        ])
        db.commit()
        return night_id


def assert_public_conversation(body, ids):
    assert set(body) == {"id", "type", "game_night_id", "participants", "created_at"}
    assert [p["id"] for p in body["participants"]] == ids
    for profile in body["participants"]:
        assert set(profile) == {"id", "name", "bio", "avatar_url"}
        assert "email" not in profile and "password_hash" not in profile
    assert "private_user_low_id" not in body and "private_user_high_id" not in body
    assert body["created_at"].endswith("Z")


@pytest.mark.parametrize("participants", [[2], [1, 2]])
def test_private_creation_includes_creator_once_and_is_public(chat, participants):
    client, factory = chat
    response = create(client, participants=participants)
    assert response.status_code == 201
    body = response.json()["conversation"]
    assert_public_conversation(body, [1, 2])
    assert body["type"] == "private" and body["game_night_id"] is None
    with factory() as db:
        row = db.get(Conversation, body["id"])
        assert (row.private_user_low_id, row.private_user_high_id) == (1, 2)
        assert db.scalar(select(func.count()).select_from(ConversationMember)) == 2
    detail = client.get(f"/api/conversations/{body['id']}", headers=auth(2))
    assert detail.status_code == 200
    assert detail.json() == response.json()


def test_group_creation_allows_same_members_again_without_mutual_friendships(chat):
    client, factory = chat
    first = create(client, participants=[2, 3], kind="group")
    second = create(client, participants=[1, 2, 3], kind="group")
    assert first.status_code == second.status_code == 201
    assert first.json()["conversation"]["id"] != second.json()["conversation"]["id"]
    assert_public_conversation(first.json()["conversation"], [1, 2, 3])
    with factory() as db:
        assert all(row.private_user_low_id is None for row in db.scalars(select(Conversation)))


@pytest.mark.parametrize("actor,participants", [(1, [2]), (2, [1])])
def test_private_duplicates_in_both_directions(chat, actor, participants):
    client, factory = chat
    conversation_id(client)
    assert create(client, actor=actor, participants=participants).status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 1
        assert db.scalar(select(func.count()).select_from(ConversationMember)) == 2


@pytest.mark.parametrize("kind,participants,extra", [
    ("private", [1], {}), ("private", [2, 3], {}),
    ("private", [2], {"game_night_id": 1}), ("group", [1], {}),
])
def test_semantically_invalid_composition(chat, kind, participants, extra):
    client, factory = chat
    assert create(client, participants, kind, **extra).status_code == 400
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0


@pytest.mark.parametrize("body", [
    {}, {"participant_ids": [2]}, {"type": "private"},
    {"participant_ids": [], "type": "private"},
    {"participant_ids": [2, 2], "type": "private"},
    {"participant_ids": [0], "type": "private"},
    {"participant_ids": [-1], "type": "private"},
    {"participant_ids": [2_147_483_648], "type": "private"},
    {"participant_ids": [True], "type": "private"},
    {"participant_ids": ["2"], "type": "private"},
    {"participant_ids": None, "type": "private"},
    {"participant_ids": [2], "type": "other"},
    {"participant_ids": [2], "type": "group", "game_night_id": None},
    {"participant_ids": [2], "type": "group", "game_night_id": 0},
    {"participant_ids": [2], "type": "group", "game_night_id": 10**100},
    {"participant_ids": [2], "type": "private", "creator_id": 3},
])
def test_conversation_request_validation(chat, body):
    client, _ = chat
    assert client.post("/api/conversations", headers=auth(), json=body).status_code == 422


def test_missing_users_and_game_nights(chat):
    client, factory = chat
    assert create(client, participants=[999]).status_code == 404
    assert create(client, participants=[2], kind="group", game_night_id=999).status_code == 404
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0


def test_conversation_list_is_scoped_and_empty(chat):
    client, _ = chat
    assert client.get("/api/conversations", headers=auth()).json() == {"conversations": []}
    first = conversation_id(client)
    second = conversation_id(client, participants=[3], kind="group")
    conversation_id(client, actor=4, participants=[5])
    response = client.get("/api/conversations", headers=auth())
    assert response.status_code == 200
    assert [c["id"] for c in response.json()["conversations"]] == [second, first]
    assert [c["id"] for c in client.get("/api/conversations", headers=auth(2)).json()["conversations"]] == [first]


def test_game_night_host_creates_once_with_accepted_participants(chat):
    client, factory = chat
    night = game_night(factory)
    response = create(client, participants=[2], kind="group", game_night_id=night)
    assert response.status_code == 201
    assert response.json()["conversation"]["game_night_id"] == night
    assert_public_conversation(response.json()["conversation"], [1, 2])
    assert create(client, participants=[2], kind="group", game_night_id=night).status_code == 409


@pytest.mark.parametrize("actor", [2, 3, 4, 5])
def test_only_host_creates_game_night_conversation(chat, actor):
    client, factory = chat
    night = game_night(factory)
    assert create(client, actor=actor, participants=[1], kind="group", game_night_id=night).status_code == 403


@pytest.mark.parametrize("participant", [3, 4, 5])
def test_game_night_rejects_pending_declined_and_unrelated_users(chat, participant):
    client, factory = chat
    night = game_night(factory)
    assert create(client, participants=[participant], kind="group", game_night_id=night).status_code == 403
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0


@pytest.mark.parametrize("count", [50, 51, 10_000])
def test_participant_array_bounds(chat, count):
    client, factory = chat
    if count == 50:
        with factory() as db:
            db.add_all([
                User(id=i, name=f"Player {i}", email=f"player{i}@example.com", password_hash="test-hash")
                for i in range(6, 51)
            ])
            db.add_all([
                Friend(requester_id=1, receiver_id=i, status="accepted")
                for i in range(4, 51)
            ])
            db.commit()
    response = create(client, participants=list(range(1, count + 1)), kind="group")
    assert response.status_code == (201 if count == 50 else 422), response.text
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == (1 if count == 50 else 0)
        assert db.scalar(select(func.count()).select_from(ConversationMember)) == (50 if count == 50 else 0)
    if count == 50:
        assert {user["id"] for user in response.json()["conversation"]["participants"]} == set(range(1, 51))


def test_new_attendee_is_not_automatically_a_conversation_member(chat):
    client, factory = chat
    night = game_night(factory)
    cid = conversation_id(client, kind="group", game_night_id=night)
    with factory() as db:
        db.get(GameNightMember, (night, 3)).status = "accepted"
        db.commit()
    assert client.get(f"/api/conversations/{cid}", headers=auth(3)).status_code == 403
    assert client.get("/api/conversations", headers=auth(3)).json() == {"conversations": []}
    path = f"/api/conversations/{cid}/messages"
    assert client.get(path, headers=auth(3)).status_code == 403
    assert client.post(path, headers=auth(3), json={"content": "Hello"}).status_code == 403
    with factory() as db:
        assert db.get(ConversationMember, (cid, 3)) is None
        assert db.scalar(select(func.count()).select_from(Message)) == 0


@pytest.mark.parametrize("new_status", ["pending", "declined", "removed"])
def test_former_attendee_loses_all_linked_conversation_access(chat, new_status):
    client, factory = chat
    night = game_night(factory)
    cid = conversation_id(client, kind="group", game_night_id=night)
    assert client.get(f"/api/conversations/{cid}", headers=auth(2)).status_code == 200
    with factory() as db:
        attendee = db.get(GameNightMember, (night, 2))
        if new_status == "removed":
            db.delete(attendee)
        else:
            attendee.status = new_status
        db.commit()
    assert client.get("/api/conversations", headers=auth(2)).json() == {"conversations": []}
    for method, suffix, body in [
        ("get", "", None), ("get", "/messages", None), ("post", "/messages", {"content": "Secret"}),
    ]:
        assert client.request(method, f"/api/conversations/{cid}{suffix}", headers=auth(2), json=body).status_code == 403
    assert client.get(f"/api/conversations/{cid}", headers=auth(1)).status_code == 200
    with factory() as db:
        assert db.get(ConversationMember, (cid, 2)) is not None
        assert db.scalar(select(func.count()).select_from(Message)) == 0


@pytest.mark.parametrize("method,suffix,body", [
    ("get", "", None), ("get", "/messages", None), ("post", "/messages", {"content": "Hello"}),
])
def test_nonparticipants_forbidden_and_missing_conversations_not_found(chat, method, suffix, body):
    client, _ = chat
    cid = conversation_id(client)
    assert client.request(method, f"/api/conversations/{cid}{suffix}", headers=auth(3), json=body).status_code == 403
    assert client.request(method, f"/api/conversations/999{suffix}", headers=auth(3), json=body).status_code == 404


CHAT_ENDPOINTS = [
    ("get", "/api/conversations", None),
    ("post", "/api/conversations", {"participant_ids": [2], "type": "private"}),
    ("get", "/api/conversations/1", None),
    ("get", "/api/conversations/1/messages", None),
    ("post", "/api/conversations/1/messages", {"content": "Hello"}),
]


@pytest.mark.parametrize("method,path,body", CHAT_ENDPOINTS)
@pytest.mark.parametrize("credentials", [None, "Bearer garbage", "Basic abc", "missing-user"])
def test_every_chat_endpoint_uses_real_authentication(chat, method, path, body, credentials):
    client, _ = chat
    headers = {} if credentials is None else {"Authorization": credentials}
    if credentials == "missing-user":
        headers = auth(999)
    response = client.request(method, path, headers=headers, json=body)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "Could not validate credentials"}


@pytest.mark.parametrize("content", ["Hello", " \n  Hello\tworld\n ", "x" * 2000, "🙂" * 2000])
def test_message_persists_authenticated_sender_and_preserves_formatting(chat, content):
    client, factory = chat
    cid = conversation_id(client)
    response = client.post(f"/api/conversations/{cid}/messages", headers=auth(2), json={"content": content})
    assert response.status_code == 201
    body = response.json()["message"]
    assert set(body) == {"id", "conversation_id", "user_id", "content", "created_at"}
    assert (body["conversation_id"], body["user_id"], body["content"]) == (cid, 2, content)
    assert body["created_at"].endswith("Z")
    with factory() as db:
        stored = db.get(Message, body["id"])
        assert stored.content == content and stored.user_id == 2
        assert stored.created_at.tzinfo == timezone.utc


@pytest.mark.parametrize("body", [
    {}, {"content": ""}, {"content": "   "}, {"content": "\t\n\r"}, {"content": "\u2003\u00a0"},
    {"content": "x" * 2001}, {"content": None}, {"content": 42},
    {"content": "\x00"}, {"content": "Hello\x00world"}, {"content": "Hello\x00"},
    {"content": "Hello", "user_id": 3}, {"content": "Hello", "conversation_id": 999},
])
def test_message_request_validation(chat, body):
    client, factory = chat
    cid = conversation_id(client)
    assert client.post(f"/api/conversations/{cid}/messages", headers=auth(), json=body).status_code == 422
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0


def seed_messages(factory, cid, timestamps):
    with factory() as db:
        rows = [Message(conversation_id=cid, user_id=1, content=f"Message {i}", created_at=timestamp)
                for i, timestamp in enumerate(timestamps)]
        db.add_all(rows)
        db.commit()
        return [row.id for row in rows]


def test_messages_are_scoped_and_empty(chat):
    client, factory = chat
    cid = conversation_id(client)
    other = conversation_id(client, actor=3, participants=[4])
    seed_messages(factory, other, [datetime.now(timezone.utc)])
    response = client.get(f"/api/conversations/{cid}/messages", headers=auth())
    assert response.status_code == 200 and response.json() == {"messages": []}


def test_default_limit_maximum_and_continuation(chat):
    client, factory = chat
    cid = conversation_id(client)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    ids = seed_messages(factory, cid, [base + timedelta(seconds=i) for i in range(110)])
    path = f"/api/conversations/{cid}/messages"
    first = client.get(path, headers=auth()).json()["messages"]
    assert [m["id"] for m in first] == list(reversed(ids[-50:]))
    second = client.get(path, headers=auth(), params={"before": first[-1]["created_at"]}).json()["messages"]
    assert [m["id"] for m in second] == list(reversed(ids[10:60]))
    maximum = client.get(path, headers=auth(), params={"limit": 100}).json()["messages"]
    assert len(maximum) == 100
    assert client.get(path, headers=auth(), params={"before": base.isoformat()}).json() == {"messages": []}


def test_tied_timestamp_order_and_exclusive_boundary(chat):
    client, factory = chat
    cid = conversation_id(client)
    base = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    ids = seed_messages(factory, cid, [base - timedelta(seconds=1), base, base, base + timedelta(seconds=1)])
    path = f"/api/conversations/{cid}/messages"
    first = client.get(path, headers=auth(), params={"limit": 2}).json()["messages"]
    assert [m["id"] for m in first] == [ids[3], ids[2]]
    # Timestamp-only cursors exclude every equal-time row, including ids[1].
    remaining = client.get(path, headers=auth(), params={"before": base.isoformat()}).json()["messages"]
    assert [m["id"] for m in remaining] == [ids[0]]
    offset = base.astimezone(timezone(timedelta(hours=5, minutes=30))).isoformat()
    assert client.get(path, headers=auth(), params={"before": offset}).json()["messages"] == remaining


@pytest.mark.parametrize("params", [
    {"limit": 0}, {"limit": -1}, {"limit": 101}, {"limit": "bad"}, {"limit": "1.5"},
    {"before": "bad"}, {"before": "2026-01-01T12:00:00"}, {"before": "2026-01-01"},
    {"before": "12345"}, {"before": ""}, {"before": "2026-02-30T12:00:00Z"},
    {"before": "9999-12-31T23:59:59-23:59"}, {"before": "0001-01-01T00:00:00+01:00"},
])
def test_message_query_validation(chat, params):
    client, _ = chat
    cid = conversation_id(client)
    assert client.get(f"/api/conversations/{cid}/messages", headers=auth(), params=params).status_code == 422


@pytest.mark.parametrize("value", ["bad", "0", "-1", "2147483648", str(10**100)])
@pytest.mark.parametrize("method,suffix,body", [
    ("get", "", None), ("get", "/messages", None), ("post", "/messages", {"content": "Hello"}),
])
def test_chat_path_id_bounds(chat, value, method, suffix, body):
    client, _ = chat
    response = client.request(method, f"/api/conversations/{value}{suffix}", headers=auth(), json=body)
    assert response.status_code == 422


def test_database_enforces_private_pair_and_game_night_uniqueness(chat):
    client, factory = chat
    cid = conversation_id(client)
    with factory() as db:
        db.add(Conversation(type="private", private_user_low_id=1, private_user_high_id=2))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        assert db.get(Conversation, cid) is not None
    night = game_night(factory)
    conversation_id(client, kind="group", game_night_id=night)
    with factory() as db:
        db.add(Conversation(type="group", game_night_id=night))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


@pytest.mark.parametrize("values", [
    {"type": "private"},
    {"type": "private", "private_user_low_id": 2, "private_user_high_id": 1},
    {"type": "private", "private_user_low_id": 1, "private_user_high_id": 1},
    {"type": "group", "private_user_low_id": 1, "private_user_high_id": 2},
])
def test_database_rejects_invalid_canonical_pairs(chat, values):
    _, factory = chat
    with factory() as db:
        db.add(Conversation(**values))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()


def pg_error(sqlstate="23505", table="conversations", constraint="uq_conversation_private_pair"):
    original = Exception("simulated PostgreSQL constraint failure")
    original.sqlstate = sqlstate
    original.diag = SimpleNamespace(table_name=table, constraint_name=constraint)
    return IntegrityError("INSERT", {}, original)


@pytest.mark.parametrize("constraint", ["uq_conversation_private_pair", "uq_conversation_game_night"])
def test_expected_insert_race_is_409_after_rollback(chat, monkeypatch, constraint):
    client, factory = chat
    error = pg_error(constraint=constraint)
    rollbacks = []
    original = factory.class_.rollback

    def rollback(db):
        rollbacks.append(True)
        return original(db)

    def fail(db):
        raise error

    monkeypatch.setattr(factory.class_, "rollback", rollback)
    event.listen(factory.class_, "before_commit", fail)
    try:
        response = create(client)
        assert response.status_code == 409
        assert rollbacks
    finally:
        event.remove(factory.class_, "before_commit", fail)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0
        assert db.scalar(select(func.count()).select_from(ConversationMember)) == 0


@pytest.mark.parametrize("error", [
    pg_error(sqlstate="23503"), pg_error(table="other_table"),
    pg_error(constraint="other_unique"), SQLAlchemyError("simulated failure"),
])
def test_unrelated_creation_errors_propagate_and_leave_no_partial_rows(chat, error):
    client, factory = chat

    def fail(db):
        raise error

    event.listen(factory.class_, "before_commit", fail)
    try:
        with pytest.raises(type(error)) as caught:
            create(client)
        assert caught.value is error
    finally:
        event.remove(factory.class_, "before_commit", fail)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0
        assert db.scalar(select(func.count()).select_from(ConversationMember)) == 0


def test_membership_insertion_failure_rolls_back_conversation(chat):
    client, factory = chat

    def fail_members(db, flush_context, instances):
        if any(isinstance(row, ConversationMember) for row in db.new):
            raise SQLAlchemyError("simulated membership failure")

    event.listen(factory.class_, "before_flush", fail_members)
    try:
        with pytest.raises(SQLAlchemyError, match="membership failure"):
            create(client)
    finally:
        event.remove(factory.class_, "before_flush", fail_members)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0


def test_message_commit_failure_rolls_back(chat):
    client, factory = chat
    cid = conversation_id(client)

    def fail(db):
        raise SQLAlchemyError("simulated message commit failure")

    event.listen(factory.class_, "before_commit", fail)
    try:
        with pytest.raises(SQLAlchemyError, match="message commit failure"):
            client.post(f"/api/conversations/{cid}/messages", headers=auth(), json={"content": "Hello"})
    finally:
        event.remove(factory.class_, "before_commit", fail)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 0


def test_message_database_error_rolls_back_without_translating():
    db = MagicMock(spec=Session)
    db.get.side_effect = [Conversation(id=1, type="group"), ConversationMember(conversation_id=1, user_id=1)]
    db.flush.side_effect = SQLAlchemyError("simulated insert failure")
    with pytest.raises(SQLAlchemyError, match="insert failure"):
        routes.send_message(1, MessageCreate(content="Hello"), db, User(id=1))
    db.rollback.assert_called_once()
    db.commit.assert_not_called()


def test_list_eager_loads_profiles_without_per_conversation_queries(chat):
    client, factory = chat
    for _ in range(4):
        conversation_id(client, kind="group", participants=[2, 3])
    queries = []

    def record(connection, cursor, statement, parameters, context, executemany):
        queries.append(statement)

    event.listen(factory.kw["bind"], "before_cursor_execute", record)
    try:
        response = client.get("/api/conversations", headers=auth())
        assert response.status_code == 200
        assert len(response.json()["conversations"]) == 4
        assert len(queries) == 3  # Authentication, conversation list, batched profiles.
    finally:
        event.remove(factory.kw["bind"], "before_cursor_execute", record)


def test_offline_postgresql_ddl_has_uniqueness_and_query_indexes():
    statements = []
    engine = create_mock_engine(
        "postgresql+psycopg://",
        lambda statement, *args, **kwargs: statements.append(str(statement.compile(dialect=engine.dialect))),
    )
    Base.metadata.create_all(engine, checkfirst=False)
    sql = "\n".join(statements)
    assert "CONSTRAINT uq_conversation_private_pair UNIQUE (private_user_low_id, private_user_high_id)" in sql
    assert "CONSTRAINT uq_conversation_game_night UNIQUE (game_night_id)" in sql
    assert "CONSTRAINT ck_conversation_private_pair CHECK" in sql
    for column in ("private_user_low_id", "private_user_high_id"):
        assert f"FOREIGN KEY({column}) REFERENCES users (id) ON DELETE RESTRICT" in sql
        assert f"FOREIGN KEY({column}) REFERENCES users (id) ON DELETE CASCADE" not in sql
    assert "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE" in sql
    assert "CREATE INDEX ix_conversation_members_user_conversation" in sql
    assert "CREATE INDEX ix_messages_conversation_created_id ON messages (conversation_id, created_at DESC, id DESC)" in sql
    assert "created_at TIMESTAMP WITH TIME ZONE" in sql


@pytest.mark.parametrize("path,method,codes", [
    ("/api/conversations", "get", {"200", "401"}),
    ("/api/conversations", "post", {"201", "400", "401", "403", "404", "409", "422"}),
    ("/api/conversations/{id}", "get", {"200", "401", "403", "404", "422"}),
    ("/api/conversations/{id}/messages", "get", {"200", "401", "403", "404", "422"}),
    ("/api/conversations/{id}/messages", "post", {"201", "401", "403", "404", "422"}),
])
def test_chat_openapi_documents_authentication_and_responses(path, method, codes):
    operation = app.openapi()["paths"][path][method]
    assert operation["tags"] == ["Messages"]
    assert operation["security"] == [{"HTTPBearer": []}]
    assert set(operation["responses"]) == codes
    if path == "/api/conversations" and method == "post":
        assert operation["responses"]["403"]["description"] == "Accepted friendship required, unauthorized game-night creation or ineligible participants"
        assert operation["responses"]["404"]["description"] == "Participant or game night not found"
    schemas = app.openapi()["components"]["schemas"]
    assert schemas["MessageCreate"]["properties"]["content"]["maxLength"] == 2000
    assert schemas["ConversationCreate"]["properties"]["participant_ids"]["uniqueItems"] is True
    assert schemas["ConversationCreate"]["properties"]["participant_ids"]["maxItems"] == 50
    for name in ["ConversationCreate", "ConversationResponse", "ConversationEnvelope",
                 "ConversationListResponse", "MessageCreate", "MessageResponse", "MessageEnvelope", "MessageListResponse"]:
        assert schemas[name]["additionalProperties"] is False


@pytest.mark.parametrize("kind,participants", [("private", [2]), ("group", [2, 3])])
@pytest.mark.parametrize("friend_status", ["pending", "declined", "removed"])
def test_creation_requires_every_creator_friendship(chat, kind, participants, friend_status):
    client, factory = chat
    with factory() as db:
        friendship = db.query(Friend).filter(Friend.requester_id == 1, Friend.receiver_id == 2).one()
        if friend_status == "removed":
            db.delete(friendship)
        else:
            friendship.status = friend_status
        db.commit()
    assert create(client, participants=participants, kind=kind).status_code == 403
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 0
        assert db.scalar(select(func.count()).select_from(ConversationMember)) == 0
        assert db.scalar(select(func.count()).select_from(Message)) == 0


@pytest.mark.parametrize("actor,other", [(1, 2), (2, 1), (1, 3), (3, 1)])
def test_accepted_friendship_creation_in_either_direction(chat, actor, other):
    client, _ = chat
    assert create(client, actor=actor, participants=[other]).status_code == 201


@pytest.mark.parametrize("replacement_status", ["pending", "declined", "removed"])
def test_private_revocation_and_refriending_preserve_history(chat, replacement_status):
    client, factory = chat
    cid = conversation_id(client)
    path = f"/api/conversations/{cid}"
    sent = client.post(path + "/messages", headers=auth(), json={"content": "History"})
    assert sent.status_code == 201
    message_id = sent.json()["message"]["id"]
    with factory() as db:
        friendship = db.query(Friend).filter(Friend.requester_id == 1, Friend.receiver_id == 2).one()
        if replacement_status == "removed":
            db.delete(friendship)
        else:
            friendship.status = replacement_status
        db.commit()
    for actor in [1, 2]:
        assert client.get("/api/conversations", headers=auth(actor)).json() == {"conversations": []}
        assert client.get(path, headers=auth(actor)).status_code == 403
        assert client.get(path + "/messages", headers=auth(actor)).status_code == 403
        assert client.post(path + "/messages", headers=auth(actor), json={"content": "Denied"}).status_code == 403
    with factory() as db:
        assert db.get(Conversation, cid) is not None
        assert db.scalar(select(func.count()).select_from(ConversationMember)) == 2
        assert db.scalar(select(func.count()).select_from(Message)) == 1
        db.query(Friend).filter(Friend.requester_id == 1, Friend.receiver_id == 2).delete()
        db.add(Friend(requester_id=2, receiver_id=1, status="accepted"))
        db.commit()
    for actor in [1, 2]:
        assert client.get(path, headers=auth(actor)).status_code == 200
        assert [c["id"] for c in client.get("/api/conversations", headers=auth(actor)).json()["conversations"]] == [cid]
        assert message_id in [m["id"] for m in client.get(path + "/messages", headers=auth(actor)).json()["messages"]]
        assert create(client, actor=actor, participants=[3 - actor]).status_code == 409
        assert client.post(path + "/messages", headers=auth(actor), json={"content": "Restored"}).status_code == 201


def test_group_access_survives_unfriending(chat):
    client, factory = chat
    cid = conversation_id(client, kind="group", participants=[2, 3])
    with factory() as db:
        db.query(Friend).delete()
        db.commit()
    for actor in [1, 2, 3]:
        assert client.get(f"/api/conversations/{cid}", headers=auth(actor)).status_code == 200
        assert len(client.get("/api/conversations", headers=auth(actor)).json()["conversations"]) == 1
        assert client.post(f"/api/conversations/{cid}/messages", headers=auth(actor), json={"content": "Group"}).status_code == 201
        assert client.get(f"/api/conversations/{cid}/messages", headers=auth(actor)).status_code == 200
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ConversationMember)) == 3


def test_game_night_chat_does_not_require_friendship(chat):
    client, factory = chat
    with factory() as db:
        db.query(Friend).delete()
        db.commit()
    night = game_night(factory)
    cid = conversation_id(client, kind="group", game_night_id=night)
    for actor in [1, 2]:
        assert client.get(f"/api/conversations/{cid}", headers=auth(actor)).status_code == 200
        assert len(client.get("/api/conversations", headers=auth(actor)).json()["conversations"]) == 1
        assert client.post(f"/api/conversations/{cid}/messages", headers=auth(actor), json={"content": "Event"}).status_code == 201
        assert client.get(f"/api/conversations/{cid}/messages", headers=auth(actor)).status_code == 200


def test_unfriend_endpoint_revokes_only_the_matching_private_pair(chat):
    client, factory = chat
    revoked = conversation_id(client)
    retained = conversation_id(client, participants=[3])
    assert client.delete("/api/friends/1", headers=auth(2)).status_code == 204
    for actor in [1, 2]:
        path = f"/api/conversations/{revoked}"
        assert client.get(path, headers=auth(actor)).status_code == 403
        assert client.get(path + "/messages", headers=auth(actor)).status_code == 403
        assert client.post(path + "/messages", headers=auth(actor), json={"content": "Denied"}).status_code == 403
    assert [row["id"] for row in client.get("/api/conversations", headers=auth()).json()["conversations"]] == [retained]
    assert client.get("/api/conversations", headers=auth(2)).json() == {"conversations": []}
    assert create(client).status_code == 403
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Conversation)) == 2
        assert db.scalar(select(func.count()).select_from(Message)) == 0


def chat_history(client):
    private = conversation_id(client)
    group = conversation_id(client, kind="group", participants=[2, 3])
    for actor, cid in [(1, private), (2, private), (2, group), (3, group)]:
        response = client.post(f"/api/conversations/{cid}/messages", headers=auth(actor), json={"content": f"From {actor}"})
        assert response.status_code == 201
    return private, group


def chat_snapshot(factory):
    with factory() as db:
        return {
            "users": db.execute(select(User.id, User.email).order_by(User.id)).all(),
            "conversations": db.execute(select(
                Conversation.id, Conversation.type, Conversation.private_user_low_id, Conversation.private_user_high_id,
            ).order_by(Conversation.id)).all(),
            "members": db.execute(select(ConversationMember.conversation_id, ConversationMember.user_id).order_by(
                ConversationMember.conversation_id, ConversationMember.user_id,
            )).all(),
            "messages": db.execute(select(Message.id, Message.conversation_id, Message.user_id, Message.content)
                                   .order_by(Message.id)).all(),
            "friends": db.execute(select(Friend.id, Friend.requester_id, Friend.receiver_id, Friend.status)
                                  .order_by(Friend.id)).all(),
        }


def create_user_cascade_tables(factory):
    # ORM user deletion loads every User relationship, including tables chat tests omit.
    Base.metadata.create_all(factory.kw["bind"], tables=[
        Base.metadata.tables[name] for name in ["preferences", "games", "user_games", "game_night_games"]
    ])


def assert_private_history_readable(client, private):
    for actor in [1, 2]:
        response = client.get(f"/api/conversations/{private}/messages", headers=auth(actor))
        assert response.status_code == 200
        assert sorted(m["content"] for m in response.json()["messages"]) == ["From 1", "From 2"]


@pytest.mark.parametrize("victim", [1, 2], ids=["low-participant", "high-participant"])
def test_orm_user_deletion_blocked_by_private_conversation(chat, victim):
    client, factory = chat
    create_user_cascade_tables(factory)
    private, _ = chat_history(client)
    before = chat_snapshot(factory)
    with factory() as db:
        db.delete(db.get(User, victim))
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
    # The ORM cascades deleted messages and memberships before the user row; rollback restores them.
    assert chat_snapshot(factory) == before
    assert_private_history_readable(client, private)


@pytest.mark.parametrize("victim", [1, 2], ids=["low-participant", "high-participant"])
def test_sql_user_deletion_blocked_by_private_conversation(chat, victim):
    client, factory = chat
    private, _ = chat_history(client)
    before = chat_snapshot(factory)
    with factory() as db:
        with pytest.raises(IntegrityError):
            db.execute(text("DELETE FROM users WHERE id = :id"), {"id": victim})
        db.rollback()
    assert chat_snapshot(factory) == before
    assert_private_history_readable(client, private)


def test_user_without_private_conversation_keeps_baseline_cascades(chat):
    client, factory = chat
    create_user_cascade_tables(factory)
    private, group = chat_history(client)
    with factory() as db:
        db.delete(db.get(User, 3))
        db.commit()
    with factory() as db:
        assert db.get(User, 3) is None
        assert db.execute(select(Message.user_id).where(Message.conversation_id == group)).scalars().all() == [2]
        assert db.execute(select(ConversationMember.user_id).where(
            ConversationMember.conversation_id == group,
        ).order_by(ConversationMember.user_id)).scalars().all() == [1, 2]
        assert db.scalar(select(func.count()).select_from(Friend).where(
            (Friend.requester_id == 3) | (Friend.receiver_id == 3),
        )) == 0
    assert_private_history_readable(client, private)
