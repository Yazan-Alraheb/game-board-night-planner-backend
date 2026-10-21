from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.user import PublicUser


DatabaseId = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
ConversationType = Literal["private", "group"]


class ChatErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_ids: list[DatabaseId] = Field(min_length=1, max_length=50, json_schema_extra={"uniqueItems": True})
    type: ConversationType
    game_night_id: DatabaseId | None = None

    @field_validator("participant_ids")
    @classmethod
    def unique_participants(cls, values):
        if len(values) != len(set(values)):
            raise ValueError("participant_ids must be unique")
        return values

    @model_validator(mode="after")
    def supplied_game_night_is_not_null(self):
        if "game_night_id" in self.model_fields_set and self.game_night_id is None:
            raise ValueError("Omit game_night_id when the conversation is not linked to an event")
        return self


class ConversationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    type: ConversationType
    game_night_id: int | None = None
    participants: list[PublicUser]
    created_at: datetime


class ConversationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversation: ConversationResponse


class ConversationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    conversations: list[ConversationResponse]
