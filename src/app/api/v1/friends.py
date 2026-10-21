from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.friend import Friend
from app.models.user import User
from app.schemas.friends import FriendsListResponse
from app.schemas.friend import FriendErrorResponse


router = APIRouter(
    prefix="/api/friends",
    tags=["Friends"],
)


@router.get(
    "",
    response_model=FriendsListResponse,
    responses={401: {"model": FriendErrorResponse, "description": "Missing, invalid or expired access token"}},
)
def get_friends(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    friendships = (
        db.query(Friend)
        .filter(
            Friend.status == "accepted",
            or_(
                Friend.requester_id == current_user.id,
                Friend.receiver_id == current_user.id,
            ),
        )
        .all()
    )

    friend_ids = [
        friendship.receiver_id
        if friendship.requester_id == current_user.id
        else friendship.requester_id
        for friendship in friendships
    ]

    if not friend_ids:
        return {"friends": []}

    friends = (
        db.query(User)
        .filter(User.id.in_(friend_ids))
        .order_by(User.name, User.id)
        .all()
    )

    return {"friends": friends}


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": FriendErrorResponse, "description": "Missing, invalid or expired access token"},
        404: {"model": FriendErrorResponse, "description": "Friend not found"},
    },
)
def remove_friend(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    friendship = (
        db.query(Friend)
        .filter(
            Friend.status == "accepted",
            or_(
                (Friend.requester_id == current_user.id)
                & (Friend.receiver_id == id),
                (Friend.requester_id == id)
                & (Friend.receiver_id == current_user.id),
            ),
        )
        .first()
    )

    if friendship is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Friend not found",
        )

    try:
        db.delete(friendship)
        db.commit()
    except Exception:
        db.rollback()
        raise
