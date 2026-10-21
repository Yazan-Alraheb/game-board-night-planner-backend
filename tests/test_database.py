from unittest.mock import MagicMock

import pytest

from app.core import database


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
