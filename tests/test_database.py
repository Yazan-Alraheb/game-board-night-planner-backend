from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_mock_engine

from app.core import database


def test_fresh_postgresql_schema_includes_friend_resolution_column_and_indexes():
    # Register every table, including foreign-key targets, without connecting.
    import app.models

    statements = []
    mock_engine = create_mock_engine(
        "postgresql+psycopg://",
        lambda statement, *args, **kwargs: statements.append(
            str(statement.compile(dialect=mock_engine.dialect))
        ),
    )
    database.Base.metadata.create_all(mock_engine, checkfirst=False)

    friend_table = next(sql for sql in statements if "CREATE TABLE friends (" in sql)
    assert "resolved_at TIMESTAMP WITH TIME ZONE" in friend_table
    decline_index = next(sql for sql in statements if "CREATE INDEX ix_friends_decline_lookup" in sql)
    assert "(requester_id, receiver_id, resolved_at DESC)" in decline_index
    assert "WHERE status = 'declined' AND resolved_at IS NOT NULL" in decline_index
    active_index = next(sql for sql in statements if "CREATE UNIQUE INDEX uq_active_friend_pair" in sql)
    assert "least(requester_id, receiver_id)" in active_index
    assert "greatest(requester_id, receiver_id)" in active_index
    assert "WHERE status IN ('pending', 'accepted')" in active_index


def test_database_settings_are_isolated_from_project_dotenv():
    assert database.settings.database_url == "sqlite:///:memory:"
    assert database.Settings.model_config["env_file"] is None
    assert database.Settings().database_url == "sqlite:///:memory:"


def test_get_db_closes_session(monkeypatch):
    mock_session = MagicMock()

    monkeypatch.setattr(database, "SessionLocal", lambda: mock_session)

    dependency = database.get_db()

    assert next(dependency) is mock_session

    with pytest.raises(StopIteration):
        next(dependency)

    mock_session.close.assert_called_once()


def test_get_db_closes_session_on_exception(monkeypatch):
    mock_session = MagicMock()
    monkeypatch.setattr(database, "SessionLocal", lambda: mock_session)

    dependency = database.get_db()

    assert next(dependency) is mock_session

    with pytest.raises(ValueError, match="Test error"):
        dependency.throw(ValueError("Test error"))

    mock_session.close.assert_called_once()
