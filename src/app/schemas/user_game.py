from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.game import GameResponse


CollectionStatus = Literal["owned", "wishlist"]


class CollectionAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_id: int = Field(gt=0)
    status: CollectionStatus


class CollectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: CollectionStatus


class CollectionEntryResponse(BaseModel):
    game_id: int
    status: CollectionStatus


class CollectionGameResponse(BaseModel):
    game: GameResponse
    status: CollectionStatus


class CollectionListResponse(BaseModel):
    games: list[CollectionGameResponse]
