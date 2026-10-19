from functools import lru_cache

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    jwt_secret_key: SecretStr
    jwt_access_token_expire_minutes: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if not secret.strip() or len(secret.encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET_KEY must contain at least 32 UTF-8 bytes")
        return value

    @field_validator("jwt_access_token_expire_minutes", mode="before")
    @classmethod
    def validate_lifetime(cls, value):
        if isinstance(value, bool):
            raise ValueError("Token lifetime must be a positive integer")
        return value

    @field_validator("jwt_access_token_expire_minutes")
    @classmethod
    def validate_positive_lifetime(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Token lifetime must be a positive integer")
        return value


@lru_cache(maxsize=1)
def get_auth_settings() -> AuthSettings:
    return AuthSettings()
