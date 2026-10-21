from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.game import GameResponse
from app.schemas.user import PublicUser


PositiveInteger = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
DatabaseId = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]
Category = Annotated[str, Field(strict=True, min_length=1, max_length=100)]


class RecommendationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["personal", "game_night"]
    game_night_id: DatabaseId | None = None
    player_count: PositiveInteger | None = None
    max_playtime: PositiveInteger
    categories: list[Category] = Field(default_factory=list, max_length=50)
    experience_level: Literal["Beginner", "Intermediate", "Experienced"] | None = None

    @field_validator("categories")
    @classmethod
    def normalize_categories(cls, values: list[str]) -> list[str]:
        result = sorted({value.strip().casefold() for value in values})
        if "" in result:
            raise ValueError("Categories must not be blank")
        return result

    @model_validator(mode="after")
    def reject_explicit_nulls(self):
        for name in ("game_night_id", "player_count", "experience_level"):
            if name in self.model_fields_set and getattr(self, name) is None:
                raise ValueError(f"Omit {name} instead of sending null")
        return self


class RecommendedGame(GameResponse):
    # Overrides the parent validator: stored JSON may hold non-string entries,
    # which are dropped here so /api/games behavior stays unchanged.
    @field_validator("categories", mode="before")
    @classmethod
    def normalize_categories(cls, value):
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game: RecommendedGame
    score: float = Field(ge=0, le=100)
    reason: str
    owners: list[PublicUser]


class RecommendationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendations: list[Recommendation]


class RecommendationError(BaseModel):
    detail: str
