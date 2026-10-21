from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.schemas.token import AuthResponse
from app.schemas.user import LoginRequest, RegisterRequest, UserResponse
from app.services import user as user_service

router = APIRouter(prefix ="/api/auth", tags = ["auth"])


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED, responses={status.HTTP_409_CONFLICT: {"description": "Email is already registered"}})
def register(data : RegisterRequest, db: Session = Depends(get_db)):
    try:
        user, token = user_service.register_user(db, data)
        return AuthResponse(user=UserResponse.model_validate(user), access_token=token)
    except user_service.EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail = "Email is already registered",
        )


@router.post("/login", response_model=AuthResponse, responses={status.HTTP_401_UNAUTHORIZED: {"description": "Invalid email or password"}})
def login(data: LoginRequest, db: Session = Depends(get_db)):
    try:
        user, token = user_service.login_user(db, data)
        return AuthResponse(user=UserResponse.model_validate(user), access_token=token)
    except user_service.InvalidCredentialsError:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "Invalid email or password",
            headers = {"WWW-Authenticate": "Bearer"},
        )
