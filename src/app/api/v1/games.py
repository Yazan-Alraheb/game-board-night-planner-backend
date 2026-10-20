from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import cast, or_
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.game import Game
from app.schemas.game import GameDetailResponse, GameListResponse


router = APIRouter(
    prefix="/api/games",
    tags=["Games"],
)


@router.get(
    "",
    response_model=GameListResponse,
)
def list_games(
    search: str | None = Query(default=None, max_length=200),
    players: int | None = Query(default=None, ge=1),
    category: str | None = Query(default=None, min_length=1),
    difficulty: Literal["Easy", "Medium", "Hard"] | None = None,
    playtime: int | None = Query(default=None, gt=0),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    query = db.query(Game)

    if search and search.strip():
        phrase = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Game.name.ilike(phrase),
                Game.description.ilike(phrase),
            )
        )

    if players is not None:
        query = query.filter(
            Game.minimum_players <= players,
            Game.maximum_players >= players,
        )

    if category is not None:
        query = query.filter(
            cast(Game.categories, JSONB).contains([category])
        )

    if difficulty is not None:
        query = query.filter(Game.difficulty == difficulty)

    if playtime is not None:
        query = query.filter(Game.playtime <= playtime)

    total = query.count()

    games = (
        query.order_by(Game.id.asc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )

    return {
        "games": games,
        "total": total,
        "page": page,
    }


@router.get(
    "/{id}",
    response_model=GameDetailResponse,
    responses={
        404: {"description": "Game not found"},
    },
)
def get_game(
    id: int,
    db: Session = Depends(get_db),
):
    game = db.get(Game, id)

    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    return {"game": game}
