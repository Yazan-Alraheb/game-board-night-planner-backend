from typing import Literal, Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status, Path
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.game import Game
from app.models.user import User
from app.models.user_game import UserGame
from app.schemas.user_game import (
    CollectionAdd,
    CollectionEntryResponse,
    CollectionListResponse,
    CollectionUpdate,
)


router = APIRouter(
    prefix="/api/users",
    tags=["Game Collections"],
)


def ensure_owner(id: int, current_user: User) -> None:
    if current_user.id != id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only manage your own collection",
        )


@router.get(
    "/{id}/collection",
    response_model=CollectionListResponse,
    responses={
        401: {"description": "Missing or invalid bearer credentials"},
        403: {"description": "Not your collection"},
        404: {"description": "User not found"},
    },
)
def get_collection(
    id: int,
    collection_status: Literal["owned", "wishlist"] | None = Query(
        default=None,
        alias="status",
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_owner(id, current_user)

    if db.get(User, id) is None:
        raise HTTPException(
            status_code=404,
            detail="User not found",
        )

    query = (
        db.query(UserGame)
        .options(joinedload(UserGame.game))
        .filter(UserGame.user_id == id)
    )

    if collection_status is not None:
        query = query.filter(UserGame.status == collection_status)

    entries = query.all()

    return {
        "games": [
            {
                "game": entry.game,
                "status": entry.status,
            }
            for entry in entries
        ]
    }


@router.post(
    "/{id}/collection",
    response_model=CollectionEntryResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        401: {"description": "Missing or invalid bearer credentials"},
        403: {"description": "Not your collection"},
        404: {"description": "Game not found"},
        409: {"description": "Game already in collection"},
    },
)
def add_to_collection(
    id: int,
    data: CollectionAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_owner(id, current_user)

    if db.get(Game, data.game_id) is None:
        raise HTTPException(
            status_code=404,
            detail="Game not found",
        )

    existing = db.get(UserGame, (id, data.game_id))

    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Game already in collection",
        )

    entry = UserGame(
        user_id=id,
        game_id=data.game_id,
        status=data.status,
    )

    try:
        db.add(entry)
        db.commit()

    except IntegrityError as exc:
        db.rollback()

        diag = getattr(exc.orig, "diag", None)

        if (
            getattr(exc.orig, "sqlstate", None) == "23505"
            and getattr(diag, "constraint_name", None)
            == "user_games_pkey"
        ):
            raise HTTPException(
                status_code=409,
                detail="Game already in collection",
            ) from exc

        raise

    except Exception:
        db.rollback()
        raise

    return {
        "game_id": entry.game_id,
        "status": entry.status,
    }


@router.put(
    "/{id}/collection/{game_id}",
    response_model=CollectionEntryResponse,
    responses={
        401: {"description": "Missing or invalid bearer credentials"},
        403: {"description": "Not your collection"},
        404: {"description": "Game not in collection"},
    },
)
def update_collection_game(
    id: int,
    game_id: Annotated[int, Path(gt=0, le=2_147_483_647)],
    data: CollectionUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_owner(id, current_user)

    entry = db.get(UserGame, (id, game_id))

    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="Game not in collection",
        )

    entry.status = data.status

    try:
        db.commit()
        db.refresh(entry)

    except Exception:
        db.rollback()
        raise

    return {
        "game_id": entry.game_id,
        "status": entry.status,
    }


@router.delete(
    "/{id}/collection/{game_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"description": "Missing or invalid bearer credentials"},
        403: {"description": "Not your collection"},
        404: {"description": "Game not in collection"},
    },
)
def remove_from_collection(
    id: int,
    game_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    ensure_owner(id, current_user)

    entry = db.get(UserGame, (id, game_id))

    if entry is None:
        raise HTTPException(
            status_code=404,
            detail="Game not in collection",
        )

    try:
        db.delete(entry)
        db.commit()

    except Exception:
        db.rollback()
        raise
