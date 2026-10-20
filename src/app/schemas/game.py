from typing import Literal

from pydantic import BaseModel, ConfigDict


Difficulty = Literal["Easy", "Medium", "Hard"]


class GameResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    minimum_players: int
    maximum_players: int
    playtime: int
    difficulty: Difficulty
    categories: list[str] | None = None
    image_url: str | None = None
    rating: float | None = None
    review_count: int | None = None
    instructions: str | None = None

    model_config = ConfigDict(from_attributes=True)


class GameDetailResponse(BaseModel):
    game: GameResponse


class GameListResponse(BaseModel):
    games: list[GameResponse]
    total: int
    page: int
