from pydantic import BaseModel, ConfigDict

from app.schemas.user import PublicUser


class FriendsListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    friends: list[PublicUser]
