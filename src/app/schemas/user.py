from datetime import datetime
from typing import Annotated
from pydantic import AliasChoices

from pydantic import (
    AfterValidator, AnyUrl, BaseModel, ConfigDict, EmailStr, Field, StringConstraints, WithJsonSchema,
)


def validate_uri(value: str) -> str:
    AnyUrl(value)
    return value


URI = Annotated[str, AfterValidator(validate_uri), WithJsonSchema({"type": "string", "format": "uri"})]

Username = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=3,
        max_length=32,
        pattern=r"^[a-zA-Z0-9_]+$",
    ),
]

# Defines what users can see on a public profile
class PublicUser(BaseModel):
    id: int
    name: str
    username: str
    bio: str | None = None
    avatar_url: URI | None = None

    model_config = ConfigDict(from_attributes=True)


# Validates information submitted when editing a profile
class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    bio: str | None = None
    avatar_url: URI | None = None


# Defines the information returned about an authenticated user's account
class UserResponse(BaseModel):
    created_at: datetime
    id: int
    email: str
    name: str
    username: str
    bio: str | None = None
    avatar_url: URI | None = None

    model_config = ConfigDict(from_attributes=True)


class PublicUserResponse(BaseModel):
    user: PublicUser


class UserUpdateResponse(BaseModel):
    user: UserResponse

class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=100,
        ),
    ]
    username: Username
    email: EmailStr
    password: str = Field(min_length=8, max_length=100)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identifier: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=1,
            max_length=254,
        ),
    ] = Field(
        validation_alias=AliasChoices("identifier", "email")
    )

    password: str

class UserSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    users: list[PublicUser]
