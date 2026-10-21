import os
from tempfile import TemporaryDirectory

import pytest

# Database settings are loaded at import time; never use the development URL.
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

# Initialize the import-time database settings where no project .env exists.
# Restore cwd immediately; subsequent test settings use public model_config.
with TemporaryDirectory(prefix="gamenight-test-settings-") as settings_directory:
    with pytest.MonkeyPatch.context() as settings_patch:
        settings_patch.chdir(settings_directory)
        from app.core.database import Settings as DatabaseSettings

from app.core.auth_settings import AuthSettings, get_auth_settings
from app.core.friend_settings import FriendRequestSettings, get_friend_request_settings

DatabaseSettings.model_config["env_file"] = None
AuthSettings.model_config["env_file"] = None
FriendRequestSettings.model_config["env_file"] = None


@pytest.fixture
def jwt_secret():
    return "test-only-signing-secret-for-jwt-tests-with-at-least-64-bytes-of-data"


@pytest.fixture
def auth_environment(monkeypatch, jwt_secret):
    get_auth_settings.cache_clear()
    get_friend_request_settings.cache_clear()
    # Ignore local dotenv files without changing the working directory.
    monkeypatch.setitem(AuthSettings.model_config, "env_file", None)
    monkeypatch.setenv("JWT_SECRET_KEY", jwt_secret)
    monkeypatch.delenv("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
    monkeypatch.setenv("FRIEND_REQUEST_COOLDOWN_DAYS", "7")
    try:
        yield
    finally:
        get_auth_settings.cache_clear()
        get_friend_request_settings.cache_clear()
