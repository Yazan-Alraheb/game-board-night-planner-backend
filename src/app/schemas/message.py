from datetime import datetime, timezone
from typing import Annotated

from pydantic import AfterValidator, AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, field_validator


def require_datetime_string(value):
    # Do not silently treat numeric query strings as Unix timestamps.
    if isinstance(value, str) and "T" not in value.upper():
        raise ValueError("Use a timezone-aware RFC 3339 timestamp")
    return value


def normalize_before_timestamp(value):
    try:
        return value.astimezone(timezone.utc)
    except OverflowError as exc:
        raise ValueError("Timestamp is outside the supported UTC datetime range") from exc


BeforeTimestamp = Annotated[
    AwareDatetime, BeforeValidator(require_datetime_string), AfterValidator(normalize_before_timestamp),
]


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=2000)

    @field_validator("content")
    @classmethod
    def meaningful_content(cls, value):
        if "\x00" in value:
            raise ValueError("Message must not contain NUL characters")
        if not value.strip():
            raise ValueError("Message must contain a non-whitespace character")
        return value


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: int
    conversation_id: int
    user_id: int
    content: str
    created_at: datetime


class MessageEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: MessageResponse


class MessageListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[MessageResponse]
