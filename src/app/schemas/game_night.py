from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.game import GameResponse
from app.schemas.user import PublicUser


GameNightMemberStatus = Literal["pending", "accepted", "declined"]


class GameNightCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    starts_at: datetime
    location: str = Field(min_length=1)
    notes: str | None = None
    game_ids: list[int] = Field(default_factory=list)
    invitee_ids: list[int] = Field(default_factory=list)


class GameNightUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    starts_at: datetime
    location: str = Field(min_length=1)
    notes: str | None = None


class GameNightResponse(BaseModel):
    id: int
    host_id: int
    name: str
    starts_at: datetime
    location: str
    notes: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class GameNightDetailResponse(BaseModel):
    game_night: GameNightResponse


class GameNightListResponse(BaseModel):
    game_nights: list[GameNightResponse]


class GameNightInvite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(gt=0)


class GameNightMemberResponse(BaseModel):
    user: PublicUser
    status: GameNightMemberStatus


class GameNightMembersResponse(BaseModel):
    members: list[GameNightMemberResponse]


class RSVPUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted", "declined"]


class RSVPResponse(BaseModel):
    game_night_id: int
    status: GameNightMemberStatus


class GameNightGameAdd(BaseModel):
    model_config = ConfigDict(extra="forbid")

    game_id: int = Field(gt=0)


class GameNightGameResponse(BaseModel):
    game_id: int
    game_night_id: int


class GameNightAvailableGame(BaseModel):
    game: GameResponse
    owners: list[PublicUser]
    selected: bool


class GameNightAvailableGamesResponse(BaseModel):
    games: list[GameNightAvailableGame]