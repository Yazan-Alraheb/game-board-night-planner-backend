from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime
from typing import Literal


class FriendErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    detail: str


class FriendRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int = Field(
        ge=1,
        le=2_147_483_647,
        description="The ID of the user receiving the friend request",
    )


class FriendRequestResponse(BaseModel):
    id: int
    requester_id: int
    receiver_id: int
    status: Literal["pending", "accepted", "declined"]
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, extra="forbid")


class FriendRequestListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: list[FriendRequestResponse]


class FriendRequestUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["accepted", "declined"]


class FriendRequestEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    friend_request: FriendRequestResponse
