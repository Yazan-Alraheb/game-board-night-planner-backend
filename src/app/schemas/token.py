from pydantic import BaseModel

from app.schemas.user import UserResponse


class AuthResponse(BaseModel):
    user: UserResponse
    access_token: str
    token_type: str = "bearer"
