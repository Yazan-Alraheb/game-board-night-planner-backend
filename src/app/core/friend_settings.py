from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class FriendRequestSettings(BaseSettings):
    cooldown_days: int = Field(default=7, ge=1)

    model_config = SettingsConfigDict(
        env_prefix="FRIEND_REQUEST_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_friend_request_settings() -> FriendRequestSettings:
    return FriendRequestSettings()
