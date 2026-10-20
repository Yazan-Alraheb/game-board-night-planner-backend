from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Difficulty = Literal["Easy", "Medium", "Hard"]


class GameResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    minimum_players: int
    maximum_players: int
    playtime: int
    difficulty: Difficulty
    categories: list[str] = Field(default_factory=list)
    image_url: str | None = None
    rating: float | None = None
    review_count: int | None = None
    instructions: str | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("categories", mode="before")
    @classmethod
    def normalize_categories(cls, value):
        return [] if value is None else value

class GameDetailResponse(BaseModel):
    game: GameResponse


class GameListResponse(BaseModel):
    games: list[GameResponse]
    total: int
    page: int
