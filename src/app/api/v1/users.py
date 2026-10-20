from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.preference import Preference
from app.models.user import User
from app.schemas.preference import PreferenceDetailResponse, PreferenceUpdateResponse, PreferenceUpdate
from app.schemas.user import PublicUserResponse, UserUpdate, UserUpdateResponse


router = APIRouter(
    prefix="/api/users",
    tags=["Users / Preferences"],
)


@router.get(
    "/{id}",
    response_model=PublicUserResponse,
    dependencies=[Depends(get_current_user)],
    responses={
        401: {"description": "Missing or invalid bearer credentials"},
        404: {"description": "User not found"},
    },
)
def get_user(
    id: int,
    db: Session = Depends(get_db),
):
    user = db.get(User, id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return {"user": user}



@router.put(
    "/{id}",
    response_model=UserUpdateResponse,
    responses={
        401: {"description": "Missing or invalid bearer credentials"},
        403: {"description": "You can only update your own profile"},
        404: {"description": "User not found"},
    },
)
def update_user(
    id: int,
    user_data: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own profile",
        )

    user = db.get(User, id)

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.name = user_data.name
    user.bio = user_data.bio
    user.avatar_url = user_data.avatar_url

    try:
        db.commit()
        db.refresh(user)
    except Exception:
        db.rollback()
        raise

    return {"user": user}



@router.get(
    "/{id}/preferences",
    response_model=PreferenceDetailResponse,
    responses={
        401: {"description": "Missing or invalid bearer credentials"},
        403: {"description": "You can only view your own preferences"},
        404: {"description": "Preferences not found"},
    },
)
def get_user_preferences(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only view your own preferences",
        )

    preferences = (
        db.query(Preference)
        .filter(Preference.user_id == id)
        .first()
    )

    if preferences is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preferences not found",
        )

    return {"preferences": preferences}


@router.put(
    "/{id}/preferences",
    response_model=PreferenceUpdateResponse,
    responses={
        401: {"description": "Missing or invalid bearer credentials"},
        403: {"description": "You can only update your own preferences"},
    },
)
def update_user_preferences(
    id: int,
    preferences_data: PreferenceUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.id != id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only update your own preferences",
        )

    preferences = (
        db.query(Preference)
        .filter(Preference.user_id == id)
        .first()
    )

    creating = preferences is None
    if creating:
        preferences = Preference(user_id=id)
        db.add(preferences)

    values = preferences_data.model_dump()
    for field, value in values.items():
        setattr(preferences, field, value)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # PostgreSQL names the model's unnamed UNIQUE(user_id) constraint this way.
        # Only recover a competing insert, never another integrity failure.
        diag = getattr(exc.orig, "diag", None)
        if not (
            creating
            and getattr(exc.orig, "sqlstate", None) == "23505"
            and getattr(diag, "table_name", None) == "preferences"
            and getattr(diag, "constraint_name", None) == "preferences_user_id_key"
        ):
            raise

        try:
            preferences = (
                db.query(Preference)
                .filter(Preference.user_id == id)
                .first()
            )
            if preferences is None:
                # The conflicting row may have been deleted; preserve the error.
                raise exc
            for field, value in values.items():
                setattr(preferences, field, value)
            db.commit()
        except Exception:
            db.rollback()
            raise
    except Exception:
        db.rollback()
        raise

    db.refresh(preferences)
    return {"preferences": preferences}
