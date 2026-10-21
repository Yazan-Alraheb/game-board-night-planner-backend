"""Cooldown/cancellation use real SQLite persistence and the production JWT path."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import event, select
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.exc import SQLAlchemyError, StatementError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex

from app.api.v1 import friend_requests as routes
from app.core.friend_settings import FriendRequestSettings, get_friend_request_settings
from app.core.time_types import UTCDateTime
from app.models.friend import Friend
from app.models.user import User
from app.schemas.friend import FriendRequestUpdate
from test_friend_endpoints import auth, friendship_db, insert_request


@pytest.fixture
def clock(monkeypatch):
    instant = [datetime(2026, 10, 21, 12, tzinfo=timezone.utc)]
    monkeypatch.setattr(routes, "utc_now", lambda: instant[0])
    return instant


def declined(factory, when, sender=1, receiver=2, created_at=None):
    with factory() as db:
        row = Friend(
            requester_id=sender, receiver_id=receiver, status="declined",
            resolved_at=when,
            created_at=created_at or datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        db.add(row)
        db.commit()
        return row.id


def send(client, sender=1, receiver=2):
    return client.post("/api/friend-requests", headers=auth(sender), json={"user_id": receiver})


@pytest.mark.parametrize("offset,expected", [
    (timedelta(microseconds=-1), 409), (timedelta(0), 201),
    (timedelta(microseconds=1), 201),
])
def test_cooldown_exact_boundary(friendship_db, clock, offset, expected):
    client, factory = friendship_db
    resolution = clock[0] - timedelta(days=7)
    declined(factory, resolution)
    clock[0] += offset
    response = send(client)
    assert response.status_code == expected
    if expected == 409:
        assert response.json() == {"detail": "Friend request decline cooldown has not expired"}
    with factory() as db:
        pending = db.scalars(select(Friend).where(Friend.status == "pending")).all()
        assert len(pending) == (1 if expected == 201 else 0)


def test_cooldown_uses_decline_time_not_old_creation(friendship_db, clock):
    client, factory = friendship_db
    request_id = insert_request(factory)
    with factory() as db:
        db.get(Friend, request_id).created_at = clock[0] - timedelta(days=100)
        db.commit()
    response = client.put(f"/api/friend-requests/{request_id}", headers=auth(2),
                          json={"status": "declined"})
    assert response.status_code == 200
    assert set(response.json()["friend_request"]) == {
        "id", "requester_id", "receiver_id", "status", "created_at",
    }
    with factory() as db:
        assert db.get(Friend, request_id).resolved_at == clock[0]
    assert send(client).status_code == 409


def test_cooldown_is_directed_and_not_global(friendship_db, clock):
    client, factory = friendship_db
    declined(factory, clock[0])
    assert send(client).status_code == 409
    assert send(client, 1, 3).status_code == 201
    assert send(client, 4, 2).status_code == 201
    assert send(client, 2, 1).status_code == 201
    # Reverse-direction permission never bypasses active-pair uniqueness.
    assert send(client).status_code == 409


def test_historical_null_declines_are_grandfathered(friendship_db, clock):
    client, factory = friendship_db
    declined(factory, None, created_at=clock[0])
    assert send(client).status_code == 201


@pytest.mark.parametrize("recent", [True, False])
def test_latest_decline_wins_not_row_id_or_creation_time(friendship_db, clock, recent):
    client, factory = friendship_db
    latest = clock[0] - timedelta(days=1 if recent else 8)
    declined(factory, latest, created_at=clock[0] - timedelta(days=100))
    # Insert an older resolution later, with a newer creation time.
    declined(factory, clock[0] - timedelta(days=20), created_at=clock[0] - timedelta(days=21))
    # A historical row must not mask a timestamped decline.
    declined(factory, None, created_at=clock[0])
    assert send(client).status_code == (409 if recent else 201)


def test_second_decline_starts_a_new_cooldown(friendship_db, clock):
    client, factory = friendship_db
    declined(factory, clock[0] - timedelta(days=8))
    request_id = send(client).json()["friend_request"]["id"]
    assert client.put(f"/api/friend-requests/{request_id}", headers=auth(2),
                      json={"status": "declined"}).status_code == 200
    assert send(client).status_code == 409
    clock[0] += timedelta(days=7)
    assert send(client).status_code == 201


@pytest.mark.parametrize("status", ["accepted", "declined"])
def test_repeated_resolution_never_resets_timestamp(friendship_db, clock, status):
    client, factory = friendship_db
    request_id = insert_request(factory)
    path = f"/api/friend-requests/{request_id}"
    assert client.put(path, headers=auth(2), json={"status": status}).status_code == 200
    resolved_at = clock[0]
    clock[0] += timedelta(days=2)
    for repeat in ("accepted", "declined"):
        assert client.put(path, headers=auth(2), json={"status": repeat}).status_code == 409
    with factory() as db:
        assert db.get(Friend, request_id).resolved_at == resolved_at


@pytest.mark.parametrize("days,expected", [(2, 201), (4, 409)])
def test_configurable_cooldown(friendship_db, clock, monkeypatch, days, expected):
    client, factory = friendship_db
    monkeypatch.setenv("FRIEND_REQUEST_COOLDOWN_DAYS", str(days))
    get_friend_request_settings.cache_clear()
    declined(factory, clock[0] - timedelta(days=3))
    assert send(client).status_code == expected


def test_settings_default(monkeypatch):
    monkeypatch.delenv("FRIEND_REQUEST_COOLDOWN_DAYS", raising=False)
    assert FriendRequestSettings(_env_file=None).cooldown_days == 7


@pytest.mark.parametrize("value", ["0", "-1", "bad", "1.5"])
def test_settings_reject_invalid_cooldown(monkeypatch, value):
    monkeypatch.setenv("FRIEND_REQUEST_COOLDOWN_DAYS", value)
    with pytest.raises(ValidationError):
        FriendRequestSettings(_env_file=None)


def test_offset_timestamp_is_read_as_aware_utc(friendship_db, clock):
    client, factory = friendship_db
    offset = timezone(timedelta(hours=5, minutes=30))
    timestamp = (clock[0] - timedelta(days=7)).astimezone(offset)
    request_id = declined(factory, timestamp)
    with factory() as db:
        value = db.get(Friend, request_id).resolved_at
        assert value == clock[0] - timedelta(days=7)
        assert value.tzinfo == timezone.utc
    assert send(client).status_code == 201


def test_naive_resolution_writes_are_rejected(friendship_db):
    _, factory = friendship_db
    with factory() as db:
        db.add(Friend(requester_id=1, receiver_id=2, status="declined",
                      resolved_at=datetime(2026, 1, 1)))
        with pytest.raises(StatementError, match="timezone-aware"):
            db.commit()
        db.rollback()


def test_postgresql_offset_normalization():
    value = datetime(2026, 1, 1, 12, tzinfo=timezone(timedelta(hours=-4)))
    normalized = UTCDateTime().process_result_value(value, dialect())
    assert normalized == datetime(2026, 1, 1, 16, tzinfo=timezone.utc)
    assert normalized.tzinfo == timezone.utc


def test_sender_cancellation_is_empty_and_allows_resend(friendship_db):
    client, factory = friendship_db
    request_id = insert_request(factory)
    response = client.delete(f"/api/friend-requests/{request_id}", headers=auth())
    assert response.status_code == 204
    assert response.content == b""
    with factory() as db:
        assert db.get(Friend, request_id) is None
    assert client.delete(f"/api/friend-requests/{request_id}", headers=auth()).status_code == 404
    response = send(client)
    assert response.status_code == 201
    with factory() as db:
        assert db.get(Friend, response.json()["friend_request"]["id"]).resolved_at is None


@pytest.mark.parametrize("actor", [2, 3])
def test_only_sender_can_cancel(friendship_db, actor):
    client, factory = friendship_db
    request_id = insert_request(factory)
    assert client.delete(f"/api/friend-requests/{request_id}", headers=auth(actor)).status_code == 403
    with factory() as db:
        assert db.get(Friend, request_id).status == "pending"


@pytest.mark.parametrize("status", ["accepted", "declined"])
def test_resolved_request_cannot_be_canceled(friendship_db, status):
    client, factory = friendship_db
    request_id = insert_request(factory, status=status)
    assert client.delete(f"/api/friend-requests/{request_id}", headers=auth()).status_code == 409
    with factory() as db:
        assert db.get(Friend, request_id).status == status


def test_missing_cancellation(friendship_db):
    client, _ = friendship_db
    assert client.delete("/api/friend-requests/999", headers=auth()).status_code == 404


@pytest.mark.parametrize("value", ["bad", "0", "-1", "2147483648", str(10**100)])
def test_cancellation_id_validation(friendship_db, value):
    client, _ = friendship_db
    assert client.delete(f"/api/friend-requests/{value}", headers=auth()).status_code == 422


def test_cancel_preserves_existing_decline_history(friendship_db, clock):
    client, factory = friendship_db
    history_id = declined(factory, clock[0])
    request_id = insert_request(factory)
    assert client.delete(f"/api/friend-requests/{request_id}", headers=auth()).status_code == 204
    assert send(client).status_code == 409
    with factory() as db:
        assert db.get(Friend, history_id).resolved_at == clock[0]


@pytest.mark.parametrize("status", ["accepted", "declined"])
def test_stale_cancel_cannot_delete_resolution(friendship_db, clock, status):
    _, factory = friendship_db
    request_id = insert_request(factory)
    with factory() as resolver, factory() as canceler:
        stale = canceler.get(Friend, request_id)
        assert stale.status == "pending"
        routes.update_friend_request(request_id, FriendRequestUpdate(status=status), resolver, User(id=2))
        with pytest.raises(HTTPException) as caught:
            routes.cancel_friend_request(request_id, canceler, User(id=1))
        assert caught.value.status_code == 409
    with factory() as db:
        assert db.get(Friend, request_id).status == status
        assert db.get(Friend, request_id).resolved_at == clock[0]


def test_cancellation_wins_against_stale_resolution(friendship_db):
    _, factory = friendship_db
    request_id = insert_request(factory)
    with factory() as resolver, factory() as canceler:
        stale = resolver.get(Friend, request_id)
        assert stale.status == "pending"
        routes.cancel_friend_request(request_id, canceler, User(id=1))
        with pytest.raises(HTTPException) as caught:
            routes.update_friend_request(request_id, FriendRequestUpdate(status="accepted"), resolver, User(id=2))
        assert caught.value.status_code == 409
    with factory() as db:
        assert db.get(Friend, request_id) is None


def test_two_stale_cancellations_return_404_to_loser(friendship_db):
    _, factory = friendship_db
    request_id = insert_request(factory)
    with factory() as first, factory() as second:
        stale = second.get(Friend, request_id)
        assert stale.status == "pending"
        routes.cancel_friend_request(request_id, first, User(id=1))
        with pytest.raises(HTTPException) as caught:
            routes.cancel_friend_request(request_id, second, User(id=1))
        assert caught.value.status_code == 404


@pytest.mark.parametrize("stage", ["execute", "commit"])
def test_cancellation_failures_roll_back(stage):
    db = MagicMock(spec=Session)
    db.get.return_value = Friend(id=1, requester_id=1, receiver_id=2, status="pending")
    db.execute.return_value.rowcount = 1
    error = SQLAlchemyError("simulated cancellation failure")
    getattr(db, stage).side_effect = error
    with pytest.raises(SQLAlchemyError) as caught:
        routes.cancel_friend_request(1, db, User(id=1))
    assert caught.value is error
    db.rollback.assert_called_once()


def test_decline_lookup_failure_rolls_back():
    db = MagicMock(spec=Session)
    db.get.return_value = User(id=2)
    db.query.return_value.filter.return_value.first.return_value = None
    error = SQLAlchemyError("simulated decline lookup failure")
    db.query.return_value.filter.return_value.scalar.side_effect = error
    from app.schemas.friend import FriendRequestCreate
    with pytest.raises(SQLAlchemyError) as caught:
        routes.create_friend_request(FriendRequestCreate(user_id=2), db, User(id=1))
    assert caught.value is error
    db.rollback.assert_called_once()
    db.add.assert_not_called()


def test_decline_index_is_non_unique_and_active_index_is_unchanged(friendship_db):
    _, factory = friendship_db
    index = next(i for i in Friend.__table__.indexes if i.name == "ix_friends_decline_lookup")
    ddl = str(CreateIndex(index).compile(dialect=dialect(), compile_kwargs={"literal_binds": True}))
    assert "CREATE INDEX ix_friends_decline_lookup" in ddl
    assert "requester_id, receiver_id, resolved_at DESC" in ddl
    assert "status = 'declined' AND resolved_at IS NOT NULL" in ddl
    with factory.kw["bind"].connect() as connection:
        indexes = {
            row[1]: row for row in connection.exec_driver_sql("PRAGMA index_list('friends')")
        }
    assert indexes["ix_friends_decline_lookup"][2] == 0
    assert indexes["uq_active_friend_pair"][2] == 1
    assert next(i for i in Friend.__table__.indexes if i.name == "uq_active_friend_pair").unique


@pytest.mark.parametrize("operation", ["decline", "cancel"])
def test_failed_commit_restores_pending_row_and_timestamp(friendship_db, clock, operation):
    client, factory = friendship_db
    request_id = insert_request(factory)
    error = SQLAlchemyError("simulated commit failure after SQL execution")

    def fail_commit(db):
        raise error

    event.listen(factory.class_, "before_commit", fail_commit)
    try:
        with pytest.raises(SQLAlchemyError) as caught:
            path = f"/api/friend-requests/{request_id}"
            if operation == "decline":
                client.put(path, headers=auth(2), json={"status": "declined"})
            else:
                client.delete(path, headers=auth())
        assert caught.value is error
    finally:
        event.remove(factory.class_, "before_commit", fail_commit)

    with factory() as db:
        row = db.get(Friend, request_id)
        assert row is not None
        assert row.status == "pending"
        assert row.resolved_at is None
