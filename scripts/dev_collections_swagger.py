import uvicorn
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

import app.models
from app.api.dependencies import get_current_user
from app.core.database import engine, get_db
from app.main import app
from app.models.user import User


TEST_EMAIL = "swagger-test@example.invalid"


def create_test_user():
    with Session(engine) as db:
        user = (
            db.query(User)
            .filter(User.email == TEST_EMAIL)
            .first()
        )

        if user is None:
            user = User(
                name="Swagger Test User",
                email=TEST_EMAIL,
                password_hash="test-only-not-a-real-password-hash",
            )

            db.add(user)
            db.commit()
            db.refresh(user)

        print(f"Test User ID: {user.id}")


def mock_current_user(
    db: Session = Depends(get_db),
):
    user = (
        db.query(User)
        .filter(User.email == TEST_EMAIL)
        .first()
    )

    if user is None:
        raise HTTPException(
            status_code=404,
            detail="Test user not found",
        )

    return user


if __name__ == "__main__":
    create_test_user()

    app.dependency_overrides[get_current_user] = mock_current_user

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
    )
