from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies import get_current_user
from app.core.database import get_db
from app.models.conversation import Conversation
from app.models.conversation_member import ConversationMember
from app.models.friend import Friend
from app.models.game_night import GameNight
from app.models.game_night_member import GameNightMember
from app.models.message import Message
from app.models.user import User
from app.schemas.conversation import (
    ChatErrorResponse, ConversationCreate, ConversationEnvelope,
    ConversationListResponse, ConversationResponse,
)
from app.schemas.message import (
    BeforeTimestamp, MessageCreate, MessageEnvelope, MessageListResponse, MessageResponse,
)
from app.schemas.user import PublicUser


router = APIRouter(prefix="/api/conversations", tags=["Messages"])
ConversationId = Annotated[int, Path(ge=1, le=2_147_483_647)]
READ_ERRORS = {
    401: {"model": ChatErrorResponse, "description": "Missing, invalid or expired access token"},
    403: {"model": ChatErrorResponse, "description": "Not an authorized participant or private friendship is no longer accepted"},
    404: {"model": ChatErrorResponse, "description": "Conversation not found"},
}
_PARTICIPANTS = selectinload(Conversation.participants).joinedload(ConversationMember.user)


def _serialize_conversation(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        type=conversation.type,
        game_night_id=conversation.game_night_id,
        created_at=conversation.created_at,
        participants=[
            PublicUser.model_validate(member.user)
            for member in sorted(conversation.participants, key=lambda member: member.user_id)
        ],
    )


def _accepted_friendship(first_id, second_id):
    return and_(
        Friend.status == "accepted",
        or_(
            and_(Friend.requester_id == first_id, Friend.receiver_id == second_id),
            and_(Friend.requester_id == second_id, Friend.receiver_id == first_id),
        ),
    )


def _authorized_conversation(db: Session, id: int, user_id: int) -> Conversation:
    conversation = db.get(Conversation, id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if db.get(ConversationMember, (id, user_id)) is None:
        raise HTTPException(status_code=403, detail="Not a conversation participant")
    if conversation.type == "private":
        friendship = db.query(Friend.id).filter(_accepted_friendship(
            conversation.private_user_low_id, conversation.private_user_high_id,
        )).first()
        if friendship is None:
            raise HTTPException(status_code=403, detail="Private conversations require accepted friendship")
    if conversation.game_night_id is not None:
        game_night = db.get(GameNight, conversation.game_night_id)
        if game_night is None:
            raise HTTPException(status_code=403, detail="Game-night access is no longer available")
        if game_night.host_id != user_id:
            attendee = db.get(GameNightMember, (game_night.id, user_id))
            if attendee is None or attendee.status != "accepted":
                raise HTTPException(status_code=403, detail="Not an accepted game-night attendee")
    return conversation


def _expected_creation_conflict(exc: IntegrityError) -> bool:
    diag = getattr(exc.orig, "diag", None)
    return (
        getattr(exc.orig, "sqlstate", None) == "23505"
        and getattr(diag, "table_name", None) == "conversations"
        and getattr(diag, "constraint_name", None) in {
            "uq_conversation_private_pair", "uq_conversation_game_night",
        }
    )


@router.get(
    "", response_model=ConversationListResponse,
    responses={401: READ_ERRORS[401]}, operation_id="get_api_conversations",
)
def list_conversations(
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    user_id = current_user.id
    eligible_game_night = Conversation.game_night.has(or_(
        GameNight.host_id == user_id,
        GameNight.members.any(and_(
            GameNightMember.user_id == user_id, GameNightMember.status == "accepted",
        )),
    ))
    eligible_private = db.query(Friend.id).filter(_accepted_friendship(
        Conversation.private_user_low_id, Conversation.private_user_high_id,
    )).exists()
    conversations = (
        db.query(Conversation)
        .options(_PARTICIPANTS)
        .filter(
            Conversation.participants.any(ConversationMember.user_id == user_id),
            or_(Conversation.game_night_id.is_(None), eligible_game_night),
            or_(Conversation.type != "private", eligible_private),
        )
        .order_by(Conversation.created_at.desc(), Conversation.id.desc())
        .all()
    )
    return {"conversations": [_serialize_conversation(row) for row in conversations]}


@router.post(
    "", response_model=ConversationEnvelope, status_code=status.HTTP_201_CREATED,
    responses={
        **READ_ERRORS,
        403: {"model": ChatErrorResponse, "description": "Accepted friendship required, unauthorized game-night creation or ineligible participants"},
        404: {"model": ChatErrorResponse, "description": "Participant or game night not found"},
        400: {"model": ChatErrorResponse, "description": "Invalid conversation composition"},
        409: {"model": ChatErrorResponse, "description": "Private pair or game-night conversation already exists"},
    },
    operation_id="post_api_conversations",
)
def create_conversation(
    data: ConversationCreate, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    participant_ids = set(data.participant_ids) | {current_user.id}
    if data.type == "private" and (len(participant_ids) != 2 or data.game_night_id is not None):
        raise HTTPException(status_code=400, detail="Private conversations require two users and no game night")
    if len(participant_ids) < 2:
        raise HTTPException(status_code=400, detail="Conversations require at least two distinct users")

    try:
        found_ids = {row[0] for row in db.query(User.id).filter(User.id.in_(participant_ids)).all()}
        if found_ids != participant_ids:
            raise HTTPException(status_code=404, detail="Participant not found")

        if data.game_night_id is not None:
            game_night = db.get(GameNight, data.game_night_id)
            if game_night is None:
                raise HTTPException(status_code=404, detail="Game night not found")
            if game_night.host_id != current_user.id:
                raise HTTPException(status_code=403, detail="Only the game-night host can create its conversation")
            eligible = {game_night.host_id} | {
                row[0] for row in db.query(GameNightMember.user_id).filter(
                    GameNightMember.game_night_id == game_night.id,
                    GameNightMember.status == "accepted",
                ).all()
            }
            if not participant_ids <= eligible:
                raise HTTPException(status_code=403, detail="Participants must be host or accepted attendees")

        else:
            other_ids = participant_ids - {current_user.id}
            friends = db.query(Friend).filter(
                Friend.status == "accepted",
                or_(
                    and_(Friend.requester_id == current_user.id, Friend.receiver_id.in_(other_ids)),
                    and_(Friend.receiver_id == current_user.id, Friend.requester_id.in_(other_ids)),
                ),
            ).all()
            friend_ids = {
                row.receiver_id if row.requester_id == current_user.id else row.requester_id
                for row in friends
            }
            if not other_ids <= friend_ids:
                raise HTTPException(status_code=403, detail="Participants must be accepted friends of the creator")

        low, high = sorted(participant_ids) if data.type == "private" else (None, None)
        if data.type == "private":
            duplicate = db.query(Conversation.id).filter(
                Conversation.private_user_low_id == low,
                Conversation.private_user_high_id == high,
            ).first()
        elif data.game_night_id is not None:
            duplicate = db.query(Conversation.id).filter(
                Conversation.game_night_id == data.game_night_id,
            ).first()
        else:
            duplicate = None
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="Conversation already exists")

        conversation = Conversation(
            type=data.type, game_night_id=data.game_night_id,
            private_user_low_id=low, private_user_high_id=high,
        )
        db.add(conversation)
        db.flush()
        db.add_all([
            ConversationMember(conversation_id=conversation.id, user_id=user_id)
            for user_id in sorted(participant_ids)
        ])
        db.flush()
        loaded = db.query(Conversation).options(_PARTICIPANTS).filter(
            Conversation.id == conversation.id,
        ).one()
        response = _serialize_conversation(loaded)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if _expected_creation_conflict(exc):
            raise HTTPException(status_code=409, detail="Conversation already exists") from exc
        raise
    except Exception:
        db.rollback()
        raise
    return {"conversation": response}


@router.get(
    "/{id}", response_model=ConversationEnvelope, responses=READ_ERRORS,
    operation_id="get_api_conversations_id",
)
def get_conversation(
    id: ConversationId, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    conversation = _authorized_conversation(db, id, current_user.id)
    # Authorization precedes loading the public participant profiles.
    db.query(Conversation).options(_PARTICIPANTS).filter(Conversation.id == id).one()
    return {"conversation": _serialize_conversation(conversation)}


@router.get(
    "/{id}/messages", response_model=MessageListResponse, responses=READ_ERRORS,
    operation_id="get_api_conversations_id_messages",
)
def list_messages(
    id: ConversationId,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before: Annotated[BeforeTimestamp | None, Query()] = None,
    db: Session = Depends(get_db), current_user: User = Depends(get_current_user),
):
    _authorized_conversation(db, id, current_user.id)
    query = db.query(Message).filter(Message.conversation_id == id)
    if before is not None:
        query = query.filter(Message.created_at < before)
    messages = query.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit).all()
    return {"messages": messages}


@router.post(
    "/{id}/messages", response_model=MessageEnvelope, status_code=status.HTTP_201_CREATED,
    responses=READ_ERRORS, operation_id="post_api_conversations_id_messages",
)
def send_message(
    id: ConversationId, data: MessageCreate, db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        _authorized_conversation(db, id, current_user.id)
        message = Message(conversation_id=id, user_id=current_user.id, content=data.content)
        db.add(message)
        db.flush()
        response = MessageResponse.model_validate(message)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"message": response}
