from typing import Annotated, Literal
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import and_, delete, func, or_, update
from sqlalchemy.exc import IntegrityError

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.core.friend_settings import get_friend_request_settings
from app.models.friend import Friend
from app.models.user import User
from app.schemas.friend import FriendErrorResponse, FriendRequestCreate, FriendRequestEnvelope, FriendRequestListResponse, FriendRequestUpdate


router = APIRouter(
    prefix="/api/friend-requests",
    tags=["Friends"],
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@router.post(
    "",
    response_model=FriendRequestEnvelope,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"model": FriendErrorResponse, "description": "Bad request"},
        401: {"model": FriendErrorResponse, "description": "Missing, invalid or expired access token"},
        404: {"model": FriendErrorResponse, "description": "User not found"},
        409: {"model": FriendErrorResponse, "description": "Active friendship/request exists or decline cooldown has not expired"},
    },
)
def create_friend_request(
    friend_request_data: FriendRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    receiver_id = friend_request_data.user_id

    # 1. Prevent users from sending requests to themselves
    if current_user.id == receiver_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot send a friend request to yourself",
        )

    # 2. Check if the receiving user exists
    receiver = db.get(User, receiver_id)

    if receiver is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # 3. Check for an existing pending request or friendship
    existing_friendship = (
        db.query(Friend)
        .filter(
            or_(
                and_(
                    Friend.requester_id == current_user.id,
                    Friend.receiver_id == receiver_id,
                ),
                and_(
                    Friend.requester_id == receiver_id,
                    Friend.receiver_id == current_user.id,
                ),
            ),
            Friend.status.in_(["pending", "accepted"]),
        )
        .first()
    )

    if existing_friendship is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A friendship or friend request already exists between these users",
        )

    # Directed cooldown: A declining B's request only prevents B from resending
    # to A. Unknown historical resolution times intentionally do not count.
    try:
        latest_decline = (
            db.query(func.max(Friend.resolved_at))
            .filter(
                Friend.requester_id == current_user.id,
                Friend.receiver_id == receiver_id,
                Friend.status == "declined",
                Friend.resolved_at.is_not(None),
            )
            .scalar()
        )
        if latest_decline is not None:
            cooldown = timedelta(days=get_friend_request_settings().cooldown_days)
            if utc_now() < latest_decline + cooldown:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Friend request decline cooldown has not expired",
                )
    except Exception:
        db.rollback()
        raise

    # 4. Create the new pending friend request
    new_friend_request = Friend(
        requester_id=current_user.id,
        receiver_id=receiver_id,
        status="pending",
    )

    db.add(new_friend_request)

    # 5. Save the request to the database
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        diag = getattr(exc.orig, "diag", None)
        if not (
            getattr(exc.orig, "sqlstate", None) == "23505"
            and getattr(diag, "table_name", None) == "friends"
            and getattr(diag, "constraint_name", None) == "uq_active_friend_pair"
        ):
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A friendship or friend request already exists between these users",
        ) from exc
    except Exception:
        db.rollback()
        raise

    db.refresh(new_friend_request)

    # 6. Return the newly created friend request
    return {"friend_request": new_friend_request}


@router.get(
    "",
    response_model=FriendRequestListResponse,
    responses={401: {"model": FriendErrorResponse, "description": "Missing, invalid or expired access token"}},
)
def get_friend_requests(
    type: Literal["incoming", "outgoing"] | None = Query(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(Friend).filter(
        Friend.status == "pending",
    )

    if type == "incoming":
        query = query.filter(
            Friend.receiver_id == current_user.id
        )

    elif type == "outgoing":
        query = query.filter(
            Friend.requester_id == current_user.id
        )

    else:
        query = query.filter(
            or_(
                Friend.requester_id == current_user.id,
                Friend.receiver_id == current_user.id,
            )
        )

    requests = query.order_by(Friend.created_at.desc()).all()

    return {"requests": requests}


@router.put(
    "/{id}",
    response_model=FriendRequestEnvelope,
    responses={
        401: {"model": FriendErrorResponse, "description": "Missing, invalid or expired access token"},
        403: {"model": FriendErrorResponse, "description": "Only the recipient can resolve this request"},
        404: {"model": FriendErrorResponse, "description": "Friend request not found"},
        409: {"model": FriendErrorResponse, "description": "Friend request has already been resolved"},
    },
)
def update_friend_request(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    data: FriendRequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    friend_request = db.get(Friend, id)

    if friend_request is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Friend request not found",
        )

    # Only the recipient can accept or decline
    if friend_request.receiver_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot respond to this friend request",
        )

    # A request can only be resolved once
    if friend_request.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Friend request has already been resolved",
        )

    try:
        # Check pending status in SQL, not only on a potentially stale ORM object.
        result = db.execute(
            update(Friend)
            .where(
                Friend.id == id,
                Friend.receiver_id == current_user.id,
                Friend.status == "pending",
            )
            .values(status=data.status, resolved_at=utc_now())
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Friend request has already been resolved",
            )

        db.commit()
        db.refresh(friend_request)
    except Exception:
        db.rollback()
        raise

    return {"friend_request": friend_request}


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        401: {"model": FriendErrorResponse, "description": "Missing, invalid or expired access token"},
        403: {"model": FriendErrorResponse, "description": "Only the original sender can cancel this request"},
        404: {"model": FriendErrorResponse, "description": "Friend request not found or already canceled"},
        409: {"model": FriendErrorResponse, "description": "Only pending requests can be canceled"},
    },
)
def cancel_friend_request(
    id: Annotated[int, Path(ge=1, le=2_147_483_647)],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    friend_request = db.get(Friend, id)
    if friend_request is None:
        raise HTTPException(status_code=404, detail="Friend request not found")
    if friend_request.requester_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the original sender can cancel this request")
    if friend_request.status != "pending":
        raise HTTPException(status_code=409, detail="Only pending requests can be canceled")

    try:
        result = db.execute(
            delete(Friend)
            .where(
                Friend.id == id,
                Friend.requester_id == current_user.id,
                Friend.status == "pending",
            )
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            # Bypass the identity map after losing a race to resolution/cancel.
            current = db.get(Friend, id, populate_existing=True)
            if current is None:
                raise HTTPException(status_code=404, detail="Friend request not found")
            raise HTTPException(status_code=409, detail="Only pending requests can be canceled")
        db.commit()
    except Exception:
        db.rollback()
        raise
