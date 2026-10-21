from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.friend import Friend
from app.models.game import Game
from app.models.game_night import GameNight
from app.models.game_night_game import GameNightGame
from app.models.game_night_member import GameNightMember
from app.models.user import User
from app.models.user_game import UserGame
from app.schemas.game_night import (
    GameNightAvailableGamesResponse,
    GameNightCreate,
    GameNightDetailResponse,
    GameNightGameAdd,
    GameNightGameResponse,
    GameNightInvite,
    GameNightListResponse,
    GameNightMembersResponse,
    RSVPResponse,
    RSVPUpdate,
    GameNightUpdate,
)


router = APIRouter(
    prefix="/api/game-nights",
    tags=["Game Nights"],
)


def get_visible_game_night(
    game_night_id: int,
    db: Session,
    current_user: User,
) -> GameNight:
    game_night = (
        db.query(GameNight)
        .outerjoin(
            GameNightMember,
            GameNightMember.game_night_id == GameNight.id,
        )
        .filter(
            GameNight.id == game_night_id,
            or_(
                GameNight.host_id == current_user.id,
                GameNightMember.user_id == current_user.id,
            ),
        )
        .first()
    )

    if game_night is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game night not found",
        )

    return game_night


def ensure_host(game_night: GameNight, current_user: User) -> None:
    if game_night.host_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the host can perform this action",
        )


@router.get("", response_model=GameNightListResponse)
def list_game_nights(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    game_nights = (
        db.query(GameNight)
        .outerjoin(
            GameNightMember,
            GameNightMember.game_night_id == GameNight.id,
        )
        .filter(
            or_(
                GameNight.host_id == current_user.id,
                GameNightMember.user_id == current_user.id,
            )
        )
        .distinct()
        .order_by(GameNight.starts_at.asc())
        .all()
    )

    return {"game_nights": game_nights}


@router.post(
    "",
    response_model=GameNightDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_game_night(
    data: GameNightCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    game_ids = list(dict.fromkeys(data.game_ids))
    invitee_ids = list(dict.fromkeys(data.invitee_ids))

    for game_id in game_ids:
        game = db.get(Game, game_id)

        if game is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Game not found",
            )

        owned_game = (
            db.query(UserGame)
            .filter(
                UserGame.user_id == current_user.id,
                UserGame.game_id == game_id,
                UserGame.status == "owned",
            )
            .first()
        )

        if owned_game is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only select games from attendee collections",
            )

    for invitee_id in invitee_ids:
        if invitee_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You cannot invite yourself",
            )

        if db.get(User, invitee_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitee not found",
            )

        friendship = (
            db.query(Friend)
            .filter(
                Friend.status == "accepted",
                or_(
                    (
                        (Friend.requester_id == current_user.id)
                        & (Friend.receiver_id == invitee_id)
                    ),
                    (
                        (Friend.requester_id == invitee_id)
                        & (Friend.receiver_id == current_user.id)
                    ),
                ),
            )
            .first()
        )

        if friendship is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You can only invite accepted friends",
            )

    game_night = GameNight(
        host_id=current_user.id,
        name=data.name,
        starts_at=data.starts_at,
        location=data.location,
        notes=data.notes,
    )

    db.add(game_night)
    db.flush()

    db.add(
        GameNightMember(
            game_night_id=game_night.id,
            user_id=current_user.id,
            status="accepted",
        )
    )

    for game_id in game_ids:
        db.add(
            GameNightGame(
                game_night_id=game_night.id,
                game_id=game_id,
            )
        )

    for invitee_id in invitee_ids:
        db.add(
            GameNightMember(
                game_night_id=game_night.id,
                user_id=invitee_id,
                status="pending",
            )
        )

    db.commit()
    db.refresh(game_night)

    return {"game_night": game_night}


@router.get("/{id}", response_model=GameNightDetailResponse)
def get_game_night(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    game_night = get_visible_game_night(id, db, current_user)
    return {"game_night": game_night}


@router.put("/{id}", response_model=GameNightDetailResponse)
def update_game_night(
    id: int,
    data: GameNightUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    game_night = db.get(GameNight, id)

    if game_night is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game night not found",
        )

    ensure_host(game_night, current_user)

    game_night.name = data.name
    game_night.starts_at = data.starts_at
    game_night.location = data.location
    game_night.notes = data.notes

    db.commit()
    db.refresh(game_night)

    return {"game_night": game_night}


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_game_night(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    game_night = db.get(GameNight, id)

    if game_night is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game night not found",
        )

    ensure_host(game_night, current_user)

    db.delete(game_night)
    db.commit()


@router.get("/{id}/members", response_model=GameNightMembersResponse)
def list_members(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    game_night = get_visible_game_night(id, db, current_user)

    members = (
        db.query(GameNightMember)
        .options(joinedload(GameNightMember.user))
        .filter(GameNightMember.game_night_id == game_night.id)
        .all()
    )

    return {
        "members": [
            {
                "user": member.user,
                "status": member.status,
            }
            for member in members
        ]
    }


@router.post(
    "/{id}/members",
    response_model=GameNightMembersResponse,
    status_code=status.HTTP_201_CREATED,
)
def invite_member(
    id: int,
    data: GameNightInvite,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    game_night = db.get(GameNight, id)

    if game_night is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game night not found",
        )

    ensure_host(game_night, current_user)

    if db.get(User, data.user_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    existing_member = db.get(
        GameNightMember,
        (game_night.id, data.user_id),
    )

    if existing_member is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member",
        )

    friendship = (
        db.query(Friend)
        .filter(
            Friend.status == "accepted",
            or_(
                (
                    (Friend.requester_id == current_user.id)
                    & (Friend.receiver_id == data.user_id)
                ),
                (
                    (Friend.requester_id == data.user_id)
                    & (Friend.receiver_id == current_user.id)
                ),
            ),
        )
        .first()
    )

    if friendship is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only invite accepted friends",
        )

    member = GameNightMember(
        game_night_id=game_night.id,
        user_id=data.user_id,
        status="pending",
    )

    db.add(member)
    db.commit()

    return {"members": []}


@router.put("/{id}/rsvp", response_model=RSVPResponse)
def update_rsvp(
    id: int,
    data: RSVPUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    game_night = db.get(GameNight, id)

    if game_night is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game night not found",
        )

    member = db.get(GameNightMember, (id, current_user.id))

    if member is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not invited to this game night",
        )

    member.status = data.status
    db.commit()

    return {
        "game_night_id": id,
        "status": member.status,
    }


@router.delete("/{id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    id: int,
    user_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    game_night = db.get(GameNight, id)

    if game_night is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game night not found",
        )

    if current_user.id != game_night.host_id and current_user.id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot remove this member",
        )

    if user_id == game_night.host_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The host cannot leave the game night",
        )

    member = db.get(GameNightMember, (id, user_id))

    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found",
        )

    db.delete(member)
    db.commit()


@router.get(
    "/{id}/games",
    response_model=GameNightAvailableGamesResponse,
)
def list_available_games(
    id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    game_night = get_visible_game_night(id, db, current_user)

    owned_entries = (
        db.query(UserGame)
        .join(
            GameNightMember,
            GameNightMember.user_id == UserGame.user_id,
        )
        .options(
            joinedload(UserGame.game),
            joinedload(UserGame.user),
        )
        .filter(
            GameNightMember.game_night_id == game_night.id,
            GameNightMember.status == "accepted",
            UserGame.status == "owned",
        )
        .all()
    )

    selected_game_ids = {
        entry.game_id
        for entry in db.query(GameNightGame)
        .filter(GameNightGame.game_night_id == game_night.id)
        .all()
    }

    games = defaultdict(lambda: {"game": None, "owners": []})

    for entry in owned_entries:
        games[entry.game_id]["game"] = entry.game
        games[entry.game_id]["owners"].append(entry.user)

    return {
        "games": [
            {
                "game": item["game"],
                "owners": item["owners"],
                "selected": game_id in selected_game_ids,
            }
            for game_id, item in games.items()
        ]
    }


@router.post(
    "/{id}/games",
    response_model=GameNightGameResponse,
    status_code=status.HTTP_201_CREATED,
)
def select_game(
    id: int,
    data: GameNightGameAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    game_night = db.get(GameNight, id)

    if game_night is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game night not found",
        )

    ensure_host(game_night, current_user)

    if db.get(Game, data.game_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game not found",
        )

    available_game = (
        db.query(UserGame)
        .join(
            GameNightMember,
            GameNightMember.user_id == UserGame.user_id,
        )
        .filter(
            GameNightMember.game_night_id == id,
            GameNightMember.status == "accepted",
            UserGame.game_id == data.game_id,
            UserGame.status == "owned",
        )
        .first()
    )

    if available_game is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Game is not owned by an accepted attendee",
        )

    existing = db.get(GameNightGame, (id, data.game_id))

    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Game is already selected",
        )

    selected_game = GameNightGame(
        game_night_id=id,
        game_id=data.game_id,
    )

    db.add(selected_game)
    db.commit()

    return {
        "game_id": data.game_id,
        "game_night_id": id,
    }


@router.delete(
    "/{id}/games/{game_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_selected_game(
    id: int,
    game_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    game_night = db.get(GameNight, id)

    if game_night is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Game night not found",
        )

    ensure_host(game_night, current_user)

    selected_game = db.get(GameNightGame, (id, game_id))

    if selected_game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Selected game not found",
        )

    db.delete(selected_game)
    db.commit()