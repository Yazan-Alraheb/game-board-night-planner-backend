from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.schemas.token import TokenResponse
from app.schemas.user import LoginRequest, RegisterRequest, UserResponse
from app.services import user as user_service

router = APIRouter(prefix ="/api/auth", tags = ["auth"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def register(data : RegisterRequest, db: Session = Depends(get_db)):
    try:
        return user_service.register_user(db, data)
    except user_service.EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail = "Email is already registered",
        )


@router.post("/login", response_model=TokenResponse)
def login(data: LoginRequest, db: Session = Depends(get_db)):
    try:
        token = user_service.login_user(db, data)
    except user_service.InvalidCredentialsError:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "Invalid email or password",
            headers = {"WWW-Authenticate": "Bearer"},
        )



    return TokenResponse(access_token = token)
