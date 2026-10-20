from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PreferenceResponse(BaseModel):
    id: int
    user_id: int
    favorite_categories: list[str]
    disliked_categories: list[str]
    preferred_difficulty: Literal["Easy", "Medium", "Hard"] | None = None
    preferred_playtime: int | None = Field(default=None, ge=1)

    model_config = ConfigDict(from_attributes=True)


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    favorite_categories: list[str]
    disliked_categories: list[str]
    preferred_difficulty: Literal["Easy", "Medium", "Hard"] | None = None
    preferred_playtime: int | None = Field(default=None, ge=1)


class PreferenceDetailResponse(BaseModel):
    preferences: PreferenceResponse


class PreferenceUpdateResponse(BaseModel):
    preferences: PreferenceResponse
